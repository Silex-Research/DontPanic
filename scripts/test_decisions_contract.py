"""decisions.jsonl line contract test — plan 2026-08-12-001 F002.

Locks one jsonl line at ``schemas/v1.0/decisions.schema.json`` +
``schemas/v1.0/models/decisions_model.py``.

DontPanic already writes two line shapes. This contract accepts both
without a mass rewrite:

  * current: ``id`` / ``date`` / ``question`` / ``answer`` / ``status``
  * legacy:  ``id`` / ``ts`` / ``by`` / ``title`` / ``body``

``id`` must match ``^D\\d{3}$``. A line needs ``date`` or ``ts``, and
``question`` or ``title``. When ``status`` is present it is
``open|resolved|deferred``.

Validator dispatch stays advisory for jsonl — this file does not teach
``validate.py`` to walk ``decisions.jsonl``. Existing plan files are not
edited.

Fixtures under ``tests/decisions/``:

  1. ``question-answer-resolved`` -> accepted (current convention)
  2. ``title-body-legacy``        -> accepted (legacy shape)
  3. ``missing-id``               -> rejected (acceptance 2)
  4. ``bad-id``                   -> rejected
  5. ``missing-date-and-ts``      -> rejected
  6. ``missing-question-and-title``-> rejected
  7. ``status-unknown``           -> rejected
  8. ``extra-key``                -> rejected

Each fixture is checked twice — JSON Schema and Pydantic — and the two
verdicts must agree.

Usage:

    python3 scripts/test_decisions_contract.py

Exit 0 if every case passes; 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1.0"
DECISIONS_SCHEMA = SCHEMAS_DIR / "decisions.schema.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "decisions"

sys.path.insert(0, str(SCHEMAS_DIR))

import jsonschema  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from models.decisions_model import Decision  # noqa: E402

CASES: list[tuple[str, bool]] = [
    ("question-answer-resolved", True),
    ("title-body-legacy", True),
    ("missing-id", False),
    ("bad-id", False),
    ("missing-date-and-ts", False),
    ("missing-question-and-title", False),
    ("status-unknown", False),
    ("extra-key", False),
]

NULL_PARITY_CASES: list[tuple[str, str]] = [
    ("date", "the date field"),
    ("ts", "the timestamp field"),
    ("question", "the question field"),
    ("title", "the title field"),
    ("status", "the status field"),
]

STATUS_SWEEP = ("open", "resolved", "deferred")


def _schema_accepts(schema: dict, doc: dict) -> tuple[bool, str]:
    try:
        jsonschema.Draft202012Validator(schema).validate(doc)
    except jsonschema.ValidationError as exc:
        return False, exc.message
    return True, ""


def _model_accepts(doc: dict) -> tuple[bool, str]:
    try:
        Decision.model_validate(doc)
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
    failures: list[str] = []
    base = json.loads((FIXTURES_DIR / "question-answer-resolved.json").read_text())
    for status in STATUS_SWEEP:
        doc = dict(base)
        doc["status"] = status
        failures.extend(_agreement(schema, doc, f"status [{status}]", True))
    return failures


def _run_null_parity(schema: dict) -> list[str]:
    failures: list[str] = []
    for key, what in NULL_PARITY_CASES:
        doc = json.loads((FIXTURES_DIR / "question-answer-resolved.json").read_text())
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


def _run_closed_object(schema: dict) -> list[str]:
    if schema.get("additionalProperties") is not False:
        return ["additionalProperties: decisions schema is not closed (must be false)"]
    print("  ✓ additionalProperties is false")
    return []


def main() -> int:
    schema = json.loads(DECISIONS_SCHEMA.read_text())

    print("decisions line contract (plan 2026-08-12-001 F002)")
    failures = _run_fixture_cases(schema)
    failures.extend(_run_status_sweep(schema))
    failures.extend(_run_null_parity(schema))
    failures.extend(_run_closed_object(schema))

    if failures:
        print("\nFAIL:")
        for failure in failures:
            print(f"  ✗ {failure}")
        return 1

    print(
        f"\nPASS: {len(CASES)} fixtures × 2 validators agree, "
        f"{len(STATUS_SWEEP)} statuses accepted by both, "
        f"{len(NULL_PARITY_CASES)} null cases rejected by both"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
