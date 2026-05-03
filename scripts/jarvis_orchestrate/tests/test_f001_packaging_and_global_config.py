"""Plan 2026-05-03-001 F001 — packaging + console-script + global config.

Tests cover the deterministic acceptance items: pyproject parses as PEP
621, `[project.scripts] dontpanic` exists, the legacy `jarvis` alias
still exists, `__version__` is resolvable,
`--version` / `-V` exit 0 with the right format, `python -m
jarvis_orchestrate` backward-compat works, and the global-config loader
handles missing / invalid / valid files without raising.

All tests use the ``JARVIS_HOME`` env var to redirect to ``tmp_path``
so the user's real ``~/.jarvis`` is never read or written.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_f001_packaging_and_global_config.py
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import __version__, cli  # noqa: E402
from jarvis_orchestrate import global_config as gc  # noqa: E402

REPO_ROOT = HERE.parents[3]


# ──────────────────────────────  pyproject.toml shape  ──────────────────────────────


def _load_pyproject() -> dict:
    try:
        import tomllib
    except ImportError:  # Python <3.11 fallback
        import tomli as tomllib  # type: ignore[no-redef]
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


class TestPyproject:
    def test_parses_as_pep621(self):
        d = _load_pyproject()
        project = d["project"]
        assert project["name"] == "dontpanic-orchestrate"
        assert (
            project["description"]
            == "The safety layer between the agent says it's done and you merge it."
        )
        assert "requires-python" in project
        assert project["requires-python"].startswith(">=3.10")

    def test_console_scripts_declared(self):
        d = _load_pyproject()
        scripts = d["project"]["scripts"]
        assert scripts["dontpanic"] == "jarvis_orchestrate.cli:main"
        assert scripts["jarvis"] == "jarvis_orchestrate.cli:main"

    def test_project_urls_point_at_renamed_repo(self):
        d = _load_pyproject()
        urls = d["project"]["urls"]
        assert urls["Homepage"] == "https://github.com/Silex-Research/DontPanic"
        assert urls["Repository"] == "https://github.com/Silex-Research/DontPanic"
        assert urls["Issues"] == "https://github.com/Silex-Research/DontPanic/issues"

    def test_runtime_deps_present(self):
        d = _load_pyproject()
        deps = d["project"]["dependencies"]
        assert any(s.startswith("pydantic") for s in deps)
        assert any(s.startswith("pyyaml") for s in deps)

    def test_version_is_dynamic(self):
        d = _load_pyproject()
        assert d["project"]["dynamic"] == ["version"]
        assert d["tool"]["setuptools"]["dynamic"]["version"] == {
            "attr": "jarvis_orchestrate.__version__"
        }

    def test_packages_find_under_scripts(self):
        d = _load_pyproject()
        find_config = d["tool"]["setuptools"]["packages"]["find"]
        assert find_config["where"] == ["scripts"]
        assert "jarvis_orchestrate*" in find_config["include"]
        # Don't ship tests in the wheel.
        assert "jarvis_orchestrate.tests*" in find_config["exclude"]

    def test_build_system_setuptools(self):
        d = _load_pyproject()
        build = d["build-system"]
        assert build["build-backend"] == "setuptools.build_meta"
        assert any(req.startswith("setuptools") for req in build["requires"])


# ──────────────────────────────  __version__ + --version  ──────────────────────────────


class TestVersion:
    def test_version_attribute_resolves(self):
        # Single source of truth — pyproject's [tool.setuptools.dynamic]
        # reads `attr = "jarvis_orchestrate.__version__"`. If this test
        # passes, the build's dynamic-version resolution will too.
        assert isinstance(__version__, str)
        # PEP 440 minimum: `<digits>.<digits>.<digits>` core.
        parts = __version__.split(".")
        assert len(parts) >= 3
        assert all(p.isdigit() for p in parts[:3])

    def test_version_flag_long(self, capsys):
        rc = cli.main(["--version"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == f"dontpanic {__version__}"

    def test_version_flag_short(self, capsys):
        rc = cli.main(["-V"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == f"dontpanic {__version__}"

    def test_version_via_module_invoke(self):
        # Backward-compat path: `python -m jarvis_orchestrate --version`
        # should work for users who haven't migrated to the console
        # script yet (D001).
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT / "scripts") + os.pathsep + env.get(
            "PYTHONPATH", ""
        )
        result = subprocess.run(
            [sys.executable, "-m", "jarvis_orchestrate", "--version"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert result.stdout.strip() == f"dontpanic {__version__}"


# ──────────────────────────────  global config loader  ──────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_jarvis_home(tmp_path, monkeypatch):
    """Reroute ``$JARVIS_HOME`` to a tmp dir so the user's real
    ``~/.jarvis`` is never touched. Autouse to protect every test
    in this module."""
    monkeypatch.setenv(gc.JARVIS_HOME_ENV, str(tmp_path / ".jarvis"))


class TestJarvisHome:
    def test_jarvis_home_respects_env_override(self, tmp_path):
        # Fixture set $JARVIS_HOME to tmp_path/.jarvis already.
        home = gc.jarvis_home()
        assert home == tmp_path / ".jarvis"

    def test_jarvis_home_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
        home = gc.jarvis_home()
        # Should resolve under user's real home dir (not asserting equality
        # because we don't want to assume what the runner's $HOME is).
        assert home.name == ".jarvis"
        assert home.parent == Path.home()

    def test_ensure_jarvis_home_creates_dir(self):
        home = gc.ensure_jarvis_home()
        assert home.is_dir()
        # Idempotent.
        home2 = gc.ensure_jarvis_home()
        assert home2 == home


class TestLoadConfig:
    def test_missing_file_returns_empty_defaults(self):
        # No file written; loader returns empty config without warning.
        config = gc.load_config()
        assert config.default_implementer is None
        assert config.default_auditor is None
        assert config.default_tier is None
        assert config.calibration_path is None

    def test_valid_file_populates_fields(self, tmp_path):
        gc.ensure_jarvis_home()
        path = gc.config_path()
        path.write_text(
            json.dumps(
                {
                    "default_implementer": "claude",
                    "default_auditor": "codex",
                    "default_tier": "trivial",
                }
            )
        )
        config = gc.load_config()
        assert config.default_implementer == "claude"
        assert config.default_auditor == "codex"
        assert config.default_tier == "trivial"
        assert config.calibration_path is None

    def test_invalid_json_warns_returns_empty(self, caplog):
        gc.ensure_jarvis_home()
        gc.config_path().write_text("not json at all {{{")
        with caplog.at_level(logging.WARNING, logger="jarvis_orchestrate.global_config"):
            config = gc.load_config()
        assert config.default_implementer is None
        assert any("invalid JSON" in m or "unreadable" in m for m in caplog.messages)

    def test_extra_field_warns_returns_empty(self, caplog):
        gc.ensure_jarvis_home()
        gc.config_path().write_text(
            json.dumps({"default_implementer": "claude", "rogue_field": "x"})
        )
        with caplog.at_level(logging.WARNING, logger="jarvis_orchestrate.global_config"):
            config = gc.load_config()
        # Pydantic extra='forbid' rejects rogue_field; loader degrades to empty.
        assert config.default_implementer is None
        assert any("schema validation" in m for m in caplog.messages)

    def test_does_not_raise_on_unreadable_file(self, monkeypatch):
        gc.ensure_jarvis_home()
        gc.config_path().write_text(json.dumps({"default_implementer": "claude"}))
        # Simulate an OSError on read.
        original_read = Path.read_text

        def _raise_oserror(self, *args, **kwargs):
            if self == gc.config_path():
                raise OSError("simulated permission denied")
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _raise_oserror)
        # Must not raise.
        config = gc.load_config()
        assert config.default_implementer is None


class TestSaveConfig:
    def test_save_then_load_roundtrip(self):
        config = gc.GlobalConfig(
            default_implementer="claude",
            default_auditor="codex",
            default_tier="local",
        )
        path = gc.save_config(config)
        assert path.is_file()
        # Round-trip.
        reloaded = gc.load_config()
        assert reloaded.default_implementer == "claude"
        assert reloaded.default_auditor == "codex"
        assert reloaded.default_tier == "local"

    def test_save_excludes_none_fields(self):
        config = gc.GlobalConfig(default_implementer="claude")
        path = gc.save_config(config)
        raw = json.loads(path.read_text())
        # Only the explicitly-set field is present.
        assert raw == {"default_implementer": "claude"}

    def test_save_creates_jarvis_home_if_missing(self, tmp_path):
        # Fixture set $JARVIS_HOME but didn't create it.
        target = tmp_path / ".jarvis"
        assert not target.exists()
        gc.save_config(gc.GlobalConfig(default_implementer="claude"))
        assert target.is_dir()


class TestMergeWithDefaults:
    def test_empty_config_uses_fallbacks(self):
        merged = gc.merge_with_defaults(gc.GlobalConfig())
        assert merged["implementer"] == "claude"
        assert merged["auditor"] == "codex"

    def test_populated_config_overrides_fallbacks(self):
        merged = gc.merge_with_defaults(
            gc.GlobalConfig(default_implementer="gemini", default_auditor="grok")
        )
        assert merged["implementer"] == "gemini"
        assert merged["auditor"] == "grok"

    def test_partial_config_mixes_with_fallbacks(self):
        merged = gc.merge_with_defaults(
            gc.GlobalConfig(default_implementer="gemini")  # auditor unset
        )
        assert merged["implementer"] == "gemini"
        assert merged["auditor"] == "codex"


# ──────────────────────────────  no repo-specific assumptions  ──────────────────────────────


class TestNoRepoSpecificAssumptions:
    """Acceptance: F001 must not require running from inside the DontPanic
    source tree. The console script + global config + version flag must
    work from any cwd."""

    def test_global_config_works_from_arbitrary_cwd(self, tmp_path, monkeypatch):
        # cd into an unrelated directory; loader still works.
        unrelated = tmp_path / "some" / "other" / "place"
        unrelated.mkdir(parents=True)
        monkeypatch.chdir(unrelated)
        config = gc.load_config()
        assert config.default_implementer is None  # missing-file → empty

    def test_version_flag_works_from_arbitrary_cwd(self, tmp_path, monkeypatch, capsys):
        unrelated = tmp_path / "some" / "other" / "place"
        unrelated.mkdir(parents=True)
        monkeypatch.chdir(unrelated)
        rc = cli.main(["--version"])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out == f"dontpanic {__version__}"

    def test_jarvis_home_does_not_assume_repo_root(self, tmp_path):
        # $JARVIS_HOME points anywhere, including outside any repo.
        home = gc.jarvis_home()
        assert str(tmp_path) in str(home)
