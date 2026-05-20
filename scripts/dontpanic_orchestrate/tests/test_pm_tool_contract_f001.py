"""Plan 2026-05-20-001 F001 — PM-tool category contract tests.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_pm_tool_contract_f001.py

Coverage targets (acceptance ≥10 cases):

- PMIssue round-trip + frozen invariant + extra='forbid'.
- PMToolMappingConfig validators: happy path, missing PMStatus value,
  duplicate (case-insensitive) status label, missing required field
  path, operator-extras passthrough.
- translate_status / reverse_translate_status case-insensitive +
  unmapped errors.
- LinearPMTool wired to LinearPPAdapter: read_issue happy path with
  stub subprocess factory, push_status dry-run produces PENDING + no
  subprocess invocation, push_status PUSHED on mock success,
  push_status FAILED when subprocess raises, URI-scheme rejection.
- LinearPPAdapter boundary invariants: mutating tool hard-rejected
  on generic call_tool, push_status routes 'issueUpdate' through
  the explicit codepath, redact + sanitize annotations appear on
  every response, SanitizationFailed raised on surviving secrets.
- ExternalSyncRecord rejects naive datetime.
- Helper factories preserve invariants.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.integrations.linear_pm_tool import LinearPMTool  # noqa: E402
from dontpanic_orchestrate.integrations.linear_pp_adapter import (  # noqa: E402
    LinearPPAdapter,
    MutationRejected,
    SanitizationFailed,
    redact_and_sanitize,
)
from dontpanic_orchestrate.integrations.pm_tool_mapping import (  # noqa: E402
    PMToolMappingConfig,
    load_mapping_config,
)
from dontpanic_orchestrate.integrations.pm_tool_models import (  # noqa: E402
    PMComment,
    PMIssue,
    PMProject,
    PMStatus,
)
from dontpanic_orchestrate.integrations.pm_tool_sync import (  # noqa: E402
    ExternalSyncRecord,
    ExternalSyncStatus,
    make_failed_record,
    make_pending_record,
    make_pushed_record,
)


# ───────────────────────────  helpers / fixtures  ───────────────────────────


def _valid_mapping_payload() -> dict:
    return {
        "service_name": "linear",
        "uri_scheme": "linear",
        "field_name_map": {
            "PMIssue.id": "id",
            "PMIssue.project_id": "team.id",
            "PMIssue.title": "title",
            "PMIssue.status": "state.name",
            "PMIssue.uri": "url",
        },
        "status_enum_map": {
            "Triage": "backlog",
            "Backlog": "backlog",
            "Todo": "active",
            "In Progress": "in_progress",
            "Done": "done",
            "Cancelled": "cancelled",
        },
        "push_status_tool": "issueUpdate",
        "read_issue_tool": "issue",
    }


def _vendor_issue_payload() -> dict:
    return {
        "id": "ISSUE-123",
        "title": "Ship F001 contract",
        "state": {"name": "In Progress"},
        "team": {"id": "TEAM-7"},
        "url": "https://example.com/issue/ISSUE-123",
    }


class _FakePipe:
    """Minimal stdin/stdout fake — enough for LinearPPAdapter._send_and_receive."""

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self._lines: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def flush(self) -> None:
        pass

    def queue_line(self, line: bytes) -> None:
        self._lines.append(line)

    def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""


class _FakeProc:
    """Stand-in for subprocess.Popen[bytes] — tests inject one per case."""

    def __init__(self, responses: list[dict] | None = None, raise_on_send: Exception | None = None) -> None:
        self.stdin = _FakePipe()
        self.stdout = _FakePipe()
        self._responses = responses or []
        self._raise = raise_on_send
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def poll(self) -> int | None:
        return None if not self.closed else 0

    def _emit_next(self) -> None:
        if self._raise is not None:
            raise self._raise
        if not self._responses:
            return
        payload = self._responses.pop(0)
        envelope = {"jsonrpc": "2.0", "id": 1, "result": payload}
        self.stdout.queue_line((json.dumps(envelope) + "\n").encode("utf-8"))


def _make_adapter(proc: _FakeProc) -> LinearPPAdapter:
    """Construct a LinearPPAdapter whose subprocess_factory returns ``proc``."""

    # Patch _FakePipe to drive _emit_next when write() is called so the
    # test's queued response is available when stdout.readline() runs.
    original_write = proc.stdin.write

    def write_then_emit(data: bytes) -> None:
        original_write(data)
        proc._emit_next()

    proc.stdin.write = write_then_emit  # type: ignore[method-assign]

    return LinearPPAdapter(
        binary_path=Path("/nonexistent/pp-binary"),
        subprocess_factory=lambda _path: proc,  # type: ignore[arg-type]
    )


# ───────────────────────────  model tests  ───────────────────────────


def test_pmissue_round_trip_minimum_fields():
    """Case 1: PMIssue with v0-minimum fields validates + round-trips."""
    issue = PMIssue(
        id="ISSUE-1",
        project_id="TEAM-1",
        title="Ship the bridge",
        status=PMStatus.IN_PROGRESS,
        uri="linear://issue/ISSUE-1",
    )
    payload = issue.model_dump()
    restored = PMIssue.model_validate(payload)
    assert restored == issue


def test_pmissue_is_frozen():
    """Case 2: PMIssue is frozen — mutating an attribute raises."""
    issue = PMIssue(
        id="x", project_id="p", title="t", status=PMStatus.BACKLOG, uri="linear://issue/x"
    )
    with pytest.raises(ValidationError):
        issue.title = "tampered"  # type: ignore[misc]


def test_pmissue_rejects_unknown_field():
    """Case 3: extra='forbid' rejects vendor-specific concepts leaking in."""
    with pytest.raises(ValidationError):
        PMIssue.model_validate({
            "id": "x",
            "project_id": "p",
            "title": "t",
            "status": "backlog",
            "uri": "linear://issue/x",
            "vendor_concept": "shouldn't leak through",
        })


def test_pmproject_and_pmcomment_basic_shape():
    """Case 4: PMProject + PMComment validate at v0 minimum."""
    project = PMProject(id="TEAM-1", name="DontPanic Core", uri="linear://project/TEAM-1")
    comment = PMComment(
        id="C-1",
        author_id="USER-9",
        body="LGTM",
        created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert project.uri.startswith("linear://")
    assert comment.body == "LGTM"


# ───────────────────────────  mapping config tests  ───────────────────────────


def test_mapping_happy_path_validates():
    """Case 5: a well-formed mapping config validates."""
    config = load_mapping_config(_valid_mapping_payload())
    assert config.service_name == "linear"
    assert config.translate_status("in progress") is PMStatus.IN_PROGRESS
    assert config.reverse_translate_status(PMStatus.DONE) == "Done"


def test_mapping_rejects_missing_pmstatus_member():
    """Case 6: validator rejects a status_enum_map missing PMStatus members."""
    payload = _valid_mapping_payload()
    payload["status_enum_map"] = {
        "Todo": "active",
        "In Progress": "in_progress",
        "Done": "done",
    }
    with pytest.raises(ValidationError) as exc:
        load_mapping_config(payload)
    text = str(exc.value)
    assert "backlog" in text and "cancelled" in text


def test_mapping_rejects_case_insensitive_duplicate_status_labels():
    """Case 7: case-insensitive duplicate status keys are rejected."""
    payload = _valid_mapping_payload()
    payload["status_enum_map"] = {
        "Triage": "backlog",
        "Todo": "active",
        "In Progress": "in_progress",
        "in progress": "active",
        "Done": "done",
        "Cancelled": "cancelled",
    }
    with pytest.raises(ValidationError) as exc:
        load_mapping_config(payload)
    assert "duplicate" in str(exc.value).lower()


def test_mapping_rejects_missing_required_field_path():
    """Case 8: field_name_map missing a REQUIRED path is rejected."""
    payload = _valid_mapping_payload()
    del payload["field_name_map"]["PMIssue.status"]
    with pytest.raises(ValidationError) as exc:
        load_mapping_config(payload)
    assert "PMIssue.status" in str(exc.value)


def test_translate_status_raises_on_unmapped_label():
    """Case 9: translate_status fails loud on a vendor label not in the map."""
    config = load_mapping_config(_valid_mapping_payload())
    with pytest.raises(KeyError):
        config.translate_status("Doing the Thing")


def test_mapping_allows_operator_extras():
    """Case 10: pp_version / api_key_env keys pass through silently."""
    payload = _valid_mapping_payload()
    payload["pp_version"] = "v0.4.2"
    payload["api_key_env"] = "VENDOR_TOKEN"
    config = load_mapping_config(payload)
    assert config.service_name == "linear"


# ───────────────────────────  linear wrapper tests (PP-adapter wired) ─────


def test_linear_read_issue_happy_path_via_pp_adapter():
    """Case 11: LinearPMTool.read_issue routes through LinearPPAdapter."""
    config = load_mapping_config(_valid_mapping_payload())
    proc = _FakeProc(responses=[_vendor_issue_payload()])
    adapter = _make_adapter(proc)

    wrapper = LinearPMTool(mapping=config, pp_adapter=adapter)
    issue = wrapper.read_issue("linear://issue/ISSUE-123")

    assert issue.id == "ISSUE-123"
    assert issue.project_id == "TEAM-7"
    assert issue.status is PMStatus.IN_PROGRESS
    assert issue.title == "Ship F001 contract"
    # Confirm we hit the subprocess seam once.
    assert len(proc.stdin.written) == 1
    sent = json.loads(proc.stdin.written[0].decode("utf-8"))
    assert sent["params"]["name"] == "issue"
    assert sent["params"]["arguments"] == {"issue_id": "ISSUE-123"}


def test_linear_push_status_dry_run_produces_pending_no_subprocess_call():
    """Case 12: dry_run=True yields PENDING + no subprocess interaction."""
    config = load_mapping_config(_valid_mapping_payload())
    proc = _FakeProc(responses=[])
    adapter = _make_adapter(proc)

    wrapper = LinearPMTool(mapping=config, pp_adapter=adapter)
    record = wrapper.push_status(
        uri="linear://issue/ISSUE-123",
        new_status=PMStatus.DONE,
        dry_run=True,
    )
    assert record.status is ExternalSyncStatus.PENDING
    assert record.intended_status is PMStatus.DONE
    assert record.ref_uri == "linear://issue/ISSUE-123"
    assert record.response is not None
    assert record.response["tool"] == "issueUpdate"
    assert record.response["arguments"] == {"issue_id": "ISSUE-123", "status": "Done"}
    # Subprocess was never invoked.
    assert proc.stdin.written == []


def test_linear_push_status_pushed_on_subprocess_success():
    """Case 13: live mode invokes PP adapter push_status + returns PUSHED."""
    config = load_mapping_config(_valid_mapping_payload())
    proc = _FakeProc(responses=[{"success": True, "updated_at": "2026-05-20T12:00:00Z"}])
    adapter = _make_adapter(proc)

    wrapper = LinearPMTool(mapping=config, pp_adapter=adapter)
    record = wrapper.push_status(
        uri="linear://issue/ISSUE-7",
        new_status=PMStatus.DONE,
        dry_run=False,
    )
    assert record.status is ExternalSyncStatus.PUSHED
    assert record.response is not None
    assert record.response["success"] is True
    # PP adapter annotated the response with redact + sanitize boundaries.
    assert record.response["_redact_level"] == "internal"
    assert record.response["_sanitized_at"] == "adapter_response_boundary"
    assert record.error is None


def test_linear_push_status_failed_on_subprocess_exception():
    """Case 14: subprocess exception produces a FAILED record (never silent)."""
    config = load_mapping_config(_valid_mapping_payload())
    proc = _FakeProc(raise_on_send=ConnectionError("vendor 503"))
    adapter = _make_adapter(proc)

    wrapper = LinearPMTool(mapping=config, pp_adapter=adapter)
    record = wrapper.push_status(
        uri="linear://issue/ISSUE-7",
        new_status=PMStatus.DONE,
        dry_run=False,
    )
    assert record.status is ExternalSyncStatus.FAILED
    assert record.error is not None
    assert "vendor 503" in record.error
    assert record.response is None


def test_linear_rejects_uri_with_wrong_scheme():
    """Case 15: cross-service URI cannot accidentally hit the wrong wrapper."""
    config = load_mapping_config(_valid_mapping_payload())
    adapter = _make_adapter(_FakeProc())
    wrapper = LinearPMTool(mapping=config, pp_adapter=adapter)
    with pytest.raises(ValueError):
        wrapper.read_issue("jira://issue/ABC-1")


def test_linear_from_config_path_round_trip(tmp_path):
    """Case 16: from_config_path loads a JSON file end-to-end."""
    payload = _valid_mapping_payload()
    payload["pp_version"] = "v0.4.2"
    config_file = tmp_path / "linear.json"
    config_file.write_text(json.dumps(payload), encoding="utf-8")

    proc = _FakeProc(responses=[_vendor_issue_payload()])
    adapter = _make_adapter(proc)
    wrapper = LinearPMTool.from_config_path(pp_adapter=adapter, config_path=config_file)
    assert wrapper.mapping.service_name == "linear"
    issue = wrapper.read_issue("linear://issue/ISSUE-123")
    assert issue.id == "ISSUE-123"


# ───────────────────────────  PP-adapter boundary tests  ──────────────────


def test_pp_adapter_rejects_mutating_tool_on_generic_call_tool():
    """Case 17: read-only proxy hard-rejects MUTATING_TOOLS by name."""
    adapter = _make_adapter(_FakeProc())
    with pytest.raises(MutationRejected):
        adapter.call_tool("issueUpdate", {"issue_id": "X"})


def test_pp_adapter_push_status_only_allows_issueupdate():
    """Case 18: the explicit mutation codepath refuses other tool names."""
    adapter = _make_adapter(_FakeProc())
    with pytest.raises(MutationRejected):
        adapter.push_status("issueArchive", {"issue_id": "X"})


def test_pp_adapter_response_carries_redact_and_sanitize_annotations():
    """Case 19: every response that crosses the boundary is annotated.

    F002's plan-close walker reads these annotations to confirm the
    middleware actually ran; absence is a hard failure signal.
    """
    proc = _FakeProc(responses=[{"id": "ISSUE-9", "title": "OK"}])
    adapter = _make_adapter(proc)
    result = adapter.call_tool("issue", {"issue_id": "ISSUE-9"})
    assert result["_redact_level"] == "internal"
    assert result["_redacted_at"] == "adapter_response_boundary"
    assert result["_sanitized_at"] == "adapter_response_boundary"
    assert result["_sanitizer_redact_level"] == "internal"


def test_pp_adapter_sanitizer_fails_closed_on_secret_shaped_substring():
    """Case 20: a bearer-token-shaped substring surviving redact triggers
    SanitizationFailed before the payload reaches the caller."""
    with pytest.raises(SanitizationFailed):
        redact_and_sanitize(
            {"body": "Authorization: Bearer abcdefghij0123456789klmno"},
            level="internal",
        )


# ───────────────────────────  sync record tests  ───────────────────────────


def test_external_sync_record_rejects_naive_datetime():
    """Case 21: naive datetimes can't sneak into evidence rows."""
    with pytest.raises(ValidationError):
        ExternalSyncRecord(
            ref_uri="linear://issue/x",
            kind="pm_issue",
            attempted_at=datetime(2026, 5, 20),
            status=ExternalSyncStatus.PENDING,
        )


def test_helper_factories_produce_consistent_records():
    """Case 22: make_* helpers preserve invariants (status / error / response polarity)."""
    pushed = make_pushed_record(
        ref_uri="linear://issue/x",
        kind="pm_issue",
        intended_status=PMStatus.DONE,
        response={"ok": True},
    )
    failed = make_failed_record(
        ref_uri="linear://issue/x",
        kind="pm_issue",
        intended_status=PMStatus.DONE,
        error="timeout",
    )
    pending = make_pending_record(
        ref_uri="linear://issue/x",
        kind="pm_issue",
        intended_status=PMStatus.DONE,
    )

    assert pushed.status is ExternalSyncStatus.PUSHED
    assert pushed.error is None and pushed.response == {"ok": True}
    assert failed.status is ExternalSyncStatus.FAILED
    assert failed.error == "timeout" and failed.response is None
    assert pending.status is ExternalSyncStatus.PENDING
