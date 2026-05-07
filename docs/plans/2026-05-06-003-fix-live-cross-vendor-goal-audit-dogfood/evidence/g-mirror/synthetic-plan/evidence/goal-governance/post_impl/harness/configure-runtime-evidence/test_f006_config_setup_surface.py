"""Plan G F006 / G0 — Minimum operator configuration surface.

Tests cover:

  - ``RolesConfig`` + ``RuntimeEvidenceConfig`` Pydantic shape (extra='forbid').
  - Global config gains ``roles`` block (D013); ``runtime_evidence`` is
    NOT a global field at all (D015 enforced both via Pydantic and
    greppable source assertion).
  - Project config gains ``roles`` AND ``runtime_evidence`` blocks.
  - ``resolve_role`` precedence: per-call > project.roles > project legacy
    (``implementer`` / ``auditor``) > global.roles > global legacy
    (``default_implementer`` / ``default_auditor``) > hardcoded fallback.
  - ``resolve_runtime_evidence`` precedence: per-call > project.runtime_evidence
    > empty (no global tier per D015).
  - ``dontpanic config show/set`` — happy path + invalid key + canonical
    write to ``roles.implementer`` (not legacy ``default_implementer``).
  - ``dontpanic project config init/set`` — happy path, ``--overwrite``
    discipline, refusal to write ``runtime_evidence`` at the global tier.
  - ``dontpanic setup`` — preview-by-default, ``--yes`` mutates,
    non-interactive without ``--yes`` refuses, secret-shaped pointer
    values rejected (D014).
  - Doctor framework: ``register_doctor_check`` + ``run_all_checks``,
    idempotent registration. F006 ships baseline check only — adapter-
    specific checks land with G2-G5 (D013).
  - F003 (sufficiency_auditor) reads ``roles.goal_auditor`` first, falls
    through to existing default_auditor / hardcoded path when absent.
  - Greppable D014 assertion: ``config/`` package and CLI subcommand
    bodies contain no credential-bearing literals.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_f006_config_setup_surface.py
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import cli  # noqa: E402
from dontpanic_orchestrate import global_config as gc  # noqa: E402
from dontpanic_orchestrate import project_config as pc  # noqa: E402
from dontpanic_orchestrate import projects_registry as pr  # noqa: E402
from dontpanic_orchestrate import sufficiency_auditor as sa  # noqa: E402
from dontpanic_orchestrate.config import (  # noqa: E402, I001
    RolesConfig,
    RuntimeEvidenceConfig,
    doctor_registry,
    resolvers,
)
from dontpanic_orchestrate.config import setup as setup_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_dontpanic_home(tmp_path, monkeypatch):
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))
    # Reset doctor-registry singleton between tests so registrations don't
    # cross-pollinate (the registry is intentionally process-level singleton
    # — adapters register at import time).
    doctor_registry._reset_for_tests()


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "some-project"
    d.mkdir()
    return d


# ────────────────────────────  Pydantic shape  ────────────────────────────


class TestPydanticShape:
    def test_roles_config_all_fields_optional(self):
        cfg = RolesConfig()
        assert cfg.implementer is None
        assert cfg.auditor is None
        assert cfg.goal_auditor is None

    def test_roles_config_extra_forbidden(self):
        with pytest.raises(ValidationError):
            RolesConfig.model_validate({"implementer": "claude", "stranger": "x"})

    def test_runtime_evidence_config_all_fields_optional(self):
        cfg = RuntimeEvidenceConfig()
        assert cfg.web is None
        assert cfg.ios is None
        assert cfg.android is None
        assert cfg.backend is None

    def test_runtime_evidence_config_extra_forbidden(self):
        with pytest.raises(ValidationError):
            RuntimeEvidenceConfig.model_validate({"web": {"base_url": "http://x"}, "stranger": {}})

    def test_runtime_evidence_sub_models_extra_forbidden(self):
        with pytest.raises(ValidationError):
            RuntimeEvidenceConfig.model_validate(
                {"web": {"base_url": "http://x", "extra_thing": True}}
            )


# ────────────────────────────  D015 enforcement  ────────────────────────────


class TestD015GlobalConfigRefusesRuntimeEvidence:
    def test_global_config_has_no_runtime_evidence_field(self):
        # Pydantic enforcement: ``runtime_evidence`` is NOT a field on GlobalConfig.
        # Setting it must fail because GlobalConfig has extra='forbid'.
        with pytest.raises(ValidationError):
            gc.GlobalConfig.model_validate({"runtime_evidence": {"web": {"base_url": "http://x"}}})

    def test_global_config_accepts_roles_block(self):
        cfg = gc.GlobalConfig.model_validate(
            {"roles": {"implementer": "claude", "auditor": "codex", "goal_auditor": "codex"}}
        )
        assert cfg.roles is not None
        assert cfg.roles.implementer == "claude"
        assert cfg.roles.goal_auditor == "codex"

    def test_greppable_global_config_source_has_no_runtime_evidence(self):
        # Defense in depth: a future contributor cannot silently slip a
        # ``runtime_evidence`` field onto GlobalConfig because the source
        # is grepped here (D015).
        src = (HERE.parents[2] / "dontpanic_orchestrate" / "global_config.py").read_text()
        # Only allowance: docstrings/comments may mention it, but a Pydantic
        # field declaration `runtime_evidence: ...` must not exist.
        assert not re.search(r"^\s*runtime_evidence\s*:", src, flags=re.MULTILINE), (
            "GlobalConfig must not declare a runtime_evidence field (D015 — "
            "runtime evidence is project-scoped only)"
        )


class TestProjectConfigAcceptsBothBlocks:
    def test_project_config_accepts_roles_and_runtime_evidence(self, project_dir):
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps(
                {
                    "roles": {"implementer": "claude", "goal_auditor": "codex"},
                    "runtime_evidence": {
                        "web": {"base_url": "http://localhost:3000"},
                        "ios": {"scheme": "Glam", "simulator": "iPhone 15"},
                        "android": {
                            "package": "com.example.app",
                            "adb_device_serial": "emulator-5554",
                        },
                        "backend": {"provider": "firebase", "project": "myproj-dev", "auth": "adc"},
                    },
                }
            )
        )
        cfg = pc.load_project_config(project_dir)
        assert cfg is not None
        assert cfg.roles is not None
        assert cfg.roles.implementer == "claude"
        assert cfg.roles.goal_auditor == "codex"
        assert cfg.runtime_evidence is not None
        assert cfg.runtime_evidence.web is not None
        assert cfg.runtime_evidence.web.base_url == "http://localhost:3000"
        assert cfg.runtime_evidence.backend is not None
        assert cfg.runtime_evidence.backend.auth == "adc"


# ────────────────────────────  Resolution layering  ────────────────────────────


class TestResolveRole:
    def test_per_call_wins_over_all(self, project_dir, tmp_path):
        # Set every layer; per-call still wins.
        gc.save_config(gc.GlobalConfig(roles=RolesConfig(implementer="global-impl")))
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"roles": {"implementer": "project-impl"}}))
        result = resolvers.resolve_role(project_dir, "implementer", per_call="caller-impl")
        assert result == "caller-impl"

    def test_project_roles_wins_over_global_roles(self, project_dir):
        gc.save_config(gc.GlobalConfig(roles=RolesConfig(implementer="global-impl")))
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"roles": {"implementer": "project-impl"}}))
        assert resolvers.resolve_role(project_dir, "implementer") == "project-impl"

    def test_legacy_project_implementer_field_honored(self, project_dir):
        # Legacy: pre-F006 projects set ``implementer`` at top-level.
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"implementer": "legacy-impl"}))
        assert resolvers.resolve_role(project_dir, "implementer") == "legacy-impl"

    def test_roles_block_wins_over_legacy_within_same_file(self, project_dir):
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps({"implementer": "legacy-impl", "roles": {"implementer": "new-impl"}})
        )
        assert resolvers.resolve_role(project_dir, "implementer") == "new-impl"

    def test_legacy_global_default_implementer_honored(self, project_dir):
        gc.save_config(gc.GlobalConfig(default_implementer="legacy-global-impl"))
        assert resolvers.resolve_role(project_dir, "implementer") == "legacy-global-impl"

    def test_global_roles_wins_over_legacy_global(self, project_dir):
        gc.save_config(
            gc.GlobalConfig(
                default_implementer="legacy-global-impl",
                roles=RolesConfig(implementer="new-global-impl"),
            )
        )
        assert resolvers.resolve_role(project_dir, "implementer") == "new-global-impl"

    def test_hardcoded_fallback_when_all_layers_unset(self, project_dir):
        assert resolvers.resolve_role(project_dir, "implementer") == "claude"
        assert resolvers.resolve_role(project_dir, "auditor") == "codex"

    def test_goal_auditor_no_legacy_field_falls_through_to_auditor(self, project_dir):
        # ``goal_auditor`` has no legacy field — falls back to auditor when
        # nothing names it explicitly. Operator can override by setting
        # ``roles.goal_auditor`` on either tier.
        gc.save_config(gc.GlobalConfig(default_auditor="legacy-aud"))
        assert resolvers.resolve_role(project_dir, "goal_auditor") == "legacy-aud"

    def test_goal_auditor_explicit_wins(self, project_dir):
        gc.save_config(gc.GlobalConfig(roles=RolesConfig(goal_auditor="explicit-goal-aud")))
        assert resolvers.resolve_role(project_dir, "goal_auditor") == "explicit-goal-aud"

    def test_unknown_role_name_raises(self, project_dir):
        with pytest.raises(ValueError, match="unknown role"):
            resolvers.resolve_role(project_dir, "stranger")  # type: ignore[arg-type]


class TestResolveRuntimeEvidence:
    def test_per_call_wins(self, project_dir):
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps({"runtime_evidence": {"web": {"base_url": "http://project:3000"}}})
        )
        result = resolvers.resolve_runtime_evidence(
            project_dir, "web", per_call={"base_url": "http://caller:8080"}
        )
        assert result["base_url"] == "http://caller:8080"

    def test_project_only_when_no_per_call(self, project_dir):
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps({"runtime_evidence": {"web": {"base_url": "http://project:3000"}}})
        )
        result = resolvers.resolve_runtime_evidence(project_dir, "web")
        assert result == {"base_url": "http://project:3000"}

    def test_empty_dict_when_no_layer_set(self, project_dir):
        # No global tier per D015. Empty dict is the valid zero state.
        result = resolvers.resolve_runtime_evidence(project_dir, "web")
        assert result == {}

    def test_unknown_source_raises(self, project_dir):
        with pytest.raises(ValueError, match="unknown source"):
            resolvers.resolve_runtime_evidence(project_dir, "stranger")  # type: ignore[arg-type]

    def test_per_call_merges_atop_project_defaults(self, project_dir):
        # Per-call overrides specific keys but doesn't blow away the rest.
        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps({"runtime_evidence": {"ios": {"scheme": "Glam", "simulator": "iPhone 15"}}})
        )
        result = resolvers.resolve_runtime_evidence(
            project_dir, "ios", per_call={"simulator": "iPhone 16 Pro"}
        )
        assert result["scheme"] == "Glam"
        assert result["simulator"] == "iPhone 16 Pro"


# ────────────────────────────  CLI: config show/set  ────────────────────────────


class TestConfigCLI:
    def test_config_show_empty_emits_resolved_view(self, capsys):
        rc = cli.main(["config", "show"])
        assert rc == 0
        out = capsys.readouterr().out
        # Resolved view always includes roles block (possibly empty) and the
        # legacy fields surfaced through it for migration clarity.
        assert "roles" in out

    def test_config_set_writes_to_roles_block(self, capsys):
        rc = cli.main(["config", "set", "roles.implementer", "claude"])
        assert rc == 0
        cfg = gc.load_config()
        assert cfg.roles is not None
        assert cfg.roles.implementer == "claude"

    def test_config_set_legacy_default_implementer_still_works(self, capsys):
        # Operators with muscle memory for the old key still get a working
        # write (forwarded to roles.implementer for canonical storage).
        rc = cli.main(["config", "set", "default_implementer", "claude"])
        assert rc == 0
        cfg = gc.load_config()
        # The legacy key writes through the legacy field for round-trip
        # readability (config show still surfaces it via the resolved view).
        assert cfg.default_implementer == "claude" or (
            cfg.roles is not None and cfg.roles.implementer == "claude"
        )

    def test_config_set_runtime_evidence_refused_at_global(self, capsys):
        # D015: runtime_evidence is per-project only. Global writes refuse.
        rc = cli.main(["config", "set", "runtime_evidence.web.base_url", "http://x"])
        assert rc != 0
        err = capsys.readouterr().err
        assert "project" in err.lower()  # message points operator at per-project

    def test_config_set_unknown_key_refused(self, capsys):
        rc = cli.main(["config", "set", "stranger.field", "value"])
        assert rc != 0

    def test_config_set_invalid_value_refused(self, capsys):
        # Empty string for a role isn't useful — refuse rather than silently
        # storing nothing.
        rc = cli.main(["config", "set", "roles.implementer", ""])
        assert rc != 0


# ────────────────────────────  CLI: project config init/set  ────────────────────────────


class TestProjectConfigCLI:
    def test_project_config_init_writes_skeleton(self, project_dir, capsys, monkeypatch):
        monkeypatch.chdir(project_dir)
        rc = cli.main(["project", "config", "init"])
        assert rc == 0
        path = pc.project_config_path(project_dir)
        assert path.is_file()
        assert path.read_text().strip() in ("{}", "{}\n", "{\n}")

    def test_project_config_init_refuses_overwrite(self, project_dir, capsys, monkeypatch):
        monkeypatch.chdir(project_dir)
        cli.main(["project", "config", "init"])
        rc = cli.main(["project", "config", "init"])
        assert rc != 0
        err = capsys.readouterr().err
        assert "exists" in err.lower() or "refus" in err.lower()

    def test_project_config_init_overwrite_flag_works(self, project_dir, capsys, monkeypatch):
        monkeypatch.chdir(project_dir)
        cli.main(["project", "config", "init"])
        rc = cli.main(["project", "config", "init", "--overwrite"])
        assert rc == 0

    def test_project_config_set_runtime_evidence_writes(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        cli.main(["project", "config", "init"])
        rc = cli.main(
            [
                "project",
                "config",
                "set",
                "runtime_evidence.web.base_url",
                "http://localhost:3000",
            ]
        )
        assert rc == 0
        cfg = pc.load_project_config(project_dir)
        assert cfg is not None
        assert cfg.runtime_evidence is not None
        assert cfg.runtime_evidence.web is not None
        assert cfg.runtime_evidence.web.base_url == "http://localhost:3000"

    def test_project_config_set_roles_writes(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        cli.main(["project", "config", "init"])
        rc = cli.main(["project", "config", "set", "roles.goal_auditor", "codex"])
        assert rc == 0
        cfg = pc.load_project_config(project_dir)
        assert cfg is not None
        assert cfg.roles is not None
        assert cfg.roles.goal_auditor == "codex"


# ────────────────────────────  CLI: setup  ────────────────────────────


class TestSetupCLI:
    def test_setup_preview_by_default(self, capsys, monkeypatch):
        # No --yes → preview only, no writes. Non-interactive (no stdin TTY)
        # so we don't actually prompt.
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        rc = cli.main(["setup", "--implementer", "claude", "--auditor", "codex"])
        assert rc == 0
        # Config file MUST NOT exist after preview.
        assert not gc.config_path().exists()
        out = capsys.readouterr().out
        assert "preview" in out.lower() or "would write" in out.lower()

    def test_setup_yes_actually_writes(self, capsys, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        rc = cli.main(["setup", "--implementer", "claude", "--auditor", "codex", "--yes"])
        assert rc == 0
        assert gc.config_path().exists()
        cfg = gc.load_config()
        assert cfg.roles is not None
        assert cfg.roles.implementer == "claude"
        assert cfg.roles.auditor == "codex"

    def test_setup_non_interactive_without_yes_refuses_when_no_args(self, capsys, monkeypatch):
        # No TTY + no flags + no --yes: nothing to preview, nothing to write.
        # Should refuse with exit 2 (usage error) rather than hang on input.
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        rc = cli.main(["setup"])
        assert rc != 0


class TestSetupCredentialPointerValidation:
    """D014 — setup refuses secret-shaped values for pointer fields."""

    @pytest.mark.parametrize(
        "rejected_value",
        [
            "AKIAIOSFODNN7EXAMPLE",  # AWS-shaped
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",  # GitHub PAT-shaped
            "Bearer abcdef.ghijkl.mnopqr",  # bearer literal
            "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789",  # OpenAI-shaped
            "xoxb-1234567890-abcdef",  # Slack token-shaped
        ],
    )
    def test_setup_rejects_secret_shaped_backend_auth(self, capsys, monkeypatch, rejected_value):
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        rc = cli.main(
            [
                "setup",
                "--backend-provider",
                "firebase",
                "--backend-project",
                "myproj-dev",
                "--backend-auth",
                rejected_value,
                "--yes",
            ]
        )
        assert rc != 0
        err = capsys.readouterr().err.lower()
        assert "credential" in err or "pointer" in err or "secret" in err

    @pytest.mark.parametrize(
        "accepted_value",
        [
            "adc",  # Application Default Credentials sentinel
            "env:GLAM_FIREBASE_SA",  # env-var pointer
            "./secrets/sa.json",  # path-only pointer
            "~/.config/firebase-sa.json",  # home-relative path
            "/abs/path/to/sa.json",  # absolute path
        ],
    )
    def test_setup_accepts_pointer_shapes(self, capsys, monkeypatch, accepted_value):
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        rc = cli.main(
            [
                "setup",
                "--backend-provider",
                "firebase",
                "--backend-project",
                "myproj-dev",
                "--backend-auth",
                accepted_value,
                "--project-dir",
                str(Path.cwd()),  # accept current dir; doesn't actually mutate without --yes
            ]
        )
        # Preview run — must succeed (rc=0) without secret rejection.
        assert rc == 0


class TestSetupValidatorUnit:
    """Unit tests of the pointer-shape validator that ``setup`` calls."""

    @pytest.mark.parametrize(
        "value",
        [
            "adc",
            "env:NAME",
            "env:GLAM_FIREBASE_SA",
            "./relative/path.json",
            "../other/path.json",
            "~/abs/path.json",
            "/abs/path/to/file.json",
        ],
    )
    def test_accepts_pointer_shapes(self, value):
        assert setup_mod.is_credential_pointer(value), (
            f"expected {value!r} to be accepted as a pointer shape"
        )

    @pytest.mark.parametrize(
        "value",
        [
            "AKIAIOSFODNN7EXAMPLE",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "Bearer abc.def.ghi",
            "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789",
            "xoxb-1234567890-abcdef",
            "password=secret",
        ],
    )
    def test_rejects_secret_shapes(self, value):
        assert not setup_mod.is_credential_pointer(value), (
            f"expected {value!r} to be rejected as a credential value"
        )


# ────────────────────────────  Doctor framework  ────────────────────────────


class TestDoctorRegistry:
    def test_register_and_run(self):
        called = []

        def my_check():
            called.append("ran")
            return doctor_registry.DoctorResult(name="test", status="pass", detail="ok")

        doctor_registry.register_doctor_check("test:probe", my_check)
        results = doctor_registry.run_all_checks()
        assert any(r.name == "test" and r.status == "pass" for r in results)
        assert called == ["ran"]

    def test_idempotent_registration(self):
        def my_check():
            return doctor_registry.DoctorResult(name="dup", status="pass")

        doctor_registry.register_doctor_check("dup:probe", my_check)
        doctor_registry.register_doctor_check(
            "dup:probe", my_check
        )  # second registration is a no-op
        results = doctor_registry.run_all_checks()
        # One row, not two.
        assert sum(1 for r in results if r.name == "dup") == 1

    def test_baseline_check_present_after_module_import(self):
        # F006 ships a baseline check (the Python-version probe). Adapter
        # specific checks land with G2-G5; F006 explicitly does NOT bundle
        # adapter checks (D013).
        from dontpanic_orchestrate.config import doctor_registry as dr

        dr._reset_for_tests()
        dr._register_baseline_checks()
        names = {r.name for r in dr.run_all_checks()}
        assert "python_version" in names

    def test_no_adapter_specific_checks_in_f006(self):
        # Greppable: F006's baseline registration must not reference adapter
        # source names (web/ios/android/backend) — those land in their own
        # plans (D013).
        src = (
            HERE.parents[2] / "dontpanic_orchestrate" / "config" / "doctor_registry.py"
        ).read_text()
        for adapter in ("playwright", "xcrun", "simctl", "adb", "firebase_admin"):
            assert adapter not in src, (
                f"F006 must not register adapter-specific check {adapter!r}; "
                "adapter checks ship with their own plan (G2-G5)"
            )


# ────────────────────────────  F003 amendment  ────────────────────────────


class TestSufficiencyAuditorRolesGoalAuditorLookup:
    def test_resolves_from_roles_goal_auditor_when_set(self, project_dir, monkeypatch):
        # Register the project so F003's plan→project lookup finds it.
        gc.ensure_dontpanic_home()
        pr.add_project(name="testproj", path=project_dir)

        cfg_path = pc.project_config_path(project_dir)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"roles": {"goal_auditor": "explicit-goal-aud"}}))

        plan_dir = project_dir / "docs" / "plans" / "x"
        plan_dir.mkdir(parents=True)

        result = sa._resolve_goal_auditor_agent(plan_dir, implementer_agent="claude")
        assert result == "explicit-goal-aud"

    def test_falls_through_to_legacy_auditor_when_unset(self, project_dir, monkeypatch):
        # No roles.goal_auditor → falls through to existing
        # resolve_dispatch_defaults path (which uses default_auditor /
        # auditor / hardcoded). F1's locked behavior preserved.
        gc.save_config(gc.GlobalConfig(default_auditor="legacy-aud"))
        pr.add_project(name="testproj2", path=project_dir)
        plan_dir = project_dir / "docs" / "plans" / "y"
        plan_dir.mkdir(parents=True)
        result = sa._resolve_goal_auditor_agent(plan_dir, implementer_agent="claude")
        assert result == "legacy-aud"


# ────────────────────────────  D014 source-grep assertion  ────────────────────────────


class TestD014NoCredentialLiteralsInSource:
    """Greppable: ``config/`` package must not contain credential-bearing
    literals. Pointer values stay as user-supplied strings; we never bake
    them in."""

    _FORBIDDEN = (
        re.compile(r"password\s*=\s*['\"]\w+", re.IGNORECASE),
        re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE),
        re.compile(r"api_key\s*=\s*['\"][A-Za-z0-9]+", re.IGNORECASE),
    )

    def test_config_package_source_clean(self):
        config_pkg = HERE.parents[2] / "dontpanic_orchestrate" / "config"
        for py in config_pkg.rglob("*.py"):
            text = py.read_text()
            lines = text.splitlines()
            in_forbidden_block = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # Track entry/exit of the regex-pattern tuple. The constant
                # contains the rejection regexes themselves — those are
                # explicitly allowed to mention "Bearer" / "password=" /
                # etc. since they're WHAT we reject.
                if "_FORBIDDEN_LITERAL_PATTERNS" in line:
                    in_forbidden_block = True
                if in_forbidden_block:
                    if stripped.endswith(")") and not stripped.endswith("),"):
                        # ``)`` alone closes the tuple. ``),`` is mid-tuple.
                        in_forbidden_block = False
                    continue
                for rx in self._FORBIDDEN:
                    assert not rx.search(line), (
                        f"{py.relative_to(HERE.parents[3])}:{i + 1} contains a "
                        f"credential-bearing literal: {line!r}"
                    )
