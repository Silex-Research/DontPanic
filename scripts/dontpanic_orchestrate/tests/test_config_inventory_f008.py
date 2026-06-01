"""Tests for config_inventory — Plan 2026-05-30-001 F008.

Covers acceptance items (1)-(8): one-command inventory of every config surface
(>=10 providers), JSON shape, dashboard Settings/Setup state shape, safe-command
routing through validated surfaces, secret-safe output (no secret values),
optional-vs-required classification, project-scoped overrides, active/inactive
dashboard hints, dashboard-hint deduplication, and the setup/update planner.

The autouse ``_isolate_jarvis_state`` conftest fixture redirects DONTPANIC_HOME /
JARVIS_HOME to a per-test tmp dir, so every inventory here runs against a clean
home with no global config / registry / manifest.
"""
from __future__ import annotations

import json

import pytest

from dontpanic_orchestrate import config_inventory as ci


# ───────────────────────────── helpers ─────────────────────────────


def _by_id(inv: ci.Inventory, item_id: str) -> ci.InventoryItem:
    return next(i for i in inv.items if i.id == item_id)


# EXACT, runnable, placeholder-free commands a ``safe_command`` is allowed to
# be. Anything arg-taking (`roles set <role> <executor>`, `project config set
# <key> <value>`, …) is a TEMPLATE and must live in
# ``dashboard_mutation_shape.command_template`` — never in ``safe_command``
# (audit finding: safe_command must be exact + validated). install_reconcile
# emits one of two reconcile commands depending on split-home state.
_EXACT_SAFE_COMMANDS = {
    "dontpanic project config init",
    "dontpanic manifest init",
    "dontpanic quota-caps init",
    "dontpanic reconcile baseline",
    "dontpanic reconcile homes --dry-run",
}

# Acceptance-listed validated edit routes (step 5). Each must be reachable —
# either as an exact safe_command above, or as a mutation command template.
_REQUIRED_ROUTE_SUBSTRINGS = (
    "dontpanic roles set",
    "dontpanic project config set",
    "dontpanic capabilities setup",
    "dontpanic quota-caps init",
    "dontpanic reconcile",
    "dontpanic projects add",
)


# ─────────────────── (1)+(2) completeness: >=10 providers ───────────────────


def test_inventory_covers_at_least_ten_providers():
    inv = ci.collect_inventory()
    assert len(inv.items) >= 10
    # The acceptance-named surfaces must all be present.
    ids = {i.id for i in inv.items}
    required = {
        "global_config",
        "project_config",
        "projects_registry",
        "agent_manifest",
        "roles",
        "runtime_evidence",
        "gates_paths",
        "quota",
        "circuit_breakers",
        "notifications",
        "dashboard",
        "capabilities",
        "mcp",
        "environments",
        "install_reconcile",
        "pm_credentials",
        "secret_anthropic_auth",
    }
    missing = required - ids
    assert not missing, f"missing inventory providers: {sorted(missing)}"


def test_every_item_carries_required_model_fields():
    inv = ci.collect_inventory()
    for item in inv.items:
        assert isinstance(item.scope, ci.Scope)
        assert isinstance(item.status, ci.Status)
        assert item.title
        assert item.owner_file_or_env
        # current_value_summary may be empty only for UNKNOWN fallbacks.
        assert item.current_value_summary or item.status is ci.Status.UNKNOWN


# ───────────────────────────── (2) JSON shape ──────────────────────────────


def test_inventory_to_dict_is_json_serializable_and_shaped():
    inv = ci.collect_inventory()
    d = inv.to_dict()
    blob = json.dumps(d)  # must not raise
    assert blob
    assert set(d.keys()) >= {"project_name", "project_path", "items", "dashboard_hint"}
    for item in d["items"]:
        assert set(item.keys()) >= {
            "id",
            "title",
            "scope",
            "status",
            "editable",
            "human_required",
            "optional",
            "current_value_summary",
            "owner_file_or_env",
            "safe_command",
            "dashboard_mutation_shape",
            "risks",
            "doctor_probes",
            "dashboard_hint_ref",
        }


# ──────────────────────── (3) dashboard state shape ─────────────────────────


