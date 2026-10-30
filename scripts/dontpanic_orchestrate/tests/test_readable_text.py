"""Tests for readable_text: templates, lint, the synthetic probe, and wired generators."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import prompts, readable_text as rt, readable_text_probe as probe, supervisor


def rules(items: list[str]) -> set[str]:
    return {v.rule for v in rt.lint_items(items)}


# ── templates ────────────────────────────────────────────────────────────────


def test_status_line_puts_status_first_and_orders_fields() -> None:
    line = rt.status_line(rt.BLOCKED, "p1", "approval needed", stage="s", gate="g")
    assert line == "Blocked: job p1 — approval needed (gate g, stage s)"


def test_status_line_rejects_unknown_status_and_field() -> None:
    with pytest.raises(ValueError):
        rt.status_line("Had issues", "p1", "x")
    with pytest.raises(ValueError):
        rt.status_line(rt.FAILED, "p1", "x", color="red")


@pytest.mark.parametrize(
    ("result", "status"), [("ok", "Passed"), ("error", "Failed"), ("interrupted", "Stopped")]
)
def test_invocation_status_maps_result_to_past_tense(result: str, status: str) -> None:
    assert rt.invocation_status(result, "plan lock x", "p1").startswith(f"{status}: job p1")


# ── lint: positive ───────────────────────────────────────────────────────────


def test_lint_accepts_template_output() -> None:
    items = [
        rt.rollup_item(rt.RUNNING, "p1", "volley starting", gate="g"),
        rt.rollup_item(rt.FAILED, "p2", "audit fails", gate="h"),
        rt.gate_entry(rt.BLOCKED, "p3", "pre_merge", "approval needed"),
    ]
    assert rt.lint_items(items) == []


# ── lint: negative ───────────────────────────────────────────────────────────


def test_lint_flags_status_not_first_and_unknown_status() -> None:
    assert "status-first" in rules(["job p1 is done"])
    assert "unknown-status" in rules(["Done: job p1 — ok"])


@pytest.mark.parametrize(
    "line", ["Failed: session p1 — x", "Failed: job p1 — task x", "Blocked: job p1 — check x"]
)
def test_lint_flags_mixed_vocabulary(line: str) -> None:
    assert "vocabulary" in rules([line])


def test_lint_allows_running_status_word() -> None:
    assert rt.lint_items(["Running: job p1 — volley starting"]) == []


@pytest.mark.parametrize(
    "line",
    [
        "Failed: job p1 — had issues with audit",
        "Failed: job p1 — encountered an error",
        "Blocked: job p1 — was blocked by gate",
    ],
)
def test_lint_flags_vague_or_passive_failure(line: str) -> None:
    assert "failure-verb" in rules([line])


def test_lint_flags_wrong_tense() -> None:
    assert "tense" in rules(["Running: job p1 — finished audit"])
    assert "tense" in rules(["Passed: job p1 — still running"])


def test_lint_flags_inconsistent_field_sets() -> None:
    items = ["Blocked: job a — x (gate g)", "Blocked: job b — y"]
    assert "fields" in rules(items)


# ── wired generators ─────────────────────────────────────────────────────────


def test_gate_pause_reconciliation_body_leads_with_status() -> None:
    from dontpanic_orchestrate import gate_pause

    err = gate_pause.GateStateReconciliationError(
        kind="k", plan_id="p1", persisted_state_path=Path("/tmp/x"), gate="g", stage="s", remediation="fix"
    )
    first = gate_pause.format_reconciliation_inbox_body(err).splitlines()[0]
    assert rt.lint_items([first]) == []
    assert first.startswith("Blocked: job p1")


def test_operator_console_gate_title_passes_lint() -> None:
    from types import SimpleNamespace

    from dontpanic_orchestrate import operator_console as oc

    gate = SimpleNamespace(plan_id="p1", gate_name="pre_impl", kind="pre_impl", reason="r")
    (item,) = oc.provide_gate_actions([gate])
    assert item.title == "Blocked: job p1 — approval needed (gate pre_impl)"
    assert rt.lint_items([item.title]) == []


def test_quota_entries_pass_lint() -> None:
    lines = [
        rt.quota_entry(rt.RUNNING, "p1", "agent-x", "quota soft warning at 80% of weekly cap"),
        rt.quota_entry(rt.STOPPED, "p1", "agent-y", "quota hard limit stops the implementer: cap"),
    ]
    assert rt.lint_items(lines) == []


# Guide content is restated here so an empty or reworded PROMPT_GUIDE fails.
_GUIDE_MARKERS = (
    "<Status>: job <name> — <reason>",
    "Status first",
    "fails, blocks, stops",
    "Env: and Project: lines, finding IDs and code",
)


def _assert_guide(text: str) -> None:
    assert rt.PROMPT_GUIDE.strip()
    assert rt.PROMPT_GUIDE in text
    for marker in _GUIDE_MARKERS:
        assert marker in text, marker


_FEATURE = {"id": "F1", "description": "d", "acceptance": "a"}


def test_initial_implementer_prompt_carries_guide() -> None:
    _assert_guide(prompts.implementer_prompt("p1", Path("/tmp/p"), _FEATURE, 0))


def test_retry_implementer_prompt_carries_guide(tmp_path: Path) -> None:
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"findings": []}))
    text = prompts.implementer_prompt("p1", tmp_path, _FEATURE, 1, prior_auditor_path=audit)
    assert "Prior round's auditor produced findings" in text
    _assert_guide(text)


def test_supervisor_quota_warn_emission(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(supervisor.inbox, "append_event", lambda *a, **kw: sent.append(kw))
    monkeypatch.setattr(supervisor.notify_event, "dispatch_event", lambda *a, **kw: None)
    supervisor._maybe_emit_quota_warn(tmp_path, "p1", "agent-x", 99.0, "F001")
    (event,) = sent
    body = str(event["body"])
    assert body.startswith("Running: job p1 — quota soft warning at 99.0% of weekly cap")
    assert body.endswith("(agent agent-x)")
    assert rt.lint_items([body]) == []


@pytest.mark.parametrize("role", ["implementer", "auditor"])
def test_supervisor_quota_hard_stop_body(role: str) -> None:
    body = supervisor._quota_hard_stop_body("p1", "agent-x", role, "weekly cap reached")
    assert body == f"Stopped: job p1 — quota hard limit stops the {role}: weekly cap reached (agent agent-x)"
    assert rt.lint_items([body]) == []


def test_dispatch_volley_emits_hard_stop_through_template() -> None:
    src = inspect.getsource(supervisor.dispatch_volley)
    assert src.count("body=_quota_hard_stop_body(loaded.plan_id, impl_name, \"implementer\", exc)") == 1
    assert src.count("body=_quota_hard_stop_body(loaded.plan_id, aud_name, \"auditor\", exc)") == 1
    assert "Quota hard-block" not in src


# ── lint: robustness ─────────────────────────────────────────────────────────


def test_lint_reports_none_instead_of_raising() -> None:
    violations = rt.lint_items([None, "Passed: job p1 — gate passes"])  # type: ignore[list-item]
    assert [(v.index, v.rule) for v in violations] == [(0, "not-text")]


@pytest.mark.parametrize("line", ["Passed: nonsense", "Passed: job p1", "Blocked: job  — x"])
def test_lint_flags_missing_job_shape(line: str) -> None:
    assert "shape" in rules([line])


# ── probe (synthetic) ────────────────────────────────────────────────────────


def test_probe_has_20_synthetic_records_each_and_says_so() -> None:
    assert len(probe.SYNTHETIC_INVOCATIONS) == 20
    assert len(probe.SYNTHETIC_EVENTS) == 20
    md = probe.render()
    assert "These records are synthetic." in md
    for leak in ("/Users/", "/home/", "~/", "@"):
        assert leak not in md


def test_probe_new_lines_pass_lint() -> None:
    rows = [probe.invocation_old_new(r) for r in probe.SYNTHETIC_INVOCATIONS]
    rows += [probe.event_old_new(r) for r in probe.SYNTHETIC_EVENTS]
    mapped = [new for _, new in rows if new is not None]
    assert len(mapped) >= 30
    for line in mapped:
        assert rt.lint_items([line]) == [], line


def test_help_and_listing_calls_are_not_jobs() -> None:
    assert rt.invocation_status("ok", "plan lock --help") is None
    assert probe.invocation_old_new({"command": "projects list", "result": "ok"})[1] is None
    assert rt.invocation_status("ok", "plan lock x", "p1") == "Passed: job p1 — plan lock passes"


@pytest.mark.parametrize(
    ("final", "expected"),
    [
        ("signed_off", "Passed: job p1 — audit signs off"),
        ("merged", "Merged: job p1 — pull request merges into main"),
        ("stopped_cap", "Stopped: job p1 — volley stops: cap"),
        ("blocked", "Blocked: job p1 — audit blocks"),
        ("failed", "Failed: job p1 — volley fails"),
    ],
)
def test_terminal_outcomes_map_explicitly(final: str, expected: str) -> None:
    rec = probe._terminal("p1", final, 2)
    assert probe.event_old_new(rec)[1] == expected


def test_unknown_outcome_and_kind_are_left_as_is() -> None:
    assert rt.terminal_status("stopped_some_new_reason") is None
    assert probe.event_old_new(probe._terminal("p1", "stopped_some_new_reason", 1))[1] is None
    unknown = {"title": "x", "detail": "y", "dedupe_key": "supervisor:verdict_mismatch:p1:F001"}
    assert probe.event_old_new(unknown)[1] is None
    assert probe.UNMAPPED in probe.render([], [unknown])


def test_gate_hit_maps_to_blocked_with_gate_field() -> None:
    _, new = probe.event_old_new(probe._gate("p1", "pre_merge"))
    assert new == "Blocked: job p1 — approval needed (gate pre_merge)"


def test_lint_rejects_past_tense_reason_on_running_status():
    violations = rt.lint_items(["Running: job p1 — volley started"])
    assert [v.rule for v in violations] == ["tense"]
