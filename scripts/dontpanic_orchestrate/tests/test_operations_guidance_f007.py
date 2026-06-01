"""Tests for operations_guidance — Plan 2026-05-30-001 F007 AC(1)-(8).

The decision engine converts operational blockers into a short typed
ActionChoice set. Coverage spans the >=9 decision states AC(8) requires plus the
dashboard parity (AC3), affordance dedup (AC6), and the concrete Codex
cooldown + max_iterations example.
"""
from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from dontpanic_orchestrate import gate_pause, operations_guidance as og

PLAN_ID = "2026-05-30-ops-demo"
# Collector tests load a real plan.md, so the id must match the strict schema
# pattern; pure-engine tests use the short PLAN_ID where the value is opaque.
COLLECT_PLAN_ID = "2026-05-30-001-feat-ops-demo"


# ───────────────────────────── helpers ─────────────────────────────


def _running_dashboard() -> og.DashboardAffordance:
    return og.DashboardAffordance(is_running=True, url="http://127.0.0.1:8787/")


def _stopped_dashboard() -> og.DashboardAffordance:
    return og.DashboardAffordance(is_running=False)


def _kinds(guidance: og.Guidance) -> list[str]:
    return [c.kind for c in guidance.choices]


def _by_kind(guidance: og.Guidance, kind: str) -> og.ActionChoice:
    return next(c for c in guidance.choices if c.kind == kind)


# ─────────── (1) quota cooldown: wait-until + redispatch + raise alt ───────────


def test_quota_cooldown_recommends_wait_until_then_raise_alt():
    state = og.QuotaCooldownState(
        agent="codex",
        observed_pct=82.0,
        threshold=70.0,
        wait_until="14:35",
        raise_target_pct=90.0,
    )
    g = og.build_guidance(PLAN_ID, feature_id="F007", quota_cooldown=state)
    assert og.KIND_WAIT_REDISPATCH in _kinds(g)
    assert og.KIND_RAISE_CEILING in _kinds(g)
    wait = _by_kind(g, og.KIND_WAIT_REDISPATCH)
    assert wait.recommended is True
    assert "14:35" in wait.rationale
    assert wait.exact_command == f"dontpanic orchestrate {PLAN_ID} --confirm"
    raise_alt = _by_kind(g, og.KIND_RAISE_CEILING)
    assert raise_alt.recommended is False
    assert raise_alt.requires_human is True
    # AC7: no safe one-shot `quota-caps set` exists, so no command is emitted —
    # the editable caps file is named in the rationale instead.
    assert raise_alt.exact_command is None
    assert "quota_caps.json" in raise_alt.rationale


def test_quota_cooldown_without_raise_target_omits_raise_alt():
    state = og.QuotaCooldownState(agent="codex", observed_pct=82.0, threshold=70.0)
    g = og.build_guidance(PLAN_ID, quota_cooldown=state)
    assert og.KIND_RAISE_CEILING not in _kinds(g)


# ───────────────── (2) max_iterations remaining + within cap ─────────────────


def test_iteration_remaining_states_count_and_within_cap():
    it = og.IterationState(max_iterations=3, iterations_used=2)
    assert it.remaining == 1
    assert it.next_within_cap is True
    g = og.build_guidance(PLAN_ID, feature_id="F007", iteration=it)
    cont = _by_kind(g, og.KIND_CONTINUE_ITERATION)
    assert "1 fix iteration(s) remain" in cont.rationale
    assert "within cap" in cont.rationale
    assert cont.exact_command == f"dontpanic orchestrate {PLAN_ID} --confirm"


def test_iteration_exhausted_offers_close_and_approve():
    it = og.IterationState(max_iterations=3, iterations_used=3)
    assert it.exhausted is True
    g = og.build_guidance(PLAN_ID, feature_id="F007", iteration=it)
    assert og.KIND_CLOSE in _kinds(g)
    assert og.KIND_APPROVE_GATE in _kinds(g)
    close = _by_kind(g, og.KIND_CLOSE)
    assert "OVER cap" in close.rationale
    # AC7 / Finding 2: the close <class> is a human decision, so no exact_command
    # is emitted — only a hint in the rationale.
    assert close.exact_command is None
    assert "close --operator-resolved" in close.rationale
    assert close.requires_human is True


# ───────── concrete Codex example: budget cooling + remaining iterations ─────────


def test_codex_cooldown_plus_remaining_iterations_example():
    """AC(8) named example: Codex budget cooling + remaining max_iterations
    recommends wait+redispatch with a raise-ceiling alternative, and states the
    iteration cap."""
    quota = og.QuotaCooldownState(
        agent="codex", observed_pct=85.0, threshold=70.0,
        wait_until="14:35", raise_target_pct=95.0,
    )
    it = og.IterationState(max_iterations=3, iterations_used=2)
    g = og.build_guidance(PLAN_ID, feature_id="F007", quota_cooldown=quota, iteration=it)
    wait = _by_kind(g, og.KIND_WAIT_REDISPATCH)
    assert wait.recommended is True
    # iteration cap stated inside the recommended choice's rationale.
    assert "max_iterations=3" in wait.rationale
    assert "within cap" in wait.rationale
    # alternative raise path present.
    assert _by_kind(g, og.KIND_RAISE_CEILING).requires_human is True
    # iteration carried by quota choice → no standalone continue choice.
    assert og.KIND_CONTINUE_ITERATION not in _kinds(g)


# ─────────────── (3) dashboard ActionItems parity with CLI data ───────────────


def test_budget_and_iteration_guidance_parity_cli_and_dashboard():
    budget = og.BudgetCeilingState(
        agent="codex", observed_native=120000.0, cap=100000.0, unit="tokens",
    )
    it = og.IterationState(max_iterations=3, iterations_used=1)
    g = og.build_guidance(
        PLAN_ID, feature_id="F007", budget_ceiling=budget, iteration=it,
        dashboard=_stopped_dashboard(),
    )
    items = g.to_action_items(updated_at="2026-06-01T00:00:00Z")
    # one ActionItem per choice; commands match the typed ActionChoice data.
    assert len(items) == len(g.choices)
    cmds_cli = {c.exact_command for c in g.choices}
    cmds_dash = {i.exact_command for i in items}
    assert cmds_cli == cmds_dash
    # the recommended wait/redispatch is automatable; the raise-ceiling is not.
    wait_item = next(i for i in items if i.id.endswith("budget-wait-redispatch"))
    assert wait_item.automatable is True
    raise_item = next(i for i in items if i.id.endswith("budget-raise-ceiling"))
    assert raise_item.automatable is False
    assert raise_item.human_required_reason is not None


# ──────── (4) signed_off paused at pre_merge: gate state + finalize path ────────


def test_signoff_pre_merge_pending_shows_gate_state_and_approve():
    s = og.SignoffState(
        feature_id="F001",
        verdict="signed_off",
        pre_merge_cleared=False,
        pre_merge_pending=True,
    )
    g = og.build_guidance(PLAN_ID, feature_id="F001", signoff=s)
    approve = _by_kind(g, og.KIND_APPROVE_GATE)
    assert "pre_merge PENDING" in approve.rationale
    assert approve.exact_command == f"dontpanic approve {PLAN_ID} pre_merge"
    assert og.KIND_FINALIZE not in _kinds(g)


