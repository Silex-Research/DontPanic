"""Plan 2026-05-03-003 F001 — global agent manifest.

Tests cover the deterministic acceptance for the agent-discoverability file
at ``~/.dontpanic/agent-manifest.json`` (preferred) / ``~/.jarvis/agent-manifest.json``
(legacy fallback):

- Pydantic v2 schema with ``extra='forbid'`` (D006 secret-free invariant)
- ``install_source`` enum {pipx, pip-editable, source}
- ``schema_version`` pinned at "1.0"
- ``safety_rules`` MUST contain the "do not dispatch without user approval"
  rule (D007)
- Load is total: missing → None, invalid JSON → WARN+None, schema-violation
  → WARN+None
- Save is regenerable: same inputs → byte-identical file (D006)
- Bootstrap collects host inputs (dontpanic version, install source, CLI path)
- CLI: ``dontpanic manifest {init|show}`` with ``--json``, collision exit 2,
  ``--force --yes`` overwrite (parity with ``dontpanic projects add``)

All tests redirect ``$DONTPANIC_HOME`` to ``tmp_path`` so the user's real
``~/.dontpanic/agent-manifest.json`` is never read or written. ``$JARVIS_HOME``
is unset so legacy-fallback paths are deterministic per test.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_f001_agent_manifest.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import agent_manifest as am  # noqa: E402
from jarvis_orchestrate import cli  # noqa: E402
from jarvis_orchestrate import global_config as gc  # noqa: E402

# Canonical safety-rule string (D007). Must appear verbatim in the manifest's
# safety_rules field — every agent reading the manifest sees it.
SAFETY_RULE_NO_AUTO_DISPATCH = (
    "Always surface the plan to the user before calling "
    "dispatch(confirm=true). Do NOT auto-confirm."
)


@pytest.fixture(autouse=True)
def _isolate_dontpanic_home(tmp_path, monkeypatch):
    """Reroute ``$DONTPANIC_HOME`` to a tmp dir so the user's real
    ``~/.dontpanic/agent-manifest.json`` is never touched. Unset
    ``$JARVIS_HOME`` so legacy-fallback resolution is deterministic
    in every test."""
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))


def _valid_manifest_kwargs(**overrides):
    """Build the minimum-valid AgentManifest input dict. Tests that need to
    construct a fresh manifest use this and override only the fields they
    care about."""
    base = {
        "schema_version": "1.0",
        "dontpanic_version": "0.1.0",
        "install_source": "source",
        "cli_path": "/usr/local/bin/dontpanic",
        "project_registry_path": "/Users/test/.dontpanic/projects.json",
        "supported_commands": ["projects", "doctor", "manifest"],
        "safety_rules": [SAFETY_RULE_NO_AUTO_DISPATCH],
    }
    base.update(overrides)
    return base


# ──────────────────────────────  schema (D006 + D007)  ──────────────────────────────


class TestSchema:
    def test_minimum_valid_manifest(self):
        m = am.AgentManifest(**_valid_manifest_kwargs())
        assert m.schema_version == "1.0"
        assert m.dontpanic_version == "0.1.0"
        assert m.install_source == "source"
        # mcp_server is optional and defaults to None — F001 ships without it;
        # F002 lands the server and re-runs bootstrap to populate it.
        assert m.mcp_server is None

    def test_extra_field_forbidden(self):
        with pytest.raises(ValueError):
            am.AgentManifest(
                **_valid_manifest_kwargs(),
                rogue_field="x",  # type: ignore[call-arg]
            )

    @pytest.mark.parametrize(
        "bad_install_source",
        ["", "wheel", "git", "snap", "homebrew", "Pip", "PIPX"],
    )
    def test_install_source_enum_rejects_unknown(self, bad_install_source):
        with pytest.raises(ValueError):
            am.AgentManifest(**_valid_manifest_kwargs(install_source=bad_install_source))

    @pytest.mark.parametrize("good_install_source", ["pipx", "pip-editable", "source"])
    def test_install_source_enum_accepts_known(self, good_install_source):
        m = am.AgentManifest(**_valid_manifest_kwargs(install_source=good_install_source))
        assert m.install_source == good_install_source

    @pytest.mark.parametrize(
        "credential_shaped_field",
        [
            "api_token",
            "auth_token",
            "secret_key",
            "service_account_key",
            "openai_api_key",
            "auth_secret",
            "private_secret",
        ],
    )
    def test_credential_shaped_extra_fields_rejected(self, credential_shaped_field):
        # D006: manifest is secret-free. The schema's `extra='forbid'` rejects
        # ALL unknown fields, but credential-shaped names get extra-loud
        # treatment in the surface so an operator's "I'll just stash my API
        # key here" mistake is caught early.
        with pytest.raises(ValueError):
            am.AgentManifest(
                **_valid_manifest_kwargs(),
                **{credential_shaped_field: "leaked-secret-value"},
            )

    def test_schema_defines_no_credential_shaped_fields(self):
        # D006 design discipline: the manifest's OWN field names must not
        # contain `_token` / `_key` / `_secret`. A future contributor adding
        # such a field accidentally is caught here, not by sanitization
        # post-hoc. This is meta-validation against the model class itself.
        forbidden_substrings = ("_token", "_key", "_secret")
        for field_name in am.AgentManifest.model_fields:
            for substring in forbidden_substrings:
                assert substring not in field_name, (
                    f"AgentManifest.{field_name} contains forbidden substring "
                    f"{substring!r}; secret-shaped field names are banned by D006"
                )

    def test_safety_rules_contains_no_auto_dispatch_rule(self):
        # D007: the canonical "do not dispatch without user approval" rule
        # must appear in the manifest's safety_rules. The schema does not
        # require it (the schema is generic), but bootstrap_manifest +
        # write_manifest must produce manifests that contain it. Tested
        # via TestBootstrap.test_bootstrap_safety_rule below; here we just
        # confirm a manifest CAN carry the canonical string.
        m = am.AgentManifest(**_valid_manifest_kwargs(safety_rules=[SAFETY_RULE_NO_AUTO_DISPATCH]))
        assert SAFETY_RULE_NO_AUTO_DISPATCH in m.safety_rules

    def test_required_fields_missing_rejected(self):
        # All required fields must be present. Pydantic ValidationError on miss.
        with pytest.raises(ValueError):
            am.AgentManifest(  # type: ignore[call-arg]
                schema_version="1.0",
                dontpanic_version="0.1.0",
                install_source="source",
                # cli_path missing
                project_registry_path="/x.json",
                supported_commands=[],
                safety_rules=[],
            )


# ──────────────────────────────  paths + load/save  ──────────────────────────────


class TestPaths:
    def test_manifest_path_under_dontpanic_home(self, tmp_path):
        # Fixture set $DONTPANIC_HOME to tmp_path/.dontpanic.
        path = am.manifest_path()
        assert path == tmp_path / ".dontpanic" / "agent-manifest.json"

    def test_manifest_path_under_jarvis_home_legacy_fallback(self, tmp_path, monkeypatch):
        # If $DONTPANIC_HOME is unset and $JARVIS_HOME is set, the manifest
        # path resolves under the legacy directory. Existing installs do
        # not break.
        monkeypatch.delenv(gc.DONTPANIC_HOME_ENV, raising=False)
        monkeypatch.setenv(gc.JARVIS_HOME_ENV, str(tmp_path / ".jarvis"))
        path = am.manifest_path()
        assert path == tmp_path / ".jarvis" / "agent-manifest.json"


class TestLoadSave:
    def test_missing_file_returns_none(self):
        assert am.load_manifest() is None

    def test_save_then_load_roundtrip(self):
        m = am.AgentManifest(**_valid_manifest_kwargs())
        am.write_manifest(m)
        reloaded = am.load_manifest()
        assert reloaded == m

    def test_invalid_json_warns_returns_none(self, caplog):
        gc.ensure_dontpanic_home()
        am.manifest_path().write_text("not json {{{")
        with caplog.at_level(logging.WARNING, logger="jarvis_orchestrate.agent_manifest"):
            result = am.load_manifest()
        assert result is None
        assert any("invalid JSON" in m or "unreadable" in m for m in caplog.messages)

    def test_extra_field_in_persisted_manifest_warns_returns_none(self, caplog):
        gc.ensure_dontpanic_home()
        raw = _valid_manifest_kwargs()
        raw["rogue_field"] = "x"
        am.manifest_path().write_text(json.dumps(raw))
        with caplog.at_level(logging.WARNING, logger="jarvis_orchestrate.agent_manifest"):
            result = am.load_manifest()
        assert result is None
        assert any("schema validation" in m for m in caplog.messages)

    def test_save_creates_dontpanic_home_if_missing(self, tmp_path):
        # Fixture set $DONTPANIC_HOME but didn't create it.
        target = tmp_path / ".dontpanic"
        assert not target.exists()
        am.write_manifest(am.AgentManifest(**_valid_manifest_kwargs()))
        assert target.is_dir()
        assert (target / "agent-manifest.json").is_file()

    def test_save_legacy_jarvis_home_still_writes_manifest(self, tmp_path, monkeypatch):
        # $JARVIS_HOME-only env still writes (legacy compat).
        monkeypatch.delenv(gc.DONTPANIC_HOME_ENV, raising=False)
        monkeypatch.setenv(gc.JARVIS_HOME_ENV, str(tmp_path / ".jarvis"))
        path = am.write_manifest(am.AgentManifest(**_valid_manifest_kwargs()))
        assert path == tmp_path / ".jarvis" / "agent-manifest.json"
        assert path.is_file()


# ──────────────────────────────  D006: regenerable + idempotent  ──────────────────────────────


class TestRegenerable:
    """D006 invariant: re-running write_manifest with the same inputs produces
    a byte-identical file. No timestamps in the body, no nondeterministic
    list ordering. Operators (or future bootstrap) can `rm` the file and
    re-bootstrap without losing state."""

    def test_byte_identical_rewrite(self):
        m = am.AgentManifest(**_valid_manifest_kwargs())
        path1 = am.write_manifest(m)
        bytes1 = path1.read_bytes()
        path2 = am.write_manifest(m)
        bytes2 = path2.read_bytes()
        assert path1 == path2
        assert bytes1 == bytes2

    def test_no_iso_timestamp_in_body(self):
        # D006: no nondeterministic timestamps. A naive implementation might
        # stamp a "generated_at" field; this test catches that regression.
        m = am.AgentManifest(**_valid_manifest_kwargs())
        path = am.write_manifest(m)
        body = path.read_text()
        # Match ISO-8601 like 2026-05-03T15:00:00Z. None of the input fields
        # carry timestamps, so any match means a non-input timestamp leaked.
        import re

        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", body), (
            "manifest body contains an ISO timestamp; this breaks the "
            "regenerable invariant (D006). If a timestamp is genuinely "
            "needed, surface it as an explicit input the caller controls."
        )

    def test_extra_none_fields_excluded_from_disk(self):
        # mcp_server is optional and None when F002 hasn't shipped yet. The
        # on-disk file should NOT serialize None fields; otherwise re-running
        # on a different machine where F002 is later present would produce
        # different bytes for the same logical state.
        m = am.AgentManifest(**_valid_manifest_kwargs())
        assert m.mcp_server is None
        path = am.write_manifest(m)
        raw = json.loads(path.read_text())
        assert "mcp_server" not in raw


# ──────────────────────────────  D006: secret-free invariant  ──────────────────────────────


class TestSecretFree:
    """D006: a written manifest must contain no operator-specific secrets.
    Combined with TestSchema.test_credential_shaped_extra_fields_rejected,
    these two surfaces ensure both schema-level and content-level discipline."""

    def test_written_manifest_contains_no_credential_substrings(self):
        m = am.AgentManifest(**_valid_manifest_kwargs())
        path = am.write_manifest(m)
        body = path.read_text().lower()
        # The cli_path containing literal "token" or "secret" would be a
        # legitimate concern, but the test fixture uses a clean path.
        # If a future field unintentionally surfaces credential-shaped
        # content, this test catches it.
        for needle in ("api_token", "secret_key", "auth_secret", "service_account"):
            assert needle not in body, (
                f"manifest body contains credential-shaped substring "
                f"{needle!r} (D006 secret-free invariant)"
            )


# ──────────────────────────────  bootstrap  ──────────────────────────────


class TestBootstrap:
    """bootstrap_manifest collects host inputs (version + install source +
    CLI path) and returns a fresh AgentManifest. Safe to re-run."""

    def test_bootstrap_pins_dontpanic_version_from_init(self):
        from jarvis_orchestrate import __version__

        m = am.bootstrap_manifest(install_source="source", cli_path="/x")
        assert m.dontpanic_version == __version__

    def test_bootstrap_schema_version_pinned_at_1_0(self):
        m = am.bootstrap_manifest(install_source="source", cli_path="/x")
        assert m.schema_version == "1.0"

    def test_bootstrap_safety_rule_present_verbatim(self):
        # D007: the canonical "do not dispatch without user approval" rule
        # MUST be in the bootstrapped manifest's safety_rules.
        m = am.bootstrap_manifest(install_source="source", cli_path="/x")
        assert SAFETY_RULE_NO_AUTO_DISPATCH in m.safety_rules

    def test_bootstrap_idempotent(self):
        # Same inputs → same output. This composes with the regenerable
        # invariant: bootstrap → write produces a byte-identical file every
        # time the bootstrap inputs match.
        m1 = am.bootstrap_manifest(install_source="source", cli_path="/x")
        m2 = am.bootstrap_manifest(install_source="source", cli_path="/x")
        assert m1 == m2

    def test_bootstrap_project_registry_path_under_dontpanic_home(self, tmp_path):
        m = am.bootstrap_manifest(install_source="source", cli_path="/x")
        # Fixture put $DONTPANIC_HOME at tmp_path/.dontpanic.
        assert m.project_registry_path == str(tmp_path / ".dontpanic" / "projects.json")

    def test_bootstrap_supported_commands_includes_core_set(self):
        m = am.bootstrap_manifest(install_source="source", cli_path="/x")
        # The exact list may grow; the core Phase A surface must be advertised.
        for required in ("projects", "doctor", "manifest"):
            assert required in m.supported_commands

    def test_bootstrap_populates_mcp_server_when_f002_importable(self):
        """Plan 2026-05-03-003 F002 amendment: once F002's mcp_server module
        ships, bootstrap_manifest() detects it via :func:`_detect_mcp_server`
        and populates the manifest's ``mcp_server`` field with the canonical
        ``dontpanic mcp serve`` invocation. Before F002 shipped this field
        stayed ``None``; the regression test pins the post-F002 invariant
        so a future change that drops the wiring is caught."""
        from jarvis_orchestrate import mcp_server

        m = am.bootstrap_manifest(install_source="source", cli_path="/x")
        assert m.mcp_server is not None, (
            "F002's mcp_server module is importable, so bootstrap_manifest() "
            "must populate the manifest's mcp_server block. See plan "
            "2026-05-03-003 audit-focus #6."
        )
        assert m.mcp_server.command == mcp_server.MCP_SERVER_COMMAND
        assert m.mcp_server.args == list(mcp_server.MCP_SERVER_ARGS)
        # Operator-canonical surface (D011): use `dontpanic mcp serve`, not
        # `python -m dontpanic_orchestrate mcp serve`.
        assert m.mcp_server.command == "dontpanic"
        assert m.mcp_server.args == ["mcp", "serve"]

    def test_bootstrap_supported_commands_includes_mcp_when_f002_present(self):
        """F002 amendment: the ``mcp`` subcommand is appended to
        supported_commands once F002 ships, so agents reading the manifest
        learn about the new surface without operator action."""
        m = am.bootstrap_manifest(install_source="source", cli_path="/x")
        assert "mcp" in m.supported_commands


# ──────────────────────────────  CLI: dontpanic manifest init|show  ──────────────────────────────


class TestCLIInit:
    def test_init_writes_manifest(self, capsys):
        rc = cli.main(["manifest", "init"])
        assert rc == 0
        # File now exists at the expected path.
        assert am.load_manifest() is not None

    def test_init_collision_exits_2(self, capsys):
        cli.main(["manifest", "init"])
        capsys.readouterr()
        rc = cli.main(["manifest", "init"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "already" in err.lower() or "exists" in err.lower()

    def test_init_force_without_yes_refuses(self, capsys):
        cli.main(["manifest", "init"])
        capsys.readouterr()
        rc = cli.main(["manifest", "init", "--force"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "--yes" in err

    def test_init_force_yes_overwrites(self, capsys):
        cli.main(["manifest", "init"])
        capsys.readouterr()
        rc = cli.main(["manifest", "init", "--force", "--yes"])
        assert rc == 0
        assert am.load_manifest() is not None

    def test_init_json_output(self, capsys):
        rc = cli.main(["manifest", "init", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["action"] == "wrote"
        assert "manifest" in payload
        assert payload["manifest"]["schema_version"] == "1.0"

    def test_init_cli_path_override(self, capsys):
        rc = cli.main(["manifest", "init", "--cli-path", "/custom/dontpanic"])
        assert rc == 0
        m = am.load_manifest()
        assert m is not None
        assert m.cli_path == "/custom/dontpanic"


class TestCLIShow:
    def test_show_existing(self, capsys):
        cli.main(["manifest", "init"])
        capsys.readouterr()
        rc = cli.main(["manifest", "show"])
        assert rc == 0
        out = capsys.readouterr().out
        # Default `show` prints structured JSON for readability + agent parsing.
        payload = json.loads(out)
        assert payload["schema_version"] == "1.0"

    def test_show_missing_exits_2(self, capsys):
        rc = cli.main(["manifest", "show"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "not found" in err.lower() or "missing" in err.lower()

    def test_show_json(self, capsys):
        cli.main(["manifest", "init"])
        capsys.readouterr()
        rc = cli.main(["manifest", "show", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["dontpanic_version"]


class TestCLIDispatch:
    def test_no_subcommand_prints_usage(self, capsys):
        rc = cli.main(["manifest"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "usage" in err.lower()
        assert "init" in err and "show" in err

    def test_unknown_subcommand_exits_2(self, capsys):
        rc = cli.main(["manifest", "delete"])
        assert rc == 2

    def test_works_from_arbitrary_cwd(self, tmp_path, monkeypatch, capsys):
        # The manifest is machine-level state — operating from any cwd works.
        unrelated = tmp_path / "some" / "other" / "place"
        unrelated.mkdir(parents=True)
        monkeypatch.chdir(unrelated)
        rc = cli.main(["manifest", "init"])
        assert rc == 0
        assert am.load_manifest() is not None