def test_dashboard_state_splits_settings_and_setup_cards():
    inv = ci.collect_inventory()
    state = ci.to_dashboard_state(inv)
    assert state["kind"] == "config_inventory"
    assert "settings_cards" in state and "setup_cards" in state
    # Setup cards are exactly the incomplete items.
    setup_ids = {c["id"] for c in state["setup_cards"]}
    incomplete_ids = {i.id for i in inv.incomplete_items()}
    assert setup_ids == incomplete_ids
    # No item appears in both buckets.
    settings_ids = {c["id"] for c in state["settings_cards"]}
    assert settings_ids.isdisjoint(setup_ids)
    json.dumps(state)  # serializable


# ──────────────────── (5) safe-command routing validation ───────────────────


def test_safe_commands_are_exact_runnable_validated_commands():
    # Every emitted safe_command must be an EXACT command from the allowlist:
    # no placeholders, no build/serve surfaces, no `config set roles.*`.
    inv = ci.collect_inventory()
    for item in inv.items:
        if not item.safe_command:
            continue
        cmd = item.safe_command
        assert cmd.startswith("dontpanic "), f"{item.id}: {cmd!r}"
        # No template placeholders may leak into a runnable command.
        assert "<" not in cmd and ">" not in cmd, f"{item.id}: placeholder in {cmd!r}"
        # Must match a known exact, validated edit command verbatim.
        assert cmd in _EXACT_SAFE_COMMANDS, f"{item.id}: {cmd!r} not an exact validated command"


def test_every_safe_command_passes_command_validation(tmp_path):
    # AC5b / AC8 round-trip: EVERY non-null safe_command must be a real,
    # validated CLI invocation — it must PASS command_validation.validate_command_tokens
    # after stripping the `dontpanic` / `python -m dontpanic_orchestrate` prefix.
    # A string-equality allowlist is not enough; this drives the actual validator
    # so an unrunnable shape (wrong subcommand, missing required flag, a
    # build/serve surface) can never ride along as an "edit" affordance.
    from dontpanic_orchestrate import command_validation as cv

    # Exercise both the machine scope and a project scope so project-scoped
    # providers (project_config init, runtime_evidence, gates) also contribute
    # their safe_commands to the round-trip.
    proj = tmp_path / "repo"
    (proj / ".dontpanic").mkdir(parents=True)
    (proj / ".dontpanic" / "dontpanic.json").write_text(json.dumps({"implementer": "claude"}))

    for inv in (ci.collect_inventory(), ci.collect_inventory(project=str(proj))):
        for item in inv.items:
            if not item.safe_command:
                continue
            tokens = item.safe_command.split()
            # Strip the CLI prefix the validator does not expect.
            if tokens[:1] == ["dontpanic"]:
                tokens = tokens[1:]
            elif tokens[:3] == ["python", "-m", "dontpanic_orchestrate"]:
                tokens = tokens[3:]
            result = cv.validate_command_tokens(tokens)
            assert result.ok, f"{item.id}: safe_command {item.safe_command!r} failed validation: {result.reason}"


def test_setup_plan_exact_commands_pass_command_validation():
    # The planner's automatable choices carry exact_command — those must be
    # validated too (they are the same safe_command the inventory emits).
    from dontpanic_orchestrate import command_validation as cv

    inv = ci.collect_inventory()
    plan = ci.build_setup_plan(inv)
    for choice in plan["choices"]:
        cmd = choice.get("exact_command")
        if not cmd:
            continue
        tokens = cmd.split()
        if tokens[:1] == ["dontpanic"]:
            tokens = tokens[1:]
        assert cv.validate_command_tokens(tokens).ok, f"{choice['id']}: {cmd!r}"


def test_no_safe_command_is_a_build_or_serve_surface():
    # `dashboard build` / `mcp serve` are start/build surfaces, not config
    # edits — they must NOT appear as safe_command (audit finding).
    inv = ci.collect_inventory()
    safe_cmds = {i.safe_command for i in inv.items if i.safe_command}
    for forbidden in ("dontpanic dashboard build", "dontpanic mcp serve"):
        assert forbidden not in safe_cmds, forbidden
    # Global role edits must route through `roles set`, never `config set roles.*`.
    for cmd in safe_cmds:
        assert not cmd.startswith("dontpanic config set"), cmd


