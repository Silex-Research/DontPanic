"""Plan 2026-05-20-001 F002 — external_refs sync tests.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_external_refs_sync_f002.py

Coverage targets (acceptance ≥12 cases):

  Schema-level (Pydantic ExternalRef on plan_model):
    1. Valid ref shape round-trips.
    2. Missing `kind` rejected.
    3. Bad `uri` pattern rejected (no scheme).
    4. Bad `sync` enum rejected.
    5. plan_loader surfaces external_refs[] on LoadedPlan.

  Lock-time:
    6. push_status ref reachable → validate_refs_for_lock passes.
    7. push_status ref unreachable → ExternalRefsSyncError.
    8. sync=none ref unreachable → no raise (tolerated).
    9. push_status ref with no registered adapter → AdapterUnavailable.
   10. read cache short-circuits repeat calls within a session.

  Close-time:
   11. push_status PUSHED ref → evidence file has status=pushed; close not blocked.
   12. push_status FAILED ref (vendor raises) → status=failed; close not blocked.
   13. sync=none ref → status=skipped; no hook call.
   14. dry_run=True → status=pending; vendor NOT called.

  Resync + helpers:
   15. resync replays failed entries to pushed; idempotent on pushed rows.
   16. format_dry_run_preview renders the intended payload.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    cli,
    plan_loader,
)
from dontpanic_orchestrate import external_refs_sync as ers  # noqa: E402
from dontpanic_orchestrate.integrations.pm_tool_models import (  # noqa: E402
    PMIssue,
    PMStatus,
)
from dontpanic_orchestrate.integrations.pm_tool_sync import (  # noqa: E402
    ExternalSyncRecord,
    ExternalSyncStatus,
    make_pushed_record,
)

# Plan model imports — agent-conventions v1.10.0
_SCHEMAS = HERE.parents[2].parent / "claude" / "shared" / "schemas" / "v1.0"
sys.path.insert(0, str(_SCHEMAS))
from models.plan_model import ExternalRef, ExternalRefKind, ExternalRefSync  # noqa: E402

# ───────────────────────────  helpers / fakes  ───────────────────────────


class _FakeHook:
    """Minimal :class:`PMToolSyncHook` for tests. Tracks call counts and
    can be configured to raise on read or push."""

    service_name = "linear"
    uri_scheme = "linear"

    def __init__(
        self,
        *,
        read_should_raise: Exception | None = None,
        push_should_raise: Exception | None = None,
        push_returns: ExternalSyncRecord | None = None,
    ) -> None:
        self.read_calls = 0
        self.push_calls: list[tuple[str, PMStatus, bool]] = []
        self.read_should_raise = read_should_raise
        self.push_should_raise = push_should_raise
        self.push_returns = push_returns

    def read_issue(self, uri: str) -> PMIssue:
        self.read_calls += 1
        if self.read_should_raise is not None:
            raise self.read_should_raise
        return PMIssue(
            id=uri.rsplit("/", 1)[-1],
            project_id="TEAM-1",
            title="Stub",
            status=PMStatus.IN_PROGRESS,
            uri=uri,
        )

    def push_status(
        self, uri: str, new_status: PMStatus, dry_run: bool = False
    ) -> ExternalSyncRecord:
        self.push_calls.append((uri, new_status, dry_run))
        if dry_run:
            return ers.make_pending_record(
                ref_uri=uri,
                kind="pm_issue",
                intended_status=new_status,
                payload={"tool": "issueUpdate", "uri": uri},
            )
        if self.push_should_raise is not None:
            raise self.push_should_raise
        return self.push_returns or make_pushed_record(
            ref_uri=uri,
            kind="pm_issue",
            intended_status=new_status,
            response={"ok": True},
        )


def _ref(uri: str = "linear://issue/ABC-1", sync: str = "push_status") -> ExternalRef:
    return ExternalRef(
        kind=ExternalRefKind.pm_issue,
        uri=uri,
        sync=ExternalRefSync(sync),
    )


def _resolver(hook: _FakeHook | None = None) -> ers.AdapterResolver:
    resolver = ers.AdapterResolver()
    if hook is not None:
        resolver.register(hook)
    return resolver


def _write_cli_plan(plan_dir: Path, refs_yaml: str) -> None:
    plan_dir.mkdir()
    (plan_dir / "plan.md").write_text(
        "---\n"
        "id: 2026-05-20-003-infra-cli-external-ref-fixture\n"
        "title: CLI external refs fixture\n"
        "type: infra\n"
        "tier: local\n"
        "status: active\n"
        "date: '2026-05-20'\n"
        "description: Fixture plan for F002 CLI close integration tests\n"
        "external_refs:\n"
        f"{refs_yaml}"
        "---\n\n"
        "# Fixture\n\n"
        "## Target\n\n"
        "```yaml\n"
        "target_env: dev\n"
        "target_project: none\n"
        "```\n"
    )


def _patch_plan_close(monkeypatch: pytest.MonkeyPatch, resolver: ers.AdapterResolver) -> None:
    def fake_close_plan(plan_dir: Path, *, override_reason=None, dry_run=False):
        return SimpleNamespace(
            audit_result=None,
            notes=[],
            override_recorded=False,
            status_flipped=not dry_run,
            plan_md=Path(plan_dir) / "plan.md",
        )

    monkeypatch.setattr(cli.completion_gate, "close_plan", fake_close_plan)
    monkeypatch.setattr(cli, "_RESOLVER_FACTORY", lambda: resolver)


@pytest.fixture(autouse=True)
def _reset_read_cache():
    """Cache state bleeds across tests; reset before each."""

    ers.reset_read_cache()
    yield
    ers.reset_read_cache()


# ───────────────────────────  schema-level  ───────────────────────────


def test_external_ref_valid_round_trip():
    """Case 1: valid ExternalRef round-trips through model_dump."""

    ref = _ref()
    restored = ExternalRef.model_validate(ref.model_dump())
    assert restored == ref


def test_external_ref_rejects_missing_kind():
    """Case 2: omitting `kind` raises ValidationError."""

    with pytest.raises(ValidationError):
        ExternalRef.model_validate({"uri": "linear://issue/ABC-1", "sync": "push_status"})


def test_external_ref_rejects_bad_uri_pattern():
    """Case 3: a URI without a scheme fails validation."""

    with pytest.raises(ValidationError):
        ExternalRef.model_validate({"kind": "pm_issue", "uri": "no-scheme-here", "sync": "none"})


def test_plan_loader_exposes_external_sync_record():
    """Acceptance #2: ExternalSyncRecord MUST be importable from
    plan_loader (the loader-boundary export surface). The model itself
    lives in integrations/pm_tool_sync.py; plan_loader re-exports it so
    downstream consumers don't reach into the integrations subpackage."""

    assert hasattr(plan_loader, "ExternalSyncRecord")
    assert hasattr(plan_loader, "ExternalSyncStatus")
    # Same class, not a coincidental shadow.
    assert plan_loader.ExternalSyncRecord is ExternalSyncRecord
    assert plan_loader.ExternalSyncStatus is ExternalSyncStatus