def test_signoff_pre_merge_not_pending_emits_no_approve_command():
    # AC7 (respects current state): signed_off but pre_merge is neither cleared
    # nor currently pending — `approve <plan> pre_merge` would exit 2, so
    # guidance must fall back to human-required advisory text with NO command.
    s = og.SignoffState(
        feature_id="F001",
        verdict="signed_off",
        pre_merge_cleared=False,
        pre_merge_pending=False,
    )
    g = og.build_guidance(PLAN_ID, feature_id="F001", signoff=s)
    approve = _by_kind(g, og.KIND_APPROVE_GATE)
    assert approve.exact_command is None
    assert approve.requires_human is True
    assert "not currently pending" in approve.rationale
    assert "dontpanic approve" not in (approve.exact_command or "")
    assert og.KIND_FINALIZE not in _kinds(g)


def test_signoff_pre_merge_cleared_offers_no_paid_finalize():
    s = og.SignoffState(feature_id="F001", verdict="signed_off", pre_merge_cleared=True)
    g = og.build_guidance(PLAN_ID, feature_id="F001", signoff=s)
    fin = _by_kind(g, og.KIND_FINALIZE)
    assert fin.recommended is True
    assert fin.requires_human is False  # no paid call, no human gate left
    assert fin.exact_command == f"dontpanic finalize {PLAN_ID} --feature F001"
    assert "no fresh paid dispatch" in fin.rationale


# ─────────────────── (5) admission threshold mismatch ───────────────────


def test_admission_threshold_both_paths():
    s = og.AdmissionThresholdState(agent="claude", observed_pct=75.0, threshold=70.0)
    g = og.build_guidance(PLAN_ID, admission_threshold=s)
    assert og.KIND_WAIT_REDISPATCH in _kinds(g)
    raise_t = _by_kind(g, og.KIND_RAISE_THRESHOLD)
    assert _by_kind(g, og.KIND_WAIT_REDISPATCH).recommended is True
    assert raise_t.recommended is False
    assert raise_t.requires_human is True


# ─────────────────────── (6) no-progress stop ───────────────────────


def test_no_progress_offers_resume_and_close_with_breaker_name():
    s = og.NoProgressState(breaker_name="breaker:no_progress", detail="2 rounds, no new signal")
    g = og.build_guidance(PLAN_ID, feature_id="F001", no_progress=s)
    assert og.KIND_RESUME in _kinds(g)
    assert og.KIND_CLOSE in _kinds(g)
    resume = _by_kind(g, og.KIND_RESUME)
    assert "breaker:no_progress" in resume.rationale
    # AC7b: resume names the specific gate (the breaker) — never bare.
    assert resume.exact_command == f"dontpanic resume {PLAN_ID} --gate breaker:no_progress"


# ─────────────────── (7) setup states: onboard / role / reconcile / brief ───────────────────


def test_missing_project_registration():
    g = og.build_guidance(
        PLAN_ID, setup=og.SetupNeeds(missing_project=True, project_name="myrepo", project_path="/p")
    )
    c = _by_kind(g, og.KIND_ONBOARD)
    assert c.exact_command == "dontpanic projects add myrepo /p --onboard"
    assert c.requires_human is False


def test_stale_onboarding_and_brief():
    g = og.build_guidance(
        PLAN_ID,
        setup=og.SetupNeeds(stale_onboarding=True, project_name="r", project_path="/p", stale_brief=True),
    )
    kinds = _kinds(g)
    assert og.KIND_ONBOARD in kinds
    assert og.KIND_REFRESH_BRIEF in kinds
    assert _by_kind(g, og.KIND_REFRESH_BRIEF).exact_command == "dontpanic agent brief"


def test_stale_onboarding_already_registered_emits_force_yes():
    """AC7e: re-onboarding an ALREADY-registered project must carry
    `--force --yes` — a bare `--onboard` is invalid because the registry
    refuses an existing name without --force --yes."""
    g = og.build_guidance(
        PLAN_ID,
        setup=og.SetupNeeds(stale_onboarding=True, project_name="r", project_path="/p"),
    )
    c = _by_kind(g, og.KIND_ONBOARD)
    assert c.exact_command == "dontpanic projects add r /p --onboard --force --yes"
    assert "--force --yes" in c.exact_command
    # The first-time registration path (missing_project) must NOT carry --force.
    fresh = og.build_guidance(
        PLAN_ID,
        setup=og.SetupNeeds(missing_project=True, project_name="r", project_path="/p"),
    )
    assert _by_kind(fresh, og.KIND_ONBOARD).exact_command == "dontpanic projects add r /p --onboard"


def test_split_config_homes_recommends_reconcile():
    g = og.build_guidance(PLAN_ID, setup=og.SetupNeeds(split_config_homes=True))
    c = _by_kind(g, og.KIND_RECONCILE)
    # AC7c: bare `dontpanic reconcile` exits 2 — the command must name `homes`.
    assert c.exact_command == "dontpanic reconcile homes --dry-run"
    assert c.requires_human is True


def test_unsupported_worker_role_has_no_exact_command():
    """AC(7): exact commands only when safe — an unsupported agent cannot be
    safely auto-assigned, so no command is emitted."""
    g = og.build_guidance(
        PLAN_ID,
        setup=og.SetupNeeds(unsupported_role="grok", unsupported_role_name="auditor"),
    )
    c = _by_kind(g, og.KIND_ROLE)
    assert c.exact_command is None
    assert c.requires_human is True
    assert "cannot be DISPATCHED" in c.rationale


def test_human_required_config_points_at_doctor():
    g = og.build_guidance(
        PLAN_ID, setup=og.SetupNeeds(human_required_config="API base URL is unset.")
    )
    c = _by_kind(g, og.KIND_DOCTOR)
    assert c.exact_command == "dontpanic doctor --agent"
    assert c.requires_human is True


def test_stale_project_config_points_at_project_doctor():
    """AC5: stale/mismatched project onboarding → `doctor --project <name>`."""
    g = og.build_guidance(
        PLAN_ID,
        setup=og.SetupNeeds(stale_project_config=True, project_name="myrepo"),
    )
    c = _by_kind(g, og.KIND_PROJECT_DOCTOR)
    assert c.exact_command == "dontpanic doctor --project myrepo"
    assert c.requires_human is False


def test_project_doctor_without_name_emits_no_command():
    """AC7: with no validated project name the value is a human decision."""
    g = og.build_guidance(PLAN_ID, setup=og.SetupNeeds(stale_project_config=True))
    c = _by_kind(g, og.KIND_PROJECT_DOCTOR)
    assert c.exact_command is None
    assert c.requires_human is True


def test_missing_project_without_args_emits_no_command():
    """AC7: `projects add <name> <path>` is only runnable with concrete args."""
    g = og.build_guidance(PLAN_ID, setup=og.SetupNeeds(missing_project=True))
    c = _by_kind(g, og.KIND_ONBOARD)
    assert c.exact_command is None
    assert c.requires_human is True