def test_placeholder_in_safe_command_is_rejected_at_construction():
    # The InventoryItem invariant refuses a placeholder safe_command outright,
    # so a future provider cannot regress past the exact-command contract.
    with pytest.raises(ValueError):
        ci.InventoryItem(
            id="bad",
            title="bad",
            scope=ci.Scope.MACHINE,
            status=ci.Status.NEEDS_SETUP,
            editable=True,
            human_required=False,
            optional=False,
            current_value_summary="x",
            owner_file_or_env="x",
            safe_command="dontpanic roles set <role> <executor>",
        )


def test_acceptance_listed_edit_routes_are_all_reachable():
    # AC5 / step 5: each validated edit route must be reachable, either as an
    # exact safe_command or as a mutation command template.
    inv = ci.collect_inventory()
    reachable: set[str] = set()
    for item in inv.items:
        if item.safe_command:
            reachable.add(item.safe_command)
        shape = item.dashboard_mutation_shape or {}
        tmpl = shape.get("command_template") or shape.get("command")
        if tmpl:
            reachable.add(tmpl)
    blob = " || ".join(reachable)
    for route in _REQUIRED_ROUTE_SUBSTRINGS:
        assert route in blob, f"validated route not reachable anywhere: {route!r}"


def test_arg_taking_routes_are_templates_not_safe_commands():
    # roles / project-config / capabilities-setup / projects-add all take
    # arguments, so they must surface as command_template (not safe_command).
    inv = ci.collect_inventory()
    for item_id in ("roles", "capabilities", "projects_registry"):
        item = _by_id(inv, item_id)
        assert item.safe_command is None, f"{item_id} should not carry a safe_command"
        shape = item.dashboard_mutation_shape or {}
        assert shape.get("command_template") or shape.get("command"), item_id


def test_secret_items_never_carry_a_safe_command():
    inv = ci.collect_inventory()
    secrets = [i for i in inv.items if i.scope is ci.Scope.SECRET]
    assert secrets, "expected at least one secret-scope item"
    for item in secrets:
        assert item.safe_command is None
        assert item.dashboard_mutation_shape is None


# ─────────────────────── (5) secret-safe / no-secret output ─────────────────


def test_secret_output_reports_status_only_never_the_value(monkeypatch):
    fake_key = "sk-ant-FAKE0000000000000000000000000000SECRET"
    monkeypatch.setenv("ANTHROPIC_API_KEY", fake_key)
    inv = ci.collect_inventory()
    item = _by_id(inv, "secret_anthropic_auth")
    # Configured → "configured", and the value must appear NOWHERE in output.
    assert item.current_value_summary == "configured"
    blob = json.dumps(inv.to_dict())
    assert fake_key not in blob
    state_blob = json.dumps(ci.to_dashboard_state(inv))
    assert fake_key not in state_blob


def test_discord_webhook_value_is_redacted_from_summary(monkeypatch):
    # A discord webhook URL is a secret shape; even if a provider summary echoed
    # it, scrub_secrets must remove it before output.
    webhook = "https://discord.com/api/webhooks/123456789012345678/abcdEFGHijklMNOPqrstUVWXyz"
    monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", webhook)
    inv = ci.collect_inventory()
    blob = json.dumps(inv.to_dict())
    assert webhook not in blob


# ───────────────── (4) optional-vs-required classification ──────────────────


def test_optional_capabilities_are_labeled_optional_and_nonblocking():
    inv = ci.collect_inventory()
    # Firebase/Discord/MCP/dashboard/capabilities/PM are optional integrations.
    for opt_id in (
        "environments",
        "notifications",
        "mcp",
        "dashboard",
        "capabilities",
        "pm_credentials",
    ):
        item = _by_id(inv, opt_id)
        assert item.optional is True, opt_id
        # Optional items, when unconfigured, never land in the required "incomplete"
        # bucket (they use OPTIONAL_UNCONFIGURED, not NEEDS_SETUP/MISSING).
        assert item.status is not ci.Status.NEEDS_SETUP
        assert item.status is not ci.Status.MISSING


def test_capabilities_status_not_optimistic_when_none_ready():
    # AC2b (audit finding): the capabilities aggregate must NOT report `ok`
    # while 0 adapters are ready. It derives status from the dedicated capability
    # surface's run_status — when no adapter is ready it is OPTIONAL_UNCONFIGURED,
    # never OK — while staying optional so core use is not blocked.
    from dontpanic_orchestrate import capabilities, capabilities_status

    item = _by_id(ci.collect_inventory(), "capabilities")
    envelope = capabilities_status.run_status(capability_index=capabilities.load_capabilities(None))
    ready = sum(1 for c in envelope.capabilities if c.status.value == "ready")
    if ready == 0:
        assert item.status is ci.Status.OPTIONAL_UNCONFIGURED
        assert item.status is not ci.Status.OK
    else:
        assert item.status is ci.Status.OK
    # Either way it stays optional (AC4) — never a required-incomplete surface.
    assert item.optional is True
    assert item.status is not ci.Status.NEEDS_SETUP
    assert item.status is not ci.Status.MISSING


