"""Plan 2026-06-14-001 F007 — channel doctor: dontpanic doctor --channel <surface>.

Reuses the capability verify.probes + a structural probe registry to report
whether a named operator surface is usable. THREE OUTCOMES (D015):
  (a) recognized surface WITH a seeded manifest -> runs probes, per-check pass/warn/fail
  (b) recognized operator_surface id with NO seeded manifest -> advisory recognized_unseeded
  (c) name normalizing to unknown_surface -> non-zero exit + actionable message
No agent-channels.json is introduced. Structural-safe under --skip-auth.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import channel_doctor, cli  # noqa: E402
from dontpanic_orchestrate.capabilities import OPERATOR_SURFACE_MINIMUM_PROBES  # noqa: E402

SEEDED = ("cursor", "claude_desktop", "codex_app", "antigravity")
_VALID_STATUSES = {"pass", "warn", "fail"}


# ──────────────────────────────  outcome (a): seeded surface runs probes  ──────────────────────────────


@pytest.mark.parametrize("surface", SEEDED)
def test_seeded_surface_runs_full_minimum_probe_set(surface: str) -> None:
    result = channel_doctor.diagnose_channel(surface)
    assert result.surface == surface
    assert result.outcome == channel_doctor.OUTCOME_OK
    reported = {c["probe"] for c in result.checks}
    # the full minimum probe set is reported, each with a pass/warn/fail status
    assert OPERATOR_SURFACE_MINIMUM_PROBES <= reported
    for check in result.checks:
        assert check["status"] in _VALID_STATUSES
    assert result.exit_code in (0, 1, 2)


def test_alias_input_normalizes_to_canonical_surface() -> None:
    # 'Cursor' (display label) normalizes to the canonical id cursor (F001)
    assert channel_doctor.diagnose_channel("Cursor").surface == "cursor"


# ──────────────────────────────  outcome (b): recognized but unseeded  ──────────────────────────────


def test_recognized_unseeded_surface_is_advisory_not_unsupported() -> None:
    # 'terminal' is a recognized operator_surface id (F001) but has no seeded manifest
    result = channel_doctor.diagnose_channel("terminal")
    assert result.surface == "terminal"
    assert result.outcome == channel_doctor.OUTCOME_RECOGNIZED_UNSEEDED
    assert result.exit_code == 0  # advisory, not a failure
    assert "recognized" in result.message.lower()


# ──────────────────────────────  outcome (c): unknown surface  ──────────────────────────────


def test_unknown_surface_exits_nonzero_with_actionable_message() -> None:
    result = channel_doctor.diagnose_channel("totally-made-up-surface")
    assert result.outcome == channel_doctor.OUTCOME_UNKNOWN
    assert result.exit_code != 0
    # actionable: names the recognized surfaces the operator could mean
    assert "cursor" in result.message


# ──────────────────────────────  structural-safe + no parallel registry  ──────────────────────────────


def test_skip_auth_is_structural_safe() -> None:
    # the minimum probe set has no auth probe, so --skip-auth never hard-fails
    result = channel_doctor.diagnose_channel("cursor", skip_auth=True)
    assert result.outcome == channel_doctor.OUTCOME_OK
    assert result.exit_code != 2


def test_no_agent_channels_json_file_exists() -> None:
    repo_root = HERE.parents[2].parent  # scripts/dontpanic_orchestrate -> repo root
    offenders = [str(p) for p in repo_root.rglob("agent-channels.json")]
    assert offenders == [], f"agent-channels.json must not be introduced: {offenders}"


# ──────────────────────────────  CLI wiring  ──────────────────────────────


def test_cli_doctor_channel_json_round_trips(capsys) -> None:
    rc = cli.main(["doctor", "--channel", "cursor", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["surface"] == "cursor"
    assert out["outcome"] == channel_doctor.OUTCOME_OK
    assert OPERATOR_SURFACE_MINIMUM_PROBES <= {c["probe"] for c in out["checks"]}
    assert rc in (0, 1)


def test_cli_operator_surface_alias_flag(capsys) -> None:
    rc = cli.main(["doctor", "--operator-surface", "cursor", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["surface"] == "cursor"
    assert rc in (0, 1)


def test_cli_doctor_channel_unknown_surface_nonzero(capsys) -> None:
    rc = cli.main(["doctor", "--channel", "made-up", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == channel_doctor.OUTCOME_UNKNOWN
    assert rc != 0
