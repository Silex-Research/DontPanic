"""Plan 2026-06-01-001 F009 — actionable config-readiness pre-flight.

Acceptance coverage:
(1) reusable pre-flight check, distinct from the in-loop budget breaker
(2) invalid/empty caps OR invalid role -> clean readiness failure naming file +
    precise reason + remediation command (never a raw schema exception)
(3) the remediation command passes command_validation.validate_command_tokens
(4) the failure references the dashboard affordance
(5) tests reproduce quota_caps=={} AND invalid-roles, plus a valid pass

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_config_readiness_f009.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    command_validation,
    config_readiness,
    quota_caps_loader,  # noqa: E402
)

_REGISTERED = {"claude", "codex", "gemini", "grok"}


def _write(p: Path, obj) -> Path:
    p.write_text(json.dumps(obj))
    return p


def _valid_caps_file(tmp_path: Path) -> Path:
    """A minimal caps file that load() accepts (has a vendors{} block)."""
    caps = quota_caps_loader.starter_caps()
    return _write(tmp_path / "quota_caps.json", caps)


# ───────────────────────────  (5) quota_caps == {}  ───────────────────────────


def test_empty_caps_file_is_actionable_readiness_failure(tmp_path: Path) -> None:
    caps = _write(tmp_path / "quota_caps.json", {})
    r = config_readiness.check_quota_caps_readiness(caps)
    assert r.ok is False
    assert str(caps) == r.file
    assert r.reason and "empty" in r.reason.lower()
    # (3) remediation is a runnable dontpanic command
    assert command_validation.validate_command_tokens(list(r.remediation_tokens)).ok
    assert r.remediation_tokens == ("quota-caps", "init")
    # (4) dashboard affordance referenced
    assert "dashboard" in r.dashboard.lower()
    # (2) render is a clean message, not a traceback
    assert "Config not ready" in r.render()


def test_invalid_caps_file_does_not_raise(tmp_path: Path) -> None:
    """A malformed caps file (unsupported version) is a clean failure, NOT a
    raised QuotaCapsError escaping into a volley."""
    caps = _write(tmp_path / "quota_caps.json", {"version": 99, "vendors": {}})
    r = config_readiness.check_quota_caps_readiness(caps)
    assert r.ok is False
    assert command_validation.validate_command_tokens(list(r.remediation_tokens)).ok


# ───────────────────────────  (5) invalid roles (D065)  ───────────────────────────


def test_d065_split_brain_roles_are_actionable_failure() -> None:
    r = config_readiness.check_role_readiness(
        ["Grok-Builder", "Codex-Auditor"], registered_executors=_REGISTERED
    )
    assert r.ok is False
    assert r.file == "<roles>"
    assert r.reason and "Grok-Builder" in r.reason
    assert command_validation.validate_command_tokens(list(r.remediation_tokens)).ok
    assert "dashboard" in r.dashboard.lower()


def test_unregistered_but_well_formed_role_is_failure() -> None:
    r = config_readiness.check_role_readiness(
        ["claude", "nonesuch"], registered_executors=_REGISTERED
    )
    assert r.ok is False
    assert "not a registered executor" in r.reason
    assert command_validation.validate_command_tokens(list(r.remediation_tokens)).ok


def test_valid_roles_pass() -> None:
    r = config_readiness.check_role_readiness(
        ["claude", "codex"], registered_executors=_REGISTERED
    )
    assert r.ok is True


# ───────────────────────────  combined entry point  ───────────────────────────


def test_check_config_readiness_caps_failure_precedes_roles(tmp_path: Path) -> None:
    """Caps is checked first (it blocks every paid call); a bad caps file is
    returned even when roles are also invalid."""
    caps = _write(tmp_path / "quota_caps.json", {})
    r = config_readiness.check_config_readiness(
        roles=["Grok-Builder"], registered_executors=_REGISTERED, caps_path=caps
    )
    assert r.ok is False
    assert r.remediation_tokens == ("quota-caps", "init")  # caps, not roles


def test_check_config_readiness_all_valid_passes(tmp_path: Path) -> None:
    caps = _valid_caps_file(tmp_path)
    r = config_readiness.check_config_readiness(
        roles=["claude", "codex"], registered_executors=_REGISTERED, caps_path=caps
    )
    assert r.ok is True, r.render()


def test_check_config_readiness_valid_caps_invalid_roles(tmp_path: Path) -> None:
    caps = _valid_caps_file(tmp_path)
    r = config_readiness.check_config_readiness(
        roles=["claude", "Codex-Auditor"], registered_executors=_REGISTERED, caps_path=caps
    )
    assert r.ok is False
    assert r.file == "<roles>"
