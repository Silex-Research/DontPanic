"""Plan 2026-05-02-003 F003 — parent pause/fan-in protocol.

Verifies the pre_resume_after_child gate type, idempotent INBOX entry,
best-effort events.jsonl writes, fan-in memo + child-compliance
validation, --accept-non-satisfied override, and the bare-resume
discipline (resume cannot clear child-return gates).

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_parent_pause_protocol.py
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import cli as cli_mod  # noqa: E402
from dontpanic_orchestrate import gate_pause, inbox  # noqa: E402
from dontpanic_orchestrate.nested_orchestration import (  # noqa: E402
    FAN_IN_MEMO_TEMPLATE,
    ChildPauseApproveError,
    approve_pre_resume_after_child,
    child_compliance_side_car_path,
    events_log_path,
    fan_in_memo_path,
    pre_resume_gate_name,
    read_child_compliance,
    record_event,
)

# ──────────────────────────────  fixtures  ──────────────────────────────


def _make_plan_dir(
    tmp_path: Path,
    plan_id: str,
    *,
    orchestration_block: str = "",
    target_project: str = "jarvis-a6ee1",
) -> Path:
    """Build a minimal plan dir under tmp_path/docs/plans/{plan_id}/. Used
    when tests need plan_loader.load() to succeed; many F003 tests can use
    a bare directory and skip plan.md/features.json."""
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)

    plan_md = f"""---
id: {plan_id}
title: F003 fixture
type: infra
tier: trivial
status: active
date: "2026-05-02"
description: Synthetic plan for F003 parent-pause/fan-in tests.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
{orchestration_block}---

# F003 fixture plan

## Target

```yaml
target_env: dev
target_project: {target_project}
```
"""
    (plan_dir / "plan.md").write_text(plan_md)
    features = {
        "task_id": plan_id,
        "schema_version": "1.0",
        "features": [
            {
                "id": "F001",
                "category": "test",
                "phase": 0,
                "description": "synthetic feature for F003 protocol tests",
                "steps": ["scripted single step"],
                "acceptance": "synthetic acceptance text for F003 tests",
                "passes": False,
                "depends_on": [],
            }
        ],
    }
    (plan_dir / "features.json").write_text(json.dumps(features))
    return plan_dir


def _bare_plan_dir(tmp_path: Path, plan_id: str) -> Path:
    """Plan dir with no plan.md/features.json — sufficient for gate-state +
    INBOX + events.jsonl + side-car tests that don't load the plan model."""
    p = tmp_path / plan_id
    p.mkdir()
    return p


def _write_satisfied_compliance(child_plan_dir: Path, child_plan_id: str) -> Path:
    p = child_compliance_side_car_path(child_plan_dir, child_plan_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "task_id": child_plan_id,
                "return_condition_status": "satisfied",
                "compliance_checks_satisfied": ["tests_pass"],
                "commit_policy_mode": "evidence_only",
                "decided_at": "2026-05-02T20:00:00Z",
            }
        )
    )
    return p


def _write_non_satisfied_compliance(child_plan_dir: Path, child_plan_id: str, status: str) -> Path:
    p = child_compliance_side_car_path(child_plan_dir, child_plan_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "task_id": child_plan_id,
                "return_condition_status": status,
                "compliance_checks_satisfied": [],
                "commit_policy_mode": "evidence_only",
                "decided_at": "2026-05-02T20:00:00Z",
            }
        )
    )
    return p


def _write_satisfied_fan_in_memo(parent_plan_dir: Path, child_plan_id: str) -> Path:
    memo = fan_in_memo_path(parent_plan_dir, child_plan_id)
    memo.parent.mkdir(parents=True, exist_ok=True)
    memo.write_text(FAN_IN_MEMO_TEMPLATE.format(child_plan_id=child_plan_id))
    return memo


def _write_non_satisfied_fan_in_memo(
    parent_plan_dir: Path, child_plan_id: str, status: str
) -> Path:
    memo = fan_in_memo_path(parent_plan_dir, child_plan_id)
    memo.parent.mkdir(parents=True, exist_ok=True)
    memo.write_text(
        FAN_IN_MEMO_TEMPLATE.format(child_plan_id=child_plan_id).replace(
            "status: satisfied", f"status: {status}"
        )
    )
    return memo


# ──────────────────────────────  events.jsonl best-effort writes  ──────────────────────────────


