"""Plan 2026-05-21-001 F004 — external_refs capability_id binding tests.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_external_refs_sync_capability_binding_f004.py -q

Acceptance covered:
  (1) ExternalRef supports optional capability_id.
  (2) PM-tool push refs bind to registered adapters by capability_id.
  (3) Invalid or incompatible capability IDs fail with actionable errors.
  (4) sync=none remains non-blocking.
  (5) Existing external_refs tests remain green (covered by the F002 suite,
      which still passes after this change; the changes are strictly
      additive on the ExternalRef model and the resolver).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import capabilities as cap  # noqa: E402
from dontpanic_orchestrate import cli  # noqa: E402
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

_SCHEMAS = HERE.parents[2].parent / "claude" / "shared" / "schemas" / "v1.0"
sys.path.insert(0, str(_SCHEMAS))
from models.plan_model import ExternalRef, ExternalRefKind, ExternalRefSync  # noqa: E402

REPO_ROOT = HERE.parents[3]


# ───────────────────────────  helpers / fakes  ───────────────────────────


class _FakeHook:
    """Minimal PMToolSyncHook stub for resolver tests."""

    def __init__(self, scheme: str = "linear", service: str = "linear") -> None:
        self.service_name = service
        self.uri_scheme = scheme
        self.read_calls = 0
        self.push_calls: list[tuple[str, PMStatus, bool]] = []

    def read_issue(self, uri: str) -> PMIssue:
        self.read_calls += 1
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
        return make_pushed_record(
            ref_uri=uri,
            kind="pm_issue",
            intended_status=new_status,
            response={"ok": True},
        )


def _ref(
    *,
    uri: str = "linear://issue/ABC-1",
    sync: str = "push_status",
    capability_id: str | None = "linear",
) -> ExternalRef:
    return ExternalRef(
        kind=ExternalRefKind.pm_issue,
        uri=uri,
        sync=ExternalRefSync(sync),
        capability_id=capability_id,
    )


@pytest.fixture(autouse=True)
def _reset_read_cache():
    ers.reset_read_cache()
    yield
    ers.reset_read_cache()


# ───────────────────────────  (1) ExternalRef accepts capability_id  ───


def test_external_ref_accepts_capability_id() -> None:
    ref = _ref(capability_id="linear")
    assert ref.capability_id == "linear"
    # Round-trip via model_dump.
    restored = ExternalRef.model_validate(ref.model_dump())
    assert restored.capability_id == "linear"


def test_external_ref_default_capability_id_is_none() -> None:
    """Backward compatibility: legacy refs without capability_id parse."""

    ref = ExternalRef.model_validate(
        {
            "kind": "pm_issue",
            "uri": "linear://issue/ABC-1",
            "sync": "push_status",
        }
    )
    assert ref.capability_id is None


def test_external_ref_rejects_malformed_capability_id() -> None:
    """capability_id must match ``^[a-z0-9][a-z0-9-]*$`` — uppercase rejected."""

    with pytest.raises(ValidationError):
        ExternalRef.model_validate(
            {
                "kind": "pm_issue",
                "uri": "linear://issue/ABC-1",
                "sync": "none",
                "capability_id": "Linear-BadCaps",
            }
        )


# ───────────────────────────  (3) capability validation  ───


def test_validate_capability_bindings_accepts_real_linear_ref() -> None:
    """Linear ref bound to the real ``linear`` manifest validates."""

    index = cap.load_capabilities(REPO_ROOT)
    ers.validate_capability_bindings([_ref(capability_id="linear")], index)


def test_validate_capability_bindings_skips_refs_without_capability_id() -> None:
    """Legacy refs (no capability_id) are not validated against the index."""

    empty_index = cap.CapabilityIndex([])
    ers.validate_capability_bindings(
        [_ref(capability_id=None)],
        empty_index,
    )


def test_validate_capability_bindings_rejects_unknown_id() -> None:
    """(3) Unknown capability_id is actionable, regardless of sync mode."""

    index = cap.load_capabilities(REPO_ROOT)
    with pytest.raises(ers.ExternalRefCapabilityBindingError, match="unknown capability_id"):
        ers.validate_capability_bindings([_ref(capability_id="not-a-capability")], index)


def test_validate_capability_bindings_rejects_incompatible_category() -> None:
    """(3) PM-tool ref bound to a non-pm-tool capability fails with the
    category mismatch named explicitly. ``firebase-dashboard`` has
    category ``dashboard-realtime``, not ``pm-tool``."""

    index = cap.load_capabilities(REPO_ROOT)
    with pytest.raises(
        ers.ExternalRefCapabilityBindingError,
        match="manifest category is 'dashboard-realtime'",
    ):
        ers.validate_capability_bindings([_ref(capability_id="firebase-dashboard")], index)


def test_validate_refs_for_lock_runs_capability_validation_first() -> None:
    """validate_refs_for_lock surfaces capability errors before resolver
    lookups so an unknown id fails with the actionable message even when
    no adapter is registered."""

    index = cap.load_capabilities(REPO_ROOT)
    resolver = ers.AdapterResolver()
    with pytest.raises(ers.ExternalRefCapabilityBindingError, match="unknown capability_id"):
        ers.validate_refs_for_lock(
            [_ref(capability_id="not-a-capability")],
            resolver,
            capability_index=index,
        )


# ───────────────────────────  (2) resolver routes by capability_id  ───


def test_resolver_register_accepts_capability_id() -> None:
    resolver = ers.AdapterResolver()
    hook = _FakeHook()
    resolver.register(hook, capability_id="linear")
    assert resolver.has("linear")
    assert resolver.has_capability_id("linear")
    assert resolver.resolve_by_capability_id("linear") is hook


def test_resolver_resolve_by_unknown_capability_id_raises() -> None:
    resolver = ers.AdapterResolver()
    with pytest.raises(ers.AdapterUnavailable, match="capability_id='linear'"):
        resolver.resolve_by_capability_id("linear")


def test_resolver_register_rejects_duplicate_capability_id() -> None:
    resolver = ers.AdapterResolver()
    resolver.register(_FakeHook(scheme="linear"), capability_id="linear")
    with pytest.raises(ers.ExternalRefsSyncError, match="capability_id='linear'"):
        # Same capability_id, different scheme — must fail loud rather than
        # silently overwriting the first registration.
        resolver.register(_FakeHook(scheme="linear-mirror"), capability_id="linear")


def test_lock_with_capability_id_routes_through_capability_index() -> None:
    """(2) When the ref has capability_id, resolver uses the capability
    index — not the URI scheme — to find the hook."""

    index = cap.load_capabilities(REPO_ROOT)
    hook = _FakeHook()
    resolver = ers.AdapterResolver()
    resolver.register(hook, capability_id="linear")
    ers.validate_refs_for_lock(
        [_ref(capability_id="linear")],
        resolver,
        capability_index=index,
    )
    assert hook.read_calls == 1


def test_lock_push_status_with_capability_id_no_matching_adapter_blocks() -> None:
    """(2) sync=push_status + capability_id set + no adapter registered
    with that capability_id ⇒ AdapterUnavailable. Even if a same-scheme
    adapter is registered without capability_id binding, the
    capability-aware lookup MUST fail loud."""

    index = cap.load_capabilities(REPO_ROOT)
    resolver = ers.AdapterResolver()
    # Register a same-scheme hook WITHOUT capability_id — proves the
    # capability lookup is not falling back to scheme.
    resolver.register(_FakeHook(), capability_id=None)
    with pytest.raises(ers.AdapterUnavailable, match="capability_id='linear'"):
        ers.validate_refs_for_lock(
            [_ref(capability_id="linear", sync="push_status")],
            resolver,
            capability_index=index,
        )


def test_lock_cache_does_not_bypass_capability_bound_adapter_lookup() -> None:
    """A legacy same-URI cache hit must not satisfy a later capability-bound ref.

    Regression for the F004 iter1 auditor finding: `_READ_CACHE` used to
    be keyed only by URI and checked before capability-aware resolution,
    so a legacy validation of `linear://issue/ABC-1` could let a
    `capability_id: linear` push ref pass without any registered adapter
    for that capability.
    """

    index = cap.load_capabilities(REPO_ROOT)
    resolver = ers.AdapterResolver()
    legacy_hook = _FakeHook()
    resolver.register(legacy_hook, capability_id=None)

    ers.validate_refs_for_lock(
        [_ref(capability_id=None, sync="push_status")],
        resolver,
    )
    assert legacy_hook.read_calls == 1

    with pytest.raises(ers.AdapterUnavailable, match="capability_id='linear'"):
        ers.validate_refs_for_lock(
            [_ref(capability_id="linear", sync="push_status")],
            resolver,
            capability_index=index,
        )
    assert legacy_hook.read_calls == 1


def test_lock_sync_none_with_unbound_capability_does_not_block() -> None:
    """(4) sync=none + capability_id with no matching adapter ⇒ no raise.
    Capability validation still passes (the manifest exists) and the
    missing-adapter case is treated as informational because the ref is
    not push_status."""

    index = cap.load_capabilities(REPO_ROOT)
    resolver = ers.AdapterResolver()  # no adapters registered
    ers.validate_refs_for_lock(
        [_ref(capability_id="linear", sync="none")],
        resolver,
        capability_index=index,
    )


def test_lock_without_capability_id_uses_scheme_resolution() -> None:
    """Legacy refs (no capability_id) keep using scheme-based resolution.
    This protects existing plans that pre-date F004."""

    hook = _FakeHook()
    resolver = ers.AdapterResolver()
    resolver.register(hook, capability_id=None)
    # Note: capability_index unset — backward compatibility path.
    ers.validate_refs_for_lock(
        [_ref(capability_id=None, sync="push_status")],
        resolver,
    )
    assert hook.read_calls == 1


# ───────────────────────────  close-time wiring  ───


def test_close_push_resolves_by_capability_id_when_present(tmp_path: Path) -> None:
    """close-time also prefers capability_id-based resolution. The hook
    registered with capability_id='linear' receives the push call."""

    hook = _FakeHook()
    resolver = ers.AdapterResolver()
    resolver.register(hook, capability_id="linear")
    result = ers.run_close_push([_ref(capability_id="linear")], resolver, tmp_path)
    assert hook.push_calls and hook.push_calls[0][0] == "linear://issue/ABC-1"
    assert result.pushed_count == 1


def test_close_push_with_unbound_capability_records_failure(tmp_path: Path) -> None:
    """If sync=push_status and the capability_id is unbound at close
    time, the evidence record carries status=failed (close stays
    unblocked — failures never raise)."""

    resolver = ers.AdapterResolver()
    # Register a same-scheme hook WITHOUT capability_id binding. The
    # capability-aware close lookup must not fall back to it.
    resolver.register(_FakeHook(), capability_id=None)
    result = ers.run_close_push(
        [_ref(capability_id="linear", sync="push_status")],
        resolver,
        tmp_path,
    )
    assert result.failed_count == 1
    assert "capability_id='linear'" in (result.records[0].error or "")


def test_close_push_sync_none_with_capability_id_skips(tmp_path: Path) -> None:
    """(4) sync=none refs produce SKIPPED records regardless of
    capability_id — even with no matching adapter, close stays
    unblocked."""

    resolver = ers.AdapterResolver()  # empty
    result = ers.run_close_push(
        [_ref(capability_id="linear", sync="none")],
        resolver,
        tmp_path,
    )
    assert result.records[0].status is ExternalSyncStatus.SKIPPED


# ───────────────────────────  CLI lock-path integration  ───
#
# These tests exercise the real consumer path: cli._validate_external_refs_at_lock
# loads `external_refs[]` from plan.md frontmatter, then calls
# validate_refs_for_lock with the capability manifest index. The pure
# validate_refs_for_lock(..., capability_index=...) tests above don't cover
# the CLI seam — without these, a missing `capability_index=` kwarg at the
# CLI call site would silently regress the contract.


def _write_lock_fixture_plan(plan_dir: Path, ref_yaml_body: str) -> None:
    """Write a plan.md with a status=draft + external_refs[] frontmatter
    block. Mirrors the F002 fixture writer but stays draft so a future
    sufficiency-gate hookup doesn't need to keep this fixture warm."""

    plan_dir.mkdir()
    (plan_dir / "plan.md").write_text(
        "---\n"
        "id: 2026-05-21-001-f004-lock-path-fixture\n"
        "title: F004 lock-path capability binding fixture\n"
        "type: infra\n"
        "tier: local\n"
        "status: draft\n"
        "date: '2026-05-21'\n"
        "description: Fixture plan for F004 CLI lock-path capability binding tests.\n"
        "external_refs:\n"
        f"{ref_yaml_body}"
        "---\n\n"
        "# Fixture\n\n"
        "## Target\n\n"
        "```yaml\n"
        "target_env: dev\n"
        "target_project: none\n"
        "```\n"
    )