def test_raise_paths_never_emit_unvalidated_commands():
    """AC7 regression guard: the raise-ceiling / raise-threshold alternatives
    must NOT emit `quota-caps set ...` or a `<pct>` placeholder command — no
    such validated CLI exists. Every emitted command must be a real surface."""
    quota = og.QuotaCooldownState(
        agent="codex", observed_pct=85.0, threshold=70.0, raise_target_pct=95.0
    )
    budget = og.BudgetCeilingState(agent="codex", observed_native=9.0, cap=8.0, unit="tok")
    adm = og.AdmissionThresholdState(agent="claude", observed_pct=75.0, threshold=70.0)
    for g in (
        og.build_guidance(PLAN_ID, quota_cooldown=quota),
        og.build_guidance(PLAN_ID, budget_ceiling=budget),
        og.build_guidance(PLAN_ID, admission_threshold=adm),
    ):
        for c in g.choices:
            cmd = c.exact_command or ""
            assert "quota-caps set" not in cmd
            assert "<pct>" not in cmd
        raise_choice = next(
            c for c in g.choices
            if c.kind in (og.KIND_RAISE_CEILING, og.KIND_RAISE_THRESHOLD)
        )
        assert raise_choice.exact_command is None
        assert raise_choice.requires_human is True


# ─────────────── (8) dashboard affordance: active / inactive / dedup ───────────────


def test_affordance_active_url_when_running():
    g = og.build_guidance(
        PLAN_ID, setup=og.SetupNeeds(split_config_homes=True), dashboard=_running_dashboard()
    )
    assert g.affordance is not None
    assert g.affordance.is_running is True
    assert "http://127.0.0.1:8787/" in g.affordance.text()


def test_affordance_start_command_when_not_running():
    g = og.build_guidance(
        PLAN_ID, setup=og.SetupNeeds(split_config_homes=True), dashboard=_stopped_dashboard()
    )
    assert g.affordance is not None
    assert g.affordance.is_running is False
    assert "dontpanic dashboard serve" in g.affordance.text()


def test_affordance_deduplicated_one_per_response():
    """AC(6): exactly one response-level affordance; individual choices reference
    it by id but never repeat the full text."""
    quota = og.QuotaCooldownState(
        agent="codex", observed_pct=85.0, threshold=70.0, raise_target_pct=95.0
    )
    g = og.build_guidance(
        PLAN_ID,
        quota_cooldown=quota,
        setup=og.SetupNeeds(split_config_homes=True),
        dashboard=_running_dashboard(),
    )
    # multiple human-required choices, but exactly one affordance object.
    human_choices = [c for c in g.choices if c.requires_human]
    assert len(human_choices) >= 2
    assert g.affordance is not None
    # each human choice references the shared id, not the full dashboard text.
    for c in human_choices:
        assert c.references_affordance == og.DASHBOARD_AFFORDANCE_ID
        assert "http://127.0.0.1:8787/" not in c.rationale
    # the rendered text shows the dashboard line exactly once.
    text = og.render_text(g)
    assert text.count("Dashboard is running") == 1


def test_no_affordance_when_no_human_required():
    """A fully-automatable guidance (finalize only) attaches no affordance even
    when a dashboard is passed."""
    s = og.SignoffState(feature_id="F001", verdict="signed_off", pre_merge_cleared=True)
    g = og.build_guidance(PLAN_ID, feature_id="F001", signoff=s, dashboard=_running_dashboard())
    assert g.affordance is None


# ───────────────────────── live collector smoke ─────────────────────────


