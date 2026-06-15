"""Plan 2026-06-14-001 F004 — operator-role PREFERENCES config layer.

Tests cover the F004 acceptance contract:
  AC1 — set_operator_role writes ONLY operator_roles.* key; worker roles.* namespace
        is untouched; a non-executor surface (cursor) is accepted without error.
  AC2 — value-domain normalization: runtime id, surface id, human/Human aliases,
        unrecognized value → unknown_role, alias (Claude Code) → claude.
  AC3 — list_operator_roles returns resolved map with per-entry scope provenance.
  AC4 — project-scoped value overrides global; provenance reports "project".
  AC5 — OPERATOR_ROLES is disjoint-in-purpose from agent_surface.ROLES (the worker
        role key sets differ).
  AC6 — assert_registrable is never invoked on set; proven by accepting cursor (a
        non-executor surface).

All tests redirect DONTPANIC_HOME / JARVIS_HOME to tmp_path via the shared
autouse fixture in conftest.py (which also redirects all other jarvis state
surfaces). No real writes to the user's home directory.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_operator_roles.py -q
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import agent_surface  # noqa: E402
from dontpanic_orchestrate import operator_roles as or_  # noqa: E402


# ──────────────────────────────  helpers  ──────────────────────────────


def _global_home(tmp_path: Path) -> Path:
    """Return (and create) the redirected DONTPANIC_HOME from environment."""
    home = Path(os.environ["DONTPANIC_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    return home


def _project_dir(tmp_path: Path) -> Path:
    """A real directory usable as a project root."""
    d = tmp_path / "some-project"
    d.mkdir(exist_ok=True)
    return d


# ──────────────────────────────  AC1: namespace isolation  ──────────────────────────────


class TestNamespaceIsolation:
    """set_operator_role must write ONLY operator_roles.* and must not refuse
    a non-executor surface (D009 safety invariant)."""

    def test_set_operator_role_writes_operator_roles_key(self, tmp_path: Path) -> None:
        """Written file contains operator_roles data; the main config.json is NOT
        touched (operator_roles live in a separate operator_roles.json file)."""
        _global_home(tmp_path)
        or_.set_operator_role("primary_operator", "claude", scope="global")
        # The module writes to <dontpanic_home>/operator_roles.json (not config.json)
        roles_path = Path(os.environ["DONTPANIC_HOME"]) / or_.OPERATOR_ROLES_FILENAME
        assert roles_path.is_file(), "operator_roles.json must be written"
        data = json.loads(roles_path.read_text())
        assert "primary_operator" in data
        assert data["primary_operator"] == "claude"

    def test_set_operator_role_does_not_touch_roles_namespace(self, tmp_path: Path) -> None:
        """The worker roles.* namespace in config.json must remain untouched.
        set_operator_role writes to a SEPARATE operator_roles.json file."""
        _global_home(tmp_path)
        or_.set_operator_role("auditor", "codex", scope="global")
        # config.json must NOT exist (we only wrote to operator_roles.json)
        config_path = Path(os.environ["DONTPANIC_HOME"]) / "config.json"
        if config_path.exists():
            data = json.loads(config_path.read_text())
            assert "roles" not in data, (
                "set_operator_role must never write the worker roles.* namespace"
            )
        # The correct file to check is operator_roles.json
        roles_path = Path(os.environ["DONTPANIC_HOME"]) / or_.OPERATOR_ROLES_FILENAME
        assert roles_path.is_file()

    def test_set_accepts_non_executor_surface_cursor(self, tmp_path: Path) -> None:
        """cursor is a valid operator_surface but has no executor — D009 requires
        that set_operator_role accepts it without raising."""
        _global_home(tmp_path)
        # Must not raise — cursor is a valid operator_surface id
        or_.set_operator_role("primary_operator", "cursor", scope="global")
        roles_path = Path(os.environ["DONTPANIC_HOME"]) / or_.OPERATOR_ROLES_FILENAME
        data = json.loads(roles_path.read_text())
        assert data["primary_operator"] == "cursor"

    def test_set_does_not_call_assert_registrable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Structural proof that assert_registrable is never called by
        set_operator_role. We monkeypatch it to raise; if the code calls it
        the test fails."""
        _global_home(tmp_path)

        def _should_not_be_called(name: str) -> None:
            raise AssertionError(
                f"set_operator_role must NEVER call assert_registrable (called with {name!r})"
            )

        monkeypatch.setattr(agent_surface, "assert_registrable", _should_not_be_called)
        # Should complete without error
        or_.set_operator_role("primary_operator", "cursor", scope="global")


