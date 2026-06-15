"""Goal Governance V1 F003 — sufficiency auditor tests.

Covers the 9 cases enumerated in F003 step 8:

  (a) ``_load_objective_contract`` happy path
  (b) ``_load_objective_contract`` failures: missing goal_type,
      missing links, missing file, malformed contract
  (c) ``_resolve_goal_auditor_agent`` returns expected agent for a
      known agent_manifest / project config
  (d) same-vendor without override raises ``SufficiencyAuditError``
      (which subclasses ValueError, so plain catches still work)
  (e) ``_build_sufficiency_prompt`` includes all required sections
  (f) ``_parse_sufficiency_response`` happy path with mocked output
  (g) ``_parse_sufficiency_response`` rejects malformed JSON
  (h) ``_parse_sufficiency_response`` rejects findings whose severity
      is not in F0's audit envelope severity enum (reuses the F0
      pattern from :class:`GoalGapFinding`)
  (i) ``run_sufficiency_audit`` end-to-end with mocked dispatch + a
      synthetic plan dir, asserts findings file lands at
      ``evidence/goal-governance/pre_impl/sufficiency-findings.json``

Run:

    PYTHONPATH=scripts python3 -m pytest \
        scripts/dontpanic_orchestrate/tests/test_sufficiency_auditor.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import project_config  # noqa: E402
from dontpanic_orchestrate.sufficiency_auditor import (  # noqa: E402
    PRE_IMPL_FINDINGS_ARTIFACT,
    SUFFICIENCY_FINDING_CLASSES,
    SUFFICIENCY_GAP_CLASSES,
    SUFFICIENCY_RAW_RESPONSE_ARTIFACT,
    SufficiencyAuditError,
    SufficiencyParseOutcome,
    _build_sufficiency_prompt,
    _load_objective_contract,
    _parse_sufficiency_response,
    _resolve_goal_auditor_agent,
    parse_sufficiency_findings,
    run_sufficiency_audit,
)

# ──────────────────────────────  fixture helpers  ──────────────────────────────


_VALID_CONTRACT = {
    "goal_type": "parity",
    "source_of_truth": "Some prior plan / curated reference",
    "user_journeys": [
        {
            "name": "onboarding",
            "description": (
                "User opens the app, completes the welcome flow, and lands on "
                "the home screen with their workspace loaded."
            ),
            "surfaces": ["ios", "android"],
            "states": ["empty", "loading", "success"],
            "acceptance_signals": [
                "welcome screen renders within 2 seconds",
                "home screen receives correct workspace",
            ],
        },
        {
            "name": "publish-flow",
            "description": (
                "Creator drafts a post, attaches a tracked link, and publishes "
                "to the configured channel with disclosure rendered."
            ),
        },
    ],
    "non_goals": ["legacy migration tooling"],
    "completion_test": (
        "Both onboarding and publish-flow run end-to-end on iOS and Android "
        "without operator intervention."
    ),
}


def _write_plan(
    plan_dir: Path,
    *,
    goal_type: str | None = "parity",
    contract: dict | str | None = "valid",
    contract_filename: str = "objective_contract.json",
    links_value: dict | None | str = "default",
) -> Path:
    """Write a minimal plan dir with an optional objective contract.

    ``contract``: ``"valid"`` writes :data:`_VALID_CONTRACT`; ``None``
    skips writing the file (lets us test missing-file). A ``dict``
    writes that exact JSON. A ``str`` other than ``"valid"`` writes the
    raw string (used for malformed-JSON cases).
    ``links_value``: ``"default"`` produces ``{"objective_contract": contract_filename}``;
    a dict overrides; ``None`` produces an empty links block.
    """
    plan_dir.mkdir(parents=True)

    fm: dict = {
        "id": "2026-05-05-999-feat-fixture",
        "title": "fixture plan",
        "type": "feat",
        "tier": "local",
        "status": "draft",
        "date": "2026-05-05",
        "description": "synthetic fixture plan for sufficiency_auditor tests",
    }
    if goal_type is not None:
        fm["goal_type"] = goal_type
    if links_value == "default":
        fm["links"] = {"objective_contract": f"./{contract_filename}"}
    elif isinstance(links_value, dict):
        fm["links"] = links_value
    elif links_value is None:
        # explicitly emit empty links to test "links present but field absent"
        fm["links"] = {}

    import yaml as _yaml

    plan_md = "---\n" + _yaml.safe_dump(fm, sort_keys=False) + "---\n\n# fixture\n"
    (plan_dir / "plan.md").write_text(plan_md)

    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "features": [
                    {
                        "id": "F001",
                        "category": "tooling",
                        "phase": 1,
                        "description": "fixture feature one for sufficiency audit testing",
                        "steps": ["step a", "step b"],
                        "acceptance": "Feature passes when both steps complete.",
                        "passes": False,
                        "depends_on": [],
                        "evidence_refs": [],
                    }
                ]
            }
        )
    )

    if contract == "valid":
        (plan_dir / contract_filename).write_text(json.dumps(_VALID_CONTRACT))
    elif isinstance(contract, dict):
        (plan_dir / contract_filename).write_text(json.dumps(contract))
    elif isinstance(contract, str) and contract != "valid":
        (plan_dir / contract_filename).write_text(contract)
    elif contract is None:
        pass  # no file at all
    return plan_dir


@pytest.fixture
def synthetic_plan(tmp_path: Path) -> Path:
    return _write_plan(tmp_path / "plan-fixture")


# ──────────────────────────────  (a) load contract — happy path  ──────────────────────────────


def test_load_objective_contract_happy_path(synthetic_plan: Path) -> None:
    contract = _load_objective_contract(synthetic_plan)
    assert contract.goal_type.value == "parity"
    assert len(contract.user_journeys) == 2
    assert contract.user_journeys[0].name == "onboarding"
    assert contract.completion_test.startswith("Both onboarding")


# ──────────────────────────────  (b) load contract — failure modes  ──────────────────────────────


def test_load_objective_contract_missing_goal_type(tmp_path: Path) -> None:
    plan_dir = _write_plan(tmp_path / "no-goal-type", goal_type=None)
    with pytest.raises(SufficiencyAuditError, match="does not declare goal_type"):
        _load_objective_contract(plan_dir)


def test_load_objective_contract_missing_links_field(tmp_path: Path) -> None:
    plan_dir = _write_plan(tmp_path / "no-links", links_value=None)
    with pytest.raises(SufficiencyAuditError, match="links.objective_contract is missing"):
        _load_objective_contract(plan_dir)


def test_load_objective_contract_missing_file(tmp_path: Path) -> None:
    plan_dir = _write_plan(tmp_path / "no-file", contract=None)
    with pytest.raises(SufficiencyAuditError, match="does not exist"):
        _load_objective_contract(plan_dir)


def test_load_objective_contract_malformed_json(tmp_path: Path) -> None:
    plan_dir = _write_plan(tmp_path / "bad-json", contract="{ not real json")
    with pytest.raises(SufficiencyAuditError, match="failed to read"):
        _load_objective_contract(plan_dir)


def test_load_objective_contract_schema_violation(tmp_path: Path) -> None:
    bad_contract = {
        "goal_type": "parity",
        # missing source_of_truth + completion_test, and zero user_journeys
        "user_journeys": [],
        "completion_test": "short",  # below minLength
    }
    plan_dir = _write_plan(tmp_path / "schema-bad", contract=bad_contract)
    with pytest.raises(SufficiencyAuditError, match="failed schema validation"):
        _load_objective_contract(plan_dir)


# ──────────────────────────────  (c) goal-auditor resolution — known config  ──────────────────────────────


def test_resolve_goal_auditor_returns_default_codex_when_implementer_is_claude(
    synthetic_plan: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No project context → falls through to project_config's hardcoded
    fallback (FALLBACK_IMPLEMENTER='claude' / FALLBACK_AUDITOR='codex').
    Verifies the cross-vendor default holds without any override."""
    monkeypatch.setattr(project_config, "find_project_for_plan_dir", lambda _: None)
    auditor = _resolve_goal_auditor_agent(synthetic_plan)
    assert auditor == "codex"


