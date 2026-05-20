"""Plan 2026-05-19-003 F001 — agent-conventions v1.9.0 additive properties.

Verifies that `orchestration`, `child_charter`, and `commit_policy` declared
on the Plan schema root accept the enum + property shape the plan acceptance
text specifies: spawn_reason ∈ {operator_manual, auto, test};
kind ∈ {implementation, investigation, migration}; mode ∈ {child_commit,
parent_commit, manual}; requires is an array of plain strings (the runtime
narrows the vocabulary, the schema does not).

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_plan_schema_v19_additive_orchestration_fields.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml
from pydantic import ValidationError

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parents[2]))
# plan_loader's _find_schemas_dir adds the schemas dir to sys.path so
# `from models.plan_model import ...` resolves. Importing it triggers that.
from dontpanic_orchestrate import plan_loader as _plan_loader  # noqa: E402,F401

from models.plan_model import Plan  # noqa: E402

V4_1_PLAN_DIR = REPO_ROOT / "docs" / "plans" / "2026-05-12-002-fix-harness-frictions-v4-1"
SCHEMA_PATH = REPO_ROOT / "claude" / "shared" / "schemas" / "v1.0" / "plan.schema.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _load_frontmatter(plan_md: Path) -> dict:
    text = plan_md.read_text()
    fm = yaml.safe_load(text.split("---", 2)[1])
    # YAML parses ISO dates into date objects; jsonschema format:date expects str.
    if hasattr(fm.get("date"), "isoformat"):
        fm["date"] = fm["date"].isoformat()
    return fm


def _minimal_plan_dict() -> dict:
    return {
        "id": "2026-05-19-099-feat-minimal-test",
        "title": "Minimal plan for v1.9 backward-compat test",
        "type": "feat",
        "tier": "trivial",
        "status": "draft",
        "date": "2026-05-19",
        "description": "A minimal plan with no orchestration metadata, to confirm v1.9.0 stays backward compatible.",
    }


# ──────────────────────────────  (a) v4.1 plan validates clean  ──────────────────────────────


def test_v4_1_plan_frontmatter_validates_against_v1_9_schema():
    """A real locked v4.1 plan, which has orchestration + child_charter +
    commit_policy in its frontmatter, must validate cleanly against the
    v1.9.0 schema (this was the original `additionalProperties not allowed`
    failure the plan exists to fix)."""
    schema = _load_schema()
    fm = _load_frontmatter(V4_1_PLAN_DIR / "plan.md")

    assert "orchestration" in fm
    assert "child_charter" in fm
    assert "commit_policy" in fm

    # Must not raise.
    jsonschema.validate(fm, schema)


# ──────────────────────────────  (b) Pydantic mirror accepts same dict  ──────────────────────────────


def test_v4_1_plan_frontmatter_accepted_by_pydantic_plan_model():
    """The Pydantic mirror in `models/plan_model.py` must accept the same
    dict the JSON schema does — acceptance #2 of the plan: 'Pydantic mirror
    MUST validate the same plans the JSON schema validates.' Required so
    that callers of `Plan.model_validate` on raw frontmatter (without the
    loader's pop-then-validate pattern) work for v1.9+ shapes."""
    fm = _load_frontmatter(V4_1_PLAN_DIR / "plan.md")

    plan = Plan.model_validate(fm)

    assert plan.orchestration is not None
    assert plan.orchestration.parent_plan_id == (
        "2026-05-11-001-infra-state-projection-adapters-meta"
    )
    assert plan.orchestration.spawn_reason.value == "operator_manual"
    assert plan.orchestration.depth_limit == 3

    assert plan.child_charter is not None
    assert plan.child_charter.kind.value == "implementation"
    assert plan.child_charter.may_edit_product_code is True
    assert len(plan.child_charter.allowed_paths) >= 1

    assert plan.commit_policy is not None
    assert plan.commit_policy.mode.value == "child_commit"
    assert plan.commit_policy.requires == ["tests_pass", "evidence_packaged"]


# ──────────────────────────────  (c) minimal plan still validates  ──────────────────────────────


def test_minimal_plan_without_new_fields_still_validates():
    """Acceptance #1: 'existing root properties unchanged' — a minimal plan
    that omits orchestration / child_charter / commit_policy must still
    validate cleanly against both the JSON schema and the Pydantic mirror.
    Backward compatibility safety net for every pre-v1.9 plan."""
    schema = _load_schema()
    fm = _minimal_plan_dict()

    assert "orchestration" not in fm
    assert "child_charter" not in fm
    assert "commit_policy" not in fm

    jsonschema.validate(fm, schema)

    plan = Plan.model_validate(fm)
    assert plan.orchestration is None
    assert plan.child_charter is None
    assert plan.commit_policy is None


# ──────────────────────────────  (d) malformed orchestration fails  ──────────────────────────────


def test_malformed_orchestration_fails_jsonschema_with_helpful_error():
    """Malformed orchestration (wrong type for depth_limit) must fail
    jsonschema validation with a message that names the offending field.
    Catches the case where future authors put garbage in the block —
    important since the runtime would also reject it, but at a much later
    stage of dispatch."""
    schema = _load_schema()
    fm = _load_frontmatter(V4_1_PLAN_DIR / "plan.md")
    bad = copy.deepcopy(fm)
    bad["orchestration"]["depth_limit"] = "not-an-integer"

    with pytest.raises(jsonschema.ValidationError) as exc:
        jsonschema.validate(bad, schema)
    msg = str(exc.value)
    assert "depth_limit" in msg or "integer" in msg


def test_malformed_orchestration_fails_pydantic_with_helpful_error():
    """Companion to the jsonschema check — the Pydantic mirror must reject
    the same malformed shape (with a message that names the offending field
    OR the type constraint)."""
    fm = _load_frontmatter(V4_1_PLAN_DIR / "plan.md")
    bad = copy.deepcopy(fm)
    bad["orchestration"]["depth_limit"] = "not-an-integer"

    with pytest.raises(ValidationError) as exc:
        Plan.model_validate(bad)
    msg = str(exc.value)
    assert "depth_limit" in msg or "integer" in msg


# ──────────────────────────────  (e) plan-acceptance enum contract  ──────────────────────────────
#
# Codex-auditor F001-i0 finding: schema enums must match the plan's literal
# acceptance text (operator_manual|auto|test, implementation|investigation|
# migration, child_commit|parent_commit|manual). These tests pin the contract
# so future drift fails a real check.


@pytest.mark.parametrize("spawn_reason", ["operator_manual", "auto", "test"])
def test_spawn_reason_accepts_each_plan_enum_value(spawn_reason: str):
    """Every spawn_reason value the plan acceptance text declares must
    validate. 'operator_manual' is what every existing locked plan uses;
    'auto' and 'test' are reserved for automated + fixture spawns."""
    schema = _load_schema()
    fm = _load_frontmatter(V4_1_PLAN_DIR / "plan.md")
    candidate = copy.deepcopy(fm)
    candidate["orchestration"]["spawn_reason"] = spawn_reason

    jsonschema.validate(candidate, schema)
    plan = Plan.model_validate(candidate)
    assert plan.orchestration is not None
    assert plan.orchestration.spawn_reason.value == spawn_reason


@pytest.mark.parametrize("kind", ["implementation", "investigation", "migration"])
def test_child_charter_kind_accepts_each_plan_enum_value(kind: str):
    """child_charter.kind values per plan acceptance text — schema and
    Pydantic mirror must accept all three."""
    schema = _load_schema()
    fm = _load_frontmatter(V4_1_PLAN_DIR / "plan.md")
    candidate = copy.deepcopy(fm)
    candidate["child_charter"]["kind"] = kind

    jsonschema.validate(candidate, schema)
    plan = Plan.model_validate(candidate)
    assert plan.child_charter is not None
    assert plan.child_charter.kind.value == kind


@pytest.mark.parametrize("mode", ["child_commit", "parent_commit", "manual"])
def test_commit_policy_mode_accepts_each_plan_enum_value(mode: str):
    """commit_policy.mode values per plan acceptance text — schema and
    Pydantic mirror must accept all three."""
    schema = _load_schema()
    fm = _load_frontmatter(V4_1_PLAN_DIR / "plan.md")
    candidate = copy.deepcopy(fm)
    candidate["commit_policy"]["mode"] = mode

    jsonschema.validate(candidate, schema)
    plan = Plan.model_validate(candidate)
    assert plan.commit_policy is not None
    assert plan.commit_policy.mode.value == mode


def test_commit_policy_requires_accepts_arbitrary_strings():
    """The plan acceptance text says `requires array of strings` (no enum).
    The schema must therefore accept vocabulary outside the runtime's
    current {patch_completeness, tests_pass, evidence_packaged} set so the
    runtime can extend the vocabulary without a schema bump."""
    schema = _load_schema()
    fm = _load_frontmatter(V4_1_PLAN_DIR / "plan.md")
    candidate = copy.deepcopy(fm)
    candidate["commit_policy"]["requires"] = [
        "tests_pass",
        "evidence_packaged",
        "future_check_runtime_will_add",
    ]

    jsonschema.validate(candidate, schema)
    plan = Plan.model_validate(candidate)
    assert plan.commit_policy is not None
    assert plan.commit_policy.requires == [
        "tests_pass",
        "evidence_packaged",
        "future_check_runtime_will_add",
    ]


def test_unknown_spawn_reason_still_rejected_by_jsonschema():
    """Schema enum still rejects values outside the plan's declared set so
    typos and stale-from-v1.8 values (e.g. 'auditor_finding') fail fast."""
    schema = _load_schema()
    fm = _load_frontmatter(V4_1_PLAN_DIR / "plan.md")
    bad = copy.deepcopy(fm)
    bad["orchestration"]["spawn_reason"] = "auditor_finding"

    with pytest.raises(jsonschema.ValidationError) as exc:
        jsonschema.validate(bad, schema)
    msg = str(exc.value)
    assert "spawn_reason" in msg or "auditor_finding" in msg or "enum" in msg


def test_unknown_kind_still_rejected_by_jsonschema():
    """child_charter.kind enum stays a closed set — unknown values fail."""
    schema = _load_schema()
    fm = _load_frontmatter(V4_1_PLAN_DIR / "plan.md")
    bad = copy.deepcopy(fm)
    bad["child_charter"]["kind"] = "governance_design"

    with pytest.raises(jsonschema.ValidationError) as exc:
        jsonschema.validate(bad, schema)
    msg = str(exc.value)
    assert "kind" in msg or "governance_design" in msg or "enum" in msg


def test_unknown_commit_policy_mode_still_rejected_by_jsonschema():
    """commit_policy.mode enum stays a closed set — unknown values fail."""
    schema = _load_schema()
    fm = _load_frontmatter(V4_1_PLAN_DIR / "plan.md")
    bad = copy.deepcopy(fm)
    bad["commit_policy"]["mode"] = "evidence_only"

    with pytest.raises(jsonschema.ValidationError) as exc:
        jsonschema.validate(bad, schema)
    msg = str(exc.value)
    assert "mode" in msg or "evidence_only" in msg or "enum" in msg