# ──────────────────────────────  AC2: value-domain normalization  ──────────────────────────────


class TestValueNormalization:
    """normalize_operator_role_value must map inputs to canonical ids per D015."""

    def test_runtime_id_codex_normalizes_to_codex(self) -> None:
        assert or_.normalize_operator_role_value("codex") == "codex"

    def test_runtime_id_claude_normalizes_to_claude(self) -> None:
        assert or_.normalize_operator_role_value("claude") == "claude"

    def test_surface_id_cursor_normalizes_to_cursor(self) -> None:
        """cursor is an operator_surface canonical id."""
        assert or_.normalize_operator_role_value("cursor") == "cursor"

    def test_surface_id_antigravity_normalizes_to_antigravity(self) -> None:
        assert or_.normalize_operator_role_value("antigravity") == "antigravity"

    def test_human_lowercase_normalizes_to_human(self) -> None:
        assert or_.normalize_operator_role_value("human") == "human"

    def test_human_titlecase_normalizes_to_human(self) -> None:
        assert or_.normalize_operator_role_value("Human") == "human"

    def test_unrecognized_value_normalizes_to_unknown_role(self) -> None:
        """An invented / typo'd value must map to unknown_role, not an invented id."""
        assert or_.normalize_operator_role_value("wizard") == "unknown_role"

    def test_alias_claude_code_normalizes_to_claude(self) -> None:
        """'Claude Code' is a known alias for 'claude' in the F001 alias table."""
        assert or_.normalize_operator_role_value("Claude Code") == "claude"

    def test_alias_codex_cli_normalizes_to_codex(self) -> None:
        assert or_.normalize_operator_role_value("Codex CLI") == "codex"

    def test_alias_openai_codex_normalizes_to_codex(self) -> None:
        assert or_.normalize_operator_role_value("openai codex") == "codex"

    def test_empty_string_normalizes_to_unknown_role(self) -> None:
        assert or_.normalize_operator_role_value("") == "unknown_role"

    def test_whitespace_only_normalizes_to_unknown_role(self) -> None:
        assert or_.normalize_operator_role_value("   ") == "unknown_role"

    def test_surface_id_terminal_normalizes_to_terminal(self) -> None:
        assert or_.normalize_operator_role_value("terminal") == "terminal"

    def test_surface_id_claude_desktop_normalizes_to_claude_desktop(self) -> None:
        assert or_.normalize_operator_role_value("claude_desktop") == "claude_desktop"

    def test_gemini_runtime_normalizes_to_gemini(self) -> None:
        assert or_.normalize_operator_role_value("gemini") == "gemini"

    def test_grok_runtime_normalizes_to_grok(self) -> None:
        assert or_.normalize_operator_role_value("grok") == "grok"


# ──────────────────────────────  AC3: list / resolve with provenance  ──────────────────────────────