def test_external_ref_rejects_bad_sync_enum():
    """Case 4: `sync` outside the {none, push_status} set is rejected."""

    with pytest.raises(ValidationError):
        ExternalRef.model_validate(
            {
                "kind": "pm_issue",
                "uri": "linear://issue/ABC-1",
                "sync": "two_way",
            }
        )


def test_plan_loader_surfaces_external_refs(tmp_path: Path) -> None:
    """Case 5: a plan.md with external_refs[] surfaces on LoadedPlan.

    Builds a minimal plan dir; intentionally exercises only the
    external_refs path on the loader.
    """

    plan_dir = tmp_path / "2026-05-20-002-infra-bridge-fixture"
    plan_dir.mkdir()
    (plan_dir / "plan.md").write_text(
        "---\n"
        "id: 2026-05-20-002-infra-bridge-fixture\n"
        "title: Fixture plan with external_refs\n"
        "type: infra\n"
        "tier: local\n"
        "status: draft\n"
        "date: '2026-05-20'\n"
        "description: external_refs fixture for F002 loader tests\n"
        "external_refs:\n"
        "  - kind: pm_issue\n"
        "    uri: linear://issue/ABC-1\n"
        "    sync: push_status\n"
        "  - kind: pm_issue\n"
        "    uri: linear://issue/ABC-2\n"
        "    sync: none\n"
        "---\n\n"
        "# Fixture\n\n"
        "## Target\n\n"
        "```yaml\n"
        "target_env: dev\n"
        "target_project: none\n"
        "```\n"
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": "2026-05-20-002-infra-bridge-fixture",
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "infra",
                        "phase": 1,
                        "description": "stub feature for loader fixture testing",
                        "steps": ["stub"],
                        "acceptance": "stub",
                        "passes": False,
                    }
                ],
            }
        )
    )
    loaded = plan_loader.load(plan_dir)
    assert len(loaded.external_refs) == 2
    assert loaded.external_refs[0].sync is ExternalRefSync.push_status
    assert loaded.external_refs[1].sync is ExternalRefSync.none


