"""F001 — target-context prelude pure helpers + regression fixtures.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_target_context_prelude.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate.target_context_prelude import (  # noqa: E402
    PRELUDE_TEMPLATE,
    TargetContextError,
    parse_prelude_block,
    render_prelude,
    resolve_repo,
    validate_target_context,
)

REPO_ROOT = HERE.parents[3]
FIXTURES_DIR = (
    REPO_ROOT
    / "docs"
    / "plans"
    / "2026-05-01-005-feat-target-context-platform-fix"
    / "evidence"
    / "f001"
    / "fixtures"
)

FIXTURE_FILES = (
    "case-a-implementer-missing-prelude.json",
    "case-b-auditor-self-finding.json",
    "case-c-golden-valid-struct-valid-prelude.json",
    "case-d-struct-absent.json",
    "case-e-struct-invalid-empty-env.json",
    "case-f-commands-without-target.json",
    "case-g-prelude-value-mismatch.json",
)


# ──────────────────────────────  PRELUDE_TEMPLATE shape  ──────────────────────────────


def test_prelude_template_byte_for_byte_d001() -> None:
    """D001: heading + 4 fields (Repo, Env, Project, Command) + trailing blank."""
    expected = (
        "## Target context\n"
        "- Repo: {repo}\n"
        "- Env: {env}\n"
        "- Project: {project}\n"
        "- Command: {command_count} (see structured target_context.commands_run)\n"
        "\n"
    )
    assert PRELUDE_TEMPLATE == expected
    # Exactly 5 newlines (heading + 4 field lines) + trailing blank line newline = 6
    assert PRELUDE_TEMPLATE.count("\n") == 6
    # Trailing blank line: ends with two newlines
    assert PRELUDE_TEMPLATE.endswith("\n\n")


# ──────────────────────────────  render_prelude golden  ──────────────────────────────


def test_render_prelude_golden_output_struct_repo() -> None:
    rendered = render_prelude(
        {
            "repo": "Jarvis",
            "env": "dev",
            "project": "jarvis-a6ee1",
            "commands_run": ["pytest -q", "ruff check ."],
        }
    )
    expected = (
        "## Target context\n"
        "- Repo: Jarvis\n"
        "- Env: dev\n"
        "- Project: jarvis-a6ee1\n"
        "- Command: 2 (see structured target_context.commands_run)\n"
        "\n"
    )
    assert rendered == expected


def test_render_prelude_deterministic_100_calls() -> None:
    """Acceptance: 100 calls with same input return identical strings."""
    tc = {
        "repo": "Jarvis",
        "env": "dev",
        "project": "jarvis-a6ee1",
        "commands_run": ["pytest -q"],
    }
    first = render_prelude(tc)
    for _ in range(100):
        assert render_prelude(tc) == first


@pytest.mark.parametrize(
    "project_value, expected_line",
    [
        (None, "- Project: (none)\n"),
        ("", "- Project: (none)\n"),
        ("none", "- Project: (none)\n"),
        ("None", "- Project: (none)\n"),
        ("(none)", "- Project: (none)\n"),
        ("jarvis-a6ee1", "- Project: jarvis-a6ee1\n"),
        ("my-project", "- Project: my-project\n"),
    ],
)
def test_render_prelude_project_special_values(project_value, expected_line) -> None:
    rendered = render_prelude(
        {
            "repo": "Jarvis",
            "env": "dev",
            "project": project_value,
            "commands_run": [],
        }
    )
    assert expected_line in rendered


def test_render_prelude_command_count_zero_when_empty() -> None:
    rendered = render_prelude({"repo": "Jarvis", "env": "dev", "project": None, "commands_run": []})
    assert "- Command: 0 (see structured target_context.commands_run)\n" in rendered


# ──────────────────────────────  render_prelude purity (i0 auditor F3)  ──────────────────────────────


def test_render_prelude_repo_from_struct_first() -> None:
    rendered = render_prelude(
        {"repo": "MyExplicitRepo", "env": "dev", "project": None, "commands_run": []}
    )
    assert "- Repo: MyExplicitRepo\n" in rendered


def test_render_prelude_raises_on_missing_repo() -> None:
    """render_prelude is pure — D002 cwd fallback lives in resolve_repo, not here."""
    with pytest.raises(TargetContextError, match="repo missing"):
        render_prelude({"env": "dev", "project": None, "commands_run": []})


def test_render_prelude_raises_on_missing_env() -> None:
    with pytest.raises(TargetContextError, match="env missing"):
        render_prelude({"repo": "Jarvis", "project": None, "commands_run": []})


def test_render_prelude_raises_on_none_target_context() -> None:
    with pytest.raises(TargetContextError, match="missing"):
        render_prelude(None)  # type: ignore[arg-type]


# ──────────────────────────────  resolve_repo D002 precedence (cwd I/O)  ──────────────────────────────


def test_resolve_repo_struct_first() -> None:
    """Struct value wins; subprocess never called."""
    assert resolve_repo({"repo": "MyExplicitRepo", "env": "dev"}) == "MyExplicitRepo"


def test_resolve_repo_struct_value_is_stripped() -> None:
    assert resolve_repo({"repo": "  Jarvis  "}) == "Jarvis"


def test_resolve_repo_cwd_fallback(tmp_path, monkeypatch) -> None:
    """Cwd fallback: struct lacks repo -> git rev-parse from os.getcwd()."""
    repo_dir = tmp_path / "FakeRepoName"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    monkeypatch.chdir(repo_dir)
    assert resolve_repo({"env": "dev"}) == "FakeRepoName"


def test_resolve_repo_hard_fail_when_neither(tmp_path, monkeypatch) -> None:
    """No struct.repo, no git toplevel reachable -> TargetContextError."""
    non_git_dir = tmp_path / "not-a-repo"
    non_git_dir.mkdir()
    monkeypatch.chdir(non_git_dir)
    # Defensive: also point HOME away so a parent .git can't be found
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    with pytest.raises(TargetContextError, match="repo missing"):
        resolve_repo({"env": "dev"})


def test_resolve_repo_compose_with_render_prelude(tmp_path, monkeypatch) -> None:
    """F002's intended composition pattern: resolve_repo + render_prelude."""
    repo_dir = tmp_path / "ComposedRepo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    monkeypatch.chdir(repo_dir)
    tc = {"env": "dev", "project": None, "commands_run": ["pytest -q"]}
    repo = resolve_repo(tc)
    rendered = render_prelude({**tc, "repo": repo})
    assert "- Repo: ComposedRepo\n" in rendered
    assert "- Env: dev\n" in rendered
    assert "- Project: (none)\n" in rendered
    assert "- Command: 1 (see structured target_context.commands_run)\n" in rendered


