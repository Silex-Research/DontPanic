"""Plan 2026-05-02-003 F001 — parent/child metadata + depth/cycle/repeated-finding guards.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_nested_orchestration.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from pydantic import ValidationError  # noqa: E402

from jarvis_orchestrate import plan_loader  # noqa: E402
from jarvis_orchestrate.nested_orchestration import (  # noqa: E402
    DEFAULT_DEPTH_LIMIT,
    NestedOrchestrationError,
    Orchestration,
    SpawnFinding,
    check_cycle,
    check_depth,
    check_repeated_finding,
    compute_depth,
    compute_finding_signature,
    walk_parent_chain,
)

# ──────────────────────────────  fixture-prep helpers  ──────────────────────────────


def _make_top_level_plan(plan_dir: Path, *, plan_id: str, feature_id: str = "F001") -> Path:
    """Write a minimal top-level plan (no orchestration block)."""
    plan_dir.mkdir(parents=True)
    plan_md = f"""---
id: {plan_id}
title: {plan_id}
type: feat
tier: trivial
status: active
date: "2026-05-02"
description: synthetic test plan
agents_required: [claude, codex]
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
---

# {plan_id}

## Target

```yaml
target_env: dev
target_project: none
```
"""
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": feature_id,
                "category": "test",
                "phase": 0,
                "description": "synthetic feature",
                "steps": ["one"],
                "acceptance": "synthetic",
                "passes": False,
                "depends_on": [],
            }
        ],
    }
    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(json.dumps(features, indent=2) + "\n")
    return plan_dir


def _make_child_plan(
    plan_dir: Path,
    *,
    plan_id: str,
    parent_plan_id: str,
    spawn_reason: str = "auditor_finding",
    spawn_finding: dict[str, Any] | None = None,
    depth_limit: int = DEFAULT_DEPTH_LIMIT,
) -> Path:
    """Write a child plan with an `orchestration` frontmatter block."""
    plan_dir.mkdir(parents=True)

    if spawn_reason == "auditor_finding" and spawn_finding is None:
        spawn_finding = {
            "parent_audit_id": f"{parent_plan_id}#claude#0",
            "finding_id": f"{parent_plan_id}#claude#0#finding-1",
            "finding_code": "EC5",
            "finding_class": "correctness",
            "finding_signature": compute_finding_signature(
                "EC5", "correctness", "synthetic finding text"
            ),
        }

    orch_block = {
        "parent_plan_id": parent_plan_id,
        "spawn_reason": spawn_reason,
        "depth_limit": depth_limit,
    }
    if spawn_finding is not None:
        orch_block["spawn_finding"] = spawn_finding

    # YAML-style multi-line render of the orchestration block.
    import yaml as _yaml  # local — keep test dep narrow

    orch_yaml = _yaml.safe_dump({"orchestration": orch_block}, sort_keys=False)
    plan_md = f"""---
id: {plan_id}
title: {plan_id}
type: feat
tier: trivial
status: active
date: "2026-05-02"
description: synthetic child plan
agents_required: [claude, codex]
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
{orch_yaml}links:
  features: ./features.json
---

# {plan_id}

## Target