def _make_plan(
    tmp_path: Path,
    *,
    audit_status: str = "signed_off",
    max_iters: int = 3,
    feature_id: str = "F001",
) -> Path:
    plan_dir = tmp_path / "docs" / "plans" / COLLECT_PLAN_ID
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        f"id: {COLLECT_PLAN_ID}\n"
        "title: Ops demo\n"
        "type: feat\ntier: local\nstatus: active\n"
        'date: "2026-05-30"\n'
        "goal_type: infra\n"
        "surfaces:\n  - infra\n"
        "agents_required:\n  - claude\n"
        "human_gates:\n  - pre_impl\n"
        f"loop_caps:\n  max_iterations: {max_iters}\n  no_progress_threshold: 2\n"
        "  wall_clock_hours: 4\n  hard_stop: false\n"
        "privacy_tier: internal\n"
        "links:\n  features: ./features.json\n  decisions: ./decisions.jsonl\n"
        "  evidence_dir: ./evidence/\n"
        "description: |\n  Ops demo.\n"
        "motivation: |\n  Ops demo.\n"
        "---\n"
        "# demo\n\n## Target\n\n```yaml\ntarget_env: dev\ntarget_project: none\n```\n\n"
        "## Acceptance Summary\n\n- x\n"
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": COLLECT_PLAN_ID,
                "schema_version": "1.0",
                "features": [
                    {
                        "id": feature_id,
                        "category": "infra",
                        "description": "Demo feature.",
                        "acceptance": "It works.",
                        "passes": False,
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    audit = plan_dir / "audit"
    audit.mkdir()
    (audit / f"claude-implementer-{feature_id}-i0.json").write_text(
        json.dumps({"agent": "claude", "agent_role": "implementer", "iteration": 0}) + "\n"
    )
    (audit / f"codex-auditor-{feature_id}-i0.json").write_text(
        json.dumps(
            {
                "audit_id": f"{COLLECT_PLAN_ID}#codex#0",
                "agent": "codex",
                "agent_role": "auditor",
                "iteration": 0,
                "audit_status": audit_status,
                "findings": [],
                "summary": "ok",
            }
        )
        + "\n"
    )
    return plan_dir


def test_collect_state_signoff_cleared_offers_finalize(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    plan_dir = _make_plan(tmp_path)
    gate_pause.approve_gate(plan_dir, "pre_impl", plan_id=COLLECT_PLAN_ID)
    gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=COLLECT_PLAN_ID)
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    assert og.KIND_FINALIZE in _kinds(g)
    fin = _by_kind(g, og.KIND_FINALIZE)
    assert fin.exact_command == f"dontpanic finalize {COLLECT_PLAN_ID} --feature F001"


def test_collect_state_signoff_pending_shows_approve(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    plan_dir = _make_plan(tmp_path)
    # AC7 (respects current state): the live approve command is only valid once
    # the supervisor has actually paused on pre_merge — record that pause so the
    # emitted `approve` mirrors a runnable CLI invocation (not an exit-2 usage
    # error). collect_state derives pre_merge_pending from this gate-state.
    gate_pause.record_pause(
        plan_dir, plan_id=COLLECT_PLAN_ID, pause_gates=["pre_merge"], stage="pre_merge"
    )
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    approve = _by_kind(g, og.KIND_APPROVE_GATE)
    assert approve.exact_command == f"dontpanic approve {COLLECT_PLAN_ID} pre_merge"
    assert "pre_merge PENDING" in approve.rationale


def test_collect_state_signoff_not_pending_emits_no_command(tmp_path, monkeypatch):
    # AC7: signed_off but the supervisor has not paused on pre_merge (no
    # pause_gates / pending_stage). collect_state must NOT emit the approve
    # command — `approve <plan> pre_merge` would exit 2 — and instead point the
    # human at the gate.
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    plan_dir = _make_plan(tmp_path)
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    approve = _by_kind(g, og.KIND_APPROVE_GATE)
    assert approve.exact_command is None
    assert approve.requires_human is True
    assert og.KIND_FINALIZE not in _kinds(g)


def test_collect_state_no_signoff_uses_iteration(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    plan_dir = _make_plan(tmp_path, audit_status="needs_changes", max_iters=3)
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    # one auditor iteration consumed (i0) → 2 remain under cap of 3.
    cont = _by_kind(g, og.KIND_CONTINUE_ITERATION)
    assert "2 fix iteration(s) remain" in cont.rationale


# ────────── dashboard ActionItem parity: built cache carries operations ──────────


def test_dashboard_gathers_operations_action_items(tmp_path, monkeypatch):
    """AC3 / Finding 1: the dashboard's ActionItem gatherer surfaces the same
    typed ActionChoice data (here, the no-paid finalize) so decisions are
    available without re-reading CLI logs."""
    from dontpanic_orchestrate import dashboard, gate_pause

    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    plan_dir = _make_plan(tmp_path)  # signed_off
    gate_pause.approve_gate(plan_dir, "pre_impl", plan_id=COLLECT_PLAN_ID)
    gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=COLLECT_PLAN_ID)

    items = dashboard._gather_operations_items({COLLECT_PLAN_ID: plan_dir})
    finalize_items = [i for i in items if "signoff-finalize" in i.id]
    assert finalize_items, "expected a finalize operations ActionItem in the cache"
    item = finalize_items[0]
    assert item.id.startswith(f"operations:{COLLECT_PLAN_ID}:")
    assert item.exact_command == f"dontpanic finalize {COLLECT_PLAN_ID} --feature F001"
    assert item.automatable is True  # no paid call, no human gate left


# ────────────── Finding 2: close placeholders emit no exact_command ──────────────


def test_no_progress_close_emits_no_command():
    """AC7 / Finding 2 regression: the no-progress close choice carries the
    command shape in its rationale, never as a non-runnable exact_command."""
    s = og.NoProgressState(breaker_name="breaker:no_progress", detail="2 rounds")
    g = og.build_guidance(PLAN_ID, feature_id="F001", no_progress=s)
    close = _by_kind(g, og.KIND_CLOSE)
    assert close.exact_command is None
    assert "close --operator-resolved" in close.rationale
    assert close.requires_human is True


# ──────── Finding 1: dashboard iterates the ACTUAL blocked feature (F007) ────────


def test_blocked_feature_ids_reads_features_json(tmp_path):
    plan_dir = _make_plan(tmp_path, feature_id="F007")
    assert og.blocked_feature_ids(plan_dir) == ["F007"]


def test_blocked_feature_ids_falls_back_when_features_missing(tmp_path):
    (tmp_path / "empty").mkdir()
    assert og.blocked_feature_ids(tmp_path / "empty") == ["F001"]


def test_dashboard_surfaces_f007_blocked_feature(tmp_path, monkeypatch):
    """Finding 1: the dashboard gatherer evaluates F007 (the actual blocked
    feature in features.json), not a hard-coded F001 — its finalize guidance
    appears in the cache."""
    from dontpanic_orchestrate import dashboard, gate_pause

    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path / "canon"))
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "legacy"))
    plan_dir = _make_plan(tmp_path, feature_id="F007")  # signed_off
    gate_pause.approve_gate(plan_dir, "pre_impl", plan_id=COLLECT_PLAN_ID)
    gate_pause.approve_gate(plan_dir, "pre_merge", plan_id=COLLECT_PLAN_ID)

    items = dashboard._gather_operations_items({COLLECT_PLAN_ID: plan_dir})
    finalize = [i for i in items if "signoff-finalize" in i.id]
    assert finalize, "expected F007 finalize guidance in the dashboard cache"
    assert finalize[0].exact_command == f"dontpanic finalize {COLLECT_PLAN_ID} --feature F007"


# ─────── Finding 3: live collector constructs budget / admission / setup ───────


def _reconciled_homes(tmp_path, monkeypatch) -> None:
    """Point both config homes at empty dirs so _collect_setup sees no split."""
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path / "canon"))
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "legacy"))


def test_collect_state_budget_ceiling_when_window_tripped(tmp_path, monkeypatch):
    """Finding 3: a TRIPPED budget window makes the live collector build a
    BudgetCeilingState (wait/redispatch + raise-ceiling), not only the builder
    tests."""
    from dontpanic_orchestrate import circuit_breakers

    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    _reconciled_homes(tmp_path, monkeypatch)
    plan_dir = _make_plan(tmp_path, audit_status="needs_changes")
    tripped = circuit_breakers.BudgetCeilingResult(
        kind=circuit_breakers.BudgetCeilingKind.TRIPPED,
        tripped=True,
        reason="codex rolling_5h over cap",
        agent="codex",
        window="rolling_5h",
        observed_native=120000.0,
        observed_unit="tokens",
        cap=100000.0,
        cap_unit="tokens",
    )
    monkeypatch.setattr(circuit_breakers, "check_budget_ceiling", lambda *a, **k: tripped)
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    assert og.KIND_WAIT_REDISPATCH in _kinds(g)
    assert og.KIND_RAISE_CEILING in _kinds(g)
    wait = _by_kind(g, og.KIND_WAIT_REDISPATCH)
    assert "budget ceiling reached" in wait.rationale
    assert wait.exact_command == f"dontpanic orchestrate {COLLECT_PLAN_ID} --confirm"


def test_collect_state_admission_threshold_when_soft_over(tmp_path, monkeypatch):
    """Finding 3: a soft over-threshold (numeric, no terminal cause) makes the
    live collector build an AdmissionThresholdState with both paths."""
    from dontpanic_orchestrate import circuit_breakers, quota_admission

    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    _reconciled_homes(tmp_path, monkeypatch)
    plan_dir = _make_plan(tmp_path, audit_status="needs_changes")
    ok = circuit_breakers.BudgetCeilingResult(
        kind=circuit_breakers.BudgetCeilingKind.OK, tripped=False, reason="under cap"
    )
    monkeypatch.setattr(circuit_breakers, "check_budget_ceiling", lambda *a, **k: ok)
    check = quota_admission.QuotaCheck(
        over_threshold=True, offending_agent="claude", observed_pct=78.0, threshold=70.0
    )
    monkeypatch.setattr(quota_admission, "evaluate_quota_threshold", lambda *a, **k: check)
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    assert og.KIND_RAISE_THRESHOLD in _kinds(g)
    wait = _by_kind(g, og.KIND_WAIT_REDISPATCH)
    assert "admission threshold" in wait.rationale
    raise_t = _by_kind(g, og.KIND_RAISE_THRESHOLD)
    assert raise_t.requires_human is True
    assert raise_t.exact_command is None  # AC7