def test_resolve_goal_auditor_respects_explicit_implementer_arg(
    synthetic_plan: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Override implementer at call time without mutating config."""
    monkeypatch.setattr(project_config, "find_project_for_plan_dir", lambda _: None)
    # explicit implementer='claude' with default auditor='codex' → cross-vendor OK
    assert _resolve_goal_auditor_agent(synthetic_plan, implementer_agent="claude") == "codex"


# ──────────────────────────────  (d) same-vendor without override is refused  ──────────────────────────────


def test_resolve_goal_auditor_same_vendor_without_override_raises(
    synthetic_plan: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_config, "find_project_for_plan_dir", lambda _: None)
    monkeypatch.delenv("DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR", raising=False)
    with pytest.raises(SufficiencyAuditError, match="cross-vendor invariant"):
        # implementer = auditor = codex → same vendor → refuse
        _resolve_goal_auditor_agent(synthetic_plan, implementer_agent="codex")


def test_resolve_goal_auditor_same_vendor_with_override_allowed(
    synthetic_plan: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_config, "find_project_for_plan_dir", lambda _: None)
    monkeypatch.setenv("DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR", "1")
    # operator override channel — auditor returned even when same-vendor
    assert _resolve_goal_auditor_agent(synthetic_plan, implementer_agent="codex") == "codex"


# ──────────────────────────────  (e) prompt structure  ──────────────────────────────


def test_build_sufficiency_prompt_includes_all_required_sections(synthetic_plan: Path) -> None:
    contract = _load_objective_contract(synthetic_plan)
    features = [
        {
            "id": "F001",
            "description": "fixture feature one",
            "acceptance": "trivial acceptance",
            "steps": ["s1", "s2"],
        }
    ]
    prompt = _build_sufficiency_prompt(contract, features)
    # Required sections by spec
    assert "## Objective contract" in prompt
    assert "## User journeys" in prompt
    assert "## Proposed features" in prompt
    assert "## Gap classes to surface" in prompt
    assert "## Output contract" in prompt
    # Each gap class listed verbatim so the auditor cannot drift the taxonomy
    for gc in SUFFICIENCY_GAP_CLASSES:
        assert f"`{gc}`" in prompt
    # Journeys named in prompt
    assert "onboarding" in prompt
    assert "publish-flow" in prompt
    # Feature visible in prompt
    assert "F001" in prompt


# ──────────────────────────────  (f) parse response — happy path  ──────────────────────────────


def test_parse_sufficiency_response_happy_path() -> None:
    payload = json.dumps(
        [
            {
                "severity": "high",
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "Onboarding journey is not covered by any current feature acceptance.",
                "feature_refs": [],
                "recommendation": "Add an onboarding-specific feature.",
            },
            {
                "severity": "medium",
                "journey_id": "publish-flow",
                "gap_class": "wiring_gap",
                "description": "Publish flow has a feature but the acceptance criterion does not bind to the disclosure surface.",
                "feature_refs": ["F001"],
            },
        ]
    )
    findings = _parse_sufficiency_response(payload)
    assert len(findings) == 2
    assert findings[0].severity == "high"
    assert findings[0].journey_id == "onboarding"
    assert findings[1].gap_class == "wiring_gap"
    assert findings[1].feature_refs == ["F001"]


def test_parse_sufficiency_response_tolerates_code_fence() -> None:
    fenced = "```json\n[]\n```"
    assert _parse_sufficiency_response(fenced) == []


def test_parse_sufficiency_response_empty_array() -> None:
    assert _parse_sufficiency_response("[]") == []


# ──────────────────────────────  (g) parse response — malformed JSON  ──────────────────────────────


def test_parse_sufficiency_response_rejects_malformed_json() -> None:
    with pytest.raises(SufficiencyAuditError, match="not valid JSON"):
        _parse_sufficiency_response("{ not json")


def test_parse_sufficiency_response_rejects_non_array_top_level() -> None:
    with pytest.raises(SufficiencyAuditError, match="must be a JSON array"):
        _parse_sufficiency_response('{"findings": []}')


# ──────────────────────────────  (h) parse response — severity guard reuses F0  ──────────────────────────────


def test_parse_sufficiency_response_rejects_unknown_severity() -> None:
    bad = json.dumps(
        [
            {
                "severity": "catastrophic",  # not in _GOAL_GAP_SEVERITY_RANK
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "Severity is not a member of F0's GoalGapFinding severity enum.",
                "feature_refs": [],
            }
        ]
    )
    with pytest.raises(SufficiencyAuditError, match="failed validation"):
        _parse_sufficiency_response(bad)


def test_parse_sufficiency_response_rejects_unknown_gap_class() -> None:
    bad = json.dumps(
        [
            {
                "severity": "medium",
                "journey_id": "onboarding",
                "gap_class": "wat_gap",  # not in SUFFICIENCY_GAP_CLASSES
                "description": "Gap class is outside the F003 taxonomy locked in the prompt.",
                "feature_refs": [],
            }
        ]
    )
    with pytest.raises(SufficiencyAuditError, match="failed validation"):
        _parse_sufficiency_response(bad)


def test_parse_sufficiency_response_rejects_short_description() -> None:
    bad = json.dumps(
        [
            {
                "severity": "medium",
                "journey_id": "onboarding",
                "gap_class": "coverage_gap",
                "description": "too short",  # below 40 chars
                "feature_refs": [],
            }
        ]
    )
    with pytest.raises(SufficiencyAuditError, match="failed validation"):
        _parse_sufficiency_response(bad)


# ──────────────────────────────  (i) end-to-end with mocked dispatch  ──────────────────────────────


def test_run_sufficiency_audit_writes_findings_file_to_pre_impl_path(
    synthetic_plan: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_config, "find_project_for_plan_dir", lambda _: None)

    captured: dict = {}

    def _fake_dispatch(agent: str, prompt: str) -> str:
        captured["agent"] = agent
        captured["prompt"] = prompt
        return json.dumps(
            [
                {
                    "severity": "medium",
                    "journey_id": "publish-flow",
                    "gap_class": "missing_feature",
                    "description": "No feature in features.json points at the publish-flow journey end-to-end.",
                    "feature_refs": [],
                }
            ]
        )

    findings = run_sufficiency_audit(synthetic_plan, dispatch=_fake_dispatch)
    assert len(findings) == 1
    assert findings[0].journey_id == "publish-flow"
    assert findings[0].gap_class == "missing_feature"

    # cross-vendor default: implementer=claude (fallback), auditor=codex
    assert captured["agent"] == "codex"

    # findings file landed at the F0-convention path
    out_path = (
        synthetic_plan / "evidence" / "goal-governance" / "pre_impl" / PRE_IMPL_FINDINGS_ARTIFACT
    )
    assert out_path.is_file()
    payload = json.loads(out_path.read_text())
    assert payload["auditor"] == "codex"
    assert isinstance(payload["findings"], list)
    assert payload["findings"][0]["journey_id"] == "publish-flow"


def test_run_sufficiency_audit_without_dispatch_raises(
    synthetic_plan: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F003 leaves production wiring to F004; calling run_sufficiency_audit
    with no dispatcher must refuse rather than silently no-op."""
    monkeypatch.setattr(project_config, "find_project_for_plan_dir", lambda _: None)
    with pytest.raises(SufficiencyAuditError, match="no dispatch function"):
        run_sufficiency_audit(synthetic_plan)


def test_run_sufficiency_audit_propagates_contract_load_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end safety: contract failures bubble up before any dispatch
    or evidence write."""
    plan_dir = _write_plan(tmp_path / "no-contract", contract=None)
    monkeypatch.setattr(project_config, "find_project_for_plan_dir", lambda _: None)

    def _should_not_be_called(_agent: str, _prompt: str) -> str:  # pragma: no cover
        raise AssertionError("dispatch must not run when contract loading fails")

    with pytest.raises(SufficiencyAuditError, match="does not exist"):
        run_sufficiency_audit(plan_dir, dispatch=_should_not_be_called)
    # No evidence file should have been created
    assert not (plan_dir / "evidence" / "goal-governance" / "pre_impl").exists()


# ──────────────────────────────  (j) resilient parse — degradation + raw persist  ──────────────────────────────
# Plan 2026-06-14-001 dogfood defect: a single finding whose `gap_class` carried a
# `finding_class` value (scope_guard) made Pydantic reject the WHOLE paid response,
# and the raw output was never persisted (validate-before-write), so an expensive
# cross-vendor audit was lost. The resilient path persists raw first, validates each
# finding independently, remaps a misplaced finding_class value, and quarantines the
# rest with raw retained — never silently passing a malformed response as clean.


def _ok_finding(journey: str = "onboarding", gap: str = "coverage_gap", severity: str = "medium") -> dict:
    return {
        "severity": severity,
        "journey_id": journey,
        "gap_class": gap,
        "description": "A sufficiently long finding description of at least forty characters.",
        "feature_refs": [],
    }


def test_finding_classes_constant_includes_scope_guard() -> None:
    assert "scope_guard" in SUFFICIENCY_FINDING_CLASSES
    # gap_class and finding_class taxonomies are disjoint vocabularies
    assert set(SUFFICIENCY_FINDING_CLASSES).isdisjoint(set(SUFFICIENCY_GAP_CLASSES))


def test_parse_findings_remaps_finding_class_value_in_gap_class() -> None:
    payload = json.dumps(
        [
            _ok_finding("onboarding", "coverage_gap"),
            {
                **_ok_finding("publish-flow"),
                "gap_class": "scope_guard",  # a finding_class value mislabeled into gap_class
                "description": "A non-goal guard the auditor put in gap_class instead of finding_class.",
            },
            _ok_finding("onboarding", "wiring_gap"),
        ]
    )
    outcome = parse_sufficiency_findings(payload)
    assert isinstance(outcome, SufficiencyParseOutcome)
    assert len(outcome.findings) == 3  # all three preserved, the middle one recovered
    assert outcome.malformed == []
    recovered = outcome.findings[1]
    assert recovered.gap_class == "coverage_gap"  # conservative default
    assert recovered.finding_class == "scope_guard"  # moved into the right field
    assert any("scope_guard" in n and "remap" in n.lower() for n in outcome.notes)


def test_parse_findings_quarantines_unrecoverable_but_keeps_valid() -> None:
    payload = json.dumps(
        [
            _ok_finding("onboarding", "coverage_gap"),
            {**_ok_finding("publish-flow"), "severity": "catastrophic"},  # not remappable
        ]
    )
    outcome = parse_sufficiency_findings(payload)
    assert len(outcome.findings) == 1
    assert outcome.findings[0].journey_id == "onboarding"
    assert len(outcome.malformed) == 1
    assert outcome.malformed[0]["raw"]["severity"] == "catastrophic"  # raw retained
    assert any("quarantin" in n.lower() for n in outcome.notes)


def test_parse_findings_raises_when_all_malformed_no_valid() -> None:
    # zero valid + at least one malformed → never silently "clean": raise.
    payload = json.dumps([{**_ok_finding(), "severity": "catastrophic"}])
    with pytest.raises(SufficiencyAuditError):
        parse_sufficiency_findings(payload)


def test_parse_findings_empty_array_is_clean() -> None:
    outcome = parse_sufficiency_findings("[]")
    assert outcome.findings == []
    assert outcome.malformed == []


def test_parse_findings_non_array_and_non_json_raise() -> None:
    with pytest.raises(SufficiencyAuditError, match="must be a JSON array"):
        parse_sufficiency_findings('{"findings": []}')
    with pytest.raises(SufficiencyAuditError, match="not valid JSON"):
        parse_sufficiency_findings("{ not json")


def test_run_sufficiency_audit_persists_raw_and_recovers_scope_guard(
    synthetic_plan: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_config, "find_project_for_plan_dir", lambda _: None)
    raw = json.dumps(
        [
            _ok_finding("onboarding", "coverage_gap"),
            {
                **_ok_finding("publish-flow"),
                "gap_class": "scope_guard",
                "description": "A non-goal guard mislabeled as gap_class instead of finding_class.",
            },
        ]
    )
    findings = run_sufficiency_audit(synthetic_plan, dispatch=lambda _a, _p: raw)
    assert len(findings) == 2  # recovered, not discarded

    pre_impl = synthetic_plan / "evidence" / "goal-governance" / "pre_impl"
    raw_path = pre_impl / SUFFICIENCY_RAW_RESPONSE_ARTIFACT
    assert raw_path.is_file()
    assert "scope_guard" in raw_path.read_text()  # raw persisted

    out = json.loads((pre_impl / PRE_IMPL_FINDINGS_ARTIFACT).read_text())
    assert len(out["findings"]) == 2
    assert out.get("malformed_findings") == []
    assert any("scope_guard" in n for n in out.get("parser_notes", []))


def test_run_sufficiency_audit_persists_raw_even_when_unparseable(
    synthetic_plan: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_config, "find_project_for_plan_dir", lambda _: None)
    with pytest.raises(SufficiencyAuditError):
        run_sufficiency_audit(synthetic_plan, dispatch=lambda _a, _p: "this is not json at all")

    pre_impl = synthetic_plan / "evidence" / "goal-governance" / "pre_impl"
    raw_path = pre_impl / SUFFICIENCY_RAW_RESPONSE_ARTIFACT
    assert raw_path.is_file()  # raw persisted BEFORE the parse failed
    assert "not json at all" in raw_path.read_text()
    # the findings artifact must NOT be written for an unusable response
    assert not (pre_impl / PRE_IMPL_FINDINGS_ARTIFACT).is_file()


def test_run_sufficiency_audit_scrubs_home_path_from_persisted_raw(
    synthetic_plan: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The codex CLI streams tool-telemetry that can embed the operator's absolute
    # home path. The raw-response writer must sanitize BEFORE persisting (the
    # standing evidence-scrubbing constraint) — home -> <home>.
    monkeypatch.setattr(project_config, "find_project_for_plan_dir", lambda _: None)
    home = str(Path.home())
    raw = (
        json.dumps([_ok_finding("onboarding", "coverage_gap")])
        + f"\n# codex pwd telemetry: {home}/Documents/GitHub/DontPanic\n"
    )
    run_sufficiency_audit(synthetic_plan, dispatch=lambda _a, _p: raw)
    raw_path = (
        synthetic_plan / "evidence" / "goal-governance" / "pre_impl"
        / SUFFICIENCY_RAW_RESPONSE_ARTIFACT
    )
    txt = raw_path.read_text()
    assert home not in txt, "absolute operator home path leaked into persisted raw response"
    assert "<home>" in txt, "home path was not replaced with the <home> placeholder"
