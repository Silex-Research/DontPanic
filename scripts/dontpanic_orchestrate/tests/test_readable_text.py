"""Tests for readable_text: templates, lint, redaction, and wired generators."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import prompts, readable_text as rt, readable_text_probe as probe


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


# ── redaction ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "/Users/someone/proj/file.txt",
        "/home/someone/proj",
        "mail me@example.com now",
        "id 123e4567-e89b-12d3-a456-426614174000",
        "hash 0123456789abcdef0123",
        "ghs_abcDEF123456",
        "key sk-abc123",
        "Authorization: Bearer abc.def",
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig",
        "-----BEGIN PRIVATE KEY-----",
        "host build-box.local",
    ],
)
def test_redact_masks_sensitive_values(raw: str) -> None:
    out = rt.redact(raw)
    for needle in ("someone", "@", "123e4567", "0123456789abcdef", "ghs_", "sk-", "abc.def", "eyJ", "BEGIN", "build-box"):
        assert needle not in out


def test_redact_keeps_tilde_relative_path() -> None:
    assert rt.redact("/Users/someone/proj/x") == "~/proj/x"


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
        rt.quota_entry(rt.RUNNING, "p1", "claude", "quota soft warning at 80% of weekly cap"),
        rt.quota_entry(rt.STOPPED, "p1", "codex", "quota hard limit stops the implementer: cap"),
    ]
    assert rt.lint_items(lines) == []


def test_implementer_prompt_carries_prompt_guide() -> None:
    text = prompts.implementer_prompt("p1", Path("/tmp/p"), {"id": "F1", "description": "d", "acceptance": "a"}, 0)
    assert rt.PROMPT_GUIDE in text


def test_probe_output_passes_lint_and_is_redacted(tmp_path: Path) -> None:
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "invocations.jsonl").write_text(
        json.dumps({"command": "plan lock /Users/someone/x", "result": "error", "plan": "p1"}) + "\n"
    )
    (tmp_path / "dashboard" / "event-actions.jsonl").write_text(
        json.dumps(
            {
                "band": "needs_action",
                "title": "Approval needed on p1",
                "detail": "Supervisor paused. Reference: plan `p1`, gate `pre_merge`.",
                "dedupe_key": "supervisor:gate_hit:p1:F001",
            }
        )
        + "\n"
    )
    md = probe.render(tmp_path)
    assert "/Users/" not in md
    old, new = probe.invocation_old_new({"command": "plan lock x", "result": "error", "plan": "p1"})
    ev_old, ev_new = probe.event_old_new(
        {"title": "Approval needed on p1", "detail": "gate `pre_merge`", "dedupe_key": "supervisor:gate_hit:p1:F001"}
    )
    assert rt.lint_items([new]) == []
    assert rt.lint_items([ev_new]) == []
    assert ev_new == "Blocked: job p1 — approval needed (gate pre_merge)"


def test_lint_rejects_past_tense_reason_on_running_status():
    violations = rt.lint_items(["Running: job p1 — volley started"])
    assert [v.rule for v in violations] == ["tense"]