def test_collect_state_cooldown_when_config_cause(tmp_path, monkeypatch):
    """Finding 3: a config-cause defer (e.g. caps_file_missing) routes to a
    cooldown state, distinct from the soft admission-threshold path."""
    from dontpanic_orchestrate import circuit_breakers, quota_admission

    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    _reconciled_homes(tmp_path, monkeypatch)
    plan_dir = _make_plan(tmp_path, audit_status="needs_changes")
    ok = circuit_breakers.BudgetCeilingResult(
        kind=circuit_breakers.BudgetCeilingKind.OK, tripped=False, reason="under cap"
    )
    monkeypatch.setattr(circuit_breakers, "check_budget_ceiling", lambda *a, **k: ok)
    check = quota_admission.QuotaCheck(
        over_threshold=True, offending_agent="codex", observed_pct=None,
        threshold=70.0, cause="caps_file_missing",
    )
    monkeypatch.setattr(quota_admission, "evaluate_quota_threshold", lambda *a, **k: check)
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    assert og.KIND_RAISE_THRESHOLD not in _kinds(g)
    wait = _by_kind(g, og.KIND_WAIT_REDISPATCH)
    assert "caps_file_missing" in wait.rationale


def test_collect_state_split_config_homes_setup(tmp_path, monkeypatch):
    """Finding 3: when the legacy home strands config the resolver won't pick,
    the live collector surfaces the reconcile setup choice."""
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    canon = tmp_path / "canon"
    legacy = tmp_path / "legacy"
    canon.mkdir()
    legacy.mkdir()
    # legacy-only config.json → split-brain the single-home resolver ignores.
    (legacy / "config.json").write_text('{"home": "legacy"}\n')
    monkeypatch.setenv("DONTPANIC_HOME", str(canon))
    monkeypatch.setenv("JARVIS_HOME", str(legacy))
    plan_dir = _make_plan(tmp_path, audit_status="needs_changes")
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    reconcile = _by_kind(g, og.KIND_RECONCILE)
    assert reconcile.exact_command == "dontpanic reconcile homes --dry-run"
    assert reconcile.requires_human is True


# ──────────── AC7a–7d direct assertions (AC8 requires each one) ────────────


import re


def _all_commands(guidance: og.Guidance) -> list[str]:
    return [c.exact_command for c in guidance.choices if c.exact_command]


def _has_bare_resume(guidance: og.Guidance) -> bool:
    """True if any command is `dontpanic resume <plan>` WITHOUT --gate or --all."""
    pat = re.compile(r"\bdontpanic resume\b")
    for cmd in _all_commands(guidance):
        if pat.search(cmd) and "--gate" not in cmd and "--all" not in cmd:
            return True
    return False


def test_7a_exhausted_iteration_emits_no_redispatch_command():
    """AC7a: when the next fix iteration would exceed max_iterations, NO
    redispatch/orchestrate command is emitted — across EVERY guidance kind that
    can otherwise emit a redispatch (quota, budget, admission threshold), plus
    the iteration-only path. The recommended choice instead becomes
    human-required."""
    exhausted = og.IterationState(max_iterations=3, iterations_used=3)

    # quota cooldown carrying an exhausted cap.
    quota = og.QuotaCooldownState(agent="codex", observed_pct=85.0, threshold=70.0)
    gq = og.build_guidance(PLAN_ID, quota_cooldown=quota, iteration=exhausted)
    wait = _by_kind(gq, og.KIND_WAIT_REDISPATCH)
    assert wait.exact_command is None
    assert wait.requires_human is True
    assert all("orchestrate" not in cmd for cmd in _all_commands(gq))

    # budget ceiling carrying an exhausted cap.
    budget = og.BudgetCeilingState(agent="codex", observed_native=9.0, cap=8.0, unit="tok")
    gb = og.build_guidance(PLAN_ID, budget_ceiling=budget, iteration=exhausted)
    wb = _by_kind(gb, og.KIND_WAIT_REDISPATCH)
    assert wb.exact_command is None
    assert wb.requires_human is True
    assert all("orchestrate" not in cmd for cmd in _all_commands(gb))

    # admission threshold carrying an exhausted cap (previously-omitted
    # redispatch path — must suppress orchestrate exactly like quota/budget).
    admission = og.AdmissionThresholdState(agent="codex", observed_pct=85.0, threshold=70.0)
    ga = og.build_guidance(PLAN_ID, admission_threshold=admission, iteration=exhausted)
    wa = _by_kind(ga, og.KIND_WAIT_REDISPATCH)
    assert wa.exact_command is None
    assert wa.requires_human is True
    assert all("orchestrate" not in cmd for cmd in _all_commands(ga))

    # iteration-only exhausted path: close + approve, neither a redispatch.
    gi = og.build_guidance(PLAN_ID, feature_id="F007", iteration=exhausted)
    assert all("orchestrate" not in cmd for cmd in _all_commands(gi))
    assert _by_kind(gi, og.KIND_CLOSE).exact_command is None
    assert _by_kind(gi, og.KIND_APPROVE_GATE).exact_command is None


def test_7a_within_cap_still_emits_redispatch():
    """AC7a guard: the within-cap case is unchanged — a redispatch command IS
    emitted when the next iteration is within the cap."""
    within = og.IterationState(max_iterations=3, iterations_used=1)
    quota = og.QuotaCooldownState(agent="codex", observed_pct=85.0, threshold=70.0)
    g = og.build_guidance(PLAN_ID, quota_cooldown=quota, iteration=within)
    wait = _by_kind(g, og.KIND_WAIT_REDISPATCH)
    assert wait.exact_command == f"dontpanic orchestrate {PLAN_ID} --confirm"
    assert wait.requires_human is False


def test_7b_resume_carries_gate_never_bare():
    """AC7b: resume commands must carry --gate or --all; no bare
    `dontpanic resume <plan>` is ever emitted."""
    s = og.NoProgressState(breaker_name="breaker:no_progress", detail="2 rounds")
    g = og.build_guidance(PLAN_ID, feature_id="F001", no_progress=s)
    resume = _by_kind(g, og.KIND_RESUME)
    assert "--gate breaker:no_progress" in resume.exact_command
    assert not _has_bare_resume(g)

    # the exhausted-iteration approve choice also emits no bare resume.
    exhausted = og.IterationState(max_iterations=2, iterations_used=2)
    gi = og.build_guidance(PLAN_ID, feature_id="F007", iteration=exhausted)
    assert not _has_bare_resume(gi)


def test_7c_reconcile_names_homes_subcommand():
    """AC7c: bare `dontpanic reconcile` exits 2 — the emitted command must name
    the `homes` subcommand."""
    g = og.build_guidance(PLAN_ID, setup=og.SetupNeeds(split_config_homes=True))
    cmd = _by_kind(g, og.KIND_RECONCILE).exact_command
    assert cmd is not None
    assert "reconcile homes" in cmd
    # never the bare form.
    assert cmd != "dontpanic reconcile"