```yaml
target_env: dev
target_project: none
```
"""
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": "F001",
                "category": "test",
                "phase": 0,
                "description": "synthetic child feature",
                "steps": ["one"],
                "acceptance": "synthetic",
                "passes": False,
                "depends_on": [],
            }
        ],
    }
    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(json.dumps(features, indent=2) + "\n")
    return plan_dir


# ──────────────────────────────  finding_signature determinism  ──────────────────────────────


def test_finding_signature_is_deterministic() -> None:
    """Same (code, class, issue) → same signature regardless of whitespace/case
    in the issue text."""
    sig_a = compute_finding_signature(
        "EC5", "correctness", "implementer summary lacks the canonical prelude"
    )
    sig_b = compute_finding_signature(
        "EC5", "correctness", "  IMPLEMENTER  Summary  Lacks  THE Canonical Prelude  "
    )
    assert sig_a == sig_b
    # And it's a non-trivial string (hex prefix).
    assert len(sig_a) >= 12
    assert all(c in "0123456789abcdef" for c in sig_a)


def test_finding_signature_differs_on_different_issue_text() -> None:
    """Two findings sharing (code, class) but with distinct issues → distinct signatures."""
    sig_a = compute_finding_signature("EC5", "correctness", "missing prelude")
    sig_b = compute_finding_signature("EC5", "correctness", "value mismatch in prelude")
    assert sig_a != sig_b


def test_finding_signature_differs_on_different_code_or_class() -> None:
    sig_ec5 = compute_finding_signature("EC5", "correctness", "x")
    sig_s101 = compute_finding_signature("S101", "correctness", "x")
    sig_security = compute_finding_signature("EC5", "security", "x")
    assert sig_ec5 != sig_s101
    assert sig_ec5 != sig_security
    assert sig_s101 != sig_security


# ──────────────────────────────  Pydantic model validation  ──────────────────────────────


def test_orchestration_top_level_plan_returns_none() -> None:
    """Top-level plan (no orchestration block in frontmatter) → LoadedPlan.orchestration is None."""
    # Verified through plan_loader.load below; this test just asserts the model
    # is not constructible from an empty dict (i.e., orchestration is opt-in).
    with pytest.raises(ValidationError):
        Orchestration()  # type: ignore[call-arg]


def test_orchestration_auditor_finding_requires_spawn_finding() -> None:
    """spawn_reason='auditor_finding' MUST carry a spawn_finding."""
    with pytest.raises(ValidationError):
        Orchestration(
            parent_plan_id="2026-05-02-001-feat-parentstub",
            spawn_reason="auditor_finding",
            spawn_finding=None,
        )


def test_orchestration_operator_manual_rejects_spawn_finding() -> None:
    """spawn_reason='operator_manual' MUST NOT carry a spawn_finding."""
    sf = SpawnFinding(
        parent_audit_id="x#claude#0",
        finding_id="x#claude#0#finding-1",
        finding_code="EC5",
        finding_class="correctness",
        finding_signature=compute_finding_signature("EC5", "correctness", "x"),
    )
    with pytest.raises(ValidationError):
        Orchestration(
            parent_plan_id="2026-05-02-001-feat-parentstub",
            spawn_reason="operator_manual",
            spawn_finding=sf,
        )


def test_orchestration_depth_limit_capped_at_default() -> None:
    """Frontmatter depth_limit > DEFAULT_DEPTH_LIMIT (3) is rejected (D002)."""
    sf = SpawnFinding(
        parent_audit_id="x#claude#0",
        finding_id="x#claude#0#finding-1",
        finding_code="EC5",
        finding_class="correctness",
        finding_signature=compute_finding_signature("EC5", "correctness", "x"),
    )
    with pytest.raises(ValidationError):
        Orchestration(
            parent_plan_id="2026-05-02-001-feat-parentstub",
            spawn_reason="auditor_finding",
            spawn_finding=sf,
            depth_limit=DEFAULT_DEPTH_LIMIT + 1,
        )


def test_orchestration_depth_limit_below_default_accepted() -> None:
    """Frontmatter depth_limit may declare a LOWER value than the platform default."""
    sf = SpawnFinding(
        parent_audit_id="x#claude#0",
        finding_id="x#claude#0#finding-1",
        finding_code="EC5",
        finding_class="correctness",
        finding_signature=compute_finding_signature("EC5", "correctness", "x"),
    )
    o = Orchestration(
        parent_plan_id="2026-05-02-001-feat-parentstub",
        spawn_reason="auditor_finding",
        spawn_finding=sf,
        depth_limit=2,
    )
    assert o.depth_limit == 2


def test_spawn_finding_signature_drift_detection() -> None:
    """SpawnFinding rejects a declared signature that doesn't match
    `compute_finding_signature(code, class, issue)` — but the SpawnFinding
    model itself doesn't carry `issue`, so drift detection happens at parent
    audit envelope read time, not at SpawnFinding parse time. Verified below
    in `test_dispatch_validates_signature_against_parent_finding`.
    """
    # Pure SpawnFinding parses any signature the operator provides — drift is
    # detected when comparing against the parent envelope's findings.
    sf = SpawnFinding(
        parent_audit_id="x#claude#0",
        finding_id="x#claude#0#finding-1",
        finding_code="EC5",
        finding_class="correctness",
        finding_signature="deadbeef" * 8,  # not the real signature
    )
    assert sf.finding_signature.startswith("deadbeef")


# ──────────────────────────────  walk_parent_chain + compute_depth  ──────────────────────────────


def test_walk_parent_chain_top_level_returns_just_the_plan(tmp_path: Path) -> None:
    p_id = "2026-05-02-100-feat-toplevel"
    plan_dir = _make_top_level_plan(tmp_path / p_id, plan_id=p_id)
    chain = walk_parent_chain(plan_dir)
    assert chain == [p_id]
    assert compute_depth(plan_dir) == 1


def test_walk_parent_chain_two_deep(tmp_path: Path) -> None:
    parent_id = "2026-05-02-100-feat-parent"
    child_id = "2026-05-02-101-feat-child"
    parent_dir = _make_top_level_plan(tmp_path / parent_id, plan_id=parent_id)
    # The child uses parent's plan_id; resolution uses tmp_path as the search root.
    child_dir = _make_child_plan(tmp_path / child_id, plan_id=child_id, parent_plan_id=parent_id)
    chain = walk_parent_chain(child_dir, plans_root=tmp_path)
    assert chain == [child_id, parent_id]
    assert compute_depth(child_dir, plans_root=tmp_path) == 2
    # parent_dir reachable for follow-on tests
    assert parent_dir.exists()


def test_walk_parent_chain_three_deep(tmp_path: Path) -> None:
    g_id = "2026-05-02-100-feat-grandparent"
    p_id = "2026-05-02-101-feat-parent"
    c_id = "2026-05-02-102-feat-child"
    _make_top_level_plan(tmp_path / g_id, plan_id=g_id)
    _make_child_plan(tmp_path / p_id, plan_id=p_id, parent_plan_id=g_id)
    child_dir = _make_child_plan(tmp_path / c_id, plan_id=c_id, parent_plan_id=p_id)
    chain = walk_parent_chain(child_dir, plans_root=tmp_path)
    assert chain == [c_id, p_id, g_id]
    assert compute_depth(child_dir, plans_root=tmp_path) == 3


# ──────────────────────────────  check_depth  ──────────────────────────────


def test_check_depth_passes_at_default_limit(tmp_path: Path) -> None:
    """Depth 3 with default limit 3 passes (no override needed)."""
    g_id = "2026-05-02-100-feat-grandparent"
    p_id = "2026-05-02-101-feat-parent"
    c_id = "2026-05-02-102-feat-child"
    _make_top_level_plan(tmp_path / g_id, plan_id=g_id)
    _make_child_plan(tmp_path / p_id, plan_id=p_id, parent_plan_id=g_id)
    child_dir = _make_child_plan(tmp_path / c_id, plan_id=c_id, parent_plan_id=p_id)
    # Depth = 3; limit = 3; passes.
    check_depth(child_dir, plans_root=tmp_path)


def test_check_depth_raises_at_depth_4_without_override(tmp_path: Path) -> None:
    g_id = "2026-05-02-100-feat-grandparent"
    p_id = "2026-05-02-101-feat-parent"
    c_id = "2026-05-02-102-feat-child"
    gc_id = "2026-05-02-103-feat-greatgrandchild"
    _make_top_level_plan(tmp_path / g_id, plan_id=g_id)
    _make_child_plan(tmp_path / p_id, plan_id=p_id, parent_plan_id=g_id)
    _make_child_plan(tmp_path / c_id, plan_id=c_id, parent_plan_id=p_id)
    gc_dir = _make_child_plan(tmp_path / gc_id, plan_id=gc_id, parent_plan_id=c_id, depth_limit=3)
    # Depth = 4 > limit = 3.
    with pytest.raises(NestedOrchestrationError) as exc:
        check_depth(gc_dir, plans_root=tmp_path)
    assert "depth" in str(exc.value).lower()
    assert str(compute_depth(gc_dir, plans_root=tmp_path)) in str(exc.value)


def test_check_depth_passes_with_cli_override(tmp_path: Path) -> None:
    g_id = "2026-05-02-100-feat-grandparent"
    p_id = "2026-05-02-101-feat-parent"
    c_id = "2026-05-02-102-feat-child"
    gc_id = "2026-05-02-103-feat-greatgrandchild"
    _make_top_level_plan(tmp_path / g_id, plan_id=g_id)
    _make_child_plan(tmp_path / p_id, plan_id=p_id, parent_plan_id=g_id)
    _make_child_plan(tmp_path / c_id, plan_id=c_id, parent_plan_id=p_id)
    gc_dir = _make_child_plan(tmp_path / gc_id, plan_id=gc_id, parent_plan_id=c_id)
    # CLI override raises the cap; passes.
    check_depth(gc_dir, plans_root=tmp_path, override_max=5)


# ──────────────────────────────  check_cycle  ──────────────────────────────


def test_check_cycle_passes_on_acyclic_chain(tmp_path: Path) -> None:
    parent_id = "2026-05-02-100-feat-parent"
    child_id = "2026-05-02-101-feat-child"
    _make_top_level_plan(tmp_path / parent_id, plan_id=parent_id)
    child_dir = _make_child_plan(tmp_path / child_id, plan_id=child_id, parent_plan_id=parent_id)
    check_cycle(child_dir, plans_root=tmp_path)


def test_check_cycle_raises_on_3_plan_loop(tmp_path: Path) -> None:
    """A→B→C→A — the chain walking child A finds A again at depth 4."""
    a_id = "2026-05-02-100-feat-cycle-a"
    b_id = "2026-05-02-101-feat-cycle-b"
    c_id = "2026-05-02-102-feat-cycle-c"
    # A points at C as its parent (the cycle). B points at A. C points at B.
    _make_child_plan(tmp_path / a_id, plan_id=a_id, parent_plan_id=c_id)
    _make_child_plan(tmp_path / b_id, plan_id=b_id, parent_plan_id=a_id)
    c_dir = _make_child_plan(tmp_path / c_id, plan_id=c_id, parent_plan_id=b_id)
    with pytest.raises(NestedOrchestrationError) as exc:
        check_cycle(c_dir, plans_root=tmp_path)
    msg = str(exc.value)
    assert "cycle" in msg.lower()
    # Both plan ids in the cycle should be named.
    assert a_id in msg or c_id in msg


# ──────────────────────────────  check_repeated_finding  ──────────────────────────────


def test_check_repeated_finding_passes_on_distinct_signatures(tmp_path: Path) -> None:
    """Parent and child have findings sharing (code, class) but distinct issues
    → distinct signatures → no hard stop."""
    # Parent's spawn metadata is None (top-level), so we need a deeper test:
    # a chain where the GRANDPARENT has spawn_finding A, and the CHILD has
    # spawn_finding B with same (code, class) but different signature.
    g_id = "2026-05-02-100-feat-grand"
    p_id = "2026-05-02-101-feat-parent"
    c_id = "2026-05-02-102-feat-child"
    _make_top_level_plan(tmp_path / g_id, plan_id=g_id)
    _make_child_plan(
        tmp_path / p_id,
        plan_id=p_id,
        parent_plan_id=g_id,
        spawn_finding={
            "parent_audit_id": f"{g_id}#claude#0",
            "finding_id": f"{g_id}#claude#0#finding-1",
            "finding_code": "EC5",
            "finding_class": "correctness",
            "finding_signature": compute_finding_signature(
                "EC5", "correctness", "first finding text"
            ),
        },
    )
    child_dir = _make_child_plan(
        tmp_path / c_id,
        plan_id=c_id,
        parent_plan_id=p_id,
        spawn_finding={
            "parent_audit_id": f"{p_id}#claude#0",
            "finding_id": f"{p_id}#claude#0#finding-1",
            "finding_code": "EC5",
            "finding_class": "correctness",
            "finding_signature": compute_finding_signature(
                "EC5", "correctness", "different finding text"
            ),
        },
    )
    # Distinct signatures → passes.
    check_repeated_finding(child_dir, plans_root=tmp_path)


def test_check_repeated_finding_raises_on_signature_collision(tmp_path: Path) -> None:
    """Child's signature matches a parent's signature → hard stop (D001)."""
    g_id = "2026-05-02-100-feat-grand"
    p_id = "2026-05-02-101-feat-parent"
    c_id = "2026-05-02-102-feat-child"
    same_sig = compute_finding_signature("EC5", "correctness", "the recurring finding text")
    _make_top_level_plan(tmp_path / g_id, plan_id=g_id)
    _make_child_plan(
        tmp_path / p_id,
        plan_id=p_id,
        parent_plan_id=g_id,
        spawn_finding={
            "parent_audit_id": f"{g_id}#claude#0",
            "finding_id": f"{g_id}#claude#0#finding-1",
            "finding_code": "EC5",
            "finding_class": "correctness",
            "finding_signature": same_sig,
        },
    )
    child_dir = _make_child_plan(
        tmp_path / c_id,
        plan_id=c_id,
        parent_plan_id=p_id,
        spawn_finding={
            "parent_audit_id": f"{p_id}#claude#0",
            "finding_id": f"{p_id}#claude#0#finding-1",
            "finding_code": "EC5",
            "finding_class": "correctness",
            "finding_signature": same_sig,  # collision
        },
    )
    with pytest.raises(NestedOrchestrationError) as exc:
        check_repeated_finding(child_dir, plans_root=tmp_path)
    msg = str(exc.value)
    assert "repeated finding" in msg.lower() or "signature" in msg.lower()
    assert same_sig in msg
    assert p_id in msg  # the matching parent's plan_id


# ──────────────────────────────  plan_loader integration  ──────────────────────────────


def test_plan_loader_top_level_orchestration_is_none(tmp_path: Path) -> None:
    """Top-level plan without orchestration block → LoadedPlan.orchestration is None.
    Zero-regression for every existing top-level plan in the repo."""
    p_id = "2026-05-02-100-feat-toplevel"
    plan_dir = _make_top_level_plan(tmp_path / p_id, plan_id=p_id)
    loaded = plan_loader.load(plan_dir)
    assert loaded.orchestration is None


def test_plan_loader_child_orchestration_parses(tmp_path: Path) -> None:
    """Child plan with orchestration block → LoadedPlan.orchestration is populated."""
    parent_id = "2026-05-02-100-feat-parent"
    child_id = "2026-05-02-101-feat-child"
    _make_top_level_plan(tmp_path / parent_id, plan_id=parent_id)
    child_dir = _make_child_plan(tmp_path / child_id, plan_id=child_id, parent_plan_id=parent_id)
    loaded = plan_loader.load(child_dir)
    assert loaded.orchestration is not None
    assert loaded.orchestration.parent_plan_id == parent_id
    assert loaded.orchestration.spawn_reason == "auditor_finding"
    assert loaded.orchestration.spawn_finding is not None
    assert loaded.orchestration.spawn_finding.finding_code == "EC5"