def test_cli_lock_path_blocks_incompatible_capability_even_when_sync_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(3) CLI consumer path: _validate_external_refs_at_lock with
    frontmatter ``capability_id: firebase-dashboard`` (category
    ``dashboard-realtime``) on a ``pm_issue`` ref MUST raise
    :class:`ExternalRefCapabilityBindingError` — even though ``sync:
    none`` would otherwise tolerate adapter problems. Capability binding
    errors are config errors, not runtime reachability issues, and must
    be loud regardless of sync mode.

    This catches scope regressions in
    :func:`cli._validate_external_refs_at_lock` that would drop the
    ``capability_index=`` kwarg and silently downgrade incompatible
    bindings to advisory."""

    plan_dir = tmp_path / "plan"
    _write_lock_fixture_plan(
        plan_dir,
        "  - kind: pm_issue\n"
        "    uri: linear://issue/ABC-1\n"
        "    sync: none\n"
        "    capability_id: firebase-dashboard\n",
    )
    # Empty resolver — capability validation must run first, so resolver
    # state is irrelevant. Forcing an empty resolver also proves the test
    # isn't accidentally validating reachability instead of bindings.
    monkeypatch.setattr(cli, "_RESOLVER_FACTORY", lambda: ers.AdapterResolver())

    with pytest.raises(
        ers.ExternalRefCapabilityBindingError,
        match="manifest category is 'dashboard-realtime'",
    ):
        cli._validate_external_refs_at_lock(plan_dir)


def test_cli_lock_path_blocks_unknown_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(3) CLI consumer path: unknown capability_id fails with the
    actionable error from the real load_capabilities()-backed index, not
    a silent fall-through to scheme-based resolution."""

    plan_dir = tmp_path / "plan"
    _write_lock_fixture_plan(
        plan_dir,
        "  - kind: pm_issue\n"
        "    uri: linear://issue/ABC-1\n"
        "    sync: push_status\n"
        "    capability_id: not-a-capability\n",
    )
    monkeypatch.setattr(cli, "_RESOLVER_FACTORY", lambda: ers.AdapterResolver())

    with pytest.raises(ers.ExternalRefCapabilityBindingError, match="unknown capability_id"):
        cli._validate_external_refs_at_lock(plan_dir)


