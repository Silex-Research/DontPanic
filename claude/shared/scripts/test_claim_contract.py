"""claim contract test — plan 2026-08-12-001 F001.

Locks the verified-admission claim contract at
``schemas/v1.0/claim.schema.json`` + ``schemas/v1.0/models/claim_model.py``.

A finding, failed hypothesis, or binding constraint may enter shared state
only when it is admitted against evidence. The rule is expressed as JSON
Schema ``if/then`` and mirrored by a Pydantic ``model_validator`` so the two
cannot drift.

Fixtures under ``tests/claim/``:

  1. ``admitted-with-evidence``      -> accepted (acceptance 1)
  2. ``admitted-empty-evidence``     -> rejected (acceptance 2)
  3. ``status-unknown``              -> rejected (acceptance 3)
  4. ``proposed-empty-evidence``     -> accepted (proposed owes no evidence)
  5. ``rejected-with-reason``        -> accepted
  6. ``rejected-missing-reason``     -> rejected
  7. ``stale-missing-reason``        -> rejected
  8. ``extra-key``                   -> rejected (acceptance 5)
  9. ``admitted-missing-admitted-by``-> rejected

Each fixture is checked twice — once against the raw JSON Schema via
``jsonschema``, once against the Pydantic ``Claim`` model — and the two
verdicts must agree. Two further checks follow: a null-parity matrix (the
schema types these fields with no ``null`` member) and an assertion that
``$defs/evidence_ref`` is byte-identical to the one in features.schema.json.

Usage:

    python3 scripts/test_claim_contract.py

Exit 0 if every case passes; 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1.0"
CLAIM_SCHEMA = SCHEMAS_DIR / "claim.schema.json"
FEATURES_SCHEMA = SCHEMAS_DIR / "features.schema.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "claim"

sys.path.insert(0, str(SCHEMAS_DIR))

import jsonschema  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from models.claim_model import Claim  # noqa: E402

CASES: list[tuple[str, bool]] = [
    ("admitted-with-evidence", True),
    ("admitted-empty-evidence", False),
    ("status-unknown", False),
    ("proposed-empty-evidence", True),
    ("rejected-with-reason", True),
    ("rejected-missing-reason", False),
    ("stale-missing-reason", False),
    ("extra-key", False),
    ("admitted-missing-admitted-by", False),
]

NULL_PARITY_CASES: list[tuple[str, str]] = [
    ("admitted_by", "who admitted the claim"),
    ("admitted_at", "when the claim was admitted"),
    ("reason", "the rejected/stale reason"),
    ("evidence_refs", "the evidence pointer list"),
]

STATUS_SWEEP = ("proposed", "admitted", "rejected", "stale")


def _schema_accepts(schema: dict, doc: dict) -> tuple[bool, str]:
    try:
        jsonschema.Draft202012Validator(schema).validate(doc)
    except jsonschema.ValidationError as exc:
        return False, exc.message
    return True, ""


def _model_accepts(doc: dict) -> tuple[bool, str]:
    try:
        Claim.model_validate(doc)
    except ValidationError as exc:
        return False, exc.errors()[0].get("msg", str(exc))
    return True, ""


def _agreement(schema: dict, doc: dict, label: str, expected_accept: bool) -> list[str]:
    schema_ok, schema_detail = _schema_accepts(schema, doc)
    model_ok, model_detail = _model_accepts(doc)

    failures: list[str] = []
    verb = "accept" if expected_accept else "reject"
    if schema_ok != expected_accept:
        failures.append(
            f"{label}: JSON Schema did not {verb} the fixture "
            f"(detail: {schema_detail or 'accepted with no error'})"
        )
    if model_ok != expected_accept:
        failures.append(
            f"{label}: Pydantic model did not {verb} the fixture "
            f"(detail: {model_detail or 'accepted with no error'})"
        )
    if schema_ok != model_ok:
        failures.append(
            f"{label}: schema/model DISAGREE — schema accepted={schema_ok} "
            f"({schema_detail or 'ok'}), model accepted={model_ok} "
            f"({model_detail or 'ok'})"
        )
    if not failures:
        print(f"  ✓ {label}: both validators {verb}ed (agreement)")
    return failures


def _run_fixture_cases(schema: dict) -> list[str]:
    failures: list[str] = []
    for stem, expected_accept in CASES:
        doc = json.loads((FIXTURES_DIR / f"{stem}.json").read_text())
        failures.extend(_agreement(schema, doc, stem, expected_accept))
    return failures


def _run_status_sweep(schema: dict) -> list[str]:
    """Every closed status must be accepted by both when the rest is well-formed.

    Without this, an implementation that only ever accepted ``admitted`` would
    pass the rejection cases for the wrong reason.
    """
    failures: list[str] = []
    templates = {
        "proposed": json.loads(
            (FIXTURES_DIR / "proposed-empty-evidence.json").read_text()
        ),
        "admitted": json.loads(
            (FIXTURES_DIR / "admitted-with-evidence.json").read_text()
        ),
        "rejected": json.loads(
            (FIXTURES_DIR / "rejected-with-reason.json").read_text()
        ),
        "stale": json.loads((FIXTURES_DIR / "rejected-with-reason.json").read_text()),
    }
    templates["stale"]["status"] = "stale"
    templates["stale"]["reason"] = "Source finding changed after admission"
    for status in STATUS_SWEEP:
        failures.extend(
            _agreement(schema, templates[status], f"status [{status}]", True)
        )
    return failures


def _run_null_parity(schema: dict) -> list[str]:
    failures: list[str] = []
    for key, what in NULL_PARITY_CASES:
        doc = json.loads((FIXTURES_DIR / "admitted-with-evidence.json").read_text())
        doc[key] = None
        schema_ok, schema_detail = _schema_accepts(schema, doc)
        model_ok, model_detail = _model_accepts(doc)
        label = f"null parity [{key}]"
        if schema_ok:
            failures.append(f"{label}: JSON Schema accepted an explicit null")
        if model_ok:
            failures.append(f"{label}: Pydantic model accepted an explicit null")
        if schema_ok != model_ok:
            failures.append(
                f"{label}: schema/model DISAGREE — schema accepted={schema_ok} "
                f"({schema_detail or 'ok'}), model accepted={model_ok} "
                f"({model_detail or 'ok'})"
            )
        elif not schema_ok:
            print(f"  ✓ {label}: both reject null for {what}")
    return failures


def _run_evidence_ref_parity(schema: dict) -> list[str]:
    """claim $defs/evidence_ref must match features.schema.json exactly."""
    features = json.loads(FEATURES_SCHEMA.read_text())
    try:
        claim_ref = schema["$defs"]["evidence_ref"]
        feature_ref = features["$defs"]["evidence_ref"]
    except KeyError as exc:
        return [f"evidence_ref parity: $defs/evidence_ref missing ({exc})"]
    if claim_ref != feature_ref:
        return [
            "evidence_ref parity: claim $defs/evidence_ref drifted from "
            "features.schema.json"
        ]
    print(
        "  ✓ evidence_ref parity: claim $defs/evidence_ref matches features.schema.json"
    )
    return []


def _run_closed_object(schema: dict) -> list[str]:
    if schema.get("additionalProperties") is not False:
        return ["additionalProperties: claim schema is not closed (must be false)"]
    print("  ✓ additionalProperties is false")
    return []


def main() -> int:
    schema = json.loads(CLAIM_SCHEMA.read_text())

    print("claim contract (plan 2026-08-12-001 F001)")
    failures = _run_fixture_cases(schema)
    failures.extend(_run_status_sweep(schema))
    failures.extend(_run_null_parity(schema))
    failures.extend(_run_evidence_ref_parity(schema))
    failures.extend(_run_closed_object(schema))

    if failures:
        print("\nFAIL:")
        for failure in failures:
            print(f"  ✗ {failure}")
        return 1

    print(
        f"\nPASS: {len(CASES)} fixtures × 2 validators agree, "
        f"{len(STATUS_SWEEP)} statuses accepted by both, "
        f"{len(NULL_PARITY_CASES)} null cases rejected by both, "
        "evidence_ref in lockstep with features.schema.json"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
