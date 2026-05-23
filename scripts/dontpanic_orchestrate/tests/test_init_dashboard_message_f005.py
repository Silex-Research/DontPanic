"""Plan 2026-05-23-004 F005 — `dontpanic init` dashboard hand-off line.

Covers:

  (a) interactive successful walk + smoke prints the dashboard pointer
  (b) ``--json`` suppresses the prose hand-off line (machine-readable
      consumers parse the envelope, not the line)
  (c) ``--non-interactive`` suppresses the prose hand-off line

The exact line content is pinned because the acceptance contract is
"points humans at `dontpanic dashboard open` or equivalent" — the test
guards against accidental drift away from that exact command.

Run:
    pytest scripts/dontpanic_orchestrate/tests/test_init_dashboard_message_f005.py -q
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from dontpanic_orchestrate import init as _init
from dontpanic_orchestrate import prereq_registry as pr

# ── Stub Walker — bypass the real sweep ──────────────────────────────────


class _StubWalker:
    """Drop-in replacement for ``init.Walker`` that always reports an
    all-pass walk so init_main proceeds to the smoke + dashboard branch.
    """

    def __init__(self, *, profile, non_interactive, **_kwargs):
        self.profile = profile
        self.non_interactive = non_interactive

    def run(self) -> _init.WalkResult:
        empty = pr.SweepResult(profile=self.profile, probes=[])
        return _init.WalkResult(
            profile=self.profile,
            initial=empty,
            final=empty,
            actions=[],
            non_interactive=self.non_interactive,
            aborted=False,
        )


class _StubSmokeResult:
    """Mirror the surface ``init_main`` reads off the smoke result."""

    exit_code = 0  # _smoke.EXIT_PASS

    def to_json(self) -> str:
        return json.dumps({"mode": "mocked", "status": "pass"})


class _StubSnap(types.ModuleType):
    """Stub install_snapshot module so init_main does not touch $HOME."""

    class CapabilityLoadError(Exception):
        pass

    def __init__(self):
        super().__init__("dontpanic_orchestrate.install_snapshot")
        self.CapabilityLoadError = _StubSnap.CapabilityLoadError

    @staticmethod
    def build_snapshot(*, profile: str):
        return {"profile": profile, "stub": True}

    @staticmethod
    def write_snapshot(snapshot):
        return Path("/tmp/install-snapshot-stub.json")


@pytest.fixture
def stub_environment(monkeypatch):
    """Wire stubs for Walker, smoke, and install_snapshot."""
    # 1. Walker → always all-pass.
    monkeypatch.setattr(_init, "Walker", _StubWalker)

    # 2. smoke.run_smoke → stub PASS result.
    from dontpanic_orchestrate import smoke as _smoke

    monkeypatch.setattr(_smoke, "run_smoke", lambda **_kwargs: _StubSmokeResult())
    monkeypatch.setattr(_smoke, "render_smoke_text", lambda r: "smoke: pass")

    # 3. install_snapshot → no-op stub. Stub at both sys.modules
    # (covers `from dontpanic_orchestrate import install_snapshot`
    # bypassing the loader) and as an attribute on the parent package
    # (covers the `from package import submodule` attribute fallback).
    import dontpanic_orchestrate as _pkg

    stub_snap = _StubSnap()
    monkeypatch.setitem(
        sys.modules, "dontpanic_orchestrate.install_snapshot", stub_snap
    )
    monkeypatch.setattr(_pkg, "install_snapshot", stub_snap, raising=False)
    return None


def test_interactive_prints_dashboard_handoff(stub_environment, capsys):
    exit_code = _init.init_main(["--profile=core"])
    captured = capsys.readouterr()
    assert exit_code == _init.EXIT_READY, captured.out
    assert "[dashboard]" in captured.out, (
        f"missing dashboard hand-off in interactive output:\n{captured.out}"
    )
    assert "dontpanic dashboard open" in captured.out
    # `serve` is offered as the live-refresh alternative.
    assert "dontpanic dashboard serve" in captured.out


def test_json_mode_suppresses_dashboard_handoff(stub_environment, capsys):
    exit_code = _init.init_main(["--profile=core", "--json"])
    captured = capsys.readouterr()
    assert exit_code == _init.EXIT_READY, captured.out
    assert "[dashboard]" not in captured.out
    # The first stdout line must still parse as JSON.
    payload = json.loads(captured.out.strip())
    assert payload["schema_version"] == "1.0.0"


def test_non_interactive_suppresses_dashboard_handoff(stub_environment, capsys):
    exit_code = _init.init_main(["--profile=core", "--non-interactive"])
    captured = capsys.readouterr()
    assert exit_code == _init.EXIT_READY, captured.out
    assert "[dashboard]" not in captured.out
