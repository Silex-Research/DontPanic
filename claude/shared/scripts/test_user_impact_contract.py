"""user_impact contract test — plan 2026-08-09-002 F001.

Locks the conditional semantics of the optional ``user_impact`` block on the
feature contract (``schemas/v1.0/features.schema.json`` +
``schemas/v1.0/models/features_model.py``).

Per decision D003, ``audience: none`` is a complete declaration on its own —
``summary`` and ``surfaces`` MUST be absent or empty. Any other audience
requires a summary of at least 10 characters and a non-empty surfaces array.
The rule is expressed as JSON Schema ``if/then/else`` and mirrored by a
Pydantic ``model_validator`` so the two cannot drift.

Fixtures under ``tests/user_impact/``:

  1. ``none-bare``               -> accepted
  2. ``none-with-summary``       -> rejected (D003: 'none' is the whole answer)
  3. ``end-user-missing-summary``-> rejected
  4. ``end-user-short-summary``  -> rejected (<10 chars)
  5. ``end-user-empty-surfaces`` -> rejected
  6. ``end-user-missing-hash``   -> rejected (D005 anchor, see below)

Cases 1-5 are the five named in F001's acceptance. Case 6 is a regression
guard: ``description_hash`` is what binds a claim to the description it was
written against, so a declaration carrying a claim must carry the digest.
Without it F003 would need a fourth "digest unknown" state alongside
declared / possibly-stale / undeclared, and it defines no such state. The
digest stays optional under ``audience: none``, which asserts no external
consequence and so has no claim that can go stale.

Each fixture is checked twice — once against the raw JSON Schema via
``jsonschema``, once against the Pydantic ``Features`` model — and the two
verdicts must agree. Three further checks follow: a positive control, a
null-parity matrix (the schema types these fields with no ``null`` member, so
Pydantic must not read an explicit ``null`` as "use the default"), and an
assertion that the ``surfaces`` enum is identical across features.schema.json,
plan.schema.json AND the Pydantic ``ImpactSurface``, so "reuses the plan-level
enum" stays a fact rather than an intention — including on the model side,
which a JSON-to-JSON comparison alone would leave free to drift.

Usage:

    python3 scripts/test_user_impact_contract.py

Exit 0 if every case passes; 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1.0"
FEATURES_SCHEMA = SCHEMAS_DIR / "features.schema.json"
PLAN_SCHEMA = SCHEMAS_DIR / "plan.schema.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "user_impact"

sys.path.insert(0, str(SCHEMAS_DIR))

import jsonschema  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from models.features_model import Features, ImpactSurface  # noqa: E402

# fixture stem -> should the contract accept it?
CASES: list[tuple[str, bool]] = [
    ("none-bare", True),
    ("none-with-summary", False),
    ("end-user-missing-summary", False),
    ("end-user-short-summary", False),
    ("end-user-empty-surfaces", False),
    ("end-user-missing-hash", False),
]

# Explicit `null` on a key the schema types with no "null" member. Each entry
# is (label, mutation) where mutation edits the loaded document in place.
NULL_PARITY_CASES: list[tuple[str, str]] = [
    ("user_impact", "the whole block"),
    ("summary", "a declared summary"),
    ("surfaces", "a declared surfaces array"),
    ("description_hash", "the staleness digest"),
]


def _schema_accepts(schema: dict, doc: dict) -> tuple[bool, str]:
    """Validate ``doc`` against the raw JSON Schema. Return (accepted, detail)."""
    try:
        jsonschema.Draft202012Validator(schema).validate(doc)
    except jsonschema.ValidationError as exc:
        return False, exc.message
    return True, ""


def _model_accepts(doc: dict) -> tuple[bool, str]:
    """Validate ``doc`` against the Pydantic model. Return (accepted, detail)."""
    try:
        Features.model_validate(doc)
    except ValidationError as exc:
        return False, exc.errors()[0].get("msg", str(exc))
    return True, ""


def _run_fixture_cases(schema: dict) -> list[str]:
    failures: list[str] = []

    for stem, expected_accept in CASES:
        fixture = FIXTURES_DIR / f"{stem}.json"
        doc = json.loads(fixture.read_text())

        schema_ok, schema_detail = _schema_accepts(schema, doc)
        model_ok, model_detail = _model_accepts(doc)

        verb = "accept" if expected_accept else "reject"
        if schema_ok != expected_accept:
            failures.append(
                f"{stem}: JSON Schema did not {verb} the fixture "
                f"(detail: {schema_detail or 'accepted with no error'})"
            )
        if model_ok != expected_accept:
            failures.append(
                f"{stem}: Pydantic model did not {verb} the fixture "
                f"(detail: {model_detail or 'accepted with no error'})"
            )
        if schema_ok != model_ok:
            failures.append(
                f"{stem}: schema/model DISAGREE — schema accepted={schema_ok} "
                f"({schema_detail or 'ok'}), model accepted={model_ok} "
                f"({model_detail or 'ok'})"
            )
        else:
            print(f"  ✓ {stem}: both validators {verb}ed (agreement)")

    return failures


def _run_positive_control(schema: dict) -> list[str]:
    """A well-formed end_user block must be ACCEPTED by both validators.

    Without this, an implementation that rejects every `user_impact` block
    would pass four of the five fixture cases for entirely the wrong reason.
    """
    doc = json.loads((FIXTURES_DIR / "end-user-empty-surfaces.json").read_text())
    doc["features"][0]["user_impact"]["surfaces"] = ["ios", "ux"]

    schema_ok, schema_detail = _schema_accepts(schema, doc)
    model_ok, model_detail = _model_accepts(doc)

    failures: list[str] = []
    if not schema_ok:
        failures.append(f"positive control: JSON Schema rejected it ({schema_detail})")
    if not model_ok:
        failures.append(f"positive control: Pydantic model rejected it ({model_detail})")
    if not failures:
        print("  ✓ positive control: well-formed end_user block accepted by both")
    return failures


def _run_null_parity(schema: dict) -> list[str]:
    """An explicit ``null`` must get the same verdict from both validators.

    The schema types ``user_impact`` as an object and its three optional keys
    as string/array, none of them admitting ``null`` — so every case here is a
    rejection. Pydantic reads a missing key and an explicit ``None`` the same
    way by default, which would accept documents the schema rejects; the
    ``mode='before'`` validators exist to close exactly that gap.
    """
    failures: list[str] = []

    for key, what in NULL_PARITY_CASES:
        doc = json.loads((FIXTURES_DIR / "none-bare.json").read_text())
        feature = doc["features"][0]
        if key == "user_impact":
            feature["user_impact"] = None
        else:
            # Start from a well-formed end_user block so the null is the only
            # thing wrong with the document.
            feature["user_impact"] = {
                "audience": "end_user",
                "summary": "Users see a guided prompt on first run",
                "surfaces": ["ios", "ux"],
                "description_hash": "7842cdf16ef0c9471dba82ce407cc62479"
                "cdc1105b005dd98acee6758d5ede87",
            }
            feature["user_impact"][key] = None

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


def _run_surface_enum_parity(schema: dict) -> list[str]:
    """All THREE surface enums must agree: features.schema.json, plan.schema.json,
    and the Pydantic ``ImpactSurface``.

    Comparing only the two JSON enums would leave the Pydantic enum free to drift
    while this check still reported parity — the exact hole the rest of this file
    exists to close, since the JSON Schema and the model are independent
    implementations. Raised by CodeRabbit on PR #2.
    """
    plan_schema = json.loads(PLAN_SCHEMA.read_text())
    plan_enum = plan_schema["properties"]["surfaces"]["items"]["enum"]

    try:
        feature_enum = (
            schema["$defs"]["user_impact"]["properties"]["surfaces"]["items"]["enum"]
        )
    except KeyError as exc:
        return [f"surface enum parity: user_impact.surfaces enum not found ({exc})"]

    if feature_enum != plan_enum:
        return [
            "surface enum parity: user_impact.surfaces enum drifted from the "
            f"plan-level enum — features={feature_enum}, plan={plan_enum}"
        ]

    pydantic_enum = [member.value for member in ImpactSurface]
    if pydantic_enum != feature_enum:
        return [
            "surface enum parity: Pydantic ImpactSurface drifted from the JSON "
            f"Schema enum — pydantic={pydantic_enum}, features={feature_enum}"
        ]

    print(
        f"  ✓ surface enum parity: {len(plan_enum)} values match across "
        "features.schema.json, plan.schema.json and ImpactSurface"
    )
    return []


def main() -> int:
    schema = json.loads(FEATURES_SCHEMA.read_text())

    print("user_impact contract (plan 2026-08-09-002 F001)")
    failures = _run_fixture_cases(schema)
    failures.extend(_run_positive_control(schema))
    failures.extend(_run_null_parity(schema))
    failures.extend(_run_surface_enum_parity(schema))

    if failures:
        print("\nFAIL:")
        for failure in failures:
            print(f"  ✗ {failure}")
        return 1

    print(
        f"\nPASS: {len(CASES)} fixtures × 2 validators agree, "
        f"{len(NULL_PARITY_CASES)} null cases rejected by both, "
        "surface enum in lockstep"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