# ──────────────────────────────  validate_target_context  ──────────────────────────────


@pytest.mark.parametrize(
    "tc, match_substring",
    [
        (None, "missing"),
        # env empty with commands_run non-empty
        (
            {"env": "", "project": "p", "commands_run": ["pytest -q"]},
            "env empty",
        ),
        (
            {"env": None, "project": "p", "commands_run": ["pytest -q"]},
            "env empty",
        ),
        # project empty string with commands_run non-empty
        (
            {"env": "dev", "project": "", "commands_run": ["pytest -q"]},
            "project empty",
        ),
        # project key absent with commands_run non-empty
        (
            {"env": "dev", "commands_run": ["pytest -q"]},
            "project key absent",
        ),
        # commands without env or project (env is empty, project missing)
        (
            {"env": "", "commands_run": ["pytest -q"]},
            "env empty",
        ),
    ],
)
def test_validate_target_context_invalid_shapes(tc, match_substring) -> None:
    with pytest.raises(TargetContextError, match=match_substring):
        validate_target_context(tc)


@pytest.mark.parametrize(
    "tc",
    [
        # case-a-style: valid struct with non-host project + commands
        {"env": "dev", "project": "jarvis-a6ee1", "commands_run": ["pytest -q"]},
        # case-c-style: valid struct, host-local project (None) + commands
        {"env": "dev", "project": None, "commands_run": ["pytest -q"]},
        # commands_run empty -> nothing to validate, valid even if project missing
        {"env": "dev"},
        # commands_run empty with everything else valid
        {"env": "dev", "project": "jarvis-a6ee1", "commands_run": []},
        # project=None + commands non-empty (host-local sentinel)
        {"env": "dev", "project": None, "commands_run": ["pytest -q", "ruff ."]},
    ],
)
def test_validate_target_context_valid_shapes(tc) -> None:
    assert validate_target_context(tc) is None


