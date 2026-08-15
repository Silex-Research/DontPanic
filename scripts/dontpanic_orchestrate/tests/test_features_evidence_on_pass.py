"""A feature claiming ``passes: true`` must carry its evidence — in BOTH arms.

`features.schema.json` has always said so:

    if   {"properties": {"passes": {"const": true}}, "required": ["passes"]}
    then {"required": ["verified_by", "verified_at", "evidence_refs"],
          "properties": {"evidence_refs": {"minItems": 1},
                         "verified_by":   {"minItems": 1}}}

But `validate.py` — the command everyone actually runs — validates
`features.json` through the Pydantic `Features` model, where those three fields
were plain `| None = None` with nothing tying them to `passes`. The two arms
disagreed, so an unbacked flip validated clean fleet-wide.

That is not hypothetical. Plan 2026-08-13-001 F001 was flipped to
``passes: true`` by an implementer with all three fields absent, and
``validate.py`` reported "✓ All plans validate" while `jsonschema` on the same
bytes reported three errors (recorded as D008 on that plan).

These tests pin the two arms together. The parity test is the load-bearing one:
it asserts the arms *agree*, so a future edit that relaxes either one fails
here rather than silently reopening the gap.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

_SCHEMAS = Path(__file__).resolve().parents[3] / "claude" / "shared" / "schemas" / "v1.0"
sys.path.insert(0, str(_SCHEMAS))
sys.path.insert(0, str(_SCHEMAS / "models"))

from features_model import Features  # noqa: E402  (path set above)

_JSON_SCHEMA = json.loads((_SCHEMAS / "features.schema.json").read_text())


def _doc(feature: dict) -> dict:
    return {
        "task_id": "2026-01-01-001-feat-fixture",
        "schema_version": "1.0",
        "features": [feature],
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


_EVIDENCE = {
    "verified_by": ["codex"],
    "verified_at": "2026-01-01T00:00:00Z",
    "evidence_refs": [{"type": "audit_json", "uri": "./audit/codex-auditor-F001-i0.json"}],
}


def _jsonschema_errors(doc: dict) -> list[str]:
    return [e.message for e in jsonschema.Draft202012Validator(_JSON_SCHEMA).iter_errors(doc)]


def _pydantic_error(doc: dict) -> str | None:
    try:
        Features.model_validate(doc)
    except Exception as exc:  # pydantic ValidationError, or our own ValueError
        return str(exc)
    return None


class TestPassesRequiresEvidence:
    """The gap D008 recorded: passes=true with nothing backing it."""

    def test_pydantic_rejects_passes_true_with_no_evidence(self):
        doc = _doc(_base(passes=True))
        err = _pydantic_error(doc)
        assert err is not None, (
            "passes=true with no verified_by/verified_at/evidence_refs was accepted "
            "by the Pydantic arm — this is the D008 gap"
        )
        for field in ("verified_by", "verified_at", "evidence_refs"):
            assert field in err, f"the refusal should name {field}; got: {err}"

    def test_pydantic_accepts_passes_true_with_full_evidence(self):
        assert _pydantic_error(_doc(_base(passes=True, **_EVIDENCE))) is None

    def test_passes_false_needs_no_evidence(self):
        """An open feature is not required to justify itself."""
        assert _pydantic_error(_doc(_base(passes=False))) is None

    @pytest.mark.parametrize("missing", ["verified_by", "verified_at", "evidence_refs"])
    def test_each_field_is_individually_required(self, missing):
        ev = {k: v for k, v in _EVIDENCE.items() if k != missing}
        err = _pydantic_error(_doc(_base(passes=True, **ev)))
        assert err is not None and missing in err

    @pytest.mark.parametrize("empty_field", ["verified_by", "evidence_refs"])
    def test_empty_list_does_not_count_as_evidence(self, empty_field):
        """The JSON Schema says minItems 1. An empty list is not a citation."""
        ev = dict(_EVIDENCE) | {empty_field: []}
        err = _pydantic_error(_doc(_base(passes=True, **ev)))
        assert err is not None, f"{empty_field}: [] was accepted as evidence"


class TestBothArmsAgree:
    """The parity guard — the test that keeps the two from drifting apart again."""

    CASES = [
        ("no evidence", _base(passes=True)),
        ("full evidence", _base(passes=True, **_EVIDENCE)),
        ("passes false", _base(passes=False)),
        ("missing verified_at", _base(passes=True, **{k: v for k, v in _EVIDENCE.items() if k != "verified_at"})),
        ("empty verified_by", _base(passes=True, **(dict(_EVIDENCE) | {"verified_by": []}))),
        ("empty evidence_refs", _base(passes=True, **(dict(_EVIDENCE) | {"evidence_refs": []}))),
    ]

    @pytest.mark.parametrize("label,feature", CASES, ids=[c[0] for c in CASES])
    def test_jsonschema_and_pydantic_reach_the_same_verdict(self, label, feature):
        doc = _doc(feature)
        js_rejects = bool(_jsonschema_errors(doc))
        py_rejects = _pydantic_error(doc) is not None
        assert js_rejects == py_rejects, (
            f"{label}: jsonschema rejects={js_rejects} but pydantic rejects={py_rejects} — "
            "the two validator arms disagree, which is exactly how an unbacked "
            "passes:true validated clean fleet-wide (D008)"
        )

    def test_the_parity_check_is_not_vacuous(self):
        """At least one case must actually be rejected, or the test proves nothing."""
        rejected = [
            label for label, feature in self.CASES if _jsonschema_errors(_doc(feature))
        ]
        assert rejected, "no case is rejected by jsonschema — the parity test is vacuous"
