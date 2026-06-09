"""Plan 2026-06-08-006 — pre-impl governance loop repair.

These tests pin the four governance defects the 2026-06-08 dogfood surfaced when
running the full orchestrate loop on DontPanic itself:

  1. ``run_sufficiency_audit`` had no production caller → ``generate_sufficiency_findings``.
  2. ``plan lock`` required findings it could not generate → CLI now generates them.
  3. design-review volley crashed on ``Category`` enum serialization → model_dump(mode="json").
  4. the sufficiency parser discarded a paid Codex JSONL response → shared codex_stream parser.

All tests are NO-PAID — Codex output is replayed from fixtures.

  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_preimpl_governance_loop.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))
REPO_ROOT = HERE.parents[3]

from dontpanic_orchestrate import codex_stream as cs  # noqa: E402
from dontpanic_orchestrate import completion_dispatch as cd  # noqa: E402
from dontpanic_orchestrate import sufficiency_auditor as sa  # noqa: E402


def _codex_stream(agent_text: str) -> str:
    """Render a realistic Codex CLI `exec --json` event stream whose final
    agent_message carries ``agent_text`` (mirrors the real stream shape)."""
    return "\n".join(
        json.dumps(ev)
        for ev in [
            {"type": "thread.started"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "reasoning", "text": "thinking"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": agent_text}},
            {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}},
        ]
    )


_VALID_FINDINGS = [
    {
        "severity": "high",
        "journey_id": "coverage-honesty",
        "gap_class": "coverage_gap",
        "description": "the architecture page needs an entering-surface proof " * 2,
    }
]


# ── shared codex parser (fix #4 primitives) ─────────────────────────────


def test_coerce_tolerates_extra_data():
    # The EXACT dogfood failure: a valid JSON value followed by trailing prose
    # ("Extra data: line 2 column 1") that strict json.loads rejects.
    assert cs.coerce_first_json_value("[]\nNo material gaps found.") == []
    assert cs.coerce_first_json_value('{"a": 1}\ntrailing') == {"a": 1}


def test_coerce_handles_code_fence():
    assert cs.coerce_first_json_value("```json\n[]\n```") == []


def test_extract_codex_stream_then_coerce():
    stream = _codex_stream(json.dumps(_VALID_FINDINGS))
    payload = cs.extract_codex_streaming_payload(stream)
    assert payload is not None
    assert cs.coerce_first_json_value(payload) == _VALID_FINDINGS


def test_non_stream_input_is_not_misread_as_codex():
    # plain JSON (no codex event types) → None, caller uses it as-is
    assert cs.extract_codex_streaming_payload("[]") is None


def test_completion_dispatch_reuses_shared_parser():
    # fix #4 reuse: the post-impl path's symbol IS the shared implementation.
    assert cd._extract_codex_streaming_payload is cs.extract_codex_streaming_payload


# ── fix #4: sufficiency parser consumes Codex output ────────────────────


def test_sufficiency_parses_codex_jsonl_stream_replay():
    # Replays the discarded paid response shape: findings wrapped in a Codex stream.
    stream = _codex_stream(json.dumps(_VALID_FINDINGS))
    findings = sa._parse_sufficiency_response(stream)
    assert len(findings) == 1
    assert findings[0].gap_class == "coverage_gap"


def test_sufficiency_parses_array_with_trailing_prose():
    # The literal "Extra data" shape that crashed the live dogfood call.
    raw = json.dumps(_VALID_FINDINGS) + "\n\nThat is my assessment."
    findings = sa._parse_sufficiency_response(raw)
    assert len(findings) == 1


def test_sufficiency_still_rejects_total_garbage():
    with pytest.raises(sa.SufficiencyAuditError):
        sa._parse_sufficiency_response("this is not json at all")


# ── fix #1: production caller writes the findings artifact (no paid call) ─


def test_run_sufficiency_audit_writes_findings_with_injected_codex_dispatch(tmp_path):
    plan_dir = _make_plan(tmp_path)
    captured = {}

    def fake_dispatch(auditor, prompt):
        captured["auditor"] = auditor
        return _codex_stream(json.dumps(_VALID_FINDINGS))  # codex-shaped, like production

    findings = sa.run_sufficiency_audit(
        plan_dir, implementer_agent="claude", dispatch=fake_dispatch
    )
    assert len(findings) == 1
    out = plan_dir / "evidence" / "goal-governance" / "pre_impl" / sa.PRE_IMPL_FINDINGS_ARTIFACT
    assert out.is_file(), "production caller must persist the findings artifact"
    persisted = json.loads(out.read_text())
    assert persisted["findings"][0]["gap_class"] == "coverage_gap"


def test_generate_sufficiency_findings_is_exported_production_entry():
    # fix #1: the production entry point exists (it did not before this plan).
    assert hasattr(sa, "generate_sufficiency_findings")
    assert "generate_sufficiency_findings" in sa.__all__


# ── fix #3: design-volley feature dicts serialize (Category enum) ────────


def test_real_plan_feature_dicts_are_json_serializable():
    from dontpanic_orchestrate import plan_loader

    plan_dir = REPO_ROOT / "docs/plans/2026-06-08-004-feat-architecture-reconciler-ui-plan-d"
    loaded = plan_loader.load(plan_dir)
    # plain model_dump() leaks the Category enum → json.dumps raises (the crash).
    with pytest.raises(TypeError):
        json.dumps([f.model_dump() for f in loaded.features.features])
    # mode="json" (the fix) serializes enums to their values → clean.
    ok = json.dumps([f.model_dump(mode="json") for f in loaded.features.features])
    assert '"functional"' in ok or '"category"' in ok


# ── fix #6: end-to-end dry-run — no crash, no paid call ─────────────────


def _make_plan(tmp_path: Path) -> Path:
    d = tmp_path / "2026-06-08-999-feat-fixture"
    d.mkdir(parents=True)
    (d / "plan.md").write_text(
        "---\n"
        "id: 2026-06-08-999-feat-fixture\n"
        "title: Fixture\n"
        "goal_type: new_feature\n"
        "links:\n"
        "  features: ./features.json\n"
        "  objective_contract: ./objective_contract.json\n"
        "---\n\n# Fixture\n"
    )
    (d / "features.json").write_text(
        json.dumps(
            {
                "task_id": "2026-06-08-999-feat-fixture",
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "functional",
                        "description": "do the thing",
                        "acceptance": "the thing is done and verified through the real surface",
                        "passes": False,
                    }
                ],
            }
        )
    )
    (d / "objective_contract.json").write_text(
        json.dumps(
            {
                "goal_type": "new_feature",
                "source_of_truth": "operator directive: build the fixture thing end to end",
                "completion_test": "the fixture thing works and is verified through its surface",
                "user_journeys": [
                    {
                        "name": "primary-journey",
                        "description": "operator does the primary fixture thing successfully",
                        "surfaces": ["core"],
                        "states": ["ready"],
                    }
                ],
                "non_goals": ["nothing out of fixture scope"],
            }
        )
    )
    return d


def test_e2e_dry_run_draft_to_gate_no_crash(tmp_path):
    """draft plan → sufficiency audit (replayed Codex) → findings written →
    gate sees findings → re-parse round-trips. The whole pre-impl loop runs
    without a paid call and without the Category/parse crashes."""
    from dontpanic_orchestrate import sufficiency_gate as sg

    plan_dir = _make_plan(tmp_path)

    # 1. sufficiency audit via replayed Codex stream (no paid call)
    sa.run_sufficiency_audit(
        plan_dir,
        implementer_agent="claude",
        dispatch=lambda a, p: _codex_stream(json.dumps(_VALID_FINDINGS)),
    )

    # 2. the lock gate's required artifact now exists where it looks for it
    assert sg._findings_path(plan_dir).is_file()

    # 3. the persisted findings re-parse cleanly (round-trip the loop)
    reparsed = sa._parse_sufficiency_response(
        json.dumps(json.loads(sg._findings_path(plan_dir).read_text())["findings"])
    )
    assert len(reparsed) == 1
