"""F003 — EC5 severity classifier + finding-aggregation downgrade.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_ec5_classifier.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import audit_writer  # noqa: E402
from jarvis_orchestrate.ec5_classifier import (  # noqa: E402
    EC5_CODE,
    EC5_VERDICT_SEVERITY,
    apply_ec5_classifier_to_findings,
    classify_ec5_severity,
    is_ec5_finding,
)
from jarvis_orchestrate.prompts import auditor_prompt  # noqa: E402

REPO_ROOT = HERE.parents[3]
PLAN_DIR = REPO_ROOT / "docs" / "plans" / "2026-05-01-005-feat-target-context-platform-fix"
FIXTURES_DIR = PLAN_DIR / "evidence" / "f001" / "fixtures"

PRELUDE_HEADER = "## Target context\n"


def _load_fixture(name: str, *, agent: str = "claude") -> dict[str, Any]:
    """Same sanitization transform as test_audit_writer_normalize._load_fixture
    (drops `_fixture_notes`, swaps fixture-agent for a real Agent enum value,
    rebuilds audit_id). Documented under D012."""
    raw = json.loads((FIXTURES_DIR / name).read_text())
    raw.pop("_fixture_notes", None)
    raw["agent"] = agent
    parts = raw["audit_id"].split("#")
    if len(parts) == 3:
        parts[1] = agent
        raw["audit_id"] = "#".join(parts)
    return raw


def _post_inject(audit: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    """Run audit through audit_writer.write; return the persisted envelope dict.
    Models the post-F002 state where the canonical prelude has been auto-injected
    into the summary."""
    out = audit_writer.write(audit, tmp_path, feature_id="F001")
    return json.loads(out.read_text())


# ──────────────────────────────  classifier verdicts (acceptance #2 + #3)  ──────────────────────────────


def test_case_a_pre_injection_returns_i0() -> None:
    """Case-a raw fixture: struct valid + summary lacks prelude → 'i0'."""
    audit = _load_fixture("case-a-implementer-missing-prelude.json", agent="claude")
    assert classify_ec5_severity(audit) == "i0"


def test_case_a_post_injection_returns_none(tmp_path: Path) -> None:
    """Case-a after F002 auto-injection: canonical prelude present + struct valid → 'none'."""
    audit = _load_fixture("case-a-implementer-missing-prelude.json", agent="claude")
    post = _post_inject(audit, tmp_path)
    assert post["summary"].startswith(PRELUDE_HEADER)
    assert classify_ec5_severity(post) == "none"


def test_case_b_post_injection_returns_none(tmp_path: Path) -> None:
    """Case-b auditor self-finding after F002 auto-injection: canonical prelude
    present + struct valid → 'none'."""
    audit = _load_fixture("case-b-auditor-self-finding.json", agent="codex")
    post = _post_inject(audit, tmp_path)
    assert post["summary"].startswith(PRELUDE_HEADER)
    assert classify_ec5_severity(post) == "none"


def test_case_c_golden_returns_none() -> None:
    """Case-c already-canonical golden: prelude present + values match struct → 'none'."""
    audit = _load_fixture("case-c-golden-valid-struct-valid-prelude.json", agent="claude")
    assert classify_ec5_severity(audit) == "none"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "case-d-struct-absent.json",
        "case-e-struct-invalid-empty-env.json",
        "case-f-commands-without-target.json",
    ],
)
def test_invalid_struct_returns_i1(fixture_name: str) -> None:
    """case-d/e/f: struct invalid (missing tc, empty env, commands without target)
    → classifier returns 'i1' regardless of summary contents (acceptance #3)."""
    audit = _load_fixture(fixture_name, agent="claude")
    assert classify_ec5_severity(audit) == "i1"


def test_case_g_prelude_value_mismatch_returns_i1() -> None:
    """Case-g (narrow downgrade negative control): struct valid (env=dev) BUT
    prelude says env=prod → 'i1'. Verifies the downgrade rule does NOT fire on
    value-mismatch (D005 + D010 narrow rule, acceptance #2 + #3)."""
    audit = _load_fixture("case-g-prelude-value-mismatch.json", agent="claude")
    assert classify_ec5_severity(audit) == "i1"


def test_malformed_prelude_with_valid_struct_returns_i0() -> None:
    """Synthetic case: struct valid, but summary's prelude has the canonical
    header and then garbage (e.g., wrong field order, missing field). Per
    acceptance #3 this is still 'i0' — F002 cannot detect it (raises now per
    confirmation-volley remediation), but the classifier sees a parse failure
    and treats it as format-only (a re-persist would fix it)."""
    audit = _load_fixture("case-a-implementer-missing-prelude.json", agent="claude")
    audit["summary"] = "## Target context\nGARBAGE LINE\n\nrest of body\n"
    assert classify_ec5_severity(audit) == "i0"


# ──────────────────────────────  is_ec5_finding heuristics  ──────────────────────────────


def test_is_ec5_finding_detects_explicit_code() -> None:
    finding = {"severity": "high", "category": "correctness", "code": EC5_CODE, "issue": "x"}
    assert is_ec5_finding(finding) is True


def test_is_ec5_finding_detects_legacy_text_heuristic() -> None:
    """Backwards-compat (acceptance #10): legacy auditor outputs without `code`
    but with issue text matching the target.context.prelude heuristic."""
    finding = {
        "severity": "high",
        "category": "correctness",
        "issue": "implementer summary lacks the canonical target-context prelude block",
    }
    assert is_ec5_finding(finding) is True


def test_is_ec5_finding_skips_unrelated_finding() -> None:
    finding = {
        "severity": "high",
        "category": "security",
        "code": "S101",
        "issue": "hardcoded API key",
    }
    assert is_ec5_finding(finding) is False


# ──────────────────────────────  apply_ec5_classifier_to_findings (D005, D008)  ──────────────────────────────


def test_aggregation_drops_ec5_finding_when_verdict_is_none() -> None:
    """Acceptance #4: when classifier returns 'none', the EC5 finding is dropped."""
    audit = _load_fixture("case-c-golden-valid-struct-valid-prelude.json", agent="claude")
    findings = [
        {
            "severity": "high",
            "category": "correctness",
            "code": EC5_CODE,
            "issue": "missing prelude",
        },
    ]
    out = apply_ec5_classifier_to_findings(findings, audit)
    assert out == []


def test_aggregation_downgrades_to_advisory_on_i0_preserves_description() -> None:
    """Acceptance #4 + #5 (D008): on 'i0' verdict, severity is downgraded to
    'advisory' (mapped from the abstract 'i0' verdict) AND description /
    issue text is preserved verbatim."""
    audit = _load_fixture("case-a-implementer-missing-prelude.json", agent="claude")
    description = (
        "implementer summary lacks the canonical target-context prelude — auditor flagged at high"
    )
    findings = [
        {
            "severity": "high",
            "category": "correctness",
            "code": EC5_CODE,
            "issue": description,
            "evidence": "Inspected summary header.",
            "recommendation": "Inject prelude.",
        }
    ]
    out = apply_ec5_classifier_to_findings(findings, audit)
    assert len(out) == 1
    assert out[0]["severity"] == EC5_VERDICT_SEVERITY["i0"]
    assert out[0]["severity"] == "advisory"
    # Description preserved verbatim
    assert out[0]["issue"] == description
    assert out[0]["evidence"] == "Inspected summary header."
    assert out[0]["recommendation"] == "Inject prelude."
    # Code preserved
    assert out[0]["code"] == EC5_CODE


def test_aggregation_leaves_i1_finding_unchanged() -> None:
    """Acceptance #4: on 'i1' verdict, the finding passes through untouched."""
    audit = _load_fixture("case-d-struct-absent.json", agent="claude")
    findings = [
        {
            "severity": "high",
            "category": "correctness",
            "code": EC5_CODE,
            "issue": "target_context absent from envelope",
        }
    ]
    out = apply_ec5_classifier_to_findings(findings, audit)
    assert out == findings  # identical list and contents


def test_aggregation_preserves_non_ec5_findings(tmp_path: Path) -> None:
    """Acceptance #7: non-EC5 findings pass through unchanged regardless of
    classifier verdict on the envelope."""
    audit = _load_fixture("case-c-golden-valid-struct-valid-prelude.json", agent="claude")
    s101 = {
        "severity": "high",
        "category": "security",
        "code": "S101",
        "issue": "hardcoded API key in source",
    }
    ec5 = {
        "severity": "high",
        "category": "correctness",
        "code": EC5_CODE,
        "issue": "missing prelude",
    }
    out = apply_ec5_classifier_to_findings([s101, ec5], audit)
    # EC5 is dropped (verdict='none' on case-c); S101 survives unchanged.
    assert len(out) == 1
    assert out[0] == s101
    assert out[0] is s101  # identity preserved (same dict reference; not mutated)


def test_aggregation_handles_legacy_finding_via_text_heuristic() -> None:
    """Acceptance #10: legacy finding without `code` field but with EC5-shaped
    issue text is downgraded by the aggregation step."""
    audit = _load_fixture("case-c-golden-valid-struct-valid-prelude.json", agent="claude")
    legacy = {
        "severity": "high",
        "category": "correctness",
        "issue": "envelope summary lacks the canonical target-context prelude block",
    }
    out = apply_ec5_classifier_to_findings([legacy], audit)
    # case-c → verdict 'none' → dropped even without explicit `code` field
    assert out == []


def test_aggregation_does_not_mutate_input_list() -> None:
    """The aggregation helper returns a NEW list; the input list and its dicts
    are not mutated. This matters when the caller wants to inspect the
    pre-classification findings post-aggregation."""
    audit = _load_fixture("case-a-implementer-missing-prelude.json", agent="claude")
    findings = [
        {"severity": "high", "category": "correctness", "code": EC5_CODE, "issue": "x"},
    ]
    snapshot = json.dumps(findings, sort_keys=True)
    apply_ec5_classifier_to_findings(findings, audit)
    assert json.dumps(findings, sort_keys=True) == snapshot


# ──────────────────────────────  classifier purity (acceptance #1)  ──────────────────────────────


def test_classifier_is_pure_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """classify_ec5_severity must not perform disk I/O. Smoke check by patching
    Path.read_text/write_text/open to fail loudly; the call must complete."""
    audit = _load_fixture("case-c-golden-valid-struct-valid-prelude.json", agent="claude")

    def _explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("classifier touched disk I/O")

    # Sentinel-patch the most likely I/O paths the classifier might leak to.
    # resolve_repo can shell out to git rev-parse but only when struct lacks
    # repo; case-c has explicit project/env so resolve is from struct.
    monkeypatch.setattr(Path, "read_text", _explode)
    monkeypatch.setattr(Path, "write_text", _explode)
    monkeypatch.setattr(Path, "stat", _explode)

    assert classify_ec5_severity(audit) == "none"


# ──────────────────────────────  prompt template (acceptance #6)  ──────────────────────────────


def test_auditor_prompt_contains_ec5_rule_paragraph() -> None:
    """Acceptance #6: auditor prompt template documents the EC5 narrow-rule
    paragraph including the value-mismatch carve-out."""
    rendered = auditor_prompt(
        plan_id="2026-05-02-test",
        plan_dir=Path("/tmp/test-plan"),
        feature={"id": "F001", "acceptance": "x", "steps": ["s"]},
        iteration=0,
        implementer_audit_path=Path("/tmp/impl.json"),
        target_env="dev",
        target_project=None,
    )
    # Representative phrase from the EC5 paragraph (per features.json acceptance #6)
    assert "EC5" in rendered
    # Value-mismatch carve-out is the key piece — auditor must NOT downgrade
    # value-mismatches just because the struct is valid.
    assert "value" in rendered.lower() and "mismatch" in rendered.lower(), (
        "EC5 paragraph must mention value-mismatch carve-out"
    )
    # The "i0 vs i1" framing should be present in some form
    assert "format-only" in rendered.lower() or "format" in rendered.lower()