def test_validate_target_context_message_format() -> None:
    """All errors carry the 'target_context invalid: <reason>' prefix."""
    try:
        validate_target_context(None)
    except TargetContextError as exc:
        assert str(exc).startswith("target_context invalid: ")
    else:
        pytest.fail("expected TargetContextError")


def test_target_context_error_is_value_error() -> None:
    assert issubclass(TargetContextError, ValueError)


# ──────────────────────────────  parse_prelude_block  ──────────────────────────────


def test_parse_prelude_block_canonical() -> None:
    summary = (
        "## Target context\n"
        "- Repo: Jarvis\n"
        "- Env: dev\n"
        "- Project: jarvis-a6ee1\n"
        "- Command: 3 (see structured target_context.commands_run)\n"
        "\n"
        "[F001] Body of the summary follows."
    )
    parsed = parse_prelude_block(summary)
    assert parsed == {
        "repo": "Jarvis",
        "env": "dev",
        "project": "jarvis-a6ee1",
        "command_count": 3,
    }


def test_parse_prelude_block_returns_none_when_no_header() -> None:
    summary = "[F001] F001 complete. No prelude here."
    assert parse_prelude_block(summary) is None


def test_parse_prelude_block_returns_none_for_legacy_inline_format() -> None:
    """Legacy `[F001] Repo: Jarvis  \\nEnv: dev` is NOT canonical - returns None."""
    summary = "[F001] Repo: Jarvis  \nEnv: dev  \nProject: jarvis-a6ee1  \n\nFINDING..."
    assert parse_prelude_block(summary) is None


def test_parse_prelude_block_returns_none_on_empty_summary() -> None:
    assert parse_prelude_block("") is None
    assert parse_prelude_block(None) is None


def test_parse_prelude_block_raises_on_wrong_field_order() -> None:
    summary = (
        "## Target context\n"
        "- Env: dev\n"  # Env before Repo - wrong order
        "- Repo: Jarvis\n"
        "- Project: jarvis-a6ee1\n"
        "- Command: 1 (see structured target_context.commands_run)\n"
        "\n"
    )
    with pytest.raises(TargetContextError, match="prelude shape invalid"):
        parse_prelude_block(summary)


def test_parse_prelude_block_raises_on_mistyped_label() -> None:
    summary = (
        "## Target context\n"
        "- Repo: Jarvis\n"
        "- Environment: dev\n"  # mistyped label
        "- Project: jarvis-a6ee1\n"
        "- Command: 1 (see structured target_context.commands_run)\n"
        "\n"
    )
    with pytest.raises(TargetContextError, match="prelude shape invalid"):
        parse_prelude_block(summary)


def test_parse_prelude_block_raises_on_missing_trailing_blank() -> None:
    """Regression — i0 auditor F2: parser must require blank separator after Command.

    Without this check, a look-alike where prose runs straight into the prelude
    after the Command line would parse as canonical. D001 mandates the trailing
    blank. The exact summary the i0 auditor flagged is reproduced below verbatim.
    """
    summary = (
        "## Target context\n"
        "- Repo: Jarvis\n"
        "- Env: dev\n"
        "- Project: (none)\n"
        "- Command: 0 (see structured target_context.commands_run)\n"
        "Body without required blank"
    )
    with pytest.raises(TargetContextError, match="blank line after Command"):
        parse_prelude_block(summary)


def test_parse_prelude_block_raises_when_only_four_lines_after_header() -> None:
    """Just the four field lines, nothing after — still missing blank separator."""
    summary = (
        "## Target context\n"
        "- Repo: Jarvis\n"
        "- Env: dev\n"
        "- Project: (none)\n"
        "- Command: 0 (see structured target_context.commands_run)"
    )
    with pytest.raises(TargetContextError, match="prelude shape invalid"):
        parse_prelude_block(summary)


def test_parse_prelude_block_raises_on_missing_command_pointer() -> None:
    summary = (
        "## Target context\n"
        "- Repo: Jarvis\n"
        "- Env: dev\n"
        "- Project: jarvis-a6ee1\n"
        "- Command: 3\n"  # missing the structured pointer
        "\n"
    )
    with pytest.raises(TargetContextError, match="Command line malformed"):
        parse_prelude_block(summary)


