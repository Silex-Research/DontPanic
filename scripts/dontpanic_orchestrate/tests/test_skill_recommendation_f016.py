"""Plan 2026-05-30-001 F016 — skill recommendation SURFACES + migration tests.

Coverage map to acceptance (AC14c):

  AC8   Missing inputs collapse to ONE concise ActionChoice naming ONLY the
        missing blocker(s) — no per-skill prompting prose.
  AC9   CLI and dashboard render the SAME RecommendationReport JSON (parity):
        the dashboard ``skill-recommendations.json`` equals the report
        ``to_dict()`` the CLI ``--format json`` prints, and the missing-input
        action also surfaces as a real what-now ActionItem.
  AC10  F008 config-inventory blockers are SPECIFIC: a blocked skill names only
        the inventory item(s) it actually depends on, never an unrelated
        credential/capability.
  AC11  Migration path: ``suggest_rubric`` proposes a SAFE (never-auto) starting
        rubric; ``skills_missing_rubrics`` identifies high-value metadata-less
        skills — advisory only.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_skill_recommendation_f016.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import skill_recommendation as sr  # noqa: E402
from dontpanic_orchestrate.skill_invocation import (  # noqa: E402
    Invocation,
    InvocationMode,
    Recommendation,
    Risk,
    RiskFlag,
    SkillAction,
    SkillRubric,
)

PLAN_ID = "2026-05-30-001-feat-universal-agent-repo-onboarding-v0"


# ─────────────────────────── fixtures / helpers ────────────────────────────


def _blocked(skill: str, *inputs: str) -> SkillAction:
    return SkillAction(
        skill_name=skill,
        recommendation=Recommendation.BLOCKED_MISSING_INPUTS,
        reason=f"missing required inputs: {list(inputs)}",
        risk=Risk.LOW,
        missing_inputs=tuple(inputs),
    )


def _approval(skill: str, *flags: RiskFlag) -> SkillAction:
    return SkillAction(
        skill_name=skill,
        recommendation=Recommendation.APPROVAL_REQUIRED,
        reason="declared approval_required",
        risk=Risk.HIGH if flags else Risk.LOW,
        approval_required=True,
    )


def _rubric(skill: str, *flags: RiskFlag, mode: InvocationMode = InvocationMode.APPROVAL_REQUIRED) -> SkillRubric:
    return SkillRubric(
        skill_name=skill,
        applicable=True,
        invocation=Invocation(mode=mode, risk_flags=tuple(flags)),
    )


def _res(item_id: str, scope: str, *, ok: bool, title: str | None = None) -> sr.ResourceStatus:
    return sr.ResourceStatus(
        id=item_id,
        title=title or item_id,
        scope=scope,
        status="ok" if ok else "needs_setup",
        ok=ok,
    )


def _write_plan(plans_root: Path) -> Path:
    plan_dir = plans_root / PLAN_ID
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\n"
        f"id: {PLAN_ID}\n"
        "title: Onboarding demo\n"
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
        "description: |\n  Onboarding recommendation demo plan.\n"
        "motivation: |\n  Onboarding recommendation demo plan.\n"
        "---\n"
        "# demo\n\n## Target\n\n```yaml\ntarget_env: dev\ntarget_project: none\n```\n\n"
        "## Acceptance Summary\n\n- x\n"
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": PLAN_ID,
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F016",
                        "category": "infra",
                        "description": "Skill recommendation surfaces demo feature.",
                        "acceptance": "The recommender renders the report on both surfaces.",
                        "passes": False,
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return plan_dir


def _write_skill(skills_dir: Path, name: str, *, frontmatter: str) -> None:
    sk = skills_dir / name
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text(f"---\n{frontmatter}---\n\n# {name}\n")


# ───────────────────────────── AC8: one concise action ─────────────────────


def test_missing_inputs_collapse_to_one_concise_action_naming_only_blockers():
    actions = [
        _blocked("alpha", "token"),
        _blocked("beta", "changed_files", "token"),
    ]
    choice = sr.build_missing_input_action(actions, plan_id=PLAN_ID)
    assert choice is not None
    assert choice.id == sr.MISSING_INPUT_CHOICE_ID
    assert choice.requires_human is True
    assert choice.exact_command is None  # no safe auto-run command for a human input
    # Names ONLY the distinct missing inputs, de-duplicated, no per-skill prose.
    assert choice.rationale == "Missing skill input(s): token, changed_files."
    assert "alpha" not in choice.rationale
    assert "beta" not in choice.rationale
    assert "automatically" not in choice.rationale.lower()


def test_no_missing_inputs_yields_no_action():
    actions = [_approval("alpha")]
    assert sr.build_missing_input_action(actions, plan_id=PLAN_ID) is None


# ───────────────────────────── AC10: specific blockers ─────────────────────


def test_paid_skill_blames_only_its_specific_credential_not_every_secret():
    actions = [_approval("paid-skill", RiskFlag.PAID)]
    rubrics = {"paid-skill": _rubric("paid-skill", RiskFlag.PAID)}
    resources = [
        _res("secret_anthropic_auth", "secret", ok=False),
        _res("secret_gcp_sa_key", "secret", ok=False),
        _res("secret_discord_webhook", "secret", ok=False),
    ]
    blockers = sr.explain_blockers(actions, rubrics, resources)
    assert len(blockers) == 1
    ids = {r.id for r in blockers[0].unavailable_resources}
    # PAID maps ONLY to the worker credential — the unrelated GCP / Discord
    # secrets are NOT attached (the prior scope-wide sweep would have).
    assert ids == {"secret_anthropic_auth"}
    assert "secret_anthropic_auth" in blockers[0].explanation
    assert "gcp" not in blockers[0].explanation.lower()


def test_network_only_skill_does_not_blame_any_secret():
    actions = [_approval("net-skill", RiskFlag.NETWORK_ACCESS)]
    rubrics = {"net-skill": _rubric("net-skill", RiskFlag.NETWORK_ACCESS)}
    resources = [_res("secret_anthropic_auth", "secret", ok=False)]
    # network_access alone maps to no specific config item → no blocker noise.
    assert sr.explain_blockers(actions, rubrics, resources) == []


def test_available_resource_produces_no_blocker():
    actions = [_approval("paid-skill", RiskFlag.PAID)]
    rubrics = {"paid-skill": _rubric("paid-skill", RiskFlag.PAID)}
    resources = [_res("secret_anthropic_auth", "secret", ok=True)]
    assert sr.explain_blockers(actions, rubrics, resources) == []


def test_explicit_required_resource_ids_override_is_honored():
    actions = [_approval("custom")]
    rubrics = {"custom": _rubric("custom")}  # no risk flags
    resources = [
        _res("secret_gcp_sa_key", "secret", ok=False),
        _res("secret_anthropic_auth", "secret", ok=False),
    ]
    blockers = sr.explain_blockers(
        actions, rubrics, resources, required_resource_ids={"custom": ["secret_gcp_sa_key"]}
    )
    assert len(blockers) == 1
    assert {r.id for r in blockers[0].unavailable_resources} == {"secret_gcp_sa_key"}


# ─────────── AC10: external-CLI binary blockers (codex i0 findings #2/#3) ───────────


def _present(_binary: str) -> bool:
    return True


def _absent(_binary: str) -> bool:
    return False


def test_absent_external_cli_emits_specific_capability_blocker_without_inventory_row():
    # A live skill declares external_cli.command = cli-printing-press; the binary
    # is NOT on PATH and NO config-inventory provider names it. The recommender
    # must still emit a SPECIFIC capability/inventory blocker (codex finding #2),
    # not silently skip it.
    actions = [_approval("printing-press-adapter")]
    rubrics = {"printing-press-adapter": _rubric("printing-press-adapter")}
    blockers = sr.explain_blockers(
        actions,
        rubrics,
        resources=[],  # no inventory row names the binary
        external_clis={"printing-press-adapter": "cli-printing-press"},
        binary_on_path=_absent,
    )
    assert len(blockers) == 1
    ids = {r.id for r in blockers[0].unavailable_resources}
    assert sr.external_binary_id("cli-printing-press") in ids
    assert "cli-printing-press" in blockers[0].explanation
    assert "PATH" in blockers[0].explanation
    # The synthesized row is capability-scoped and unavailable.
    synth = next(
        r for r in blockers[0].unavailable_resources
        if r.id == sr.external_binary_id("cli-printing-press")
    )
    assert synth.scope == "capability"
    assert synth.ok is False


def test_present_external_cli_is_not_a_blocker():
    # When the binary IS on PATH and nothing else is missing, the skill is ready
    # and produces no blocker (AC10 specificity — a present CLI is not blamed).
    actions = [_approval("printing-press-adapter")]
    rubrics = {"printing-press-adapter": _rubric("printing-press-adapter")}
    blockers = sr.explain_blockers(
        actions,
        rubrics,
        resources=[],
        external_clis={"printing-press-adapter": "cli-printing-press"},
        binary_on_path=_present,
    )
    assert blockers == []


def test_absent_external_cli_prefers_named_inventory_row_over_synthetic():
    # When a real capability row names the binary AND it is unavailable, attach
    # THAT row (specific) rather than fabricating a synthetic one — and never the
    # whole unavailable capability set.
    actions = [_approval("printing-press-adapter")]
    rubrics = {"printing-press-adapter": _rubric("printing-press-adapter")}
    resources = [
        sr.ResourceStatus(
            id="capability_cli_printing_press",
            title="cli-printing-press adapter",
            scope="capability",
            status="needs_setup",
            ok=False,
        ),
        _res("capability_unrelated", "capability", ok=False),
    ]
    blockers = sr.explain_blockers(
        actions,
        rubrics,
        resources,
        external_clis={"printing-press-adapter": "cli-printing-press"},
        binary_on_path=_absent,
    )
    assert len(blockers) == 1
    ids = {r.id for r in blockers[0].unavailable_resources}
    # Only the named row — never the unrelated capability, never a duplicate synth.
    assert ids == {"capability_cli_printing_press"}


# ───────────────────────────── AC11: migration suggestions ─────────────────


def test_suggest_rubric_proposes_safe_suggest_mode_for_benign_skill():
    sug = sr.suggest_rubric("tidy", {"description": "Reformat local files."})
    assert sug.already_has_metadata is False
    assert sug.proposed["mode"] == InvocationMode.SUGGEST.value
    # Never proposes an auto mode (always human-gated migration).
    assert "auto" not in sug.proposed["mode"]
    assert "invocation:" in sug.yaml_block


def test_suggest_rubric_escalates_risky_skill_to_approval_required():
    sug = sr.suggest_rubric("deployer", {"description": "Deploy and publish to prod."})
    assert sug.proposed["mode"] == InvocationMode.APPROVAL_REQUIRED.value
    assert sug.proposed["risk_flags"]  # at least one heuristic flag detected


def test_suggest_rubric_derives_required_inputs_from_argument_hint():
    # `autoresearch` declares an argument-hint with a required <topic> + a
    # documented [--depth N] flag. suggest_rubric must seed required_inputs from
    # them rather than proposing required_inputs: [] (codex finding #5).
    sug = sr.suggest_rubric(
        "autoresearch",
        {
            "description": "Deep multi-source web research.",
            "argument-hint": "<topic> [--depth N]",
        },
    )
    assert "topic" in sug.proposed["required_inputs"]
    assert "depth" in sug.proposed["required_inputs"]
    # The block is still a valid, never-auto rubric.
    assert sug.proposed["mode"] != "auto_safe"
    assert sug.proposed["mode"] != "auto_readonly"


def test_suggest_rubric_derives_required_inputs_from_trigger_and_explicit_fields():
    # `prompt-optimizer` documents its required eval inputs via a trigger mapping
    # and an explicit root-level required_inputs list. Both feed the proposal,
    # de-duplicated + order-preserving.
    sug = sr.suggest_rubric(
        "prompt-optimizer",
        {
            "description": "Optimize a prompt.",
            "triggers": [{"required_inputs": ["prompt", "model"]}],
            "required_inputs": ["model", "budget"],
        },
    )
    ri = sug.proposed["required_inputs"]
    assert ri == ["prompt", "model", "budget"]  # de-duped, order-preserving


def test_suggest_rubric_without_declared_inputs_stays_empty():
    # No argument-hint / triggers / explicit inputs → conservative empty list
    # (description prose is NOT parsed, so we never over-trigger).
    sug = sr.suggest_rubric("tidy", {"description": "Reformat local files quickly."})
    assert sug.proposed["required_inputs"] == []


# ───────────────────────── AC11: doctor advisory (codex finding #4) ─────────


def test_doctor_advisory_lists_missing_rubric_skills_with_suggest_commands(tmp_path):
    skills = tmp_path / "claude" / "skills"
    _write_skill(skills, "needs-rubric", frontmatter="applies_to:\n  surfaces:\n    - infra\n")
    advisory = sr.doctor_missing_rubric_advisory(skills)
    assert advisory.has_findings is True
    assert advisory.skill_names == ("needs-rubric",)
    assert "dontpanic skills rubric --suggest needs-rubric" in advisory.suggest_commands
    assert "needs-rubric" in advisory.message
    assert "dontpanic skills rubric --suggest needs-rubric" in advisory.remediation


def test_doctor_advisory_empty_when_all_skills_have_rubrics(tmp_path):
    skills = tmp_path / "claude" / "skills"
    _write_skill(
        skills,
        "has-rubric",
        frontmatter="applies_to:\n  surfaces:\n    - infra\ninvocation:\n  mode: suggest\n",
    )
    advisory = sr.doctor_missing_rubric_advisory(skills)
    assert advisory.has_findings is False
    assert advisory.skill_names == ()
    assert advisory.remediation == ""


def test_doctor_check_emits_non_blocking_warn(tmp_path, monkeypatch):
    # The dontpanic_doctor hook must surface the advisory as a WARN (ok=True,
    # warn=True) — never a FAIL — so a metadata-less skill never blocks the
    # battery (AC11).
    import dontpanic_doctor as dd

    skills = tmp_path / "claude" / "skills"
    _write_skill(skills, "needs-rubric", frontmatter="applies_to:\n  surfaces:\n    - infra\n")
    results = dd.check_skill_rubrics_advisory(repo_root=tmp_path)
    assert len(results) == 1
    r = results[0]
    assert r.name == "skill-rubrics"
    assert r.ok is True  # advisory — never a FAIL
    assert r.warn is True
    assert "needs-rubric" in r.message
    assert "skills rubric --suggest needs-rubric" in (r.remediation or "")


def test_doctor_check_passes_when_no_skills_dir(tmp_path):
    import dontpanic_doctor as dd

    results = dd.check_skill_rubrics_advisory(repo_root=tmp_path)
    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].warn is False  # PASS, not WARN


def test_skills_missing_rubrics_lists_high_value_metadata_less_skills(tmp_path):
    skills = tmp_path / "claude" / "skills"
    # High-value: declares applies_to but no invocation rubric.
    _write_skill(skills, "needs-rubric", frontmatter="applies_to:\n  surfaces:\n    - infra\n")
    # Already has a rubric → not listed.
    _write_skill(
        skills,
        "has-rubric",
        frontmatter="applies_to:\n  surfaces:\n    - infra\ninvocation:\n  mode: suggest\n",
    )
    # No applies_to and not applicable → not high-value, not listed.
    _write_skill(skills, "loner", frontmatter="description: nothing\n")
    missing = sr.skills_missing_rubrics(skills)
    assert missing == ["needs-rubric"]


# ───────────────────────────── AC9: CLI / dashboard parity ──────────────────


def test_dashboard_json_shape_matches_cli_report_dict(tmp_path):
    from dontpanic_orchestrate import dashboard

    plans_root = tmp_path / "docs" / "plans"
    plan_dir = _write_plan(plans_root)
    skills = tmp_path / "claude" / "skills"
    # A blocked-missing-input skill so the report carries actions + a single
    # missing-input action (exercises the full shape).
    _write_skill(
        skills,
        "needy",
        frontmatter=(
            "applies_to:\n  surfaces:\n    - infra\n"
            "invocation:\n  mode: suggest\n  required_inputs:\n    - token\n"
        ),
    )

    # CLI surface: the exact dict `dontpanic skills recommend --format json` prints.
    cli_dict = sr.collect(plan_dir, skills).to_dict()

    # Dashboard surface: the JSON `dashboard build` writes.
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    path = dashboard.write_skill_recommendations(
        out_dir=out_dir, plans_root=plans_root, plan_id=PLAN_ID
    )
    assert path is not None and path.is_file()
    dash_dict = json.loads(path.read_text())

    assert dash_dict == cli_dict
    # The report carries the per-skill SkillAction fields the surfaces render.
    assert dash_dict["actions"], "expected at least one surfaced skill action"
    action = next(a for a in dash_dict["actions"] if a["skill_name"] == "needy")
    for field in ("recommendation", "reason", "risk", "evidence_target"):
        assert field in action
    assert dash_dict["missing_input_action"] is not None


def test_collect_blocked_skill_emits_single_missing_input_action(tmp_path):
    plans_root = tmp_path / "docs" / "plans"
    plan_dir = _write_plan(plans_root)
    skills = tmp_path / "claude" / "skills"
    _write_skill(
        skills,
        "needy",
        frontmatter=(
            "applies_to:\n  surfaces:\n    - infra\n"
            "invocation:\n  mode: suggest\n  required_inputs:\n    - token\n"
        ),
    )
    report = sr.collect(plan_dir, skills)
    assert report.missing_input_action is not None
    assert report.missing_input_action.rationale == "Missing skill input(s): token."


# ─────────────────────── AC8/AC9: dashboard action-item wiring ──────────────


def test_dashboard_surfaces_missing_input_as_action_item(tmp_path):
    from dontpanic_orchestrate import dashboard

    plans_root = tmp_path / "docs" / "plans"
    plan_dir = _write_plan(plans_root)
    skills = tmp_path / "claude" / "skills"
    _write_skill(
        skills,
        "needy",
        frontmatter=(
            "applies_to:\n  surfaces:\n    - infra\n"
            "invocation:\n  mode: suggest\n  required_inputs:\n    - token\n"
        ),
    )
    items = dashboard._gather_skill_recommendation_items({PLAN_ID: plan_dir})
    ids = [i.id for i in items]
    assert any(sr.MISSING_INPUT_CHOICE_ID in i for i in ids), ids


def test_build_returns_skill_recommendations_path_and_action_item(tmp_path):
    from dontpanic_orchestrate import dashboard

    plans_root = tmp_path / "docs" / "plans"
    _write_plan(plans_root)
    skills = tmp_path / "claude" / "skills"
    _write_skill(
        skills,
        "needy",
        frontmatter=(
            "applies_to:\n  surfaces:\n    - infra\n"
            "invocation:\n  mode: suggest\n  required_inputs:\n    - token\n"
        ),
    )
    out_dir = tmp_path / "out"
    report = dashboard.build(
        plans_root=plans_root,
        out_dir=out_dir,
        plan_id=PLAN_ID,
        repo_root=tmp_path,
        write_capabilities_cache=False,
        check_reconcile=False,
        check_architecture=False,
    )
    assert report.skill_recommendations_path is not None
    assert report.skill_recommendations_path.is_file()
    # The missing-input action is merged into the what-now action queue.
    what_now = (out_dir / "what-now.json").read_text()
    assert sr.MISSING_INPUT_CHOICE_ID in what_now