def test_7d_referenced_dashboard_affordance_present_in_built_cache(tmp_path, monkeypatch):
    """AC7d: when an operations ActionItem references the dashboard affordance,
    that affordance must be PRESENT as its own item in the built dashboard cache
    — not merely named in another item's detail text."""
    from dontpanic_orchestrate import dashboard, operations_guidance

    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    # split-brain homes → a reconcile choice (requires_human) → affordance set.
    canon = tmp_path / "canon"
    legacy = tmp_path / "legacy"
    canon.mkdir()
    legacy.mkdir()
    (legacy / "config.json").write_text('{"home": "legacy"}\n')
    monkeypatch.setenv("DONTPANIC_HOME", str(canon))
    monkeypatch.setenv("JARVIS_HOME", str(legacy))
    plan_dir = _make_plan(tmp_path, audit_status="needs_changes")

    items = dashboard._gather_operations_items({COLLECT_PLAN_ID: plan_dir})

    # at least one item references the affordance in its detail…
    referencing = [i for i in items if i.detail and "dashboard affordance" in i.detail]
    assert referencing, "expected an item referencing the dashboard affordance"
    # …and the affordance item itself is present in the cache (by stable id).
    affordance_items = [
        i for i in items if i.id == operations_guidance.DASHBOARD_AFFORDANCE_ITEM_ID
    ]
    assert len(affordance_items) == 1, "exactly one affordance item must be present"
    hint = affordance_items[0]
    # not running in the build path → start command is the affordance.
    assert hint.exact_command == operations_guidance.DASHBOARD_START_COMMAND


# ──────── F012: full setup/doctor surface reachable via the LIVE paths ────────
#
# Finding 2 (high): F007's builder can emit missing-registration, stale-onboarding,
# unsupported-role, doctor --agent, doctor --project, and agent-brief choices, but
# prior tests only exercised them through `build_guidance` (builder-only) — never
# proving the live `collect_state()` (what-now) path and the *built* dashboard
# cache derive them. These parametrized tests drive each setup/doctor state through
# BOTH surfaces by stubbing the read-only leaf detectors `_collect_setup` calls, so
# the assembly + wiring (`_collect_setup` → SetupNeeds → choices → ActionItems) is
# what is under test, not the filesystem probes themselves.

_PROJ = (Path("/repo/myrepo"), "myrepo")


def _patch_setup(
    monkeypatch,
    *,
    split: bool = False,
    agent_doctor: str | None = None,
    resolve=None,
    missing=None,
    onboarding: tuple[bool, bool] = (False, False),
    stale_project: bool = False,
    unsupported: tuple[str | None, str | None] = (None, None),
) -> None:
    """Stub every read-only leaf detector `_collect_setup` consults so a single
    target setup state is derived deterministically (no filesystem probing)."""
    monkeypatch.setattr(og, "_detect_split_homes", lambda: split)
    monkeypatch.setattr(og, "_detect_agent_doctor", lambda: agent_doctor)
    monkeypatch.setattr(og, "_resolve_project_for_plan", lambda _pd: resolve)
    monkeypatch.setattr(og, "_detect_missing_project", lambda _pd: missing)
    monkeypatch.setattr(og, "_detect_onboarding_drift", lambda _pp: onboarding)
    monkeypatch.setattr(og, "_detect_stale_project_config", lambda _pp: stale_project)
    monkeypatch.setattr(og, "_detect_unsupported_role", lambda _pp: unsupported)


# (overrides, kind, choice_id, exact_command, requires_human)
SETUP_LIVE_CASES = [
    pytest.param(
        dict(missing=(Path("/repo/myrepo"), "myrepo")),
        og.KIND_ONBOARD, "setup-register-project",
        "dontpanic projects add myrepo /repo/myrepo --onboard", False,
        id="missing_registration",
    ),
    pytest.param(
        dict(resolve=_PROJ, onboarding=(True, False)),
        og.KIND_ONBOARD, "setup-refresh-onboarding",
        "dontpanic projects add myrepo /repo/myrepo --onboard --force --yes", False,
        id="stale_onboarding",
    ),
    pytest.param(
        dict(resolve=_PROJ, onboarding=(False, True)),
        og.KIND_REFRESH_BRIEF, "setup-refresh-brief",
        "dontpanic agent brief", False,
        id="agent_brief",
    ),
    pytest.param(
        dict(resolve=_PROJ, stale_project=True),
        og.KIND_PROJECT_DOCTOR, "setup-project-doctor",
        "dontpanic doctor --project myrepo", False,
        id="doctor_project",
    ),
    pytest.param(
        dict(resolve=_PROJ, unsupported=("grok", "auditor")),
        og.KIND_ROLE, "setup-unsupported-role", None, True,
        id="unsupported_role",
    ),
    pytest.param(
        dict(agent_doctor="Agent-level doctor check 'env' reported FAIL."),
        og.KIND_DOCTOR, "setup-human-config", "dontpanic doctor --agent", True,
        id="doctor_agent",
    ),
    pytest.param(
        dict(split=True),
        og.KIND_RECONCILE, "setup-reconcile-homes",
        "dontpanic reconcile homes --dry-run", True,
        id="home_reconcile",
    ),
]