def test_parse_prelude_block_returns_dict_for_value_mismatch_case() -> None:
    """case-g: prelude format is canonical, only values disagree with struct."""
    summary = (
        "## Target context\n"
        "- Repo: Jarvis\n"
        "- Env: prod\n"  # value disagrees but format is correct
        "- Project: jarvis-a6ee1\n"
        "- Command: 2 (see structured target_context.commands_run)\n"
        "\n"
        "Body."
    )
    parsed = parse_prelude_block(summary)
    assert parsed == {
        "repo": "Jarvis",
        "env": "prod",
        "project": "jarvis-a6ee1",
        "command_count": 2,
    }


# ──────────────────────────────  fixture files smoke + parse parametrized  ──────────────────────────────


def test_fixture_files_all_present() -> None:
    for name in FIXTURE_FILES:
        path = FIXTURES_DIR / name
        assert path.exists(), f"missing fixture: {path}"


@pytest.mark.parametrize("fixture_name", FIXTURE_FILES)
def test_fixture_files_parse_as_json_with_notes(fixture_name) -> None:
    path = FIXTURES_DIR / fixture_name
    payload = json.loads(path.read_text())
    notes = payload.get("_fixture_notes")
    assert isinstance(notes, dict), f"{fixture_name} missing _fixture_notes dict"
    assert notes.get("case"), f"{fixture_name} missing notes.case"
    assert notes.get("expected_f002_outcome") in {
        "prelude-injected",
        "no-change",
        "error-raised",
    }, f"{fixture_name} bad expected_f002_outcome"
    assert notes.get("expected_f003_verdict") in {
        "none",
        "i0",
        "i1",
    }, f"{fixture_name} bad expected_f003_verdict"


@pytest.mark.parametrize(
    "fixture_name, expected_parse",
    [
        # case-a: lacks canonical prelude -> parse returns None
        ("case-a-implementer-missing-prelude.json", None),
        # case-b: legacy inline format, no canonical header -> None
        ("case-b-auditor-self-finding.json", None),
        # case-c: golden, canonical present -> dict
        (
            "case-c-golden-valid-struct-valid-prelude.json",
            {
                "repo": "Jarvis",
                "env": "dev",
                "project": "jarvis-a6ee1",
                "command_count": 1,
            },
        ),
        # case-d: no struct, no prelude -> None
        ("case-d-struct-absent.json", None),
        # case-e: invalid struct, no prelude in summary -> None
        ("case-e-struct-invalid-empty-env.json", None),
        # case-f: invalid struct, no prelude -> None
        ("case-f-commands-without-target.json", None),
        # case-g: canonical prelude with mismatched values -> dict (mismatch is F003's job)
        (
            "case-g-prelude-value-mismatch.json",
            {
                "repo": "Jarvis",
                "env": "prod",
                "project": "jarvis-a6ee1",
                "command_count": 2,
            },
        ),
    ],
)
def test_parse_prelude_block_over_all_fixtures(fixture_name, expected_parse) -> None:
    path = FIXTURES_DIR / fixture_name
    payload = json.loads(path.read_text())
    summary = payload.get("summary", "")
    assert parse_prelude_block(summary) == expected_parse


@pytest.mark.parametrize(
    "fixture_name, struct_should_validate",
    [
        ("case-a-implementer-missing-prelude.json", True),
        ("case-b-auditor-self-finding.json", True),
        ("case-c-golden-valid-struct-valid-prelude.json", True),
        ("case-d-struct-absent.json", False),
        ("case-e-struct-invalid-empty-env.json", False),
        ("case-f-commands-without-target.json", False),
        ("case-g-prelude-value-mismatch.json", True),
    ],
)
def test_validate_target_context_over_all_fixtures(fixture_name, struct_should_validate) -> None:
    path = FIXTURES_DIR / fixture_name
    payload = json.loads(path.read_text())
    tc = payload.get("target_context")
    if struct_should_validate:
        assert validate_target_context(tc) is None
    else:
        with pytest.raises(TargetContextError):
            validate_target_context(tc)