class TestEventsLog:
    def test_record_event_appends_jsonl(self, tmp_path):
        plan_dir = _bare_plan_dir(tmp_path, "p")
        ok = record_event(plan_dir, "test.kind", {"foo": 1}, plan_id="plan-x")
        assert ok is True
        log = events_log_path(plan_dir)
        assert log.is_file()
        lines = log.read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["kind"] == "test.kind"
        assert record["plan_id"] == "plan-x"
        assert record["foo"] == 1
        assert "ts" in record

    def test_record_event_appends_multiple(self, tmp_path):
        plan_dir = _bare_plan_dir(tmp_path, "p")
        record_event(plan_dir, "k1", {"a": 1}, plan_id="px")
        record_event(plan_dir, "k2", {"b": 2}, plan_id="px")
        record_event(plan_dir, "k3", {"c": 3}, plan_id="px")
        lines = events_log_path(plan_dir).read_text().strip().split("\n")
        assert len(lines) == 3
        kinds = [json.loads(line)["kind"] for line in lines]
        assert kinds == ["k1", "k2", "k3"]

    def test_record_event_invalid_payload_returns_false(self, tmp_path):
        plan_dir = _bare_plan_dir(tmp_path, "p")
        # Sets are not JSON-serializable.
        ok = record_event(plan_dir, "k", {"bad": {1, 2, 3}}, plan_id="px")
        assert ok is False
        # No file created (or empty).
        log = events_log_path(plan_dir)
        if log.exists():
            assert log.read_text() == ""

    def test_record_event_unwritable_dir_returns_false(self, tmp_path):
        plan_dir = _bare_plan_dir(tmp_path, "p")
        # Create the events.jsonl path then revoke write permission.
        log = events_log_path(plan_dir)
        log.write_text("")  # so the directory exists
        # On macOS, chmod a parent dir to readable-only blocks the append.
        # Use the parent dir to revoke; restore in finally.
        original_mode = plan_dir.stat().st_mode
        try:
            plan_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
            log.chmod(stat.S_IRUSR)
            ok = record_event(plan_dir, "k", {"a": 1}, plan_id="px")
            assert ok is False
        finally:
            plan_dir.chmod(original_mode)
            try:
                log.chmod(stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass

    def test_record_event_never_raises_on_oserror(self, tmp_path, monkeypatch):
        """Even if the open() raises, record_event must return False, not raise."""
        plan_dir = _bare_plan_dir(tmp_path, "p")

        def _raising_open(*args, **kwargs):
            raise OSError("simulated disk full")

        monkeypatch.setattr(Path, "open", _raising_open)
        # Must not raise.
        ok = record_event(plan_dir, "k", {"a": 1}, plan_id="px")
        assert ok is False


# ──────────────────────────────  pre_resume_after_child gate lifecycle  ──────────────────────────────


class TestPreResumeAfterChildGateLifecycle:
    def test_add_idempotent(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        first = gate_pause.add_pre_resume_after_child(parent, "child-1", plan_id="parent")
        second = gate_pause.add_pre_resume_after_child(parent, "child-1", plan_id="parent")
        assert first is True
        assert second is False

    def test_active_list(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        gate_pause.add_pre_resume_after_child(parent, "c1", plan_id="parent")
        gate_pause.add_pre_resume_after_child(parent, "c2", plan_id="parent")
        active = gate_pause.active_pre_resume_after_children(parent)
        assert pre_resume_gate_name("c1") in active
        assert pre_resume_gate_name("c2") in active
        assert len(active) == 2

    def test_clear_removes_gate(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        gate_pause.add_pre_resume_after_child(parent, "c1", plan_id="parent")
        cleared = gate_pause.clear_pre_resume_after_child(parent, "c1", plan_id="parent")
        assert cleared is True
        assert gate_pause.active_pre_resume_after_children(parent) == []

    def test_clear_idempotent_when_not_armed(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        cleared = gate_pause.clear_pre_resume_after_child(parent, "ghost", plan_id="parent")
        assert cleared is False

    def test_evaluate_includes_unmet_pre_resume_gates(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        gate_pause.add_pre_resume_after_child(parent, "c1", plan_id="parent")
        check = gate_pause.evaluate(parent, declared_gates=[])
        assert check.paused is True
        assert pre_resume_gate_name("c1") in check.unmet

    def test_evaluate_clean_when_no_gates(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        check = gate_pause.evaluate(parent, declared_gates=[])
        assert check.paused is False
        assert check.unmet == []

    def test_resume_all_does_not_clear_pre_resume_after_child(self, tmp_path):
        """KEY VERIFICATION (D004 bare-resume discipline): `resume --all`
        clears declared/breakers/defers but MUST leave pre_resume_after_child
        gates intact. Operator must use `approve --child` form."""
        parent = _bare_plan_dir(tmp_path, "parent")
        gate_pause.add_pre_resume_after_child(parent, "c1", plan_id="parent")
        gate_pause.add_breaker(parent, "breaker:soft_block", plan_id="parent")
        gate_pause.resume_all(
            parent,
            plan_id="parent",
            declared_gates=["pre_impl"],
        )
        # Breaker is gone, but child-return gate persists.
        assert gate_pause.active_breakers(parent) == []
        assert pre_resume_gate_name("c1") in gate_pause.active_pre_resume_after_children(parent)
        # And evaluate still reports pause.
        check = gate_pause.evaluate(parent, declared_gates=[])
        assert check.paused is True
        assert pre_resume_gate_name("c1") in check.unmet

    def test_pause_marker_clears_when_pre_resume_resolves(self, tmp_path):
        """After clearing the only outstanding gate, paused_at + pause_gates
        should drop from gate-state.json."""
        parent = _bare_plan_dir(tmp_path, "parent")
        gate_pause.add_pre_resume_after_child(parent, "c1", plan_id="parent")
        gate_pause.record_pause(parent, plan_id="parent", pause_gates=[pre_resume_gate_name("c1")])
        gate_pause.clear_pre_resume_after_child(parent, "c1", plan_id="parent")
        state = json.loads(gate_pause.gate_state_path(parent).read_text())
        assert "paused_at" not in state
        assert "pause_gates" not in state


# ──────────────────────────────  approve helper validation  ──────────────────────────────


class TestApprovePreResumeAfterChildHelper:
    def test_refuses_when_gate_not_armed(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        child = _bare_plan_dir(tmp_path, "child")
        with pytest.raises(ChildPauseApproveError) as exc:
            approve_pre_resume_after_child(
                parent,
                parent_plan_id="parent",
                child_plan_id="child",
                child_plan_dir=child,
            )
        assert "not currently armed" in str(exc.value)

    def test_refuses_when_fan_in_memo_missing(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        child = _bare_plan_dir(tmp_path, "child")
        gate_pause.add_pre_resume_after_child(parent, "child", plan_id="parent")
        _write_satisfied_compliance(child, "child")
        with pytest.raises(ChildPauseApproveError) as exc:
            approve_pre_resume_after_child(
                parent,
                parent_plan_id="parent",
                child_plan_id="child",
                child_plan_dir=child,
            )
        assert "fan-in memo missing" in str(exc.value)

    def test_refuses_when_memo_no_return_condition_section(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        child = _bare_plan_dir(tmp_path, "child")
        gate_pause.add_pre_resume_after_child(parent, "child", plan_id="parent")
        _write_satisfied_compliance(child, "child")
        memo = fan_in_memo_path(parent, "child")
        memo.parent.mkdir(parents=True, exist_ok=True)
        memo.write_text("# Just a memo, no return condition\n")
        with pytest.raises(ChildPauseApproveError) as exc:
            approve_pre_resume_after_child(
                parent,
                parent_plan_id="parent",
                child_plan_id="child",
                child_plan_dir=child,
            )
        assert "malformed" in str(exc.value).lower() or "return condition" in str(exc.value).lower()

    def test_refuses_when_memo_status_blocked(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        child = _bare_plan_dir(tmp_path, "child")
        gate_pause.add_pre_resume_after_child(parent, "child", plan_id="parent")
        _write_satisfied_compliance(child, "child")
        _write_non_satisfied_fan_in_memo(parent, "child", "blocked")
        with pytest.raises(ChildPauseApproveError) as exc:
            approve_pre_resume_after_child(
                parent,
                parent_plan_id="parent",
                child_plan_id="child",
                child_plan_dir=child,
            )
        msg = str(exc.value)
        assert "blocked" in msg
        assert "satisfied" in msg

    def test_memo_status_override_does_not_help(self, tmp_path):
        """KEY VERIFICATION: --accept-non-satisfied does NOT override the
        memo's own status. The memo is the operator's explicit re-entry
        declaration; only the child-side status can be overridden."""
        parent = _bare_plan_dir(tmp_path, "parent")
        child = _bare_plan_dir(tmp_path, "child")
        gate_pause.add_pre_resume_after_child(parent, "child", plan_id="parent")
        _write_non_satisfied_compliance(child, "child", "blocked")
        _write_non_satisfied_fan_in_memo(parent, "child", "blocked")
        with pytest.raises(ChildPauseApproveError) as exc:
            approve_pre_resume_after_child(
                parent,
                parent_plan_id="parent",
                child_plan_id="child",
                child_plan_dir=child,
                accept_non_satisfied=True,  # does NOT override memo
            )
        # The memo check fires before the child compliance check, so the
        # message should reference the memo.
        assert "fan-in memo" in str(exc.value)

    def test_refuses_when_child_compliance_blocked_without_override(self, tmp_path):
        """KEY VERIFICATION: child status=blocked → refuse without override."""
        parent = _bare_plan_dir(tmp_path, "parent")
        child = _bare_plan_dir(tmp_path, "child")
        gate_pause.add_pre_resume_after_child(parent, "child", plan_id="parent")
        _write_satisfied_fan_in_memo(parent, "child")
        _write_non_satisfied_compliance(child, "child", "blocked")
        with pytest.raises(ChildPauseApproveError) as exc:
            approve_pre_resume_after_child(
                parent,
                parent_plan_id="parent",
                child_plan_id="child",
                child_plan_dir=child,
            )
        msg = str(exc.value)
        assert "blocked" in msg
        assert "--accept-non-satisfied" in msg

    def test_refuses_when_child_compliance_superseded_without_override(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        child = _bare_plan_dir(tmp_path, "child")
        gate_pause.add_pre_resume_after_child(parent, "child", plan_id="parent")
        _write_satisfied_fan_in_memo(parent, "child")
        _write_non_satisfied_compliance(child, "child", "superseded")
        with pytest.raises(ChildPauseApproveError) as exc:
            approve_pre_resume_after_child(
                parent,
                parent_plan_id="parent",
                child_plan_id="child",
                child_plan_dir=child,
            )
        assert "superseded" in str(exc.value)

    def test_refuses_when_child_compliance_side_car_missing_without_override(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        child = _bare_plan_dir(tmp_path, "child")
        gate_pause.add_pre_resume_after_child(parent, "child", plan_id="parent")
        _write_satisfied_fan_in_memo(parent, "child")
        # Side-car deliberately missing.
        with pytest.raises(ChildPauseApproveError) as exc:
            approve_pre_resume_after_child(
                parent,
                parent_plan_id="parent",
                child_plan_id="child",
                child_plan_dir=child,
            )
        msg = str(exc.value)
        assert "file missing" in msg or "None" in msg

    def test_override_with_blocked_clears_gate(self, tmp_path):
        """KEY VERIFICATION: --accept-non-satisfied permits child=blocked."""
        parent = _bare_plan_dir(tmp_path, "parent")
        child = _bare_plan_dir(tmp_path, "child")
        gate_pause.add_pre_resume_after_child(parent, "child", plan_id="parent")
        _write_satisfied_fan_in_memo(parent, "child")
        _write_non_satisfied_compliance(child, "child", "blocked")
        outcome = approve_pre_resume_after_child(
            parent,
            parent_plan_id="parent",
            child_plan_id="child",
            child_plan_dir=child,
            accept_non_satisfied=True,
        )
        assert outcome["override_applied"] is True
        assert outcome["child_status"] == "blocked"
        assert outcome["memo_status"] == "satisfied"
        # Gate is now cleared.
        assert pre_resume_gate_name("child") not in gate_pause.active_pre_resume_after_children(
            parent
        )

    def test_clean_path_clears_gate(self, tmp_path):
        parent = _bare_plan_dir(tmp_path, "parent")
        child = _bare_plan_dir(tmp_path, "child")
        gate_pause.add_pre_resume_after_child(parent, "child", plan_id="parent")
        _write_satisfied_fan_in_memo(parent, "child")
        _write_satisfied_compliance(child, "child")
        outcome = approve_pre_resume_after_child(
            parent,
            parent_plan_id="parent",
            child_plan_id="child",
            child_plan_dir=child,
        )
        assert outcome["override_applied"] is False
        assert outcome["memo_status"] == "satisfied"
        assert outcome["child_status"] == "satisfied"
        assert outcome["cleared"] is True
        assert pre_resume_gate_name("child") not in gate_pause.active_pre_resume_after_children(
            parent
        )


# ──────────────────────────────  read_child_compliance  ──────────────────────────────


class TestReadChildCompliance:
    def test_returns_dict_when_present(self, tmp_path):
        child = _bare_plan_dir(tmp_path, "child")
        _write_satisfied_compliance(child, "child")
        data = read_child_compliance(child, "child")
        assert data is not None
        assert data["return_condition_status"] == "satisfied"

    def test_returns_none_when_missing(self, tmp_path):
        child = _bare_plan_dir(tmp_path, "child")
        assert read_child_compliance(child, "child") is None

    def test_returns_none_on_malformed_json(self, tmp_path):
        child = _bare_plan_dir(tmp_path, "child")
        p = child_compliance_side_car_path(child, "child")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("not json at all")
        assert read_child_compliance(child, "child") is None


# ──────────────────────────────  CLI: bare-resume discipline  ──────────────────────────────


class TestResumeBareResumeDiscipline:
    def test_resume_gate_pre_resume_after_child_refuses(self, tmp_path, capsys):
        """KEY VERIFICATION: resume --gate pre_resume_after_child:CHILD must
        refuse with exit 2 and direct operator to the validating approve form."""
        parent = _make_plan_dir(tmp_path, "2026-05-02-099-feat-rparent")
        gate_pause.add_pre_resume_after_child(
            parent, "child", plan_id="2026-05-02-099-feat-rparent"
        )
        rc = cli_mod.main(
            [
                "resume",
                str(parent),
                "--gate",
                pre_resume_gate_name("child"),
            ]
        )
        assert rc == 2
        captured = capsys.readouterr()
        assert "REFUSED" in captured.err
        assert "approve" in captured.err
        assert "--child" in captured.err
        # Gate state untouched.
        assert pre_resume_gate_name("child") in gate_pause.active_pre_resume_after_children(parent)

    def test_resume_all_does_not_clear_pre_resume_via_cli(self, tmp_path, capsys):
        parent = _make_plan_dir(tmp_path, "2026-05-02-099-feat-rallparent")
        gate_pause.add_pre_resume_after_child(
            parent, "child", plan_id="2026-05-02-099-feat-rallparent"
        )
        rc = cli_mod.main(
            [
                "resume",
                str(parent),
                "--all",
            ]
        )
        # resume --all clears pre_impl, but pre_resume gates persist.
        assert rc == 0
        assert pre_resume_gate_name("child") in gate_pause.active_pre_resume_after_children(parent)


# ──────────────────────────────  CLI: approve pre_resume_after_child  ──────────────────────────────


class TestApprovePreResumeAfterChildCLI:
    def test_bare_suffix_form_refused(self, tmp_path, capsys):
        """`approve <plan> pre_resume_after_child:CHILD` (no --child flag) →
        refuse and direct to canonical form."""
        parent = _make_plan_dir(tmp_path, "2026-05-02-099-feat-bareparent")
        gate_pause.add_pre_resume_after_child(
            parent, "child", plan_id="2026-05-02-099-feat-bareparent"
        )
        rc = cli_mod.main(
            [
                "approve",
                str(parent),
                pre_resume_gate_name("child"),
            ]
        )
        assert rc == 2
        captured = capsys.readouterr()
        assert "--child" in captured.err

    def test_missing_memo_prints_template(self, tmp_path, capsys):
        parent = _make_plan_dir(tmp_path, "2026-05-02-099-feat-tplparent")
        child = _make_plan_dir(tmp_path, "2026-05-02-099-feat-tplchild")
        gate_pause.add_pre_resume_after_child(
            parent, "2026-05-02-099-feat-tplchild", plan_id="2026-05-02-099-feat-tplparent"
        )
        _write_satisfied_compliance(child, "2026-05-02-099-feat-tplchild")
        rc = cli_mod.main(
            [
                "approve",
                str(parent),
                "pre_resume_after_child",
                "--child",
                "2026-05-02-099-feat-tplchild",
            ]
        )
        assert rc == 2
        captured = capsys.readouterr()
        assert "fan-in memo missing" in captured.err
        assert "## Return Condition" in captured.err

    def test_clean_path_via_cli_clears_gate(self, tmp_path, capsys):
        parent = _make_plan_dir(tmp_path, "2026-05-02-099-feat-cleanparent")
        child = _make_plan_dir(tmp_path, "2026-05-02-099-feat-cleanchild")
        gate_pause.add_pre_resume_after_child(
            parent,
            "2026-05-02-099-feat-cleanchild",
            plan_id="2026-05-02-099-feat-cleanparent",
        )
        _write_satisfied_compliance(child, "2026-05-02-099-feat-cleanchild")
        _write_satisfied_fan_in_memo(parent, "2026-05-02-099-feat-cleanchild")
        rc = cli_mod.main(
            [
                "approve",
                str(parent),
                "pre_resume_after_child",
                "--child",
                "2026-05-02-099-feat-cleanchild",
            ]
        )
        assert rc == 0
        # Gate cleared.
        assert pre_resume_gate_name(
            "2026-05-02-099-feat-cleanchild"
        ) not in gate_pause.active_pre_resume_after_children(parent)
        # INBOX recorded.
        events = inbox.read_events(parent)
        cleared = [e for e in events if e.event == "gate_cleared"]
        assert len(cleared) == 1
        assert "2026-05-02-099-feat-cleanchild" in cleared[0].body

    def test_blocked_child_refused_without_override(self, tmp_path, capsys):
        parent = _make_plan_dir(tmp_path, "2026-05-02-099-feat-blockparent")
        child = _make_plan_dir(tmp_path, "2026-05-02-099-feat-blockchild")
        gate_pause.add_pre_resume_after_child(
            parent,
            "2026-05-02-099-feat-blockchild",
            plan_id="2026-05-02-099-feat-blockparent",
        )
        _write_non_satisfied_compliance(child, "2026-05-02-099-feat-blockchild", "blocked")
        _write_satisfied_fan_in_memo(parent, "2026-05-02-099-feat-blockchild")
        rc = cli_mod.main(
            [
                "approve",
                str(parent),
                "pre_resume_after_child",
                "--child",
                "2026-05-02-099-feat-blockchild",
            ]
        )
        assert rc == 2
        captured = capsys.readouterr()
        assert "REFUSED" in captured.err
        assert "blocked" in captured.err

    def test_blocked_child_override_clears_gate(self, tmp_path, capsys):
        """KEY VERIFICATION: --accept-non-satisfied clears with status=blocked,
        and INBOX records the override."""
        parent = _make_plan_dir(tmp_path, "2026-05-02-099-feat-ovparent")
        child = _make_plan_dir(tmp_path, "2026-05-02-099-feat-ovchild")
        gate_pause.add_pre_resume_after_child(
            parent,
            "2026-05-02-099-feat-ovchild",
            plan_id="2026-05-02-099-feat-ovparent",
        )
        _write_non_satisfied_compliance(child, "2026-05-02-099-feat-ovchild", "blocked")
        _write_satisfied_fan_in_memo(parent, "2026-05-02-099-feat-ovchild")
        rc = cli_mod.main(
            [
                "approve",
                str(parent),
                "pre_resume_after_child",
                "--child",
                "2026-05-02-099-feat-ovchild",
                "--accept-non-satisfied",
            ]
        )
        assert rc == 0
        # INBOX records override.
        events = inbox.read_events(parent)
        cleared = [e for e in events if e.event == "gate_cleared"]
        assert any("OVERRIDE" in e.body for e in cleared)


# ──────────────────────────────  Hermetic synthetic parent/child e2e  ──────────────────────────────


class TestHermeticSyntheticE2E:
    def test_full_lifecycle(self, tmp_path):
        """End-to-end: simulate child dispatch (arm gate via supervisor helper),
        verify INBOX entry idempotent, child writes compliance side-car +
        return_to_parent event, operator authors fan-in memo, operator
        approves via CLI, parent's gate clears.
        """
        from dontpanic_orchestrate import supervisor

        parent_plan_id = "2026-05-02-099-feat-e2eparent"
        child_plan_id = "2026-05-02-099-feat-e2echild"
        parent = _make_plan_dir(tmp_path, parent_plan_id)
        child_orchestration = (
            f"orchestration:\n"
            f"  parent_plan_id: {parent_plan_id}\n"
            f"  spawn_reason: operator_manual\n"
            f"  depth_limit: 3\n"
        )
        child = _make_plan_dir(
            tmp_path,
            child_plan_id,
            orchestration_block=child_orchestration,
        )

        # Step 1: simulate child dispatch — invoke the supervisor's gate-arm
        # helper directly (avoids running real volleys).
        from dontpanic_orchestrate import plan_loader

        loaded_child = plan_loader.load(child)
        supervisor._arm_parent_pre_resume_gate_for_child(loaded_child)

        # Re-invoke to verify idempotence on INBOX + gate.
        supervisor._arm_parent_pre_resume_gate_for_child(loaded_child)

        # Gate is armed exactly once.
        assert gate_pause.active_pre_resume_after_children(parent) == [
            pre_resume_gate_name(child_plan_id)
        ]

        # INBOX has a single nested_child_pending entry.
        events = inbox.read_events(parent)
        nested_pending = [e for e in events if e.event == "nested_child_pending"]
        assert len(nested_pending) == 1
        assert child_plan_id in nested_pending[0].body

        # events.jsonl on parent has spawn_child entries (best-effort —
        # both invocations recorded).
        log = events_log_path(parent)
        assert log.is_file()
        spawn_entries = [json.loads(line) for line in log.read_text().strip().split("\n") if line]
        assert all(e["kind"] == "volley.spawn_child" for e in spawn_entries)
        assert spawn_entries[0]["child_plan_id"] == child_plan_id
        assert spawn_entries[0]["parent_plan_id"] == parent_plan_id

        # Step 2: simulate child signoff — write compliance side-car directly
        # (F002 path).
        _write_satisfied_compliance(child, child_plan_id)

        # Step 3: operator authors fan-in memo with status=satisfied.
        _write_satisfied_fan_in_memo(parent, child_plan_id)

        # Step 4: operator approves via CLI.
        rc = cli_mod.main(
            [
                "approve",
                str(parent),
                "pre_resume_after_child",
                "--child",
                child_plan_id,
            ]
        )
        assert rc == 0

        # Step 5: gate cleared on parent; parent dispatch is no longer paused
        # by this gate.
        assert pre_resume_gate_name(
            child_plan_id
        ) not in gate_pause.active_pre_resume_after_children(parent)
        # INBOX has gate_cleared entry referencing the child.
        events_after = inbox.read_events(parent)
        cleared = [e for e in events_after if e.event == "gate_cleared"]
        assert len(cleared) == 1
        assert child_plan_id in cleared[0].body
        # events.jsonl has the approve event too.
        approve_events = [json.loads(line) for line in log.read_text().strip().split("\n") if line]
        return_events = [
            e for e in approve_events if e["kind"] == "volley.return_to_parent_approved"
        ]
        assert len(return_events) == 1
        assert return_events[0]["child_plan_id"] == child_plan_id
        assert return_events[0]["override_applied"] is False


# ──────────────────────────────  Canonical state primacy (D006)  ──────────────────────────────


class TestCanonicalStatePrimacy:
    def test_events_deletion_does_not_block_approve(self, tmp_path):
        """KEY VERIFICATION (D006): with events.jsonl deleted on both parent
        and child mid-flow, the approve still succeeds because canonical
        state (gate-state + child compliance side-car) carries everything."""
        parent = _bare_plan_dir(tmp_path, "parent")
        child = _bare_plan_dir(tmp_path, "child")
        gate_pause.add_pre_resume_after_child(parent, "child", plan_id="parent")
        _write_satisfied_compliance(child, "child")
        _write_satisfied_fan_in_memo(parent, "child")
        # Write some events first then delete.
        record_event(parent, "volley.spawn_child", {"x": 1}, plan_id="parent")
        record_event(child, "volley.return_to_parent", {"y": 2}, plan_id="child")
        events_log_path(parent).unlink()
        events_log_path(child).unlink()
        # Approve still works.
        outcome = approve_pre_resume_after_child(
            parent,
            parent_plan_id="parent",
            child_plan_id="child",
            child_plan_dir=child,
        )
        assert outcome["cleared"] is True

    def test_events_unwritable_does_not_block_approve(self, tmp_path, monkeypatch):
        """events.jsonl write failure during approve does NOT prevent the
        gate from clearing. Canonical state lands; trace is best-effort."""
        parent = _bare_plan_dir(tmp_path, "parent")
        child = _bare_plan_dir(tmp_path, "child")
        gate_pause.add_pre_resume_after_child(parent, "child", plan_id="parent")
        _write_satisfied_compliance(child, "child")
        _write_satisfied_fan_in_memo(parent, "child")

        def _raising_open(*args, **kwargs):
            raise OSError("simulated")

        # Patch only Path.open to fail; this affects record_event's append
        # but NOT gate_pause/inbox file writes (they use Path.write_text
        # / explicit f.write inside `with path.open(...)`).
        # Easier: just monkeypatch record_event itself to simulate failure.
        from dontpanic_orchestrate import nested_orchestration as nested

        def _failing_record(*args, **kwargs):
            return False

        monkeypatch.setattr(nested, "record_event", _failing_record)
        # Approve still works; record_event being a no-op is fine.
        outcome = approve_pre_resume_after_child(
            parent,
            parent_plan_id="parent",
            child_plan_id="child",
            child_plan_dir=child,
        )
        assert outcome["cleared"] is True


# ──────────────────────────────  signoff_writer F003 trace  ──────────────────────────────


class TestSignoffWriterReturnToParentTrace:
    """When a child plan signs off, signoff_writer records a best-effort
    volley.return_to_parent event on the child's events.jsonl. F003-only;
    top-level plans (no orchestration) skip this entirely."""

    def _stage_audit(self, plan_dir, plan_id):
        audit = {
            "task_id": plan_id,
            "audit_id": f"{plan_id}#claude#0",
            "agent": "claude",
            "agent_role": "implementer",
            "iteration": 0,
            "decided_at": "2026-05-02T20:00:00Z",
            "audit_status": "signed_off",
            "feature_id": "F001",
            "summary": "synthetic stub",
            "validation_performed": ["stub"],
            "blocking_findings": [],
            "non_blocking_findings": [],
            "patch_completeness": "complete",
            "next_action": "merge",
        }
        adir = plan_dir / "audit"
        adir.mkdir(parents=True, exist_ok=True)
        path = adir / "claude-implementer-F001-i0.json"
        path.write_text(json.dumps(audit))
        return path

    def test_child_signoff_records_return_to_parent_event(self, tmp_path):
        from dontpanic_orchestrate import signoff_writer

        plan_id = "2026-05-02-099-feat-rtpchild"
        plan_dir = tmp_path / plan_id
        plan_dir.mkdir()
        audit_path = self._stage_audit(plan_dir, plan_id)

        # Simulate F001 Orchestration model: a tiny shim with parent_plan_id.
        class _Stub:
            parent_plan_id = "2026-05-02-099-feat-rtpparent"

        signoff_writer.write_signoff(
            plan_id=plan_id,
            tier="trivial",
            iteration=0,
            agents_in_panel=["claude"],
            audit_paths=[audit_path],
            plan_dir=plan_dir,
            volley_status="signed_off",
            orchestration=_Stub(),
        )
        # events.jsonl on the child has a volley.return_to_parent entry.
        log = events_log_path(plan_dir)
        assert log.is_file()
        entries = [json.loads(line) for line in log.read_text().strip().split("\n") if line]
        rtp = [e for e in entries if e["kind"] == "volley.return_to_parent"]
        assert len(rtp) == 1
        assert rtp[0]["child_plan_id"] == plan_id
        assert rtp[0]["parent_plan_id"] == "2026-05-02-099-feat-rtpparent"

    def test_top_level_signoff_does_not_record_return_event(self, tmp_path):
        """Top-level plans (orchestration=None) MUST NOT emit a
        return_to_parent trace."""
        from dontpanic_orchestrate import signoff_writer

        plan_id = "2026-05-02-099-feat-toplevelsignoff"
        plan_dir = tmp_path / plan_id
        plan_dir.mkdir()
        audit_path = self._stage_audit(plan_dir, plan_id)
        signoff_writer.write_signoff(
            plan_id=plan_id,
            tier="trivial",
            iteration=0,
            agents_in_panel=["claude"],
            audit_paths=[audit_path],
            plan_dir=plan_dir,
            volley_status="signed_off",
        )
        log = events_log_path(plan_dir)
        assert not log.is_file() or log.read_text() == ""
