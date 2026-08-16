"""Evidence rule is a validate-time gate, not a load-time raise.

``features.schema.json`` has always required verified_by + verified_at +
non-empty evidence_refs when ``passes`` is true. The Pydantic arm once
mirrored that as a raising ``@model_validator``. That closed D008 on
writes and simultaneously broke reads: ``Features.model_validate`` is
what plan loaders call, so 39+ existing plans became unloadable.

Enforcement belongs in ``evidence_gaps()`` / ``validate.py``. The model
must stay permissive so history remains readable. JSON Schema still
rejects an unbacked flip; the two arms are allowed to disagree on
*whether to raise*, and must agree on *whether the flip is backed*.

Usage:

    python3 scripts/test_evidence_read_path.py

Exit 0 if every case passes; 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1.0"
FEATURES_SCHEMA = SCHEMAS_DIR / "features.schema.json"

sys.path.insert(0, str(SCHEMAS_DIR))

import jsonschema  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from models.features_model import Features, evidence_gaps  # noqa: E402

_EVIDENCE = {
    "verified_by": ["codex"],
    "verified_at": "2026-01-01T00:00:00Z",
    "evidence_refs": [{"type": "audit_json", "uri": "./audit/codex-auditor-F001-i0.json"}],
}


def _base(**over: object) -> dict:
    feature: dict = {
        "id": "F001",
        "category": "functional",
        "description": "A feature description long enough to satisfy min_length",
        "acceptance": "Some machine-checkable condition",
        "passes": False,
    }
    feature.update(over)
    return feature


def _doc(feature: dict) -> dict:
    return {
        "task_id": "2026-01-01-001-feat-fixture",
        "schema_version": "1.0",
        "features": [feature],
    }


def _schema_rejects(doc: dict) -> bool:
    errors = list(jsonschema.Draft202012Validator(json.loads(FEATURES_SCHEMA.read_text())).iter_errors(doc))
    return bool(errors)


def main() -> int:
    print("evidence read-path (D008 load vs validate)")
    failures: list[str] = []

    unbacked = _doc(_base(passes=True))
    try:
        parsed = Features.model_validate(unbacked)
    except ValidationError as exc:
        failures.append(
            "model must load an unbacked passes=true — enforcement belongs "
            f"at validate time, not on the read path: {exc}"
        )
        parsed = None
    else:
        print("  ✓ Pydantic loads an unbacked passes=true")

    if parsed is not None and parsed.features[0].passes is not True:
        failures.append("loaded feature did not keep passes=true")

    gaps = evidence_gaps(_base(passes=True))
    if not gaps:
        failures.append("evidence_gaps() missed an unbacked passes=true — D008 is open")
    else:
        missing_fields = [field for field in ("verified_by", "verified_at", "evidence_refs") if not any(field in gap for gap in gaps)]
        if missing_fields:
            failures.append(f"evidence_gaps() did not name {missing_fields}: {gaps}")
        else:
            print("  ✓ evidence_gaps() names the three missing fields")

    if not _schema_rejects(unbacked):
        failures.append("jsonschema accepted an unbacked passes=true — schema arm drifted")
    else:
        print("  ✓ jsonschema still rejects an unbacked flip")

    backed = _doc(_base(passes=True, **_EVIDENCE))
    try:
        Features.model_validate(backed)
    except ValidationError as exc:
        failures.append(f"model rejected a fully backed passes=true: {exc}")
    else:
        print("  ✓ Pydantic loads a backed passes=true")

    if evidence_gaps(_base(passes=True, **_EVIDENCE)):
        failures.append("evidence_gaps() flagged a fully backed flip")
    else:
        print("  ✓ evidence_gaps() is clean for a backed flip")

    if evidence_gaps(_base(passes=False)):
        failures.append("evidence_gaps() asked an open feature for evidence")
    else:
        print("  ✓ passes=false is never asked for evidence")

    if failures:
        print("\nFAIL:")
        for failure in failures:
            print(f"  ✗ {failure}")
        return 1

    print("\nPASS: model stays readable; evidence_gaps + jsonschema still catch the flip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
