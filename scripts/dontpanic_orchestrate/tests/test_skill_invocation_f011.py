"""Plan 2026-05-30-001 F011 — skill-invocation rubric CORE engine tests.

Coverage map to acceptance (D060 split):

  AC1   ``invocation:`` schema validates; metadata-less skills are a no-op.
  AC2   pure evaluator emits typed SkillAction with the five recommendations.
  AC3   metadata-less applicable skills default to suggest, never auto_run.
  AC6   deterministic risk precedence: never_auto/never_suggest win; every risk
        flag + missing inputs block auto_run regardless of declared mode;
        contradictory metadata yields a diagnostic, not silent trust.
  AC12  never_suggest opt-out keeps noisy/toolkit skills out of recommendations.
  AC13  the 13 representative skill fixtures parse and evaluate.
  AC14a each recommendation class, no-auto fallback, never_suggest opt-out,
        contradictory-metadata precedence, and missing-input handling — all at
        the pure-evaluator level.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_skill_invocation_f011.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.skill_invocation import (  # noqa: E402
    Invocation,
    InvocationMode,
    Recommendation,
    Risk,
    RiskFlag,
    SkillAction,
    SkillInvocationContext,
    SkillRubric,
    evaluate,
    load_rubric,
    parse_invocation,
    recommendations,
)

FIXTURES = HERE.parent / "fixtures" / "skill_rubrics"

REPRESENTATIVE_SKILLS = [
    "autoresearch",
    "security-review",
    "eval-harness",
    "test-runner",
    "cost-model",
    "changelog",
    "browser-use",
    "revenue-check",
    "github-pr",
    "worktree-isolation",
    "subagent-driven-dev",
    "prompt-optimizer",
    "printing-press-adapter",
]


# ────────────────────────────  helpers  ────────────────────────────


def _read_frontmatter(skill_md: Path) -> dict[str, Any]:
    text = skill_md.read_text()
    assert text.startswith("---"), f"{skill_md} missing frontmatter"
    parts = text.split("---", 2)
    loaded = yaml.safe_load(parts[1])
    assert isinstance(loaded, dict)
    return loaded


def _allow(*allowed: str):
    allowset = set(allowed)
    return lambda command: command in allowset


def _ctx(rubric: SkillRubric, **overrides: Any) -> SkillInvocationContext:
    base: dict[str, Any] = dict(
        skills=(rubric,),
        lifecycle_stage=None,
        provided_inputs=(),
        budget_ok=True,
        is_command_allowlisted=_allow(),
    )
    base.update(overrides)
    return SkillInvocationContext(**base)


def _only(ctx: SkillInvocationContext) -> SkillAction:
    actions = evaluate(ctx)
    assert len(actions) == 1
    return actions[0]


# ────────────────────────────  AC1: schema + no-op  ────────────────────────────


def test_parse_invocation_is_noop_for_metadata_less_frontmatter():
    # A skill that lacks the invocation: block parses cleanly to (None, None) —
    # adding the schema never breaks a metadata-less skill.
    inv, reason = parse_invocation({"name": "plain", "description": "no block"})
    assert inv is None
    assert reason is None


def test_parse_invocation_accepts_full_block():
    inv, reason = parse_invocation(
        {
            "invocation": {
                "mode": "auto_readonly",
                "lifecycle_stages": ["review"],
                "required_inputs": ["changed_files"],
                "risk_flags": [],
                "evidence_target": "evidence/x.json",
                "command_template": "dontpanic skills run x",
            }
        }
    )
    assert reason is None
    assert isinstance(inv, Invocation)
    assert inv.mode is InvocationMode.AUTO_READONLY
    assert inv.lifecycle_stages == ("review",)
    assert inv.command_template == "dontpanic skills run x"


@pytest.mark.parametrize(
    "block,needle",
    [
        ({"mode": "teleport"}, "mode"),
        ({"mode": "auto_safe", "risk_flags": ["meltdown"]}, "risk_flags"),
        ({"mode": "suggest", "bogus_key": 1}, "bogus_key"),
        ({"mode": "suggest", "lifecycle_stages": [""]}, "lifecycle_stages"),
        ("not-a-mapping", "mapping"),
    ],
)
def test_parse_invocation_reports_invalid_block(block, needle):
    inv, reason = parse_invocation({"invocation": block})
    assert inv is None
    assert reason is not None
    assert needle in reason


# evidence_target is part of the invocation: schema. It is REQUIRED for the
# auto-eligible modes (the only ones the evaluator can classify as auto_run, and
# the only ones that run unattended), and may be omitted for the human-driven
# modes — the explicitly-encoded narrow modes where omission is allowed (AC1).


@pytest.mark.parametrize("mode", ["auto_readonly", "auto_safe"])
def test_auto_modes_require_evidence_target(mode):
    inv, reason = parse_invocation(
        {"invocation": {"mode": mode, "command_template": "cmd"}}
    )
    assert inv is None
    assert reason is not None
    assert "evidence_target" in reason


@pytest.mark.parametrize("mode", ["auto_readonly", "auto_safe"])
def test_auto_modes_reject_blank_evidence_target(mode):
    inv, reason = parse_invocation(
        {"invocation": {"mode": mode, "evidence_target": "   "}}
    )
    assert inv is None
    assert reason is not None
    assert "evidence_target" in reason


@pytest.mark.parametrize(
    "mode", ["suggest", "approval_required", "never_auto", "never_suggest"]
)
def test_human_driven_modes_may_omit_evidence_target(mode):
    inv, reason = parse_invocation({"invocation": {"mode": mode}})
    assert reason is None, f"{mode}: {reason}"
    assert isinstance(inv, Invocation)
    assert inv.evidence_target is None


# ────────────────────────────  AC2 + AC14a: recommendation classes  ────────────────────────────


def test_auto_run_when_safe_inputs_satisfied_and_allowlisted():
    rubric = load_rubric(
        "test-runner",
        {
            "invocation": {
                "mode": "auto_safe",
                "required_inputs": ["test_path"],
                "evidence_target": "evidence/test-output.txt",
                "command_template": "pytest -q",
            }
        },
    )
    action = _only(
        _ctx(
            rubric,
            provided_inputs=("test_path",),
            is_command_allowlisted=_allow("pytest -q"),
        )
    )
    assert action.recommendation is Recommendation.AUTO_RUN
    assert action.exact_command == "pytest -q"
    assert action.risk is Risk.LOW
    assert action.approval_required is False


def test_auto_mode_downgrades_to_suggest_when_command_not_allowlisted():
    # The engine never auto-runs an un-allowlisted command — the F015 predicate
    # is the gate. exact_command stays None on the suggest path: only the
    # auto_run path (allowlisted + safe) is allowed to surface a runnable command
    # (exact_command-when-safe, AC2).
    rubric = load_rubric(
        "test-runner",
        {
            "invocation": {
                "mode": "auto_safe",
                "evidence_target": "evidence/test-output.txt",
                "command_template": "pytest -q",
            }
        },
    )
    action = _only(_ctx(rubric, is_command_allowlisted=_allow()))
    assert action.recommendation is Recommendation.SUGGEST
    assert action.exact_command is None
    assert "allowlist" in action.reason


def test_auto_mode_without_command_template_suggests():
    rubric = load_rubric(
        "x",
        {"invocation": {"mode": "auto_readonly", "evidence_target": "evidence/x.json"}},
    )
    action = _only(_ctx(rubric, is_command_allowlisted=lambda _c: True))
    assert action.recommendation is Recommendation.SUGGEST
    assert "command_template" in action.reason


def test_auto_mode_blocked_when_budget_forbids():
    rubric = load_rubric(
        "x",
        {
            "invocation": {
                "mode": "auto_safe",
                "evidence_target": "evidence/x.json",
                "command_template": "cmd",
            }
        },
    )
    action = _only(
        _ctx(rubric, budget_ok=False, is_command_allowlisted=_allow("cmd"))
    )
    assert action.recommendation is Recommendation.SUGGEST
    assert "budget" in action.reason


def test_suggest_mode():
    rubric = load_rubric("prompt-optimizer", {"invocation": {"mode": "suggest"}})
    assert _only(_ctx(rubric)).recommendation is Recommendation.SUGGEST


@pytest.mark.parametrize(
    "block,ctx_kw",
    [
        # suggest mode with a repo-mutating command must NOT leak it as runnable.
        (
            {
                "mode": "suggest",
                "risk_flags": ["repo_mutation"],
                "command_template": "git commit -am x",
            },
            {},
        ),
        # never_auto downgrade — command stays hidden even when allowlisted.
        (
            {"mode": "never_auto", "command_template": "git push"},
            {"is_command_allowlisted": lambda _c: True},
        ),
        # approval_required — command not cleared for execution.
        (
            {"mode": "approval_required", "command_template": "deploy prod"},
            {},
        ),
        # auto mode blocked by budget — un-cleared, so not surfaced.
        (
            {
                "mode": "auto_safe",
                "evidence_target": "evidence/x.json",
                "command_template": "cmd",
            },
            {"budget_ok": False, "is_command_allowlisted": lambda _c: True},
        ),
    ],
)
def test_exact_command_only_surfaced_on_auto_run(block, ctx_kw):
    # exact_command-when-safe (AC2): every non-auto_run path leaves exact_command
    # None so an unsafe/un-allowlisted command is never handed out as runnable.
    rubric = load_rubric("s", {"invocation": block})
    action = _only(_ctx(rubric, **ctx_kw))
    assert action.recommendation is not Recommendation.AUTO_RUN
    assert action.exact_command is None


def test_approval_required_mode():
    rubric = load_rubric("github-pr", {"invocation": {"mode": "approval_required"}})
    action = _only(_ctx(rubric))
    assert action.recommendation is Recommendation.APPROVAL_REQUIRED
    assert action.approval_required is True


def test_not_applicable_when_f007_excludes_skill():
    rubric = SkillRubric(skill_name="x", applicable=False)
    action = _only(_ctx(rubric))
    assert action.recommendation is Recommendation.NOT_APPLICABLE


def test_not_applicable_when_lifecycle_stage_excludes():
    rubric = load_rubric(
        "x",
        {
            "invocation": {
                "mode": "auto_safe",
                "lifecycle_stages": ["review"],
                "evidence_target": "evidence/x.json",
            }
        },
    )
    action = _only(_ctx(rubric, lifecycle_stage="planning"))
    assert action.recommendation is Recommendation.NOT_APPLICABLE
    assert "lifecycle" in action.reason


# ────────────────────────────  AC3: no-auto fallback  ────────────────────────────


def test_metadata_less_applicable_skill_defaults_to_suggest_never_auto():
    rubric = SkillRubric(skill_name="legacy-skill", applicable=True, invocation=None)
    action = _only(_ctx(rubric, is_command_allowlisted=lambda _c: True))
    assert action.recommendation is Recommendation.SUGGEST
    assert action.recommendation is not Recommendation.AUTO_RUN
    assert "never auto-run" in action.reason


# ────────────────────────────  AC6: risk precedence  ────────────────────────────


@pytest.mark.parametrize("flag", [f.value for f in RiskFlag])
def test_every_risk_flag_blocks_auto_run_regardless_of_declared_mode(flag):
    # Declaring an auto mode alongside ANY auto-blocking risk flag is
    # contradictory — the engine emits a diagnostic approval_required action
    # rather than silently trusting the unsafe auto declaration.
    rubric = load_rubric(
        "risky",
        {
            "invocation": {
                "mode": "auto_safe",
                "risk_flags": [flag],
                "evidence_target": "evidence/x.json",
                "command_template": "cmd",
            }
        },
    )
    action = _only(
        _ctx(rubric, is_command_allowlisted=_allow("cmd"))  # allowlisted yet blocked
    )
    assert action.recommendation is Recommendation.APPROVAL_REQUIRED
    assert action.recommendation is not Recommendation.AUTO_RUN
    assert action.approval_required is True
    assert action.risk is Risk.HIGH
    assert "contradictory metadata" in action.reason
    assert flag in action.reason


def test_contradictory_metadata_yields_diagnostic_not_silent_trust():
    rubric = load_rubric(
        "evil",
        {
            "invocation": {
                "mode": "auto_readonly",
                "risk_flags": ["external_writes", "repo_mutation"],
                "evidence_target": "evidence/x.json",
                "command_template": "rm -rf /",
            }
        },
    )
    action = _only(_ctx(rubric, is_command_allowlisted=lambda _c: True))
    assert action.recommendation is Recommendation.APPROVAL_REQUIRED
    assert "external_writes" in action.reason
    assert "repo_mutation" in action.reason


def test_invalid_metadata_block_is_diagnostic():
    # A present-but-malformed invocation block is a contradiction, not "no
    # metadata" — never falls through to suggest/auto.
    rubric = load_rubric("broken", {"invocation": {"mode": "not-a-mode"}})
    assert rubric.invalid_reason is not None
    action = _only(_ctx(rubric))
    assert action.recommendation is Recommendation.APPROVAL_REQUIRED
    assert action.approval_required is True
    assert "contradictory metadata" in action.reason


def test_never_auto_downgrades_to_suggest():
    rubric = load_rubric(
        "na",
        {"invocation": {"mode": "never_auto", "command_template": "cmd"}},
    )
    action = _only(_ctx(rubric, is_command_allowlisted=_allow("cmd")))
    assert action.recommendation is Recommendation.SUGGEST
    assert "never_auto" in action.reason


def test_never_auto_wins_over_auto_eligibility_even_when_allowlisted():
    # Precedence: explicit never_auto beats an otherwise auto-runnable setup.
    rubric = load_rubric(
        "na", {"invocation": {"mode": "never_auto", "command_template": "cmd"}}
    )
    action = _only(_ctx(rubric, is_command_allowlisted=lambda _c: True))
    assert action.recommendation is not Recommendation.AUTO_RUN


# ────────────────────────────  AC12: never_suggest opt-out  ────────────────────────────


def test_never_suggest_keeps_skill_out_of_recommendations():
    rubric = load_rubric("subagent-driven-dev", {"invocation": {"mode": "never_suggest"}})
    action = _only(_ctx(rubric))
    assert action.recommendation is Recommendation.NOT_APPLICABLE
    assert "never_suggest" in action.reason
    # And it is filtered out of the surfaceable set entirely.
    assert recommendations(_ctx(rubric)) == []


def test_never_suggest_wins_even_with_other_signals():
    rubric = load_rubric(
        "toolkit",
        {
            "invocation": {
                "mode": "never_suggest",
                "lifecycle_stages": ["planning"],
            }
        },
    )
    # Even in a matching lifecycle stage with inputs present, stays suppressed.
    action = _only(_ctx(rubric, lifecycle_stage="planning"))
    assert action.recommendation is Recommendation.NOT_APPLICABLE


# ────────────────────────────  AC6: missing-input handling  ────────────────────────────


def test_missing_inputs_block_with_blocked_missing_inputs():
    rubric = load_rubric(
        "needs-input",
        {
            "invocation": {
                "mode": "auto_safe",
                "required_inputs": ["research_question", "budget"],
                "evidence_target": "evidence/x.json",
                "command_template": "cmd",
            }
        },
    )
    action = _only(
        _ctx(
            rubric,
            provided_inputs=("budget",),
            is_command_allowlisted=_allow("cmd"),
        )
    )
    assert action.recommendation is Recommendation.BLOCKED_MISSING_INPUTS
    assert action.missing_inputs == ("research_question",)


def test_never_auto_wins_over_missing_input():
    # Precedence (documented rule 6): "explicit never_auto/never_suggest wins"
    # is taken literally — never_auto resolves BEFORE the missing-input check and
    # downgrades to suggest, even when required inputs are absent. The missing
    # inputs are still surfaced on the action for the operator, but the
    # recommendation stays suggest (never blocked_missing_inputs), mirroring
    # never_suggest winning outright.
    rubric = load_rubric(
        "na",
        {
            "invocation": {
                "mode": "never_auto",
                "required_inputs": ["x"],
                "command_template": "cmd",
            }
        },
    )
    action = _only(_ctx(rubric))  # x not provided
    assert action.recommendation is Recommendation.SUGGEST
    assert action.missing_inputs == ("x",)
    assert action.exact_command is None


def test_approval_required_with_missing_input_blocks():
    # Same precedence holds for approval_required.
    rubric = load_rubric(
        "ar",
        {"invocation": {"mode": "approval_required", "required_inputs": ["y"]}},
    )
    action = _only(_ctx(rubric))
    assert action.recommendation is Recommendation.BLOCKED_MISSING_INPUTS
    assert action.missing_inputs == ("y",)


def test_inputs_satisfied_clears_missing_block():
    rubric = load_rubric(
        "needs-input",
        {
            "invocation": {
                "mode": "auto_safe",
                "required_inputs": ["a"],
                "evidence_target": "evidence/x.json",
                "command_template": "cmd",
            }
        },
    )
    action = _only(
        _ctx(rubric, provided_inputs=("a",), is_command_allowlisted=_allow("cmd"))
    )
    assert action.recommendation is Recommendation.AUTO_RUN


# ────────────────────────────  AC2: typed record + determinism  ────────────────────────────


def test_to_dict_is_json_safe_and_typed():
    rubric = load_rubric("github-pr", {"invocation": {"mode": "approval_required"}})
    data = _only(_ctx(rubric)).to_dict()
    assert data["recommendation"] == "approval_required"
    assert data["risk"] in {"low", "medium", "high"}
    assert isinstance(data["missing_inputs"], list)


def test_evaluate_is_name_sorted_and_deterministic():
    rubrics = (
        load_rubric("zeta", {"invocation": {"mode": "suggest"}}),
        load_rubric("alpha", {"invocation": {"mode": "suggest"}}),
    )
    ctx = SkillInvocationContext(skills=rubrics)
    names = [a.skill_name for a in evaluate(ctx)]
    assert names == ["alpha", "zeta"]


# ────────────────────────────  AC13: representative fixtures  ────────────────────────────


def test_all_representative_fixtures_present_and_parse():
    for name in REPRESENTATIVE_SKILLS:
        skill_md = FIXTURES / name / "SKILL.md"
        assert skill_md.is_file(), f"missing fixture for {name}"
        inv, reason = parse_invocation(_read_frontmatter(skill_md))
        assert reason is None, f"{name}: {reason}"
        assert inv is not None


def _load_fixture_rubric(name: str, **kw: Any) -> SkillRubric:
    return load_rubric(name, _read_frontmatter(FIXTURES / name / "SKILL.md"), **kw)


def test_representative_fixtures_cover_every_recommendation_class():
    # security-review (auto_readonly) → auto_run when allowlisted + inputs present
    sec = _load_fixture_rubric("security-review")
    sec_action = _only(
        _ctx(
            sec,
            lifecycle_stage="review",
            provided_inputs=("changed_files",),
            is_command_allowlisted=_allow("dontpanic skills run security-review"),
        )
    )
    assert sec_action.recommendation is Recommendation.AUTO_RUN

    # github-pr → approval_required
    pr = _load_fixture_rubric("github-pr")
    assert (
        _only(_ctx(pr, lifecycle_stage="review", provided_inputs=("branch",))).recommendation
        is Recommendation.APPROVAL_REQUIRED
    )

    # changelog (repo_mutation, suggest) → suggest
    cl = _load_fixture_rubric("changelog")
    assert (
        _only(_ctx(cl, lifecycle_stage="review", provided_inputs=("version",))).recommendation
        is Recommendation.SUGGEST
    )

    # autoresearch missing its required input → blocked
    ar = _load_fixture_rubric("autoresearch")
    assert (
        _only(_ctx(ar, lifecycle_stage="planning")).recommendation
        is Recommendation.BLOCKED_MISSING_INPUTS
    )

    # toolkit opt-outs → not_applicable
    for toolkit in ("subagent-driven-dev", "printing-press-adapter"):
        tk = _load_fixture_rubric(toolkit)
        assert _only(_ctx(tk)).recommendation is Recommendation.NOT_APPLICABLE


def test_revenue_and_eval_fixtures_never_auto_run():
    for name, stage, inputs in [
        ("revenue-check", "review", ("project_id",)),
        ("eval-harness", "review", ("eval_dataset",)),
        ("browser-use", "implementation", ("target_url",)),
    ]:
        rubric = _load_fixture_rubric(name)
        action = _only(
            _ctx(
                rubric,
                lifecycle_stage=stage,
                provided_inputs=inputs,
                is_command_allowlisted=lambda _c: True,
            )
        )
        assert action.recommendation is not Recommendation.AUTO_RUN, name
        assert action.approval_required is True, name


# ────────────────────────────  purity contract  ────────────────────────────


def test_evaluator_source_is_pure():
    source = (
        HERE.parents[2] / "dontpanic_orchestrate" / "skill_invocation.py"
    ).read_text()

    # Strip docstring/comment prose so the design discussion (which uses the
    # words "subprocess"/"print"/"logging" legitimately) doesn't trip the grep.
    code_lines = []
    in_string = False
    string_delim = ""
    for raw in source.splitlines():
        stripped = raw.strip()
        if not in_string and (
            stripped.startswith('"""') or stripped.startswith("'''")
        ):
            delim = stripped[:3]
            if len(stripped) > 3 and stripped.endswith(delim):
                continue
            in_string = True
            string_delim = delim
            continue
        if in_string and stripped.endswith(string_delim):
            in_string = False
            string_delim = ""
            continue
        if in_string:
            continue
        code_lines.append(raw)
    code = "\n".join(code_lines)

    assert "import subprocess" not in code
    assert not re.search(r"\bsubprocess\.", code)
    assert not re.search(r"\blogging\.getLogger\b", code)
    assert not re.search(r"(^|\W)print\s*\(", code)
