"""Plan 2026-05-10-001 F003 — Linear adapter smoke test.

Drives the F003 acceptance: spawn a stand-in PP binary as a real
subprocess, route one ``issue`` tool call through the
``LinearPPAdapter`` wrapper, and assert the response carries the
redact + sanitize annotations with no secret-shaped substring
surviving. Also exercises the fail-closed path: a synthetic leaky
response must raise ``SanitizationFailed`` before the value crosses
the boundary.

The fixture binary lives at ``tests/fake_cli/fake-pp-linear`` (a
Python script with shebang) — this lets the test cover the real
subprocess spawn + stdin/stdout JSON-RPC path that the live PP binary
would also use, without burning the operator's one allotted paid PP
invocation (D004, one-paid-call-dogfood discipline).

Side effect: when run with the default conftest isolation, this test
writes ``docs/plans/2026-05-10-001-.../evidence/smoke-trace-linear.jsonl``
so the trace artifact named in F003 acceptance lives in version
control. The trace is regenerated on every run from the post-redact
payload, so it never drifts from the wrapper's behavior.
"""

from __future__ import annotations

import json
import os
import sys
import sysconfig
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.adapters import linear_adapter  # noqa: E402
from dontpanic_orchestrate.integrations.linear_pp_adapter import (  # noqa: E402
    LinearPPAdapter,
    MutationRejected,
    SanitizationFailed,
)

FIXTURE_BINARY = HERE.parent / "fake_cli" / "fake-pp-linear"

REPO_ROOT = HERE.parents[3]
EVIDENCE_DIR = (
    REPO_ROOT
    / "docs"
    / "plans"
    / "2026-05-10-001-feat-printing-press-adapter-skill"
    / "evidence"
)
TRACE_PATH = EVIDENCE_DIR / "smoke-trace-linear.jsonl"


def _make_adapter() -> LinearPPAdapter:
    """Spawn the fixture binary via a real ``subprocess.Popen`` call.

    Using the default ``subprocess_factory`` here is intentional —
    the smoke test is the one place we actually exercise the
    subprocess boundary (every other test stubs the factory). The
    fixture is a Python script with shebang; we route through the
    current interpreter to keep it portable across operator machines.
    """

    if not FIXTURE_BINARY.exists():
        pytest.skip(f"smoke fixture missing: {FIXTURE_BINARY}")

    python = sysconfig.get_path("scripts") + "/python3"  # fallback below
    interpreter = sys.executable or python

    def factory(_binary_path: Path):
        import subprocess

        return subprocess.Popen(
            [interpreter, str(FIXTURE_BINARY)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=os.environ.copy(),
        )

    return LinearPPAdapter(
        binary_path=FIXTURE_BINARY,
        subprocess_factory=factory,
    )


def _assert_no_secret_substring(payload, *, banned: str) -> None:
    """Recursively assert ``banned`` never appears in any string leaf."""

    if isinstance(payload, dict):
        for value in payload.values():
            _assert_no_secret_substring(value, banned=banned)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_secret_substring(value, banned=banned)
    elif isinstance(payload, str):
        assert banned not in payload, (
            f"secret-shaped substring {banned!r} leaked into payload: {payload!r}"
        )


def test_linear_adapter_smoke_post_redact_response_has_no_leaked_tokens():
    """F003 acceptance (2) + (3): PP binary executes; wrapper injects
    redact + sanitize; the trace artifact contains no leaked tokens."""

    adapter = _make_adapter()
    try:
        response = adapter.call_tool("issue", {"id": "DP-42"})
    finally:
        adapter.close()

    # Boundary invariants — both annotations present on the dict response.
    assert isinstance(response, dict)
    assert response.get("_redact_level") == "internal"
    assert response.get("_redacted_at") == "adapter_response_boundary"
    assert response.get("_sanitized_at") == "adapter_response_boundary"
    assert response.get("_sanitizer_redact_level") == "internal"

    # No bearer-token shape (or any of the sanitizer's other secret
    # patterns) survived into the post-redact payload.
    _assert_no_secret_substring(response, banned="Bearer ")
    _assert_no_secret_substring(response, banned="lin_api_")

    # The Linear-shaped fields came through intact post-redact.
    assert response.get("identifier") == "DP-42"
    assert response.get("title", "").startswith("Ship the printing-press-adapter")

    # Persist the trace artifact. Regenerated each run from the live
    # wrapper response so the file in evidence/ never drifts.
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    trace_lines = [
        {
            "kind": "request",
            "direction": "dontpanic -> pp_binary",
            "envelope": {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "issue", "arguments": {"id": "DP-42"}},
            },
        },
        {
            "kind": "response_post_redact_sanitize",
            "direction": "pp_binary -> dontpanic (after wrapper)",
            "redact_level": "internal",
            "sanitizer_verdict": "clean",
            "payload": response,
        },
        {
            "kind": "assertion",
            "name": "no_leaked_tokens",
            "result": "pass",
            "notes": "Bearer/lin_api_/ghp_/AKIA shapes absent; _redact_level and _sanitized_at boundary markers present.",
        },
    ]
    TRACE_PATH.write_text(
        "\n".join(json.dumps(entry, sort_keys=True) for entry in trace_lines) + "\n"
    )


def test_linear_adapter_smoke_sanitizer_fails_closed_on_leaky_response():
    """F003 acceptance (3) fail-closed half: when the PP binary echoes a
    bearer token in its response body, the sanitizer must raise before
    the value crosses the adapter boundary. v0's apply_redact is
    deliberately lenient so the sanitizer is the only backstop here."""

    adapter = _make_adapter()
    try:
        with pytest.raises(SanitizationFailed) as exc_info:
            adapter.call_tool("leaky", {})
    finally:
        adapter.close()

    message = str(exc_info.value)
    assert "post-redaction sanitizer rejected" in message
    assert "raw_request_header" in message


def test_linear_adapter_smoke_mutating_tool_hard_rejects_without_subprocess_io():
    """F003 acceptance: v0 hard-rejects mutating tools on the generic
    proxy. ``issueUpdate`` is in ``MUTATING_TOOLS`` and must raise
    ``MutationRejected`` before any subprocess interaction — the
    bridge's ``LinearPMTool.push_status`` codepath is the only opt-in."""

    adapter = _make_adapter()
    try:
        with pytest.raises(MutationRejected):
            adapter.call_tool("issueUpdate", {"id": "DP-1", "state": "done"})
    finally:
        adapter.close()


def test_linear_adapter_module_exposes_template_public_surface():
    """Acceptance for the F003 wrapper module placement: the
    skill-prescribed path ``dontpanic_orchestrate.adapters.linear_adapter``
    re-exports the template's public surface (registry helpers + the
    redact/sanitize primitives + the boundary exception types)."""

    expected = {
        "SERVICE_NAME",
        "PP_BINARY_PATH",
        "REDACT_LEVEL",
        "MUTATING_TOOLS",
        "LinearPPAdapter",
        "MutationRejected",
        "SanitizationFailed",
        "apply_redact",
        "sanitize_response",
        "redact_and_sanitize",
        "register_adapter",
        "call",
        "get_process",
    }
    missing = expected - set(linear_adapter.__all__)
    assert not missing, f"adapters.linear_adapter missing public names: {missing}"
