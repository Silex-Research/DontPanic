"""Plan 2026-05-30-001 F002 — ``dontpanic agent`` surface + ``orchestrate`` gateway.

Covers the machine agent surface (brief / status / setup / register-worker),
the orchestrate teaching gateway + forwarding, and the manifest's
supported_commands update. No test invokes a real agent CLI (acceptance #9):
the executor registry is read for classification only, and the one path that
would dispatch (`orchestrate <plan> --confirm`) mocks
``supervisor.dispatch_volley`` so no subprocess is spawned.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f002_agent_surface_cli.py
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))
# The sibling test module supplies the synthetic-plan helper reused by the
# orchestrate forwarding tests; put the tests dir on the path to import it.
sys.path.insert(0, str(HERE.parent))

from dontpanic_orchestrate import agent_manifest as am  # noqa: E402
from dontpanic_orchestrate import agent_surface  # noqa: E402
from dontpanic_orchestrate import cli  # noqa: E402
from dontpanic_orchestrate import executors  # noqa: E402
from dontpanic_orchestrate import global_config as gc  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_dontpanic_home(tmp_path, monkeypatch):
    """Reroute ``$DONTPANIC_HOME`` to a tmp dir so register-worker writes never
    touch the operator's real ~/.dontpanic. Clears ``$JARVIS_HOME`` for
    deterministic resolution."""
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


# ──────────────────────────────  agent brief  ──────────────────────────────


def test_agent_brief_prints_brief_exit_0() -> None:
    rc, out, _ = _run(["agent", "brief"])
    assert rc == 0
    assert "DontPanic operating brief" in out
    # Lists the real worker executors from AGENT_REGISTRY, not invented labels.
    for name in agent_surface.worker_executors():
        assert name in out


def test_agent_brief_json() -> None:
    rc, out, _ = _run(["agent", "brief", "--json"])
    assert rc == 0
    payload = json.loads(out)
    assert {"generator_version", "content_hash", "text"} <= set(payload)


# ──────────────────────────────  agent status  ──────────────────────────────


def test_agent_status_lists_executors_and_roles(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run(["agent", "status"])
    assert rc == 0
    assert "WORKER EXECUTORS" in out
    assert "CONFIGURED ROLES" in out
    for name in agent_surface.worker_executors():
        assert name in out
    # Fallback roles resolve to claude (implementer) / codex (auditor).
    assert "implementer:" in out
    assert "auditor:" in out


def test_agent_status_no_arg_classifies_current_and_lists_operators(tmp_path, monkeypatch) -> None:
    """Regression for F002-i0 finding: the no-arg status must classify the
    *current* agent and name known operator-only agents (Grok/Gemini), not just
    the worker executors. Fails if the current-agent / operator-only sections
    are absent."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(agent_surface.CURRENT_AGENT_ENV, raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    rc, out, _ = _run(["agent", "status"])
    assert rc == 0
    # Current-agent section is always present (here: unknown — no env signal).
    assert "CURRENT AGENT" in out
    # Known operator-only agents are surfaced as non-dispatchable by name.
    assert "KNOWN OPERATOR-ONLY AGENTS" in out
    for op in agent_surface.KNOWN_OPERATOR_AGENTS:
        assert op in out
    assert "grok" in out and "gemini" in out


def test_agent_status_no_arg_detects_current_agent_from_env(tmp_path, monkeypatch) -> None:
    """The no-arg status classifies the agent named by ``$DONTPANIC_AGENT``."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(agent_surface.CURRENT_AGENT_ENV, "grok")
    rc, out, _ = _run(["agent", "status"])
    assert rc == 0
    assert "CURRENT AGENT: grok" in out
    assert "operator-only" in out
    assert "can be dispatched as a worker: no" in out


def test_agent_status_classifies_named_worker(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run(["agent", "status", "claude"])
    assert rc == 0
    assert "AGENT: claude" in out
    assert "worker-capable" in out
    assert "can be dispatched as a worker: yes" in out


def test_agent_status_classifies_named_operator_only(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run(["agent", "status", "grok"])
    assert rc == 0
    assert "AGENT: grok" in out
    assert "operator-only" in out
    assert "can be dispatched as a worker: no" in out


# ──────────────────────────────  agent setup  ──────────────────────────────


def test_agent_setup_grok_operator_only_message() -> None:
    """Acceptance #3 — Grok can operate but cannot be registered as a worker."""
    rc, out, _ = _run(["agent", "setup", "grok"])
    assert rc == 0
    assert "grok can operate DontPanic" in out
    assert "CANNOT be registered as a worker" in out
    assert "no executor" in out.lower()


def test_agent_setup_worker_capable_message() -> None:
    rc, out, _ = _run(["agent", "setup", "claude"])
    assert rc == 0
    assert "CAN be dispatched as a worker" in out
    assert "register-worker claude" in out


# ──────────────────────────  agent register-worker  ──────────────────────────


def test_register_worker_unknown_refuses_without_writing(tmp_path, monkeypatch) -> None:
    """Acceptance #4 — unknown executor refused, exit 3, no config written."""
    monkeypatch.chdir(tmp_path)
    rc, _, err = _run(["agent", "register-worker", "grok"])
    assert rc == 3
    assert "REFUSED" in err
    assert not gc.config_path().exists(), "no config file should be written on refusal"


