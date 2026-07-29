"""Regression: calibrate-claude --help must not crash on argparse %-format.

Python 3.14 validates help strings at add_argument time. Literal percent
signs (weekly%, session%) must be written as %% or argparse raises
ValueError: badly formed help string — the exact failure reported on a
fresh source install when running ``dontpanic calibrate-claude --help``.
"""

from __future__ import annotations

import pytest

from dontpanic_orchestrate import cli


def test_calibrate_claude_help_does_not_raise(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli._calibrate_claude_main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--dashboard-pct" in out
    # Escaped %% must render as a single % for the operator.
    assert "weekly%" in out
    assert "session%" in out
    assert "100]" in out  # range (0, 100] may wrap across lines in help