# ───────────────────────────  lock-time  ───────────────────────────


def test_lock_validates_reachable_push_status_ref():
    """Case 6: a reachable push_status ref passes lock-time validation."""

    hook = _FakeHook()
    resolver = _resolver(hook)
    ers.validate_refs_for_lock([_ref()], resolver)
    assert hook.read_calls == 1


def test_lock_blocks_when_push_status_ref_unreachable():
    """Case 7: a push_status ref whose read raises blocks lock loud."""

    hook = _FakeHook(read_should_raise=RuntimeError("404 not found"))
    resolver = _resolver(hook)
    with pytest.raises(ers.ExternalRefsSyncError) as exc:
        ers.validate_refs_for_lock([_ref()], resolver)
    assert "not reachable" in str(exc.value)
    assert "ABC-1" in str(exc.value)


def test_lock_tolerates_unreachable_sync_none_ref():
    """Case 8: sync=none + unreachable URI does NOT block lock."""

    hook = _FakeHook(read_should_raise=RuntimeError("blowup"))
    resolver = _resolver(hook)
    # No raise. Cache miss + read raise → swallowed for sync=none.
    ers.validate_refs_for_lock([_ref(sync="none")], resolver)


def test_lock_blocks_when_no_adapter_registered_for_push_status():
    """Case 9: no wrapper registered for the URI scheme + sync=push_status
    raises AdapterUnavailable (subclass of ExternalRefsSyncError)."""

    resolver = _resolver()  # empty
    with pytest.raises(ers.AdapterUnavailable):
        ers.validate_refs_for_lock([_ref()], resolver)


def test_lock_cache_short_circuits_repeat_reads():
    """Case 10: a successful read is cached per URI; re-validate doesn't
    re-hit the vendor within the same session."""

    hook = _FakeHook()
    resolver = _resolver(hook)
    ers.validate_refs_for_lock([_ref()], resolver)
    ers.validate_refs_for_lock([_ref()], resolver)
    assert hook.read_calls == 1


# ───────────────────────────  close-time  ───────────────────────────


def test_close_writes_pushed_evidence_and_does_not_block(tmp_path: Path):
    """Case 11: PUSHED ref produces status=pushed record + close stays
    unblocked (no raise from run_close_push)."""

    hook = _FakeHook()
    resolver = _resolver(hook)
    result = ers.run_close_push([_ref()], resolver, tmp_path)
    assert result.pushed_count == 1
    assert result.failed_count == 0
    on_disk = json.loads((tmp_path / ers.EVIDENCE_RELPATH).read_text())
    assert on_disk[0]["status"] == "pushed"
    assert on_disk[0]["ref_uri"] == "linear://issue/ABC-1"