def test_register_worker_claude_writes_role_config(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run(["agent", "register-worker", "claude", "--role", "auditor"])
    assert rc == 0
    assert "roles.auditor → claude" in out
    cfg = json.loads(gc.config_path().read_text())
    assert cfg == {"roles": {"auditor": "claude"}}


def test_register_worker_default_role_is_implementer(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rc, _, _ = _run(["agent", "register-worker", "codex"])
    assert rc == 0
    cfg = json.loads(gc.config_path().read_text())
    assert cfg["roles"]["implementer"] == "codex"


def test_register_worker_dry_run_writes_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run(["agent", "register-worker", "claude", "--dry-run"])
    assert rc == 0
    assert "DRY-RUN" in out
    assert not gc.config_path().exists()


def test_register_worker_does_not_invoke_executors(tmp_path, monkeypatch) -> None:
    """Acceptance #9 — registration is config-only; never instantiates an
    executor or calls a real agent CLI."""
    monkeypatch.chdir(tmp_path)
    with mock.patch.object(executors, "get_executor") as spy:
        rc, _, _ = _run(["agent", "register-worker", "claude"])
    assert rc == 0
    spy.assert_not_called()


# ──────────────────────────────  orchestrate gateway  ──────────────────────────────


def test_orchestrate_no_args_prints_brief_and_workflow_exit_0() -> None:
    """Acceptance #5 — no args prints brief + workflow with actionable text."""
    rc, out, _ = _run(["orchestrate"])
    assert rc == 0
    assert "DontPanic operating brief" in out
    assert "CANONICAL WORKFLOW" in out
    assert "dispatch-from-plan" in out


def test_orchestrate_help_prints_brief_exit_0() -> None:
    rc, out, _ = _run(["orchestrate", "--help"])
    assert rc == 0
    assert "DontPanic operating brief" in out


def test_orchestrate_invalid_shape_exits_2(tmp_path, monkeypatch) -> None:
    """A leading flag with no plan id/path is an invalid shape: teach on stderr,
    exit 2, and never dispatch."""
    monkeypatch.chdir(tmp_path)
    with mock.patch("dontpanic_orchestrate.cli.supervisor.dispatch_volley") as spy:
        rc, _, err = _run(["orchestrate", "--confirm"])
    assert rc == 2
    assert "no plan id/path" in err
    assert "CANONICAL WORKFLOW" in err
    spy.assert_not_called()


# ── orchestrate forwarding: reuse the dispatch-from-plan synthetic plan helper ──

from test_dispatch_from_plan import _PLAN_ID, _write_plan  # noqa: E402


def test_orchestrate_plan_forwards_dry_run(tmp_path, monkeypatch) -> None:
    """Acceptance #6 — `orchestrate <plan>` forwards to dispatch-from-plan and
    preserves dry-run-by-default (dispatch_volley is never called)."""
    _write_plan(tmp_path)
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch("dontpanic_orchestrate.cli.supervisor.dispatch_volley") as spy,
    ):
        rc, out, _ = _run(["orchestrate", _PLAN_ID])
    assert rc == 0
    assert "[dispatch-from-plan]" in out
    spy.assert_not_called()


class _FakeVolleyResult:
    final_status = "signed_off"
    rounds = 1
    reason = "ok"
    audit_paths: list[str] = []


def test_orchestrate_plan_confirm_reaches_dispatch_path(tmp_path, monkeypatch) -> None:
    """Acceptance #7 — `orchestrate <plan> --confirm` reaches the same in-process
    dispatch path as `dispatch-from-plan <plan> --confirm`."""
    _write_plan(tmp_path)
    with (
        mock.patch("dontpanic_orchestrate.cli.Path.cwd", return_value=tmp_path),
        mock.patch(
            "dontpanic_orchestrate.cli.supervisor.dispatch_volley",
            return_value=_FakeVolleyResult(),
        ) as spy,
        mock.patch("dontpanic_orchestrate.cli._compute_readiness", return_value=("ok", None)),
        mock.patch("subprocess.run") as subproc_spy,
        mock.patch("subprocess.Popen") as popen_spy,
    ):
        rc, _, _ = _run(["orchestrate", _PLAN_ID, "--confirm"])
    assert spy.call_count == 1, "confirm must forward to dispatch_volley exactly once"
    # No subprocess / real CLI spawned (acceptance #9).
    subproc_spy.assert_not_called()
    popen_spy.assert_not_called()
    assert rc in (0, 3)


# ──────────────────────────────  manifest supported_commands  ──────────────────────────────


def test_bootstrap_manifest_includes_agent_and_orchestrate() -> None:
    """Acceptance #8 (source) — agent + orchestrate are advertised."""
    m = am.bootstrap_manifest(install_source="source", cli_path="/x")
    assert "agent" in m.supported_commands
    assert "orchestrate" in m.supported_commands


def test_manifest_init_then_show_includes_agent_and_orchestrate(tmp_path, monkeypatch) -> None:
    """Acceptance #8 — `manifest init`/`show` surface the new commands."""
    monkeypatch.chdir(tmp_path)
    rc, _, _ = _run(["manifest", "init"])
    assert rc == 0
    rc, out, _ = _run(["manifest", "show"])
    assert rc == 0
    payload = json.loads(out)
    assert "agent" in payload["supported_commands"]
    assert "orchestrate" in payload["supported_commands"]