def test_quota_status_non_ok_when_calibration_absent(monkeypatch):
    # AC2b/AC2c (audit finding, codex i1): quota must NOT report `ok` when caps
    # are present but calibration is absent — the breaker is uncalibrated and the
    # surface is incomplete. It reports NEEDS_SETUP, names the missing piece, and
    # routes to the calibration command (a template, since it takes operator args).
    from dontpanic_orchestrate import calibration_loader, quota_caps_loader

    caps = quota_caps_loader.effective_caps_path()
    caps.parent.mkdir(parents=True, exist_ok=True)
    caps.write_text(json.dumps({"schema_version": 2, "vendors": {}}))
    monkeypatch.setattr(calibration_loader, "load", lambda *a, **k: {})

    item = ci.provider_quota(ci.InventoryContext())
    assert item.status is not ci.Status.OK
    assert item.status is ci.Status.NEEDS_SETUP
    assert item.is_incomplete
    assert "calibration absent" in item.current_value_summary
    assert "calibrate-claude" in item.current_value_summary
    # The arg-taking calibration route is a TEMPLATE, never an exact safe_command.
    assert item.safe_command is None
    shape = item.dashboard_mutation_shape or {}
    assert "dontpanic calibrate-claude" in (shape.get("command_template") or "")


def test_quota_status_ok_only_when_caps_and_calibration_present(monkeypatch):
    from dontpanic_orchestrate import calibration_loader, quota_caps_loader

    caps = quota_caps_loader.effective_caps_path()
    caps.parent.mkdir(parents=True, exist_ok=True)
    caps.write_text(json.dumps({"schema_version": 2, "vendors": {}}))
    monkeypatch.setattr(
        calibration_loader,
        "load",
        lambda *a, **k: {"schema_version": 1, "claude": {"rolling_7d": {"ratio": 1e-8}}},
    )

    item = ci.provider_quota(ci.InventoryContext())
    assert item.status is ci.Status.OK
    # The caps re-init route is exact + runnable, so it may carry a safe_command.
    assert item.safe_command == "dontpanic quota-caps init"


# ───────── (2d) present-but-unloadable config + tripped breaker → non-ok ─────
#
# AC2d (audit i0 findings): these REAL invalid-state regressions fail before the
# fix (the prior code keyed status off file existence / hardcoded Status.OK) and
# pass after. They are NOT trivially-passing weak cases (missing file, no
# project): each arranges an actually-unloadable file or an actually-tripped
# breaker.


def test_global_config_present_but_unloadable_is_non_ok():
    # A present config file that does not parse must report non-ok, distinct
    # from the absent first-run state. The loader swallows the error (degrades to
    # an empty config without raising), so the provider must probe loadability.
    from dontpanic_orchestrate import global_config as gc

    path = gc.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not valid json ::::")
    # Loader degrades silently (the bug surface): it does NOT raise.
    assert gc.load_config() is not None

    item = ci.provider_global_config(ci.InventoryContext())
    assert item.status is not ci.Status.OK
    assert item.status is ci.Status.NEEDS_SETUP
    assert item.is_incomplete
    assert "UNLOADABLE" in item.current_value_summary


def test_global_config_present_but_schema_invalid_is_non_ok():
    # Valid JSON but a forbidden/extra field → schema validation fails. The
    # loader degrades to empty; the provider must still report non-ok.
    from dontpanic_orchestrate import global_config as gc

    path = gc.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"totally_unknown_field": 123}))

    item = ci.provider_global_config(ci.InventoryContext())
    assert item.status is not ci.Status.OK
    assert item.is_incomplete


