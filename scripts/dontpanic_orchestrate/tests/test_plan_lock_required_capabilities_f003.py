"""Plan 2026-05-22-002 F003 — required-capabilities lock-time sidecar tests.

Run: PYTHONPATH=scripts pytest \
  scripts/dontpanic_orchestrate/tests/test_plan_lock_required_capabilities_f003.py -q

Acceptance covered:
  (a) no external_refs & no requires_capabilities → no sidecar emitted.
  (b) requires_capabilities + ready capability → sidecar, no warning.
  (c) requires_capabilities + not-ready capability → sidecar + warning chip.
  (d) external_refs URI maps to registered adapter w/ capability_id → bound
      into sidecar with source='external_refs'.
  (e) Unknown capability_id in requires_capabilities → lock fails loud with
      closest-match suggestion.
  (f) Status cache absent → sidecar recomputes status.
  (g) Status cache present → sidecar reads from cache.
  (h) Plan with only external_refs whose URI doesn't map to a known adapter
      → sidecar emits empty required_capabilities[] + advisory note.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import capabilities as cap  # noqa: E402
from dontpanic_orchestrate import capabilities_lock_sidecar as sidecar  # noqa: E402
from dontpanic_orchestrate import cli  # noqa: E402
from dontpanic_orchestrate import external_refs_sync as ers  # noqa: E402
from dontpanic_orchestrate.integrations.pm_tool_models import (  # noqa: E402
    PMIssue,
    PMStatus,
)
from dontpanic_orchestrate.integrations.pm_tool_sync import (  # noqa: E402
    ExternalSyncRecord,
    make_pushed_record,
)

REPO_ROOT = HERE.parents[3]


# ───────────────────────────  helpers / fakes  ───────────────────────────


class _FakeHook:
    """Minimal PMToolSyncHook stub."""

    def __init__(self, scheme: str = "linear", service: str = "linear") -> None:
        self.service_name = service
        self.uri_scheme = scheme

    def read_issue(self, uri: str) -> PMIssue:
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
        return make_pushed_record(
            ref_uri=uri,
            kind="pm_issue",
            intended_status=new_status,
            response={"ok": True},
        )


def _write_fixture_plan(
    plan_dir: Path,
    *,
    external_refs_yaml: str = "",
    requires_capabilities_yaml: str = "",
    plan_id: str = "2026-05-22-002-feat-fixture-required-capabilities",
) -> None:
    """Write a draft plan.md with optional external_refs + requires_capabilities."""

    plan_dir.mkdir(parents=True, exist_ok=True)
    body = (
        "---\n"
        f"id: {plan_id}\n"
        "title: F003 required-capabilities lock-time sidecar fixture\n"
        "type: feat\n"
        "tier: local\n"
        "status: draft\n"
        "date: '2026-05-22'\n"
        "description: Fixture plan for F003 sidecar tests with ample length to satisfy schema.\n"
    )
    if external_refs_yaml:
        body += "external_refs:\n" + external_refs_yaml
    if requires_capabilities_yaml:
        body += "requires_capabilities:\n" + requires_capabilities_yaml
    body += "---\n\n# Fixture\n\n## Target\n\n```yaml\ntarget_env: dev\ntarget_project: none\n```\n"
    (plan_dir / "plan.md").write_text(body, encoding="utf-8")


def _resolver_with(hook: _FakeHook, *, capability_id: str | None = None) -> ers.AdapterResolver:
    resolver = ers.AdapterResolver()
    resolver.register(hook, capability_id=capability_id)
    return resolver


@pytest.fixture
def capability_index() -> cap.CapabilityIndex:
    return cap.load_capabilities(REPO_ROOT)


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the F002 cache constant at a tmp path so tests never hit the
    operator's real ``~/.dontpanic/capabilities-status.json``."""

    isolated = tmp_path / "capabilities-status.json"
    monkeypatch.setattr(sidecar, "DEFAULT_CACHE_PATH", isolated)
    return isolated


# ───────────────────────────  validate_requires_capabilities  ───


def test_unknown_capability_id_raises_with_closest_match(
    capability_index: cap.CapabilityIndex,
) -> None:
    """(e) Unknown id surfaces with a closest-match suggestion."""

    with pytest.raises(
        sidecar.RequiresCapabilityUnknownError,
        match="did you mean 'linear'",
    ):
        sidecar.validate_requires_capabilities(["linaer"], capability_index)


