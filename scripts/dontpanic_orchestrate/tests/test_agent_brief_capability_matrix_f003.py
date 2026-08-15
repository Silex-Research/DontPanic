"""Plan 2026-07-27-001 F003 — capability-matrix pointer in the agent brief.

Acceptance covered (codex audit i0, low/test_coverage finding):

1. The rendered brief contains the CAPABILITY MATRIX section with the
   canonical pointer string, so the pointer cannot silently drift out of
   the brief.
2. The pointer names the committed doc path (docs/AGENT_CAPABILITY_MATRIX.md)
   and all three capability axes (can_operate / can_be_dispatched /
   can_orchestrate) so a reader can map agents onto the axes without
   reading Python source.
3. The pointed-to doc exists in the repo and carries the axes as matrix
   columns plus the opencode operator-surface row (guards the committed
   artifact the pointer promises).

All tests redirect ``$DONTPANIC_HOME`` to ``tmp_path`` so the operator's real
home is never read or written.

Run: PYTHONPATH=scripts pytest \
  scripts/dontpanic_orchestrate/tests/test_agent_brief_capability_matrix_f003.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import agent_brief as ab  # noqa: E402
from dontpanic_orchestrate import global_config as gc  # noqa: E402

REPO_ROOT = HERE.parents[3]
MATRIX_DOC = REPO_ROOT / "docs" / "AGENT_CAPABILITY_MATRIX.md"
AXES = ("can_operate", "can_be_dispatched", "can_orchestrate")


@pytest.fixture(autouse=True)
def _isolate_dontpanic_home(tmp_path, monkeypatch):
    """Reroute ``$DONTPANIC_HOME`` to a tmp dir so the operator's real
    ``~/.dontpanic`` is never touched. Unset ``$JARVIS_HOME`` so home
    resolution is deterministic per test."""
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))


def _inputs(**overrides):
    base = {
        "dontpanic_version": "9.9.9",
        "supported_commands": ["projects", "doctor", "manifest"],
        "worker_executors": ["claude", "codex"],
        "config_home": "/tmp/home/.dontpanic",
        "using_legacy_home": False,
        "legacy_home_present": False,
    }
    base.update(overrides)
    return ab.BriefInputs(**base)


# ──────────────────────────────  (1) pointer present in brief  ──────────────────────────────


def test_brief_contains_capability_matrix_section():
    text = ab.render_brief(_inputs()).text
    assert "CAPABILITY MATRIX" in text
    # canonical pointer string is present verbatim, not a paraphrase.
    assert ab.CAPABILITY_MATRIX_POINTER in text


# ──────────────────────────────  (2) pointer names path + axes  ──────────────────────────────


def test_pointer_names_doc_path_and_all_three_axes():
    assert "docs/AGENT_CAPABILITY_MATRIX.md" in ab.CAPABILITY_MATRIX_POINTER
    for axis in AXES:
        assert axis in ab.CAPABILITY_MATRIX_POINTER
    # the live machine source of truth stays named alongside the doc.
    assert "dontpanic agent status" in ab.CAPABILITY_MATRIX_POINTER


# ──────────────────────────────  (3) pointed-to doc is committed and shaped  ──────────────────────────────


def test_matrix_doc_exists_with_axes_columns_and_opencode_row():
    assert MATRIX_DOC.is_file(), (
        "agent brief points at docs/AGENT_CAPABILITY_MATRIX.md but the doc "
        "is missing from the repo"
    )
    doc = MATRIX_DOC.read_text(encoding="utf-8")
    # the matrix table header carries all three axes as columns.
    header = "| Agent | can_operate | can_be_dispatched | can_orchestrate |"
    assert header in doc
    # opencode is documented as an operator-only surface.
    assert "`opencode`" in doc