def test_project_config_present_but_unloadable_is_non_ok(tmp_path):
    proj = tmp_path / "brokenrepo"
    (proj / ".dontpanic").mkdir(parents=True)
    (proj / ".dontpanic" / "dontpanic.json").write_text("{ broken ::::")
    inv = ci.collect_inventory(project=str(proj))
    pc_item = _by_id(inv, "project_config")
    assert pc_item.status is not ci.Status.OK
    assert pc_item.status is ci.Status.NEEDS_SETUP
    assert pc_item.is_incomplete
    assert "UNLOADABLE" in pc_item.current_value_summary


def test_circuit_breaker_tripped_is_non_ok():
    # A genuinely tripped global breaker (threshold iteration-cap hits in window)
    # must report non-ok — never `ok`. The prior provider hardcoded Status.OK.
    from dontpanic_orchestrate import circuit_breakers as cb

    for _ in range(cb.GLOBAL_THRESHOLD_HITS):
        cb.record_global_hit("plan-x", cb.BreakerKind.ITERATION_CAP)
    assert cb.evaluate_global().tripped is True

    item = ci.provider_circuit_breakers(ci.InventoryContext())
    assert item.status is not ci.Status.OK
    assert item.status is ci.Status.NEEDS_SETUP
    assert "TRIPPED" in item.current_value_summary


def test_circuit_breaker_clear_is_ok():
    # A clear breaker (fresh isolated history) reports OK — the fix must not
    # regress the healthy path into a false alarm.
    item = ci.provider_circuit_breakers(ci.InventoryContext())
    assert item.status is ci.Status.OK


# ─────────── (2c) class-wide non-optimistic-status invariant ────────────
#
# AC2c: the non-optimistic-status rule is a GENERAL invariant across EVERY
# provider, not a per-example fix. A single parametrized test arranges an
# invalid / incomplete / unrunnable underlying state for EACH provider and
# asserts the resulting status is NOT `ok`, so the suite proves the invariant
# holds class-wide rather than only for the roles example.


def _arr_global_config(monkeypatch):
    # AC2d: a REAL present-but-UNLOADABLE global config (malformed JSON), not the
    # trivially-passing "file missing" case. The loader swallows the parse error
    # and degrades to an empty config, so a status keyed off file existence would
    # falsely report OK; the provider must report non-ok.
    from dontpanic_orchestrate import global_config as gc

    path = gc.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not valid json :::")
    return ci.provider_global_config(ci.InventoryContext())


def _arr_project_config(monkeypatch, tmp_path):
    # AC2d: a REAL present-but-UNLOADABLE project config (malformed JSON). The
    # loader returns None for both absent and unloadable, so a status keyed off
    # file existence would falsely report OK; the provider must report non-ok.
    proj = tmp_path / "badprojcfg"
    (proj / ".dontpanic").mkdir(parents=True)
    (proj / ".dontpanic" / "dontpanic.json").write_text("{ broken json ::::")
    return ci.provider_project_config(
        ci.InventoryContext(project_path=proj.resolve(), project_name="badprojcfg")
    )


def _arr_projects_registry(monkeypatch):
    # Fresh home → 0 projects registered → NEEDS_SETUP.
    return ci.provider_projects_registry(ci.InventoryContext())


def _arr_agent_manifest(monkeypatch):
    # Fresh home → no agent-manifest.json → NEEDS_SETUP.
    return ci.provider_agent_manifest(ci.InventoryContext())


def _arr_roles(monkeypatch, tmp_path):
    # Resolved implementer not in AGENT_REGISTRY → unrunnable → NEEDS_SETUP.
    proj = tmp_path / "badroles"
    (proj / ".dontpanic").mkdir(parents=True)
    (proj / ".dontpanic" / "dontpanic.json").write_text(
        json.dumps({"implementer": "Grok-Builder", "auditor": "codex"})
    )
    return ci.provider_roles(
        ci.InventoryContext(project_path=proj.resolve(), project_name="badroles")
    )


def _arr_runtime_evidence(monkeypatch):
    # No project → no runtime_evidence defaults → OPTIONAL_UNCONFIGURED.
    return ci.provider_runtime_evidence(ci.InventoryContext())


def _arr_gates_paths(monkeypatch):
    # No project → defaults only → OPTIONAL_UNCONFIGURED.
    return ci.provider_gates_paths(ci.InventoryContext())