def test_validate_requires_capabilities_accepts_real_id(
    capability_index: cap.CapabilityIndex,
) -> None:
    """Happy path: known capability_id validates silently."""

    sidecar.validate_requires_capabilities(["linear", "firebase-dashboard"], capability_index)


def test_validate_requires_capabilities_empty_returns_silently(
    capability_index: cap.CapabilityIndex,
) -> None:
    """Empty list = no advisory binding declared; validation is a no-op."""

    sidecar.validate_requires_capabilities([], capability_index)


# ───────────────────────────  emit_required_capabilities  ───────────


def test_no_external_refs_no_requires_capabilities_returns_none(
    tmp_path: Path, capability_index: cap.CapabilityIndex
) -> None:
    """(a) Plan without bindings produces no sidecar."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(plan_dir)
    result = sidecar.emit_required_capabilities(
        plan_dir, capability_index=capability_index, resolver=ers.AdapterResolver()
    )
    assert result is None
    assert not (plan_dir / sidecar.SIDECAR_RELPATH).exists()


def test_requires_capabilities_ready_emits_sidecar_no_warning(
    tmp_path: Path,
    capability_index: cap.CapabilityIndex,
    _isolate_cache: Path,
) -> None:
    """(b) Ready capability → sidecar present, no warning chip needed."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        requires_capabilities_yaml="  - linear\n",
    )

    # Seed the cache with a ready status so the recompute path doesn't
    # pick up "needs_setup" from the operator's actual environment.
    _isolate_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolate_cache.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "generated_at": "2026-05-22T00:00:00Z",
                "advisory_notes": [],
                "capabilities": [
                    {
                        "capability_id": "linear",
                        "status": "ready",
                        "owner_boundary": {
                            "dontpanic_core": [],
                            "adapter": ["linear adapter wrapper"],
                            "operator": ["linear api token"],
                        },
                        "missing": [],
                        "next_actions": [
                            {
                                "id": "register",
                                "what": "Register the Linear adapter mapping",
                                "automatable": True,
                                "command_template": "dontpanic adapters register --service linear --token <YOUR_TOKEN>",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    out = sidecar.emit_required_capabilities(
        plan_dir, capability_index=capability_index, resolver=ers.AdapterResolver()
    )
    assert out is not None and out.is_file()
    payload = json.loads(out.read_text())
    assert payload["required_capabilities"][0]["status"] == "ready"
    assert sidecar.count_unready_capabilities(out) == 0
    # Sanitization invariant — no command_template leaked.
    for entry in payload["required_capabilities"]:
        for action in entry["next_actions"]:
            assert "command_template" not in action


def test_requires_capabilities_not_ready_emits_warning(
    tmp_path: Path,
    capability_index: cap.CapabilityIndex,
    _isolate_cache: Path,
) -> None:
    """(c) Not-ready capability → sidecar + warning chip from count helper."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        requires_capabilities_yaml="  - firebase-dashboard\n",
    )
    _isolate_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolate_cache.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "generated_at": "2026-05-22T00:00:00Z",
                "advisory_notes": [],
                "capabilities": [
                    {
                        "capability_id": "firebase-dashboard",
                        "status": "needs_setup",
                        "owner_boundary": {
                            "dontpanic_core": [],
                            "adapter": [],
                            "operator": ["firebase project select", "rules deploy"],
                        },
                        "missing": ["DONTPANIC_FIREBASE_PROJECT", "rules deploy"],
                        "next_actions": [
                            {
                                "id": "deploy-rules",
                                "what": "Deploy Firestore rules to the dev project",
                                "automatable": False,
                                "human_required_reason": "operator must select project",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    out = sidecar.emit_required_capabilities(
        plan_dir, capability_index=capability_index, resolver=ers.AdapterResolver()
    )
    assert out is not None
    assert sidecar.count_unready_capabilities(out) == 1
    payload = json.loads(out.read_text())
    entry = payload["required_capabilities"][0]
    assert entry["status"] == "needs_setup"
    assert entry["source"] == "requires_capabilities"
    assert "rules deploy" in entry["missing"]


def test_external_refs_resolves_to_registered_capability_id(
    tmp_path: Path, capability_index: cap.CapabilityIndex, _isolate_cache: Path
) -> None:
    """(d) external_refs URI scheme resolves to a registered adapter with
    capability_id binding → sidecar carries source='external_refs'."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        external_refs_yaml=("  - kind: pm_issue\n    uri: linear://issue/ABC-1\n    sync: none\n"),
    )
    resolver = _resolver_with(_FakeHook(), capability_id="linear")

    out = sidecar.emit_required_capabilities(
        plan_dir, capability_index=capability_index, resolver=resolver
    )
    assert out is not None
    payload = json.loads(out.read_text())
    entries = {e["capability_id"]: e for e in payload["required_capabilities"]}
    assert "linear" in entries
    assert entries["linear"]["source"] == "external_refs"
    assert entries["linear"]["external_ref_uris"] == ["linear://issue/ABC-1"]


def test_external_refs_unmapped_scheme_emits_empty_with_advisory(
    tmp_path: Path, capability_index: cap.CapabilityIndex
) -> None:
    """(h) external_refs but no scheme maps to a capability-bound adapter →
    sidecar emits empty array + advisory note."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        external_refs_yaml=("  - kind: pm_issue\n    uri: linear://issue/ABC-1\n    sync: none\n"),
    )
    # Resolver is empty — no adapter knows about the linear scheme.
    out = sidecar.emit_required_capabilities(
        plan_dir, capability_index=capability_index, resolver=ers.AdapterResolver()
    )
    assert out is not None
    payload = json.loads(out.read_text())
    assert payload["required_capabilities"] == []
    assert "advisory_notes" in payload
    assert any("no URI scheme resolved" in n for n in payload["advisory_notes"])


def test_multi_origin_source_remains_string_with_sources_array(
    tmp_path: Path, capability_index: cap.CapabilityIndex, _isolate_cache: Path
) -> None:
    """source field MUST be the string union 'external_refs' |
    'requires_capabilities' even when both origins reference the same
    capability_id. Multi-origin contribution is surfaced via the
    separate sources[] array, not by widening source to a list."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        external_refs_yaml=("  - kind: pm_issue\n    uri: linear://issue/ABC-1\n    sync: none\n"),
        requires_capabilities_yaml="  - linear\n",
    )
    resolver = _resolver_with(_FakeHook(), capability_id="linear")

    out = sidecar.emit_required_capabilities(
        plan_dir, capability_index=capability_index, resolver=resolver
    )
    assert out is not None
    payload = json.loads(out.read_text())
    entries = {e["capability_id"]: e for e in payload["required_capabilities"]}
    entry = entries["linear"]
    # Primary source precedence: requires_capabilities wins (explicit
    # operator declaration outweighs scheme-derived binding).
    assert entry["source"] == "requires_capabilities"
    assert isinstance(entry["source"], str)
    # Multi-origin surfaces via sources[] when more than one origin
    # contributed; consumers needing full attribution read this field.
    assert "sources" in entry
    assert set(entry["sources"]) == {"external_refs", "requires_capabilities"}


def test_emit_with_only_plan_dir_lazy_loads_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolate_cache: Path
) -> None:
    """Public contract: emit_required_capabilities(plan_dir) — no other
    args required. The function must lazy-load both the capability index
    and (when external_refs exist) the adapter resolver from their
    default factories instead of demanding caller injection."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        requires_capabilities_yaml="  - linear\n",
    )
    # Seed cache with a deterministic ready entry so we don't depend on
    # the operator's local environment for the assertion.
    _isolate_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolate_cache.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "generated_at": "2026-05-22T00:00:00Z",
                "advisory_notes": [],
                "capabilities": [
                    {
                        "capability_id": "linear",
                        "status": "ready",
                        "owner_boundary": {
                            "dontpanic_core": [],
                            "adapter": [],
                            "operator": [],
                        },
                        "missing": [],
                        "next_actions": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    out = sidecar.emit_required_capabilities(plan_dir)
    assert out is not None
    payload = json.loads(out.read_text())
    assert payload["required_capabilities"][0]["capability_id"] == "linear"
    assert payload["required_capabilities"][0]["source"] == "requires_capabilities"


def test_status_cache_absent_recomputes(
    tmp_path: Path,
    capability_index: cap.CapabilityIndex,
    _isolate_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(f) Missing cache → sidecar falls back to run_status recompute path."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        requires_capabilities_yaml="  - agent-claude-cli\n",
    )
    assert not _isolate_cache.exists()
    # Force recompute to a deterministic result so the sidecar status field
    # is predictable without depending on the operator's local env.
    called: dict[str, int] = {"n": 0}

    def _fake_run_status(*, capability_index, **_kw):
        called["n"] += 1

        class _Result:
            capability_id = "agent-claude-cli"
            status = sidecar.CapabilityStatus.READY
            owner_boundary = {
                "dontpanic_core": (),
                "adapter": (),
                "operator": ("install claude",),
            }
            missing = ()
            next_actions = (
                {
                    "id": "install",
                    "what": "Install the claude CLI",
                    "automatable": False,
                    "command_template": "brew install claude",
                    "human_required_reason": "operator must accept license",
                    "verify_probe": None,
                },
            )

        class _Envelope:
            capabilities = (_Result(),)

        return _Envelope()

    monkeypatch.setattr(sidecar, "run_status", _fake_run_status)

    out = sidecar.emit_required_capabilities(
        plan_dir, capability_index=capability_index, resolver=ers.AdapterResolver()
    )
    assert out is not None
    assert called["n"] == 1
    payload = json.loads(out.read_text())
    assert payload["required_capabilities"][0]["status"] == "ready"
    # Sanitization: command_template MUST NOT appear even via recompute.
    for action in payload["required_capabilities"][0]["next_actions"]:
        assert "command_template" not in action


def test_status_cache_present_short_circuits_recompute(
    tmp_path: Path,
    capability_index: cap.CapabilityIndex,
    _isolate_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(g) Cache present → sidecar reads from cache, does NOT recompute."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        requires_capabilities_yaml="  - linear\n",
    )
    _isolate_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolate_cache.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "generated_at": "2026-05-22T00:00:00Z",
                "advisory_notes": [],
                "capabilities": [
                    {
                        "capability_id": "linear",
                        "status": "ready",
                        "owner_boundary": {
                            "dontpanic_core": [],
                            "adapter": [],
                            "operator": [],
                        },
                        "missing": [],
                        "next_actions": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def _poison_run_status(*args, **kwargs):
        raise AssertionError("run_status must not be invoked when cache is present")

    monkeypatch.setattr(sidecar, "run_status", _poison_run_status)

    out = sidecar.emit_required_capabilities(
        plan_dir, capability_index=capability_index, resolver=ers.AdapterResolver()
    )
    assert out is not None
    payload = json.loads(out.read_text())
    assert payload["required_capabilities"][0]["status"] == "ready"


# ───────────────────────────  CLI lock-path integration  ───


def test_cli_lock_path_blocks_unknown_requires_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(e) CLI seam: unknown requires_capabilities id fails loud with the
    actionable suggestion message before lock proceeds."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        requires_capabilities_yaml="  - linaer\n",
    )

    with pytest.raises(
        sidecar.RequiresCapabilityUnknownError,
        match="did you mean 'linear'",
    ):
        cli._validate_requires_capabilities_at_lock(plan_dir)


def test_cli_lock_path_accepts_known_requires_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backward sanity: known id passes pre-flight without raising."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        requires_capabilities_yaml="  - linear\n",
    )

    cli._validate_requires_capabilities_at_lock(plan_dir)


def test_cli_lock_path_skips_validation_for_plans_without_requires_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plans without ``requires_capabilities[]`` MUST NOT trigger a
    manifest load — otherwise an operator without capabilities/ on disk
    would see lock blow up on plans that never declared a binding.

    Proof: replace the capability-index factory with a poison sentinel
    that raises if called."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(plan_dir)

    def _poison() -> cap.CapabilityIndex:
        raise AssertionError("capability_index factory must not be invoked")

    monkeypatch.setattr(cli, "_CAPABILITY_INDEX_FACTORY", _poison)

    cli._validate_requires_capabilities_at_lock(plan_dir)


def test_cli_emit_sidecar_writes_to_evidence_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _isolate_cache: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Integration: the post-lock helper emits the sidecar and prints the
    warning chip when any capability is not ready."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        requires_capabilities_yaml="  - firebase-dashboard\n",
    )
    # Seed cache so the test is deterministic regardless of operator env.
    _isolate_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolate_cache.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "generated_at": "2026-05-22T00:00:00Z",
                "advisory_notes": [],
                "capabilities": [
                    {
                        "capability_id": "firebase-dashboard",
                        "status": "needs_setup",
                        "owner_boundary": {
                            "dontpanic_core": [],
                            "adapter": [],
                            "operator": ["project select"],
                        },
                        "missing": ["DONTPANIC_FIREBASE_PROJECT"],
                        "next_actions": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cli._emit_required_capabilities_sidecar(plan_dir)

    out = plan_dir / sidecar.SIDECAR_RELPATH
    assert out.is_file()
    captured = capsys.readouterr()
    assert "WARN: plan requires 1 capabilities not ready" in captured.out