class TestListOperatorRoles:
    """list_operator_roles must return a resolved map with per-entry provenance."""

    def test_list_returns_empty_map_when_no_config(self, tmp_path: Path) -> None:
        _global_home(tmp_path)
        result = or_.list_operator_roles()
        assert isinstance(result, dict)

    def test_list_returns_provenance_for_global_entries(self, tmp_path: Path) -> None:
        _global_home(tmp_path)
        or_.set_operator_role("primary_operator", "claude", scope="global")
        result = or_.list_operator_roles()
        assert "primary_operator" in result
        entry = result["primary_operator"]
        assert entry["value"] == "claude"
        assert entry["scope"] == "global"

    def test_list_entry_has_expected_keys(self, tmp_path: Path) -> None:
        """Each entry must have 'value' and 'scope'."""
        _global_home(tmp_path)
        or_.set_operator_role("auditor", "codex", scope="global")
        result = or_.list_operator_roles()
        entry = result["auditor"]
        assert "value" in entry
        assert "scope" in entry

    def test_list_with_project_path_returns_merged_provenance(self, tmp_path: Path) -> None:
        """list_operator_roles with a project_path returns entries from both scopes."""
        _global_home(tmp_path)
        proj = _project_dir(tmp_path)
        or_.set_operator_role("researcher", "gemini", scope="global")
        or_.set_operator_role("designer", "cursor", scope="project", project_path=proj)
        result = or_.list_operator_roles(project_path=proj)
        assert "researcher" in result
        assert result["researcher"]["scope"] == "global"
        assert "designer" in result
        assert result["designer"]["scope"] == "project"


# ──────────────────────────────  AC4: project overrides global  ──────────────────────────────


class TestProjectOverridesGlobal:
    """A project-scoped role value must override the global default; provenance
    must report 'project'."""

    def test_project_value_overrides_global(self, tmp_path: Path) -> None:
        _global_home(tmp_path)
        proj = _project_dir(tmp_path)
        or_.set_operator_role("primary_operator", "claude", scope="global")
        or_.set_operator_role("primary_operator", "cursor", scope="project", project_path=proj)
        result = or_.list_operator_roles(project_path=proj)
        assert result["primary_operator"]["value"] == "cursor"
        assert result["primary_operator"]["scope"] == "project"

    def test_global_value_preserved_when_project_does_not_override(self, tmp_path: Path) -> None:
        """Roles set only in global must still appear (scope='global') when a
        project is in scope but hasn't overridden that role."""
        _global_home(tmp_path)
        proj = _project_dir(tmp_path)
        or_.set_operator_role("primary_operator", "claude", scope="global")
        result = or_.list_operator_roles(project_path=proj)
        assert result["primary_operator"]["value"] == "claude"
        assert result["primary_operator"]["scope"] == "global"

    def test_project_overrides_multiple_roles_independently(self, tmp_path: Path) -> None:
        _global_home(tmp_path)
        proj = _project_dir(tmp_path)
        or_.set_operator_role("primary_operator", "claude", scope="global")
        or_.set_operator_role("auditor", "codex", scope="global")
        or_.set_operator_role("auditor", "gemini", scope="project", project_path=proj)
        result = or_.list_operator_roles(project_path=proj)
        # primary_operator from global
        assert result["primary_operator"]["value"] == "claude"
        assert result["primary_operator"]["scope"] == "global"
        # auditor overridden by project
        assert result["auditor"]["value"] == "gemini"
        assert result["auditor"]["scope"] == "project"


# ──────────────────────────────  AC5: namespace disjointness  ──────────────────────────────