def test_close_writes_failed_evidence_when_push_raises(tmp_path: Path):
    """Case 12: vendor raises → status=failed record; run_close_push
    returns normally (failures never block close)."""

    hook = _FakeHook(push_should_raise=RuntimeError("HTTP 503"))
    resolver = _resolver(hook)
    result = ers.run_close_push([_ref()], resolver, tmp_path)
    assert result.failed_count == 1
    assert result.pushed_count == 0
    on_disk = json.loads((tmp_path / ers.EVIDENCE_RELPATH).read_text())
    assert on_disk[0]["status"] == "failed"
    assert "HTTP 503" in on_disk[0]["error"]


def test_close_skips_sync_none_refs(tmp_path: Path):
    """Case 13: sync=none refs produce SKIPPED records without calling
    the hook's push_status."""

    hook = _FakeHook()
    resolver = _resolver(hook)
    result = ers.run_close_push([_ref(sync="none")], resolver, tmp_path)
    assert hook.push_calls == []
    assert result.records[0].status is ExternalSyncStatus.SKIPPED


def test_close_dry_run_writes_pending_and_does_not_call_vendor(tmp_path: Path):
    """Case 14: dry_run=True writes status=pending evidence WITHOUT
    invoking the category adapter (F002 acceptance #5). The pending
    record carries the intended status + URI so operators see the
    payload that would have been sent."""

    hook = _FakeHook()
    resolver = _resolver(hook)
    result = ers.run_close_push(
        [_ref()],
        resolver,
        tmp_path,
        dry_run=True,
    )
    # Hard contract: dry-run MUST NOT call push_status.
    assert hook.push_calls == []
    assert result.records[0].status is ExternalSyncStatus.PENDING
    on_disk = json.loads((tmp_path / ers.EVIDENCE_RELPATH).read_text())
    assert on_disk[0]["status"] == "pending"
    assert on_disk[0]["response"]["uri"] == "linear://issue/ABC-1"
    assert on_disk[0]["response"]["intended_status"] == PMStatus.DONE.value


def test_close_partial_failure_does_not_block_other_pushes(tmp_path: Path):
    """Case 14b: one failing ref + one passing ref produce a mixed
    evidence array — both records are written, neither raises."""

    # Resolver returns the same hook for both URIs (same scheme); we
    # toggle the push behavior via per-uri tracking by registering one
    # hook that raises only the first time.

    class _OneShotFailingHook(_FakeHook):
        def __init__(self) -> None:
            super().__init__()
            self._calls = 0

        def push_status(self, uri, new_status, dry_run=False):
            self._calls += 1
            self.push_calls.append((uri, new_status, dry_run))
            if self._calls == 1:
                raise RuntimeError("first push fails")
            return make_pushed_record(
                ref_uri=uri,
                kind="pm_issue",
                intended_status=new_status,
                response={"ok": True},
            )

    hook = _OneShotFailingHook()
    resolver = _resolver(hook)
    result = ers.run_close_push(
        [
            _ref("linear://issue/A-1"),
            _ref("linear://issue/A-2"),
        ],
        resolver,
        tmp_path,
    )
    statuses = sorted(r.status.value for r in result.records)
    assert statuses == ["failed", "pushed"]


# ───────────────────────────  resync + helpers  ───────────────────────────


def test_resync_replays_failed_entries_and_skips_pushed(tmp_path: Path):
    """Case 15: resync retries failed entries (succeeds → pushed) and
    leaves already-pushed entries untouched (idempotent)."""

    # Seed evidence file: one failed + one pushed entry.
    seed = [
        ers.make_failed_record(
            ref_uri="linear://issue/A-1",
            kind="pm_issue",
            intended_status=PMStatus.DONE,
            error="first attempt failed",
        ),
        make_pushed_record(
            ref_uri="linear://issue/A-2",
            kind="pm_issue",
            intended_status=PMStatus.DONE,
            response={"ok": True},
        ),
    ]
    ers.write_evidence(tmp_path, seed)

    hook = _FakeHook()
    resolver = _resolver(hook)
    result = ers.run_resync(tmp_path, resolver)

    # The failed entry was retried (1 push call); the pushed entry was
    # skipped (no second push call).
    assert len(hook.push_calls) == 1
    assert hook.push_calls[0][0] == "linear://issue/A-1"
    statuses = sorted(r.status.value for r in result.records)
    assert statuses == ["pushed", "pushed"]


