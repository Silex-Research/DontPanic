"""proof + inherits contract test — plan 2026-08-13-001 F001.

Locks the two additive pieces of the outcome contract at
``schemas/v1.0/objective_contract.schema.json`` +
``schemas/v1.0/models/objective_contract_model.py``:

  - ``delivers[].proof`` — an OPTIONAL ``{metric, method, surface?}`` naming the
    cheap first-principle measurement that would show a slice's capability is
    true. ``metric`` is at least 10 characters, ``method`` is one of
    walk / request / named_test / probe, and ``surface`` (when present) comes
    from the plan-level surfaces enum. The method enum is closed on purpose:
    a proof that needs a warehouse or a quarter of data is not cheap and does
    not belong in a lock.
  - ``inherits`` — an OPTIONAL plan id this contract deltas from, so a child or
    fix plan can carry ONE slice instead of restating the parent's full outcome
    set. ``delivers[]`` stays required and non-empty at plan schema_version
    >= 1.1 (a delta IS a delivers[]); what ``inherits`` licenses is omitting the
    FULL set, not omitting the block. Whether the pointer resolves is a
    lock-time question, not a schema one — that is plan 2026-08-13-001 F002.

Fixtures under ``tests/objective_contract_proof/`` (each a whole contract doc):

  1. ``proof-walk-valid``        -> accepted (F001 acceptance 1)
  2. ``proof-method-unknown``    -> rejected: method 'kpi_warehouse' (acceptance 2)
  3. ``proof-metric-too-short``  -> rejected: metric under 10 characters
  4. ``proof-missing-method``    -> rejected: method is required inside proof
  5. ``proof-extra-key``         -> rejected: additionalProperties false on proof
  6. ``proof-surface-unknown``   -> rejected: surface outside the plan enum
  7. ``inherits-delta-one-item`` -> accepted (F001 acceptance 3)
  8. ``inherits-bad-plan-id``    -> rejected: not a plan-id
  9. ``no-proof-baseline``       -> accepted: absence of proof stays valid (acceptance 4)
 10. ``contract-extra-key``      -> rejected: additionalProperties false at contract level

Every fixture is checked TWICE — once against the raw JSON Schema via
``jsonschema``, once against the Pydantic ``ObjectiveContract`` — and the two
verdicts must agree. That agreement is the point: the schema and the model are
independent implementations, and acceptance 2 names both of them explicitly.

Three further checks follow: a null-parity matrix (the schema types these
fields with no ``null`` member, so Pydantic must not read an explicit ``null``
as "use the default"), a method-enum sweep asserting all four cheap methods are
accepted by both validators, and a surface-enum parity assertion across
objective_contract.schema.json, plan.schema.json AND the Pydantic
``ProofSurface`` — so "reuses the plan-level enum" stays a fact.

Usage:

    python3 scripts/test_objective_contract_proof.py

Exit 0 if every case passes; 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1.0"
CONTRACT_SCHEMA = SCHEMAS_DIR / "objective_contract.schema.json"
PLAN_SCHEMA = SCHEMAS_DIR / "plan.schema.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "objective_contract_proof"

sys.path.insert(0, str(SCHEMAS_DIR))

import jsonschema  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from models.objective_contract_model import ObjectiveContract, ProofSurface  # noqa: E402

# fixture stem -> should the contract accept it?
CASES: list[tuple[str, bool]] = [
    ("proof-walk-valid", True),
    ("proof-method-unknown", False),
    ("proof-metric-too-short", False),
    ("proof-missing-method", False),
    ("proof-extra-key", False),
    ("proof-surface-unknown", False),
    ("inherits-delta-one-item", True),
    ("inherits-bad-plan-id", False),
    ("no-proof-baseline", True),
    ("contract-extra-key", False),
]

# Explicit `null` on a key the schema types with no "null" member. Each entry is
# (json-path label, where the null goes).
NULL_PARITY_CASES: list[tuple[str, str]] = [
    ("proof", "the whole proof block"),
    ("metric", "the proof metric"),
    ("method", "the proof method"),
    ("surface", "the proof surface"),
    ("inherits", "the inherit pointer"),
]

CHEAP_METHODS = ["walk", "request", "named_test", "probe"]


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
        ObjectiveContract.model_validate(doc)
    except ValidationError as exc:
        return False, exc.errors()[0].get("msg", str(exc))
    return True, ""


def _agreement(
    schema: dict, doc: dict, label: str, expected_accept: bool
) -> list[str]:
    """Both validators must reach ``expected_accept``, and must agree."""
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


def _run_method_sweep(schema: dict) -> list[str]:
    """All four cheap methods must be accepted by both validators.

    Without this, an implementation that only ever accepted 'walk' would pass
    every rejection case above for entirely the wrong reason.
    """
    failures: list[str] = []
    for method in CHEAP_METHODS:
        doc = json.loads((FIXTURES_DIR / "proof-walk-valid.json").read_text())
        doc["delivers"][0]["proof"]["method"] = method
        failures.extend(_agreement(schema, doc, f"method [{method}]", True))
    return failures


def _run_null_parity(schema: dict) -> list[str]:
    """An explicit ``null`` must get the same verdict from both validators.

    The schema gives `proof` (and each of its keys, and `inherits`) no null
    member, so every case here is a rejection. Pydantic reads a missing key and
    an explicit `None` the same way by default, which would accept documents
    the schema rejects; the `mode='before'` validators close exactly that gap.
    """
    failures: list[str] = []

    for key, what in NULL_PARITY_CASES:
        doc = json.loads((FIXTURES_DIR / "proof-walk-valid.json").read_text())
        if key == "inherits":
            doc["inherits"] = None
        elif key == "proof":
            doc["delivers"][0]["proof"] = None
        else:
            doc["delivers"][0]["proof"][key] = None

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
    """All THREE surface enums must agree: objective_contract.schema.json,
    plan.schema.json, and the Pydantic ``ProofSurface``.

    Comparing only the two JSON enums would leave the Pydantic enum free to
    drift while this check still reported parity — the same hole
    test_user_impact_contract.py closes for `user_impact.surfaces`.
    """
    plan_enum = json.loads(PLAN_SCHEMA.read_text())["properties"]["surfaces"]["items"][
        "enum"
    ]

    try:
        proof_enum = schema["properties"]["delivers"]["items"]["properties"]["proof"][
            "properties"
        ]["surface"]["enum"]
    except KeyError as exc:
        return [f"surface enum parity: proof.surface enum not found ({exc})"]

    if proof_enum != plan_enum:
        return [
            "surface enum parity: proof.surface enum drifted from the plan-level "
            f"enum — proof={proof_enum}, plan={plan_enum}"
        ]

    pydantic_enum = [member.value for member in ProofSurface]
    if pydantic_enum != proof_enum:
        return [
            "surface enum parity: Pydantic ProofSurface drifted from the JSON "
            f"Schema enum — pydantic={pydantic_enum}, proof={proof_enum}"
        ]

    print(
        f"  ✓ surface enum parity: {len(plan_enum)} values match across "
        "objective_contract.schema.json, plan.schema.json and ProofSurface"
    )
    return []


def _run_inherits_pattern_parity(schema: dict) -> list[str]:
    """`inherits` and `delivers[].proof_refs[].plan` share one plan-id grammar.

    Two different regexes for "a plan id" would let a contract name a parent
    that a cross-plan proof_ref could not name (or vice versa).
    """
    contract_props = schema["properties"]
    inherits_pattern = contract_props["inherits"]["pattern"]
    ref_pattern = contract_props["delivers"]["items"]["properties"]["proof_refs"][
        "items"
    ]["properties"]["plan"]["pattern"]

    if inherits_pattern != ref_pattern:
        return [
            "plan-id pattern parity: inherits and proof_refs[].plan disagree — "
            f"inherits={inherits_pattern!r}, proof_refs={ref_pattern!r}"
        ]
    print("  ✓ plan-id pattern parity: inherits matches proof_refs[].plan")
    return []


def main() -> int:
    schema = json.loads(CONTRACT_SCHEMA.read_text())

    print("objective_contract proof + inherits (plan 2026-08-13-001 F001)")
    failures = _run_fixture_cases(schema)
    failures.extend(_run_method_sweep(schema))
    failures.extend(_run_null_parity(schema))
    failures.extend(_run_surface_enum_parity(schema))
    failures.extend(_run_inherits_pattern_parity(schema))

    if failures:
        print("\nFAIL:")
        for failure in failures:
            print(f"  ✗ {failure}")
        return 1

    print(
        f"\nPASS: {len(CASES)} fixtures × 2 validators agree, "
        f"{len(CHEAP_METHODS)} methods accepted by both, "
        f"{len(NULL_PARITY_CASES)} null cases rejected by both, "
        "surface enum and plan-id grammar in lockstep"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