def test_cli_lock_path_legacy_ref_without_capability_id_skips_manifest_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backward compatibility: plans with only legacy refs (no
    ``capability_id``) MUST NOT trigger a manifest load — otherwise an
    operator without a capabilities directory checked in would see lock
    blow up on plans that never declared a capability binding.

    Proof: we replace the capability-index factory with a poison sentinel
    that raises if called. The lock path should validate via the
    resolver only and never touch the factory."""

    plan_dir = tmp_path / "plan"
    _write_lock_fixture_plan(
        plan_dir,
        "  - kind: pm_issue\n    uri: linear://issue/ABC-1\n    sync: push_status\n",
    )

    def _poison() -> cap.CapabilityIndex:
        raise AssertionError("capability_index factory must not be invoked for legacy refs")

    monkeypatch.setattr(cli, "_CAPABILITY_INDEX_FACTORY", _poison)
    monkeypatch.setattr(cli, "_RESOLVER_FACTORY", lambda: _resolver_with(_FakeHook()))

    cli._validate_external_refs_at_lock(plan_dir)


def test_cli_lock_path_accepts_real_linear_capability_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path through the CLI seam: a ``pm_issue`` ref bound to the
    real ``linear`` manifest with a registered adapter passes lock
    validation end-to-end. Anchors the bug-free baseline so the
    incompatible/unknown tests above prove the negative case."""

    plan_dir = tmp_path / "plan"
    _write_lock_fixture_plan(
        plan_dir,
        "  - kind: pm_issue\n"
        "    uri: linear://issue/ABC-1\n"
        "    sync: push_status\n"
        "    capability_id: linear\n",
    )
    hook = _FakeHook()
    monkeypatch.setattr(
        cli,
        "_RESOLVER_FACTORY",
        lambda: _resolver_with(hook, capability_id="linear"),
    )

    cli._validate_external_refs_at_lock(plan_dir)
    assert hook.read_calls == 1


def _resolver_with(hook: _FakeHook, *, capability_id: str | None = None) -> ers.AdapterResolver:
    resolver = ers.AdapterResolver()
    resolver.register(hook, capability_id=capability_id)
    return resolver
