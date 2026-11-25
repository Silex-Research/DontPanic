"""F3 (Sentinel review 6048538810): an absent, ``null`` or malformed
``objective_contract.json`` all bind the design-review ledger as "no
contract". Behaviour is unchanged, but a present-yet-unusable file must print a
``[plan lock] design-review: WARN ...`` line so the operator sees it.
"""

from __future__ import annotations

import pytest

from dontpanic_orchestrate import cli
from dontpanic_orchestrate.tests.test_design_review_convergence import (
    _FEATURES,
    _CodexLikeReviewer,
    _make_plan,
)

_WARN = "[plan lock] design-review: WARN"


@pytest.fixture(autouse=True)
def _hermetic_codex_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("codex-home")
    (home / "config.toml").write_text('model = "gpt-test-reviewer"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))


def _lock(plan_dir) -> _CodexLikeReviewer:
    reviewer = _CodexLikeReviewer([{"verdict": "signed_off", "findings": []}])
    cli._run_pre_lock_design_volley(plan_dir, operator_requested=True, executor=reviewer)
    return reviewer


@pytest.mark.parametrize(
    "content",
    ["{not json", "null", "[1, 2]", '"a string"'],
    ids=["malformed", "null", "list", "string"],
)
def test_unusable_contract_file_prints_warning(tmp_path, capsys, content) -> None:
    plan_dir = _make_plan(tmp_path, _FEATURES)
    (plan_dir / "objective_contract.json").write_text(content)
    reviewer = _lock(plan_dir)
    out = capsys.readouterr().out
    warn_lines = [line for line in out.splitlines() if line.startswith(_WARN)]
    assert len(warn_lines) == 1, out
    assert "objective_contract.json" in warn_lines[0]
    # Behaviour otherwise unchanged: the review still runs.
    assert reviewer.calls == 1
    assert "design-review scope: full" in out


@pytest.mark.parametrize("content", [None, '{"objective": "ship it"}'], ids=["absent", "dict"])
def test_absent_or_valid_contract_prints_no_warning(tmp_path, capsys, content) -> None:
    plan_dir = _make_plan(tmp_path, _FEATURES)
    if content is not None:
        (plan_dir / "objective_contract.json").write_text(content)
    reviewer = _lock(plan_dir)
    out = capsys.readouterr().out
    assert _WARN not in out, out
    assert reviewer.calls == 1
