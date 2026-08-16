"""behavior contract test — plan 2026-08-12-001 F003.

Locks the process-behavior verdict contract at
``schemas/v1.0/behavior.schema.json`` +
``schemas/v1.0/models/behavior_model.py``.

A behavior is judged from an existing audit envelope after the fact.
The schema description must say that behavior specs are hidden from
worker prompts — they are not injected like skills.

Fixtures under ``tests/behavior/``:

  1. ``na-no-evidence``        -> accepted (acceptance 1)
  2. ``violated-no-evidence``  -> rejected (acceptance 2)
  3. ``violated-with-evidence``-> accepted
  4. ``owner-role-unknown``    -> rejected (acceptance 3)
  5. ``expected-no-evidence``  -> accepted
  6. ``extra-key``             -> rejected
  7. ``adherence-unknown``     -> rejected

Each fixture is checked twice — JSON Schema and Pydantic — and the two
verdicts must agree. Further checks: a null-parity matrix, closed
``owner_role`` / ``adherence`` sweeps, evidence_ref parity with
features.schema.json, and the hidden-from-worker-prompts description.

Usage:

    python3 scripts/test_behavior_contract.py

Exit 0 if every case passes; 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1.0"
BEHAVIOR_SCHEMA = SCHEMAS_DIR / "behavior.schema.json"
FEATURES_SCHEMA = SCHEMAS_DIR / "features.schema.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "behavior"

sys.path.insert(0, str(SCHEMAS_DIR))

import jsonschema  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from models.behavior_model import Behavior  # noqa: E402

CASES: list[tuple[str, bool]] = [
    ("na-no-evidence", True),
    ("violated-no-evidence", False),
    ("violated-with-evidence", True),
    ("owner-role-unknown", False),
    ("expected-no-evidence", True),
    ("extra-key", False),
    ("adherence-unknown", False),
]

NULL_PARITY_CASES: list[tuple[str, str]] = [
    ("evidence_refs", "the evidence pointer list"),
    ("trigger", "the trigger text"),
]

OWNER_ROLES = ("implementer", "auditor", "supervisor")
ADHERENCE = ("expected", "n/a", "violated")


def _schema_accepts(schema: dict, doc: dict) -> tuple[bool, str]:
    try:
        jsonschema.Draft202012Validator(schema).validate(doc)
    except jsonschema.ValidationError as exc:
        return False, exc.message
    return True, ""


def _model_accepts(doc: dict) -> tuple[bool, str]:
    try:
        Behavior.model_validate(doc)
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


def _run_enum_sweeps(schema: dict) -> list[str]:
    failures: list[str] = []
    base = json.loads((FIXTURES_DIR / "na-no-evidence.json").read_text())
    for role in OWNER_ROLES:
        doc = dict(base)
        doc["owner_role"] = role
        failures.extend(_agreement(schema, doc, f"owner_role [{role}]", True))

    expected = json.loads((FIXTURES_DIR / "expected-no-evidence.json").read_text())
    na = json.loads((FIXTURES_DIR / "na-no-evidence.json").read_text())
    violated = json.loads((FIXTURES_DIR / "violated-with-evidence.json").read_text())
    templates = {"expected": expected, "n/a": na, "violated": violated}
    for value in ADHERENCE:
        failures.extend(
            _agreement(schema, templates[value], f"adherence [{value}]", True)
        )
    return failures


def _run_null_parity(schema: dict) -> list[str]:
    failures: list[str] = []
    for key, what in NULL_PARITY_CASES:
        doc = json.loads((FIXTURES_DIR / "na-no-evidence.json").read_text())
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
    features = json.loads(FEATURES_SCHEMA.read_text())
    try:
        behavior_ref = schema["$defs"]["evidence_ref"]
        feature_ref = features["$defs"]["evidence_ref"]
    except KeyError as exc:
        return [f"evidence_ref parity: $defs/evidence_ref missing ({exc})"]
    if behavior_ref != feature_ref:
        return [
            "evidence_ref parity: behavior $defs/evidence_ref drifted from "
            "features.schema.json"
        ]
    print(
        "  ✓ evidence_ref parity: behavior $defs/evidence_ref matches "
        "features.schema.json"
    )
    return []


def _run_hidden_from_prompts(schema: dict) -> list[str]:
    description = schema.get("description") or ""
    lowered = description.lower()
    if "hidden" not in lowered or "prompt" not in lowered:
        return [
            "schema description must document that behavior specs are "
            "hidden from worker prompts"
        ]
    print("  ✓ schema description documents hidden-from-worker-prompts")
    return []


def _run_closed_object(schema: dict) -> list[str]:
    if schema.get("additionalProperties") is not False:
        return ["additionalProperties: behavior schema is not closed (must be false)"]
    print("  ✓ additionalProperties is false")
    return []


def main() -> int:
    schema = json.loads(BEHAVIOR_SCHEMA.read_text())

    print("behavior contract (plan 2026-08-12-001 F003)")
    failures = _run_fixture_cases(schema)
    failures.extend(_run_enum_sweeps(schema))
    failures.extend(_run_null_parity(schema))
    failures.extend(_run_evidence_ref_parity(schema))
    failures.extend(_run_hidden_from_prompts(schema))
    failures.extend(_run_closed_object(schema))

    if failures:
        print("\nFAIL:")
        for failure in failures:
            print(f"  ✗ {failure}")
        return 1

    print(
        f"\nPASS: {len(CASES)} fixtures × 2 validators agree, "
        f"{len(OWNER_ROLES)} owner_roles and {len(ADHERENCE)} adherence "
        "values accepted by both, "
        f"{len(NULL_PARITY_CASES)} null cases rejected by both, "
        "evidence_ref in lockstep, hidden-from-prompts documented"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
