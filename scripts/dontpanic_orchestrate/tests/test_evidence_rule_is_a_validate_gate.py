"""Requiring evidence on `passes: true` must gate WRITES, not break READS.

The D008 fix put the rule inside the `Feature` model as a raising
``@model_validator``. That closed the gap — an unbacked flip stopped
validating clean — but the model is also the READ path: ``plan_loader.load()``
calls ``Features.model_validate``. So the rule made 39 existing plans
unloadable, and every fleet-walking surface either crashed or silently dropped
them. ``planning_readiness.analyze_repo`` swallows the exception and returns an
empty set, which is the worst shape: features vanish from "what can I dispatch"
with no signal at all.

History predates the rule. A reader that refuses to read history leaves the
tool unable to see its own past, and no amount of backfilling fixes the class
of problem — the next schema tightening does it again.

So the rule moves to where a claim is actually asserted:

  * ``evidence_gaps()`` is a pure function any caller can ask;
  * ``validate.py`` calls it, so ``dontpanic doctor``, CI, and plan-lock all
    still refuse an unbacked flip — the D008 gap stays closed;
  * the model stays permissive, so loading a legacy plan works.

The jsonschema arm is unchanged: it always carried the conditional. Parity is
therefore asserted between jsonschema and ``evidence_gaps`` rather than between
jsonschema and a raising model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

_REPO = Path(__file__).resolve().parents[3]
_SCHEMAS = _REPO / "claude" / "shared" / "schemas" / "v1.0"
sys.path.insert(0, str(_SCHEMAS))
sys.path.insert(0, str(_SCHEMAS / "models"))

from features_model import Features, evidence_gaps  # noqa: E402

_JSON_SCHEMA = json.loads((_SCHEMAS / "features.schema.json").read_text())

_EVIDENCE = {
    "verified_by": ["codex"],
    "verified_at": "2026-01-01T00:00:00Z",
    "evidence_refs": [{"type": "audit_json", "uri": "./audit/codex-auditor-F001-i0.json"}],
}


def _base(**over: object) -> dict:
    f = {
        "id": "F001",
        "category": "functional",
        "description": "A feature description long enough to satisfy min_length",
        "acceptance": "Some machine-checkable condition",
        "passes": False,
    }
    f.update(over)
    return f


def _doc(feature: dict) -> dict:
    return {"task_id": "2026-01-01-001-feat-fixture", "schema_version": "1.0", "features": [feature]}


class TestTheRuleStillCatchesUnbackedFlips:
    def test_no_evidence_at_all_is_reported(self):
        gaps = evidence_gaps(_base(passes=True))
        assert gaps, "an unbacked passes=true must still be caught — this is D008"
        for field in ("verified_by", "verified_at", "evidence_refs"):
            assert any(field in g for g in gaps), f"{field} not named in {gaps}"

    def test_full_evidence_is_clean(self):
        assert evidence_gaps(_base(passes=True, **_EVIDENCE)) == []

    def test_passes_false_is_never_asked_for_evidence(self):
        assert evidence_gaps(_base(passes=False)) == []

    @pytest.mark.parametrize("missing", ["verified_by", "verified_at", "evidence_refs"])
    def test_each_field_is_individually_required(self, missing):
        ev = {k: v for k, v in _EVIDENCE.items() if k != missing}
        gaps = evidence_gaps(_base(passes=True, **ev))
        assert gaps and any(missing in g for g in gaps)

    @pytest.mark.parametrize("empty_field", ["verified_by", "evidence_refs"])
    def test_an_empty_list_is_not_evidence(self, empty_field):
        gaps = evidence_gaps(_base(passes=True, **(dict(_EVIDENCE) | {empty_field: []})))
        assert gaps, f"{empty_field}: [] was accepted as evidence"

    def test_it_accepts_a_model_instance_too(self):
        """Callers holding a parsed Feature shouldn't have to round-trip to dict."""
        parsed = Features.model_validate(_doc(_base(passes=True)))
        assert evidence_gaps(parsed.features[0])


class TestTheModelStaysReadable:
    """The regression this fix exists to undo."""

    def test_loading_an_unbacked_flip_no_longer_raises(self):
        parsed = Features.model_validate(_doc(_base(passes=True)))
        assert parsed.features[0].passes is True

    def test_every_checked_in_plan_still_loads(self):
        """39 real plans stopped loading. That must not happen again."""
        from dontpanic_orchestrate import plan_loader

        plans = sorted(
            d for d in (_REPO / "docs" / "plans").iterdir()
            if d.is_dir() and (d / "features.json").exists() and (d / "plan.md").exists()
        )
        assert plans, "no plans found — the guard would be vacuous"
        unloadable = []
        for d in plans:
            try:
                plan_loader.load(d)
            except Exception as exc:  # noqa: BLE001 — any load failure is the bug
                if "claims passes=true but is missing" in str(exc):
                    unloadable.append(d.name)
        assert not unloadable, (
            f"{len(unloadable)} plan(s) cannot be READ because of the evidence "
            f"rule; enforcement belongs at validate time: {unloadable[:5]}"
        )


class TestBothArmsStillAgree:
    """Parity, restated against the function rather than a raising model."""

    CASES = [
        ("no evidence", _base(passes=True)),
        ("full evidence", _base(passes=True, **_EVIDENCE)),
        ("passes false", _base(passes=False)),
        ("missing verified_at", _base(passes=True, **{k: v for k, v in _EVIDENCE.items() if k != "verified_at"})),
        ("empty verified_by", _base(passes=True, **(dict(_EVIDENCE) | {"verified_by": []}))),
        ("empty evidence_refs", _base(passes=True, **(dict(_EVIDENCE) | {"evidence_refs": []}))),
    ]

    @pytest.mark.parametrize("label,feature", CASES, ids=[c[0] for c in CASES])
    def test_jsonschema_and_evidence_gaps_reach_the_same_verdict(self, label, feature):
        js_rejects = bool(
            list(jsonschema.Draft202012Validator(_JSON_SCHEMA).iter_errors(_doc(feature)))
        )
        fn_rejects = bool(evidence_gaps(feature))
        assert js_rejects == fn_rejects, (
            f"{label}: jsonschema rejects={js_rejects} but evidence_gaps={fn_rejects} — "
            "the arms disagree again, which is how D008 happened"
        )

    def test_the_parity_check_is_not_vacuous(self):
        rejected = [
            label for label, f in self.CASES
            if list(jsonschema.Draft202012Validator(_JSON_SCHEMA).iter_errors(_doc(f)))
        ]
        assert rejected, "no case is rejected — the parity test proves nothing"


class TestValidatePyStillRefuses:
    """The gap must stay closed where operators and CI actually look."""

    def test_validator_rejects_a_plan_with_an_unbacked_flip(self, tmp_path):
        import subprocess

        plan_id = "2026-01-01-001-feat-fixture"
        d = tmp_path / "docs" / "plans" / plan_id
        d.mkdir(parents=True)
        (d / "plan.md").write_text(
            f"---\nid: {plan_id}\ntitle: t\ntype: feat\ntier: local\n"
            f'status: active\ndate: "2026-01-01"\ndescription: a description long enough\n'
            "---\n\n# t\n"
        )
        (d / "features.json").write_text(json.dumps(_doc(_base(passes=True)), indent=2))
        proc = subprocess.run(
            [sys.executable, str(_SCHEMAS / "validate.py"), str(d)],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode != 0, (
            "validate.py accepted an unbacked passes=true — the D008 gap is open again:\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
        assert "verified" in (proc.stdout + proc.stderr), "the refusal must say what is missing"