@pytest.mark.parametrize(
    "overrides,kind,choice_id,command,requires_human", SETUP_LIVE_CASES
)
def test_setup_state_reachable_via_collect_state_and_what_now(
    tmp_path, monkeypatch, capsys, overrides, kind, choice_id, command, requires_human
):
    """AC1/AC2 + Finding 2: every setup/doctor state is derived by the live
    `collect_state()` path AND rendered by the `dontpanic what-now` CLI."""
    from dontpanic_orchestrate import cli

    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    _reconciled_homes(tmp_path, monkeypatch)
    plan_dir = _make_plan(tmp_path, audit_status="needs_changes")
    _patch_setup(monkeypatch, **overrides)

    # 1. live collector (the what-now path) derives the setup state directly.
    g = og.collect_state(plan_dir, plan_id=COLLECT_PLAN_ID, feature_id="F001")
    choice = _by_kind(g, kind)
    assert choice.exact_command == command
    assert choice.requires_human is requires_human

    # 2. the `dontpanic what-now` CLI surfaces the SAME typed choice in its JSON
    #    (proves reachability through the real command, not just collect_state).
    rc = cli._what_now_main(
        [str(plan_dir), "--feature", "F001", "--format", "json"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    matched = [c for c in payload["choices"] if c["kind"] == kind]
    assert matched, f"{kind} not surfaced by `dontpanic what-now`"
    assert matched[0]["exact_command"] == command
    assert matched[0]["requires_human"] is requires_human


@pytest.mark.parametrize(
    "overrides,kind,choice_id,command,requires_human", SETUP_LIVE_CASES
)
def test_setup_state_reachable_via_built_dashboard_cache(
    tmp_path, monkeypatch, overrides, kind, choice_id, command, requires_human
):
    """AC3 + Finding 2: every setup/doctor state is rendered as an ActionItem in
    the cache produced by `dashboard.build()` (reading the written what-now.json),
    not merely by calling `_gather_operations_items` directly."""
    from dontpanic_orchestrate import dashboard

    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    _reconciled_homes(tmp_path, monkeypatch)
    plan_dir = _make_plan(tmp_path, audit_status="needs_changes")
    _patch_setup(monkeypatch, **overrides)

    out_dir = tmp_path / "dash-out"
    dashboard.build(
        plans_root=plan_dir.parent,
        out_dir=out_dir,
        write_capabilities_cache=False,
        write_what_now_cache=True,
        check_reconcile=False,
        check_architecture=False,
    )
    cache = json.loads((out_dir / "what-now.json").read_text())
    want_id = f"operations:{COLLECT_PLAN_ID}:{choice_id}"
    matched = [i for i in cache["items"] if i["id"] == want_id]
    assert matched, f"{want_id} missing from built dashboard what-now cache"
    item = matched[0]
    assert item["exact_command"] == command
    # automatable iff a safe command exists and no human decision is required.
    assert item["automatable"] is (command is not None and not requires_human)
    if requires_human or command is None:
        assert item["human_required_reason"] is not None


# ──────── AC4 + Finding 3: feature-scoped IDs — same-kind features don't collapse ────────


def _make_two_feature_plan(tmp_path: Path) -> Path:
    """A plan with TWO in-flight features (both auditor needs_changes, within
    cap) so each yields the SAME feature-scoped iteration-continue choice."""
    plan_dir = tmp_path / "docs" / "plans" / COLLECT_PLAN_ID
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        f"id: {COLLECT_PLAN_ID}\n"
        "title: Ops demo\n"
        "type: feat\ntier: local\nstatus: active\n"
        'date: "2026-05-30"\n'
        "goal_type: infra\n"
        "surfaces:\n  - infra\n"
        "agents_required:\n  - claude\n"
        "human_gates:\n  - pre_impl\n"
        "loop_caps:\n  max_iterations: 3\n  no_progress_threshold: 2\n"
        "  wall_clock_hours: 4\n  hard_stop: false\n"
        "privacy_tier: internal\n"
        "links:\n  features: ./features.json\n  decisions: ./decisions.jsonl\n"
        "  evidence_dir: ./evidence/\n"
        "description: |\n  Ops demo.\n"
        "motivation: |\n  Ops demo.\n"
        "---\n"
        "# demo\n\n## Target\n\n```yaml\ntarget_env: dev\ntarget_project: none\n```\n\n"
        "## Acceptance Summary\n\n- x\n"
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": COLLECT_PLAN_ID,
                "schema_version": "1.0",
                "features": [
                    {"id": fid, "category": "infra", "description": "Demo feature.",
                     "acceptance": "It works.", "passes": False}
                    for fid in ("F001", "F002")
                ],
            },
            indent=2,
        )
        + "\n"
    )
    audit = plan_dir / "audit"
    audit.mkdir()
    for fid in ("F001", "F002"):
        (audit / f"claude-implementer-{fid}-i0.json").write_text(
            json.dumps({"agent": "claude", "agent_role": "implementer", "iteration": 0}) + "\n"
        )
        (audit / f"codex-auditor-{fid}-i0.json").write_text(
            json.dumps(
                {
                    "audit_id": f"{COLLECT_PLAN_ID}#codex#0",
                    "agent": "codex", "agent_role": "auditor", "iteration": 0,
                    "audit_status": "needs_changes", "findings": [], "summary": "ok",
                }
            )
            + "\n"
        )
    return plan_dir


def test_two_same_kind_blocked_features_yield_two_distinct_action_items(
    tmp_path, monkeypatch
):
    """AC4/AC5 + Finding 3: two distinct blocked features sharing one choice kind
    (iteration-continue) must produce TWO distinct, feature-scoped ActionItems in
    the built dashboard cache — they must NOT collapse to a single item."""
    from dontpanic_orchestrate import dashboard

    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    _reconciled_homes(tmp_path, monkeypatch)
    plan_dir = _make_two_feature_plan(tmp_path)
    # Keep the focus on iteration items — no setup choices in the mix.
    _patch_setup(monkeypatch)

    out_dir = tmp_path / "dash-out"
    dashboard.build(
        plans_root=plan_dir.parent,
        out_dir=out_dir,
        write_capabilities_cache=False,
        write_what_now_cache=True,
        check_reconcile=False,
        check_architecture=False,
    )
    cache = json.loads((out_dir / "what-now.json").read_text())
    f1_id = f"operations:{COLLECT_PLAN_ID}:F001:iteration-continue"
    f2_id = f"operations:{COLLECT_PLAN_ID}:F002:iteration-continue"
    ids = {i["id"] for i in cache["items"]}
    assert f1_id in ids, "F001 iteration-continue item missing (collapsed?)"
    assert f2_id in ids, "F002 iteration-continue item missing (collapsed?)"
    # Both share the same choice kind yet are distinct, feature-scoped items.
    assert f1_id != f2_id


def test_plan_level_setup_choice_dedups_across_features(tmp_path, monkeypatch):
    """AC4 (preserve intentional dedup): a PLAN-level setup blocker (split homes)
    is not feature-scoped, so even with two blocked features it collapses to a
    single ActionItem — the converse of the feature-scoped case above."""
    from dontpanic_orchestrate import dashboard

    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(tmp_path / "no-quota.json"))
    _reconciled_homes(tmp_path, monkeypatch)
    plan_dir = _make_two_feature_plan(tmp_path)
    _patch_setup(monkeypatch, split=True)  # plan-level reconcile choice

    out_dir = tmp_path / "dash-out"
    dashboard.build(
        plans_root=plan_dir.parent,
        out_dir=out_dir,
        write_capabilities_cache=False,
        write_what_now_cache=True,
        check_reconcile=False,
        check_architecture=False,
    )
    cache = json.loads((out_dir / "what-now.json").read_text())
    reconcile_items = [
        i for i in cache["items"]
        if i["id"] == f"operations:{COLLECT_PLAN_ID}:setup-reconcile-homes"
    ]
    assert len(reconcile_items) == 1, "plan-level setup choice must dedup to one item"


# ──────── Finding 4: `projects add` exact commands are shell-quoted ────────


def test_setup_register_project_shell_quotes_path_with_spaces():
    """Finding 4: a valid repo path containing spaces must render a RUNNABLE
    exact_command — the path is shell-quoted, not interpolated raw."""
    path = "/Users/me/My Repos/myrepo"
    g = og.build_guidance(
        PLAN_ID,
        setup=og.SetupNeeds(missing_project=True, project_name="myrepo", project_path=path),
    )
    c = _by_kind(g, og.KIND_ONBOARD)
    assert c.exact_command == "dontpanic projects add myrepo '/Users/me/My Repos/myrepo' --onboard"
    # The rendered command round-trips through the shell to the original args.
    parts = shlex.split(c.exact_command)
    assert parts[:3] == ["dontpanic", "projects", "add"]
    assert parts[3] == "myrepo"
    assert parts[4] == path