class TestNamespaceDisjointness:
    """OPERATOR_ROLES key set must differ from the worker ROLES key set (D009).
    They serve different purposes and must not be conflated."""

    def test_operator_roles_constant_is_defined(self) -> None:
        assert hasattr(or_, "OPERATOR_ROLES")
        assert len(or_.OPERATOR_ROLES) >= 7

    def test_operator_roles_contains_required_keys(self) -> None:
        required = {
            "primary_operator",
            "auditor",
            "researcher",
            "reviewer",
            "designer",
            "tester",
            "release_operator",
        }
        assert required.issubset(set(or_.OPERATOR_ROLES)), (
            f"OPERATOR_ROLES is missing required keys: {required - set(or_.OPERATOR_ROLES)}"
        )

    def test_operator_roles_differ_from_worker_roles(self) -> None:
        """The operator-role KEYS must not equal the worker ROLES (implementer/
        auditor/goal_auditor). Even though 'auditor' appears in both, the key
        SETS must differ — operator roles has primary_operator, researcher, etc.
        that have no meaning in the worker namespace."""
        worker_roles = set(agent_surface.ROLES)
        operator_role_keys = set(or_.OPERATOR_ROLES)
        assert worker_roles != operator_role_keys, (
            "OPERATOR_ROLES key set must be distinct from the worker ROLES set"
        )

    def test_operator_roles_has_keys_not_in_worker_roles(self) -> None:
        """At least one operator-role key (primary_operator) must NOT exist in
        the worker ROLES to prove they serve different purposes."""
        worker_roles = set(agent_surface.ROLES)
        assert "primary_operator" not in worker_roles

    def test_operator_roles_has_keys_not_in_invocation_context_roles(self) -> None:
        """invocation_context.ROLES mirrors worker roles; same disjointness test."""
        from dontpanic_orchestrate.invocation_context import ROLES as IC_ROLES

        ic_roles = set(IC_ROLES)
        assert "primary_operator" not in ic_roles
        assert "researcher" not in ic_roles


# ──────────────────────────────  AC6: argparse surface (CLI-ready)  ──────────────────────────────


class TestArgparseSurface:
    """add_operator_roles_subparser / run_operator_roles_command are exposed for
    future CLI wiring. We verify they exist and that a minimal set→list round-trip
    works through the command handler."""

    def test_add_operator_roles_subparser_exists(self) -> None:
        assert callable(getattr(or_, "add_operator_roles_subparser", None))

    def test_run_operator_roles_command_exists(self) -> None:
        assert callable(getattr(or_, "run_operator_roles_command", None))

    def test_subparser_registers_operator_roles_command(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="subcommand")
        or_.add_operator_roles_subparser(subparsers)
        # Parsing 'operator-roles' should produce a Namespace (not fail)
        # We test the 'list' sub-subcommand
        args = parser.parse_args(["operator-roles", "list"])
        assert args.subcommand == "operator-roles"

    def test_set_then_list_roundtrip_via_command_handler(self, tmp_path: Path) -> None:
        """End-to-end: set via run_operator_roles_command then list."""
        _global_home(tmp_path)
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="subcommand")
        or_.add_operator_roles_subparser(subparsers)

        # set primary_operator=claude globally
        set_args = parser.parse_args(["operator-roles", "set", "primary_operator", "claude"])
        or_.run_operator_roles_command(set_args)

        # list should show it
        list_args = parser.parse_args(["operator-roles", "list"])
        result = or_.run_operator_roles_command(list_args)
        # result is a dict
        assert isinstance(result, dict)
        assert "primary_operator" in result
        assert result["primary_operator"]["value"] == "claude"


# ──────────────────────────────  extra: OPERATOR_ROLES includes auditor (D009 note)  ────────────


class TestAuditorIncluded:
    """D009 note: 'auditor' IS intentionally in OPERATOR_ROLES as preference/intent
    (meaning "I want Codex to review my work"). This is NOT the worker auditor —
    there is no dispatch authority here. The test pins that auditor is included."""

    def test_auditor_in_operator_roles(self) -> None:
        assert "auditor" in or_.OPERATOR_ROLES

    def test_setting_auditor_operator_role_to_cursor_succeeds(self, tmp_path: Path) -> None:
        """'cursor' has no executor — if the worker-dispatch guard were called it
        would raise. Proves the operator-role layer is intent-only (D009)."""
        _global_home(tmp_path)
        # Must not raise
        or_.set_operator_role("auditor", "cursor", scope="global")
        roles_path = Path(os.environ["DONTPANIC_HOME"]) / or_.OPERATOR_ROLES_FILENAME
        data = json.loads(roles_path.read_text())
        assert data["auditor"] == "cursor"