def _arr_quota(monkeypatch):
    # Caps present but calibration absent → uncalibrated → NEEDS_SETUP.
    from dontpanic_orchestrate import calibration_loader, quota_caps_loader

    caps = quota_caps_loader.effective_caps_path()
    caps.parent.mkdir(parents=True, exist_ok=True)
    caps.write_text(json.dumps({"schema_version": 2, "vendors": {}}))
    monkeypatch.setattr(calibration_loader, "load", lambda *a, **k: {})
    return ci.provider_quota(ci.InventoryContext())


def _arr_circuit_breakers(monkeypatch):
    # AC2d: a REAL tripped global breaker, not a synthetic read failure. Write
    # enough iteration-cap hits (within the window) to cross the global
    # threshold via the production record path, so evaluate_global() actually
    # returns tripped=True. The provider previously hardcoded Status.OK; it must
    # now report non-ok for a genuinely tripped breaker.
    from dontpanic_orchestrate import circuit_breakers as cb

    for _ in range(cb.GLOBAL_THRESHOLD_HITS):
        cb.record_global_hit("plan-tripping-breaker", cb.BreakerKind.ITERATION_CAP)
    assert cb.evaluate_global().tripped is True  # arrangement sanity
    return ci.provider_circuit_breakers(ci.InventoryContext())