def test_stale_onboarding_shell_quotes_path_with_spaces():
    """Finding 4: the re-onboard (`--force --yes`) command is likewise quoted."""
    path = "/Users/me/My Repos/myrepo"
    g = og.build_guidance(
        PLAN_ID,
        setup=og.SetupNeeds(stale_onboarding=True, project_name="myrepo", project_path=path),
    )
    c = _by_kind(g, og.KIND_ONBOARD)
    assert c.exact_command == (
        "dontpanic projects add myrepo '/Users/me/My Repos/myrepo' --onboard --force --yes"
    )
    parts = shlex.split(c.exact_command)
    assert parts[4] == path
    assert parts[-2:] == ["--force", "--yes"]


# ──────── AC6/AC7 (criterion 6+7): every emitted command PASSES the validator ────────
#
# The codex i2 gap: string-equality tests (``assert cmd == "dontpanic finalize …"``)
# prove the *literal string* but never that the string is a runnable CLI shape. This
# section closes it by feeding EVERY non-null exact_command operations_guidance can
# emit — across all quota/budget/iteration/finalize/setup/doctor states — through the
# REAL token-shape validator command_validation.validate_command_tokens. A command
# whose shape the validator rejects must never be emitted (it would render a broken
# copy-paste); guidance must fall back to requires_human with exact_command=None
# instead. So a single rejected command here is a hard failure.

from dontpanic_orchestrate import command_validation as _cv

# Invocation prefixes the renderer strips before validating (per
# command_validation's module docstring): a bare ``dontpanic`` or the
# ``python -m dontpanic_orchestrate`` module form.
_CMD_PREFIXES = (
    ["python", "-m", "dontpanic_orchestrate"],
    ["dontpanic"],
)


def _strip_prefix(tokens: list[str]) -> list[str]:
    for prefix in _CMD_PREFIXES:
        if tokens[: len(prefix)] == prefix:
            return tokens[len(prefix):]
    return tokens


def _every_guidance_with_commands() -> list[og.Guidance]:
    """Build one guidance per command-emitting state across the full surface so
    EVERY non-null exact_command shape is represented at least once."""
    within = og.IterationState(max_iterations=3, iterations_used=1)
    proj = dict(project_name="myrepo", project_path="/repo/myrepo")
    return [
        # quota / budget / admission within cap → orchestrate --confirm.
        og.build_guidance(
            PLAN_ID,
            quota_cooldown=og.QuotaCooldownState(
                agent="codex", observed_pct=85.0, threshold=70.0, raise_target_pct=95.0
            ),
            iteration=within,
        ),
        og.build_guidance(
            PLAN_ID,
            budget_ceiling=og.BudgetCeilingState(
                agent="codex", observed_native=9.0, cap=8.0, unit="tok"
            ),
            iteration=within,
        ),
        og.build_guidance(
            PLAN_ID,
            admission_threshold=og.AdmissionThresholdState(
                agent="claude", observed_pct=75.0, threshold=70.0
            ),
            iteration=within,
        ),
        # iteration-only within cap → orchestrate --confirm.
        og.build_guidance(PLAN_ID, feature_id="F007", iteration=within),
        # signoff pending → approve <plan> pre_merge.
        og.build_guidance(
            PLAN_ID,
            feature_id="F001",
            signoff=og.SignoffState(
                feature_id="F001", verdict="signed_off",
                pre_merge_cleared=False, pre_merge_pending=True,
            ),
        ),
        # signoff cleared → finalize <plan> --feature <F>.
        og.build_guidance(
            PLAN_ID,
            feature_id="F001",
            signoff=og.SignoffState(
                feature_id="F001", verdict="signed_off", pre_merge_cleared=True
            ),
        ),
        # no-progress → resume <plan> --gate <breaker>.
        og.build_guidance(
            PLAN_ID,
            feature_id="F001",
            no_progress=og.NoProgressState(
                breaker_name="breaker:no_progress", detail="2 rounds"
            ),
        ),
        # setup: missing registration → projects add ... --onboard.
        og.build_guidance(PLAN_ID, setup=og.SetupNeeds(missing_project=True, **proj)),
        # setup: stale onboarding → projects add ... --onboard --force --yes.
        og.build_guidance(PLAN_ID, setup=og.SetupNeeds(stale_onboarding=True, **proj)),
        # setup: stale brief → agent brief.
        og.build_guidance(PLAN_ID, setup=og.SetupNeeds(stale_brief=True, **proj)),
        # setup: stale project config → doctor --project <name>.
        og.build_guidance(
            PLAN_ID, setup=og.SetupNeeds(stale_project_config=True, project_name="myrepo")
        ),
        # setup: split homes → reconcile homes --dry-run.
        og.build_guidance(PLAN_ID, setup=og.SetupNeeds(split_config_homes=True)),
        # setup: human-required config → doctor --agent.
        og.build_guidance(
            PLAN_ID, setup=og.SetupNeeds(human_required_config="API base URL is unset.")
        ),
        # path with shell metacharacters → quoted projects add still validates.
        og.build_guidance(
            PLAN_ID,
            setup=og.SetupNeeds(
                missing_project=True, project_name="myrepo",
                project_path="/Users/me/My Repos/myrepo",
            ),
        ),
    ]


def test_every_emitted_exact_command_passes_validate_command_tokens():
    """AC6/AC7 (criterion 7): iterate EVERY non-null exact_command emitted across
    all states and assert each PASSES command_validation.validate_command_tokens
    after stripping the `dontpanic` / `python -m dontpanic_orchestrate` prefix.

    This is what makes the green suite prove validity rather than mere string
    equality (closes the codex i2 gap). Every command the AC6 set names —
    `agent brief`, `finalize … --feature`, `what-now … --feature`, `orchestrate`,
    `doctor --agent`, `doctor --project`, `reconcile homes [--dry-run]`,
    `projects add … --onboard --force --yes` — is exercised here through a real
    guidance build.
    """
    seen: set[str] = set()
    checked = 0
    for guidance in _every_guidance_with_commands():
        for choice in guidance.choices:
            cmd = choice.exact_command
            if not cmd:
                # AC7: a choice with no safe command must be requires_human.
                assert choice.requires_human, (
                    f"{choice.id} has no exact_command but is not requires_human"
                )
                continue
            tokens = _strip_prefix(shlex.split(cmd))
            result = _cv.validate_command_tokens(tokens)
            assert result.ok, (
                f"emitted command is NOT a valid CLI shape: {cmd!r} "
                f"(choice {choice.id}): {result.reason}"
            )
            seen.add(tokens[0])
            checked += 1
    assert checked >= 9, "expected commands from every emitting state"
    # The AC6 command set must all be represented across the built guidances.
    for required in {
        "orchestrate", "approve", "finalize", "resume",
        "projects", "doctor", "agent", "reconcile",
    }:
        assert required in seen, f"AC6 command {required!r} never emitted/validated"


def test_what_now_command_shape_is_validator_recognized():
    """AC6: `what-now <plan> --feature <F>` is named in the AC6 command set and
    must be a recognized validator shape even though guidance does not emit it
    (it is the surface that PRINTS guidance, not a remediation command)."""
    result = _cv.validate_command_tokens(["what-now", PLAN_ID, "--feature", "F001"])
    assert result.ok, result.reason
