"""Plan 2026-05-30-001 F006 — config-home reconciliation.

Covers the 7 acceptance criteria:
  (1) doctor surfaces split-brain ~/.dontpanic vs ~/.jarvis with file detail
  (2) reconcile dry-run prints a plan and writes nothing
  (3) reconcile confirm migrates non-conflicting legacy-only files
  (4) agent-manifest.json ends up in the canonical home after reconcile
  (5) divergent config.json / projects.json are NOT silently merged
  (6) legacy read-through remains (migration copies, never deletes legacy)
  (7) classification states + write behavior tested in isolated homes

The autouse conftest fixture redirects DONTPANIC_HOME (canonical) and
JARVIS_HOME (legacy) to temp dirs, so home_reconcile.canonical_home() /
legacy_home() resolve there.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f006_home_reconcile.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from dontpanic_orchestrate import home_reconcile as hr
from dontpanic_orchestrate.reconcile import reconcile_main

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"


@pytest.fixture
def doctor():
    spec = importlib.util.spec_from_file_location("dontpanic_doctor", DOCTOR_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dontpanic_doctor"] = mod
    spec.loader.exec_module(mod)
    return mod


def _homes() -> tuple[Path, Path]:
    canonical = hr.canonical_home()
    legacy = hr.legacy_home()
    canonical.mkdir(parents=True, exist_ok=True)
    legacy.mkdir(parents=True, exist_ok=True)
    return canonical, legacy


def _status_of(states, name):
    return next(s.status for s in states if s.name == name)


# ─────────────────────────────── AC7: classification ───────────────────────────────


def test_classify_all_states():
    canonical, legacy = _homes()
    # identical
    (canonical / "config.json").write_text('{"a":1}')
    (legacy / "config.json").write_text('{"a":1}')
    # legacy_only
    (legacy / "agent-manifest.json").write_text('{"schema_version":"1.0"}')
    # canonical_only
    (canonical / "projects.json").write_text('{"projects":[]}')

    states = hr.classify_homes()
    assert _status_of(states, "config.json") == hr.IDENTICAL
    assert _status_of(states, "agent-manifest.json") == hr.LEGACY_ONLY
    assert _status_of(states, "projects.json") == hr.CANONICAL_ONLY


def test_classify_divergent():
    canonical, legacy = _homes()
    (canonical / "config.json").write_text('{"a":1}')
    (legacy / "config.json").write_text('{"a":2}')
    states = hr.classify_homes()
    assert _status_of(states, "config.json") == hr.DIVERGENT


# ─────────────────────────────── AC2: dry-run writes nothing ───────────────────────────────


def test_dry_run_writes_nothing(capsys):
    canonical, legacy = _homes()
    (legacy / "agent-manifest.json").write_text('{"schema_version":"1.0"}')

    rc = reconcile_main(["homes", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "agent-manifest.json" in out
    assert "would migrate" in out or "preview" in out
    # nothing written canonical-ward
    assert not (canonical / "agent-manifest.json").exists()


# ─────────────────────────────── AC3 + AC4 + AC6: confirm migrates ───────────────────────────────


def test_confirm_migrates_legacy_only(capsys):
    canonical, legacy = _homes()
    (legacy / "agent-manifest.json").write_text('{"schema_version":"1.0","manifest":true}')

    rc = reconcile_main(["homes", "--confirm"])
    assert rc == 0
    # AC4: agent-manifest now in canonical home
    migrated = canonical / "agent-manifest.json"
    assert migrated.is_file()
    assert migrated.read_text() == '{"schema_version":"1.0","manifest":true}'
    # AC6: legacy copy preserved for read-through (copy, not move)
    assert (legacy / "agent-manifest.json").is_file()


def test_confirm_is_idempotent_after_migrate():
    canonical, legacy = _homes()
    (legacy / "config.json").write_text('{"a":1}')
    assert reconcile_main(["homes", "--confirm"]) == 0
    # Now identical in both homes → second run is a clean no-op.
    states = hr.classify_homes()
    assert _status_of(states, "config.json") == hr.IDENTICAL
    assert reconcile_main(["homes", "--confirm"]) == 0


# ─────────────────────────────── AC5: divergent never merged ───────────────────────────────


def test_divergent_refused_not_merged(capsys):
    canonical, legacy = _homes()
    (canonical / "config.json").write_text('{"canonical":true}')
    (legacy / "config.json").write_text('{"legacy":true}')
    (canonical / "projects.json").write_text('{"projects":["c"]}')
    (legacy / "projects.json").write_text('{"projects":["l"]}')

    rc = reconcile_main(["homes", "--confirm"])
    out = capsys.readouterr().out
    # exit 1 signals unresolved ambiguous merge
    assert rc == 1
    assert "refused" in out.lower()
    # neither file silently overwritten — canonical keeps its own content
    assert (canonical / "config.json").read_text() == '{"canonical":true}'
    assert (canonical / "projects.json").read_text() == '{"projects":["c"]}'


def test_confirm_and_dry_run_mutually_exclusive():
    assert reconcile_main(["homes", "--confirm", "--dry-run"]) == 2


# ─────────────────────────────── AC1: doctor surfaces split-brain ───────────────────────────────


def test_doctor_agent_surfaces_split_brain(doctor):
    canonical, legacy = _homes()
    (legacy / "agent-manifest.json").write_text('{"schema_version":"1.0"}')

    results = doctor.check_agent_onboarding()
    ch = next(r for r in results if r.name == "config-home")
    assert ch.warn is True
    assert "agent-manifest.json" in ch.message
    assert "reconcile homes" in ch.remediation


def test_doctor_agent_clean_when_reconciled(doctor):
    # Both homes empty (the isolated zero-state) → reconciled, no split-brain.
    _homes()
    results = doctor.check_agent_onboarding()
    ch = next(r for r in results if r.name == "config-home")
    assert ch.ok is True
    assert ch.warn is False


def test_doctor_agent_surfaces_divergent(doctor):
    canonical, legacy = _homes()
    (canonical / "config.json").write_text('{"a":1}')
    (legacy / "config.json").write_text('{"a":2}')
    results = doctor.check_agent_onboarding()
    ch = next(r for r in results if r.name == "config-home")
    assert ch.warn is True
    assert "divergent" in ch.message


def test_default_doctor_surfaces_config_home(doctor):
    # codex F005/F006 audit finding #3: the canonical default doctor path (not
    # only --agent) must surface split-brain. Empty isolated homes -> config-home
    # present + OK (so it's wired) without warning.
    _homes()
    results = doctor.run_all_checks(skip_auth=True, include_projects=True)
    ch = next((r for r in results if r.name == "config-home"), None)
    assert ch is not None, "default doctor (include_projects) must run check_config_home"
    assert ch.ok is True