def test_format_dry_run_preview_renders_intended_payload(tmp_path: Path):
    """Case 16: format_dry_run_preview emits one line per record with
    the intended payload visible to the operator."""

    hook = _FakeHook()
    resolver = _resolver(hook)
    result = ers.run_close_push(
        [_ref()],
        resolver,
        tmp_path,
        dry_run=True,
    )
    lines = ers.format_dry_run_preview(result)
    joined = "\n".join(lines)
    assert "dry-run preview" in lines[0]
    assert "PENDING linear://issue/ABC-1" in joined
    # F002 #5: dry-run constructs PENDING records directly (no vendor
    # call). Operator preview surfaces the intended status + uri.
    assert "intended_status" in joined
    assert "done" in joined


def test_close_with_no_external_refs_writes_empty_evidence(tmp_path: Path):
    """Case 17 (bonus): an empty refs iterable still creates the
    evidence path (empty array) — caller decides whether to surface it.
    """

    resolver = _resolver()
    result = ers.run_close_push([], resolver, tmp_path)
    assert result.records == ()
    on_disk = json.loads((tmp_path / ers.EVIDENCE_RELPATH).read_text())
    assert on_disk == []


def test_plan_close_cli_writes_external_sync_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Case 18: CLI close path calls the external_refs hook and writes
    evidence. This catches scope bugs hidden by the defensive close wrapper."""

    plan_dir = tmp_path / "plan"
    _write_cli_plan(
        plan_dir,
        "  - kind: pm_issue\n    uri: linear://issue/ABC-1\n    sync: push_status\n",
    )
    hook = _FakeHook()
    _patch_plan_close(monkeypatch, _resolver(hook))

    assert cli._plan_close_main([str(plan_dir)]) == 0

    assert hook.push_calls == [("linear://issue/ABC-1", PMStatus.DONE, False)]
    on_disk = json.loads((plan_dir / ers.EVIDENCE_RELPATH).read_text())
    assert on_disk[0]["status"] == "pushed"


def test_plan_close_cli_dry_run_writes_pending_without_vendor_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Case 19: CLI close --dry-run writes pending evidence and never calls
    the category adapter's push_status."""

    plan_dir = tmp_path / "plan"
    _write_cli_plan(
        plan_dir,
        "  - kind: pm_issue\n    uri: linear://issue/ABC-1\n    sync: push_status\n",
    )
    hook = _FakeHook()
    _patch_plan_close(monkeypatch, _resolver(hook))

    assert cli._plan_close_main([str(plan_dir), "--dry-run"]) == 0

    assert hook.push_calls == []
    on_disk = json.loads((plan_dir / ers.EVIDENCE_RELPATH).read_text())
    assert on_disk[0]["status"] == "pending"
    assert on_disk[0]["response"]["intended_status"] == PMStatus.DONE.value


def test_plan_close_cli_mixed_failure_writes_evidence_and_does_not_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Case 20: CLI close records mixed failed/skipped refs and still
    returns success because external sync failures do not block close."""

    plan_dir = tmp_path / "plan"
    _write_cli_plan(
        plan_dir,
        "  - kind: pm_issue\n"
        "    uri: linear://issue/ABC-1\n"
        "    sync: push_status\n"
        "  - kind: pm_issue\n"
        "    uri: linear://issue/ABC-2\n"
        "    sync: none\n",
    )
    _patch_plan_close(monkeypatch, _resolver())

    assert cli._plan_close_main([str(plan_dir)]) == 0

    on_disk = json.loads((plan_dir / ers.EVIDENCE_RELPATH).read_text())
    statuses = sorted(row["status"] for row in on_disk)
    assert statuses == ["failed", "skipped"]
    assert "No PM-tool wrapper registered" in on_disk[0]["error"]