def _arr_notifications(monkeypatch):
    monkeypatch.delenv("DONTPANIC_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("JARVIS_DISCORD_WEBHOOK_URL", raising=False)
    return ci.provider_notifications(ci.InventoryContext())


def _arr_dashboard(monkeypatch, tmp_path):
    from dontpanic_orchestrate import dashboard

    empty = tmp_path / "no_dash_state"
    empty.mkdir()
    monkeypatch.setattr(dashboard, "default_state_out_dir", lambda *a, **k: empty)
    return ci.provider_dashboard(ci.InventoryContext())


def _arr_capabilities(monkeypatch):
    # No adapter ready → must not be optimistic → OPTIONAL_UNCONFIGURED.
    import types

    from dontpanic_orchestrate import capabilities_status

    monkeypatch.setattr(
        capabilities_status,
        "run_status",
        lambda *a, **k: types.SimpleNamespace(capabilities=[]),
    )
    return ci.provider_capabilities(ci.InventoryContext())


def _arr_mcp(monkeypatch):
    # MCP is a start surface, never "configured" → OPTIONAL_UNCONFIGURED.
    return ci.provider_mcp(ci.InventoryContext())


def _arr_environments(monkeypatch):
    # No project → no environments.json → OPTIONAL_UNCONFIGURED.
    return ci.provider_environments(ci.InventoryContext())


def _arr_install_reconcile(monkeypatch):
    from dontpanic_orchestrate import install_snapshot

    monkeypatch.setattr(install_snapshot, "load_snapshot", lambda *a, **k: None)
    return ci.provider_install_reconcile(ci.InventoryContext())


def _arr_pm_credentials(monkeypatch):
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    return ci.provider_pm_credentials(ci.InventoryContext())


def _arr_secret_anthropic(monkeypatch):
    # Required secret unconfigured → HUMAN_REQUIRED (non-ok).
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    items = ci.provider_secrets_auth(ci.InventoryContext())
    return next(i for i in items if i.id == "secret_anthropic_auth")


# (provider_id, arranger). Arrangers take monkeypatch (and tmp_path where they
# need to write a fixture repo). Every entry sets up an INVALID / INCOMPLETE /
# UNRUNNABLE underlying state for that provider.
_NON_OPTIMISTIC_CASES: dict = {
    "global_config": _arr_global_config,
    "project_config": _arr_project_config,
    "projects_registry": _arr_projects_registry,
    "agent_manifest": _arr_agent_manifest,
    "roles": _arr_roles,
    "runtime_evidence": _arr_runtime_evidence,
    "gates_paths": _arr_gates_paths,
    "quota": _arr_quota,
    "circuit_breakers": _arr_circuit_breakers,
    "notifications": _arr_notifications,
    "dashboard": _arr_dashboard,
    "capabilities": _arr_capabilities,
    "mcp": _arr_mcp,
    "environments": _arr_environments,
    "install_reconcile": _arr_install_reconcile,
    "pm_credentials": _arr_pm_credentials,
    "secret_anthropic_auth": _arr_secret_anthropic,
}


def test_every_provider_is_listed_in_the_invariant_suite():
    # Guard: every single-item provider in the registry has an invariant case,
    # so a future provider cannot be added without proving its non-optimism.
    registry_ids = {p(ci.InventoryContext()).id for p in ci._PROVIDERS}
    covered = set(_NON_OPTIMISTIC_CASES) - {"secret_anthropic_auth"}
    assert registry_ids <= covered, f"providers missing invariant case: {registry_ids - covered}"


@pytest.mark.parametrize("provider_id", sorted(_NON_OPTIMISTIC_CASES))
def test_no_provider_reports_ok_on_invalid_or_incomplete_state(
    provider_id, monkeypatch, tmp_path
):
    arranger = _NON_OPTIMISTIC_CASES[provider_id]
    # Some arrangers need a tmp repo to write fixture config into.
    if provider_id in ("roles", "dashboard", "project_config"):
        item = arranger(monkeypatch, tmp_path)
    else:
        item = arranger(monkeypatch)
    assert item.id == provider_id
    assert item.status is not ci.Status.OK, (
        f"{provider_id} reported OK on an invalid/incomplete underlying state; "
        f"the non-optimistic-status invariant (AC2c) requires a non-ok status"
    )


def test_core_surfaces_are_required():
    inv = ci.collect_inventory()
    for req_id in ("global_config", "projects_registry", "agent_manifest", "roles", "quota"):
        assert _by_id(inv, req_id).optional is False, req_id


# ─────────────────────── (8) active / inactive dashboard hint ───────────────


def test_dashboard_hint_inactive_uses_start_command():
    # A fresh home leaves the required anthropic-auth secret unconfigured →
    # at least one human-required item → exactly one hint.
    inv = ci.collect_inventory(dashboard_url=None)
    assert inv.dashboard_hint is not None
    hd = inv.dashboard_hint.to_dict()
    assert hd["is_running"] is False
    assert hd["active_url"] is None
    assert hd["start_command"] == ci.DASHBOARD_START_COMMAND


def test_dashboard_hint_active_uses_url():
    url = "http://127.0.0.1:8787/"
    inv = ci.collect_inventory(dashboard_url=url)
    assert inv.dashboard_hint is not None
    hd = inv.dashboard_hint.to_dict()
    assert hd["is_running"] is True
    assert hd["active_url"] == url
    assert hd["start_command"] is None


def test_no_dashboard_hint_when_nothing_human_required(monkeypatch):
    # Configure the one required secret so no item is human-required.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-configured")
    inv = ci.collect_inventory()
    human = [i for i in inv.items if i.human_required]
    assert human == []
    assert inv.dashboard_hint is None


# ─────────────────────── (8) dashboard-hint deduplication ───────────────────


def test_dashboard_hint_appears_once_and_items_only_reference_it():
    url = "http://127.0.0.1:8787/"
    inv = ci.collect_inventory(dashboard_url=url)
    assert inv.dashboard_hint is not None
    hint_text = inv.dashboard_hint.text()
    d = inv.to_dict()
    # The full hint text appears exactly once — at the response level.
    serialized_items = json.dumps(d["items"])
    assert hint_text not in serialized_items
    # Human-required items reference the hint by id only.
    for item in inv.items:
        if item.human_required:
            assert item.dashboard_hint_ref == ci.DASHBOARD_HINT_ID
        else:
            assert item.dashboard_hint_ref is None
    # The dashboard state likewise carries the hint once at the top level.
    state = ci.to_dashboard_state(inv)
    all_cards = json.dumps(state["settings_cards"]) + json.dumps(state["setup_cards"])
    assert hint_text not in all_cards
    assert state["dashboard_hint"]["text"] == hint_text


# ───────────────────────── (7) setup/update planner ─────────────────────────


def test_setup_plan_emits_choices_and_draft_plan():
    inv = ci.collect_inventory()
    plan = ci.build_setup_plan(inv)
    assert "choices" in plan and "draft_plan" in plan
    # One choice per incomplete item.
    assert len(plan["choices"]) == len(inv.incomplete_items())
    # Draft plan has a feature per incomplete item.
    assert len(plan["draft_plan"]["features"]) == len(inv.incomplete_items())
    # Automatable choices carry an exact command; human-required ones do not.
    for choice in plan["choices"]:
        if choice["requires_human"]:
            assert choice["exact_command"] is None
        else:
            assert choice["exact_command"] is not None


def test_setup_plan_choices_reference_single_affordance():
    inv = ci.collect_inventory(dashboard_url="http://127.0.0.1:8787/")
    plan = ci.build_setup_plan(inv)
    refs = {
        c["references_affordance"]
        for c in plan["choices"]
        if c["references_affordance"]
    }
    # All references point at the same single hint id.
    assert refs <= {ci.DASHBOARD_HINT_ID}


# ───────────────────────── (2) project-scoped overrides ─────────────────────


def test_project_scoped_overrides_change_inventory(tmp_path):
    proj = tmp_path / "myrepo"
    (proj / ".dontpanic").mkdir(parents=True)
    (proj / ".dontpanic" / "dontpanic.json").write_text(
        json.dumps(
            {
                "implementer": "claude",
                "auditor": "codex",
                "plans_dir": "docs/plans",
                "default_target_env": "dev",
                "runtime_evidence": {"web": {"base_url": "http://localhost:3000"}},
            }
        )
    )
    inv = ci.collect_inventory(project=str(proj))
    assert inv.project_path == str(proj.resolve())
    # Project config now resolves OK rather than "no project in scope".
    pc_item = _by_id(inv, "project_config")
    assert pc_item.status is ci.Status.OK
    assert "claude" in pc_item.current_value_summary
    # Runtime evidence reads the project value (OK, not optional-unconfigured).
    re_item = _by_id(inv, "runtime_evidence")
    assert re_item.status is ci.Status.OK
    # Gates/paths reflect the project default_target_env.
    gp_item = _by_id(inv, "gates_paths")
    assert "dev" in gp_item.current_value_summary


def test_roles_status_is_ok_for_registered_executors(tmp_path):
    # Fallback / explicitly-registered executors (claude, codex) resolve as
    # worker-capable → the roles surface is OK.
    proj = tmp_path / "okrepo"
    (proj / ".dontpanic").mkdir(parents=True)
    (proj / ".dontpanic" / "dontpanic.json").write_text(
        json.dumps({"implementer": "claude", "auditor": "codex"})
    )
    inv = ci.collect_inventory(project=str(proj))
    roles = _by_id(inv, "roles")
    assert roles.status is ci.Status.OK


def test_roles_status_non_ok_when_resolved_executor_not_registered(tmp_path):
    # AC2b: a roles provider whose resolved implementer/auditor is NOT in
    # AGENT_REGISTRY must report a non-ok status (invalid/unrunnable), never `ok`.
    proj = tmp_path / "badrepo"
    (proj / ".dontpanic").mkdir(parents=True)
    (proj / ".dontpanic" / "dontpanic.json").write_text(
        json.dumps({"implementer": "Grok-Builder", "auditor": "codex"})
    )
    inv = ci.collect_inventory(project=str(proj))
    roles = _by_id(inv, "roles")
    assert roles.status is not ci.Status.OK
    assert roles.status is ci.Status.NEEDS_SETUP
    # Status drives setup grouping: the unrunnable role is "incomplete" work.
    assert roles.is_incomplete
    # Summary names the offending executor and routes the operator to `roles set`.
    assert "Grok-Builder" in roles.current_value_summary
    assert "dontpanic roles set" in roles.current_value_summary
    # The validated edit route is still surfaced as a template (not a safe_command).
    shape = roles.dashboard_mutation_shape or {}
    assert "dontpanic roles set" in (shape.get("command_template") or "")


def test_machine_scope_when_no_project_degrades_gracefully():
    inv = ci.collect_inventory()
    # No project in scope → project_config is not a hard error; it degrades.
    pc_item = _by_id(inv, "project_config")
    assert pc_item.status in (ci.Status.UNKNOWN, ci.Status.NEEDS_SETUP)
    # And the inventory as a whole is still complete.
    assert len(inv.items) >= 10


# ──────────────────────── provider robustness (degrade) ─────────────────────


def test_provider_failure_degrades_to_unknown(monkeypatch):
    # Force a reader to raise; the inventory must still assemble with that single
    # item degraded to UNKNOWN rather than crashing. The provider probes
    # ``config_path`` first, so failing it exercises the ``_safe`` degrade path
    # regardless of whether a config file is present.
    import dontpanic_orchestrate.global_config as gc

    def _boom():
        raise RuntimeError("synthetic reader failure")

    monkeypatch.setattr(gc, "config_path", _boom)
    inv = ci.collect_inventory()
    item = _by_id(inv, "global_config")
    assert item.status is ci.Status.UNKNOWN
    assert len(inv.items) >= 10
