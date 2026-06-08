"""Plan 2026-06-07-002 — plan-review `introduces` vocabulary affordance.

A feature may declare an optional per-feature `introduces` list naming the
symbols it defines. The coupling lint then treats an introduced symbol as
resolved for the introducing feature and any LATER feature in plan order —
never an earlier one — so greenfield/contract plans stop self-deadlocking
while dependency ordering and typo-detection stay intact.

Run targeted:
  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_plan_review_introduces_f001.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE.parents[2].parent / "claude" / "shared" / "schemas" / "v1.0" / "models"))

from dontpanic_orchestrate.plan_review.lint import Resolvers  # noqa: E402
from dontpanic_orchestrate.plan_review.report import build_plan_scope_report, render_text  # noqa: E402


def _feat(fid: str, acceptance: str, introduces=None) -> dict:
    d = {
        "id": fid,
        "category": "functional",
        "description": "A feature that defines or uses contract vocabulary here.",
        "acceptance": acceptance,
    }
    if introduces is not None:
        d["introduces"] = introduces
    return d


def _flag_kinds(fr):
    return [f.kind for f in fr.scope.flags]


# ── F001: the Feature model accepts the optional field ──────────────────


def test_feature_model_accepts_introduces():
    from features_model import Feature

    f = Feature.model_validate(
        {
            "id": "F001",
            "category": "functional",
            "description": "introduces a symbol that does not exist yet",
            "acceptance": "the model accepts the optional introduces list",
            "passes": False,
            "introduces": ["source_kind", "evidence_basis"],
        }
    )
    assert f.introduces == ["source_kind", "evidence_basis"]


def test_feature_model_without_introduces_unchanged():
    from features_model import Feature

    f = Feature.model_validate(
        {
            "id": "F002",
            "category": "functional",
            "description": "a feature with no introduces behaves as before",
            "acceptance": "absent introduces defaults to None",
            "passes": False,
        }
    )
    assert f.introduces is None


# ── F002: order-aware resolution ────────────────────────────────────────


def test_introducing_feature_does_not_self_block():
    # F001 both introduces and references `widget_kind` (a symbol absent from
    # the codebase). It must not raise missing_prereq on its own symbol.
    feats = [_feat("F001", "every node carries a widget_kind field", introduces=["widget_kind"])]
    report = build_plan_scope_report("p", feats, Resolvers())
    assert "missing_prereq" not in _flag_kinds(report.features[0])


def test_later_feature_resolves_earlier_introduced_symbol():
    feats = [
        _feat("F001", "define widget_kind on every node", introduces=["widget_kind"]),
        _feat("F002", "render widget_kind in the report"),  # uses it, introduces nothing
    ]
    report = build_plan_scope_report("p", feats, Resolvers())
    assert "missing_prereq" not in _flag_kinds(report.features[1])


def test_earlier_feature_cannot_use_later_introduced_symbol():
    # F001 references `widget_kind` but only F002 (LATER) introduces it →
    # F001 still blocks (dependency ordering preserved).
    feats = [
        _feat("F001", "render widget_kind before it exists"),
        _feat("F002", "define widget_kind", introduces=["widget_kind"]),
    ]
    report = build_plan_scope_report("p", feats, Resolvers())
    assert "missing_prereq" in _flag_kinds(report.features[0])
    assert "missing_prereq" not in _flag_kinds(report.features[1])


def test_typo_symbol_still_blocks():
    # Introduces `widget_kind` but the AC references a typo `widget_knd`.
    feats = [_feat("F001", "carry widget_knd everywhere", introduces=["widget_kind"])]
    report = build_plan_scope_report("p", feats, Resolvers())
    kinds = _flag_kinds(report.features[0])
    assert "missing_prereq" in kinds  # the typo is unresolved


def test_plain_plan_without_introduces_is_unchanged():
    # No introduces anywhere: a symbol the codebase doesn't know still blocks
    # exactly as before, and the introduced fields are empty.
    feats = [_feat("F001", "emit a brand_new_symbol nobody declares")]
    report = build_plan_scope_report("p", feats, Resolvers())
    assert "missing_prereq" in _flag_kinds(report.features[0])
    assert report.features[0].introduced_here == ()
    assert report.features[0].resolved_via_introduces == ()


def test_resolution_is_deterministic():
    feats = [
        _feat("F001", "define widget_kind", introduces=["widget_kind"]),
        _feat("F002", "use widget_kind"),
    ]
    a = build_plan_scope_report("p", feats, Resolvers())
    b = build_plan_scope_report("p", feats, Resolvers())
    assert a.to_dict() == b.to_dict()


# ── F003: report surfaces introduced symbols + provenance ───────────────


def test_report_lists_introduced_here_and_resolved_via_provenance():
    feats = [
        _feat("F001", "define widget_kind on every node", introduces=["widget_kind"]),
        _feat("F002", "render widget_kind in the report"),
    ]
    report = build_plan_scope_report("p", feats, Resolvers())

    f1, f2 = report.features
    assert "widget_kind" in f1.introduced_here
    # F002 resolved widget_kind through F001's introduces — provenance shown.
    assert ("widget_kind", "F001") in f2.resolved_via_introduces

    # JSON carries both.
    d = report.to_dict()
    assert d["features"][0]["introduced_here"] == ["widget_kind"]
    assert d["features"][1]["resolved_via_introduces"] == [["widget_kind", "F001"]]

    # Text shows both, labelled, even though the plan has no flags (verdict OK).
    text = render_text(report)
    assert "introduced-here" in text and "widget_kind" in text
    assert "resolved-via-introduces" in text and "from F001" in text
