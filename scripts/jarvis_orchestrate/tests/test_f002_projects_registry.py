"""Plan 2026-05-03-001 F002 — project registry CRUD.

Tests cover the deterministic acceptance items: registry schema (Pydantic
``extra='forbid'`` + name regex from D003), add/remove/list/show CRUD,
non-clobber semantics with ``--force --yes`` override, dry-run remove
default, ``--json`` round-trip, and ``update_last_used`` idempotency.

All tests redirect ``$JARVIS_HOME`` to ``tmp_path`` so the user's real
``~/.jarvis/projects.json`` is never read or written.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_f002_projects_registry.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import cli  # noqa: E402
from jarvis_orchestrate import global_config as gc  # noqa: E402
from jarvis_orchestrate import projects_registry as pr  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_jarvis_home(tmp_path, monkeypatch):
    """Reroute ``$JARVIS_HOME`` to a tmp dir so the user's real
    ``~/.jarvis/projects.json`` is never touched. Autouse to protect
    every test in this module."""
    monkeypatch.setenv(gc.JARVIS_HOME_ENV, str(tmp_path / ".jarvis"))


@pytest.fixture
def project_dir(tmp_path):
    """A real directory we can register as a project path. Path validation
    rejects non-existent dirs at add time."""
    d = tmp_path / "some-project"
    d.mkdir()
    return d


# ──────────────────────────────  schema + name regex (D003)  ──────────────────────────────


class TestSchema:
    def test_project_entry_validates_name_regex(self, project_dir):
        # Per D003: ^[a-z0-9][a-z0-9-]{0,63}$
        entry = pr.ProjectEntry(
            name="my-project",
            path=str(project_dir),
            created_at="2026-05-03T00:00:00Z",
        )
        assert entry.name == "my-project"

    @pytest.mark.parametrize(
        "bad_name",
        [
            "MyProject",  # uppercase
            "my_project",  # underscore
            "-leading",  # leading hyphen
            "x" * 65,  # too long
            "",  # empty
            "with space",  # space
            "weird!chars",  # special char
        ],
    )
    def test_project_entry_rejects_bad_names(self, bad_name, project_dir):
        # Pydantic v2's ValidationError inherits from ValueError, so the
        # field-validator's raise is caught here.
        with pytest.raises(ValueError):
            pr.ProjectEntry(
                name=bad_name,
                path=str(project_dir),
                created_at="2026-05-03T00:00:00Z",
            )

    def test_extra_field_forbidden_on_entry(self, project_dir):
        with pytest.raises(ValueError):
            pr.ProjectEntry(
                name="ok-name",
                path=str(project_dir),
                created_at="2026-05-03T00:00:00Z",
                rogue_field="x",  # type: ignore[call-arg]
            )

    def test_extra_field_forbidden_on_registry(self):
        with pytest.raises(ValueError):
            pr.Registry(projects=[], rogue_field="x")  # type: ignore[call-arg]

    def test_empty_registry_is_valid_zero_state(self):
        reg = pr.Registry()
        assert reg.projects == []


# ──────────────────────────────  load / save round-trip  ──────────────────────────────


class TestLoadSave:
    def test_missing_file_returns_empty_registry(self):
        reg = pr.load_registry()
        assert reg.projects == []

    def test_save_then_load_roundtrip(self, project_dir):
        entry = pr.ProjectEntry(
            name="alpha",
            path=str(project_dir),
            created_at="2026-05-03T00:00:00Z",
            default_implementer="claude",
        )
        pr.save_registry(pr.Registry(projects=[entry]))
        reloaded = pr.load_registry()
        assert len(reloaded.projects) == 1
        assert reloaded.projects[0].name == "alpha"
        assert reloaded.projects[0].default_implementer == "claude"
        # last_used_at / default_auditor / notes default to None — ensure
        # they round-trip without coercion.
        assert reloaded.projects[0].last_used_at is None
        assert reloaded.projects[0].default_auditor is None

    def test_invalid_json_warns_returns_empty(self, caplog):
        gc.ensure_jarvis_home()
        pr.registry_path().write_text("not json {{{")
        with caplog.at_level(logging.WARNING, logger="jarvis_orchestrate.projects_registry"):
            reg = pr.load_registry()
        assert reg.projects == []
        assert any("invalid JSON" in m or "unreadable" in m for m in caplog.messages)

    def test_extra_field_warns_returns_empty(self, caplog, project_dir):
        gc.ensure_jarvis_home()
        pr.registry_path().write_text(
            json.dumps(
                {
                    "projects": [
                        {
                            "name": "alpha",
                            "path": str(project_dir),
                            "created_at": "2026-05-03T00:00:00Z",
                            "rogue_field": "x",
                        }
                    ]
                }
            )
        )
        with caplog.at_level(logging.WARNING, logger="jarvis_orchestrate.projects_registry"):
            reg = pr.load_registry()
        assert reg.projects == []
        assert any("schema validation" in m for m in caplog.messages)

    def test_save_creates_jarvis_home_if_missing(self, tmp_path, project_dir):
        target = tmp_path / ".jarvis"
        assert not target.exists()
        pr.save_registry(pr.Registry())
        assert target.is_dir()
        assert (target / "projects.json").is_file()

    def test_save_excludes_none_fields(self, project_dir):
        entry = pr.ProjectEntry(
            name="alpha",
            path=str(project_dir),
            created_at="2026-05-03T00:00:00Z",
        )
        path = pr.save_registry(pr.Registry(projects=[entry]))
        raw = json.loads(path.read_text())
        # Only set fields land in the JSON — minimizes diff churn when
        # operators inspect the file.
        assert raw["projects"][0] == {
            "name": "alpha",
            "path": str(project_dir),
            "created_at": "2026-05-03T00:00:00Z",
        }


# ──────────────────────────────  CRUD helpers  ──────────────────────────────


class TestAddProject:
    def test_add_persists_entry(self, project_dir):
        entry = pr.add_project(name="alpha", path=str(project_dir))
        assert entry.name == "alpha"
        # Path is normalized to absolute (Path.expanduser().resolve()).
        assert entry.path == str(project_dir.resolve())
        assert entry.created_at  # ISO string set
        # File now contains the entry.
        reloaded = pr.load_registry()
        assert reloaded.projects[0].name == "alpha"

    def test_add_normalizes_tilde_path(self, project_dir, monkeypatch):
        # Operator typing `~/some/path` should land as absolute on disk.
        # Simulate by putting the dir under a fake $HOME.
        fake_home = project_dir.parent / "fake-home"
        fake_home.mkdir()
        target = fake_home / "proj"
        target.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        entry = pr.add_project(name="beta", path="~/proj")
        assert entry.path == str(target.resolve())
        assert "~" not in entry.path

    def test_add_collision_refuses(self, project_dir):
        pr.add_project(name="alpha", path=str(project_dir))
        with pytest.raises(pr.ProjectsRegistryError) as exc:
            pr.add_project(name="alpha", path=str(project_dir))
        assert "already" in str(exc.value).lower() or "collision" in str(exc.value).lower()

    def test_add_with_force_overwrites(self, project_dir, tmp_path):
        pr.add_project(name="alpha", path=str(project_dir), notes="first")
        other = tmp_path / "other"
        other.mkdir()
        pr.add_project(name="alpha", path=str(other), force=True, notes="second")
        reg = pr.load_registry()
        assert len(reg.projects) == 1
        assert reg.projects[0].path == str(other.resolve())
        assert reg.projects[0].notes == "second"

    def test_add_invalid_name_raises(self, project_dir):
        with pytest.raises(pr.ProjectsRegistryError):
            pr.add_project(name="My_Project", path=str(project_dir))

    def test_add_nonexistent_path_refuses(self, tmp_path):
        ghost = tmp_path / "does-not-exist"
        with pytest.raises(pr.ProjectsRegistryError) as exc:
            pr.add_project(name="alpha", path=str(ghost))
        assert "exist" in str(exc.value).lower() or "not a dir" in str(exc.value).lower()

    def test_add_with_optional_fields(self, project_dir):
        entry = pr.add_project(
            name="alpha",
            path=str(project_dir),
            default_implementer="claude",
            default_auditor="codex",
            notes="primary work repo",
        )
        assert entry.default_implementer == "claude"
        assert entry.default_auditor == "codex"
        assert entry.notes == "primary work repo"


class TestFindAndUpdate:
    def test_find_existing(self, project_dir):
        pr.add_project(name="alpha", path=str(project_dir))
        found = pr.find_project("alpha")
        assert found is not None
        assert found.name == "alpha"

    def test_find_missing_returns_none(self):
        assert pr.find_project("ghost") is None

    def test_update_last_used_sets_field(self, project_dir):
        pr.add_project(name="alpha", path=str(project_dir))
        pr.update_last_used("alpha")
        reloaded = pr.find_project("alpha")
        assert reloaded is not None
        assert reloaded.last_used_at is not None

    def test_update_last_used_idempotent_within_same_second(self, project_dir):
        pr.add_project(name="alpha", path=str(project_dir))
        pr.update_last_used("alpha")
        first = pr.find_project("alpha").last_used_at  # type: ignore[union-attr]
        pr.update_last_used("alpha")
        second = pr.find_project("alpha").last_used_at  # type: ignore[union-attr]
        # Either stamps are equal (same second) or strictly increasing.
        assert second >= first

    def test_update_last_used_unknown_name_raises(self):
        with pytest.raises(pr.ProjectsRegistryError):
            pr.update_last_used("ghost")


class TestRemoveProject:
    def test_remove_existing(self, project_dir):
        pr.add_project(name="alpha", path=str(project_dir))
        removed = pr.remove_project("alpha")
        assert removed is not None
        assert removed.name == "alpha"
        assert pr.find_project("alpha") is None

    def test_remove_missing_returns_none(self):
        assert pr.remove_project("ghost") is None


# ──────────────────────────────  CLI surface  ──────────────────────────────


class TestProjectsCLIAdd:
    def test_add_basic(self, project_dir, capsys):
        rc = cli.main(["projects", "add", "alpha", str(project_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "alpha" in out
        # Persistence side effect.
        assert pr.find_project("alpha") is not None

    def test_add_collision_exits_2(self, project_dir, capsys):
        cli.main(["projects", "add", "alpha", str(project_dir)])
        rc = cli.main(["projects", "add", "alpha", str(project_dir)])
        assert rc == 2
        err = capsys.readouterr().err
        assert "already" in err.lower() or "collision" in err.lower()

    def test_add_force_without_yes_refuses(self, project_dir, capsys, tmp_path):
        cli.main(["projects", "add", "alpha", str(project_dir)])
        other = tmp_path / "other"
        other.mkdir()
        rc = cli.main(["projects", "add", "alpha", str(other), "--force"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "--yes" in err

    def test_add_force_yes_overwrites(self, project_dir, capsys, tmp_path):
        cli.main(["projects", "add", "alpha", str(project_dir)])
        other = tmp_path / "other"
        other.mkdir()
        rc = cli.main(["projects", "add", "alpha", str(other), "--force", "--yes"])
        assert rc == 0
        assert pr.find_project("alpha").path == str(other.resolve())  # type: ignore[union-attr]

    def test_add_invalid_name_exits_2(self, project_dir, capsys):
        rc = cli.main(["projects", "add", "Bad_Name", str(project_dir)])
        assert rc == 2
        err = capsys.readouterr().err
        # Surface the regex hint so the operator knows what to fix.
        assert "name" in err.lower()

    def test_add_nonexistent_path_exits_2(self, tmp_path, capsys):
        rc = cli.main(["projects", "add", "alpha", str(tmp_path / "ghost")])
        assert rc == 2
        err = capsys.readouterr().err
        assert "exist" in err.lower() or "not a dir" in err.lower()

    def test_add_with_optional_flags(self, project_dir, capsys):
        rc = cli.main(
            [
                "projects",
                "add",
                "alpha",
                str(project_dir),
                "--implementer",
                "claude",
                "--auditor",
                "codex",
                "--notes",
                "primary",
            ]
        )
        assert rc == 0
        entry = pr.find_project("alpha")
        assert entry.default_implementer == "claude"  # type: ignore[union-attr]
        assert entry.default_auditor == "codex"  # type: ignore[union-attr]
        assert entry.notes == "primary"  # type: ignore[union-attr]

    def test_add_json_output(self, project_dir, capsys):
        rc = cli.main(["projects", "add", "alpha", str(project_dir), "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["action"] == "added"
        assert payload["project"]["name"] == "alpha"


class TestProjectsCLIList:
    def test_list_empty(self, capsys):
        rc = cli.main(["projects", "list"])
        assert rc == 0
        # Don't pin exact format, but mention "no projects" or empty.
        out = capsys.readouterr().out
        assert "no projects" in out.lower() or out.strip() != ""

    def test_list_with_entries(self, project_dir, capsys, tmp_path):
        cli.main(["projects", "add", "alpha", str(project_dir)])
        other = tmp_path / "other"
        other.mkdir()
        cli.main(["projects", "add", "beta", str(other)])
        rc = cli.main(["projects", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "alpha" in out
        assert "beta" in out

    def test_list_json(self, project_dir, capsys):
        cli.main(["projects", "add", "alpha", str(project_dir)])
        # Reset capture (cli.main prints to stdout).
        capsys.readouterr()
        rc = cli.main(["projects", "list", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert "projects" in payload
        assert len(payload["projects"]) == 1
        assert payload["projects"][0]["name"] == "alpha"


class TestProjectsCLIShow:
    def test_show_existing(self, project_dir, capsys):
        cli.main(["projects", "add", "alpha", str(project_dir)])
        capsys.readouterr()
        rc = cli.main(["projects", "show", "alpha"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "alpha" in out
        assert str(project_dir.resolve()) in out

    def test_show_missing_exits_2(self, capsys):
        rc = cli.main(["projects", "show", "ghost"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "ghost" in err or "not found" in err.lower()

    def test_show_json_roundtrip(self, project_dir, capsys):
        cli.main(["projects", "add", "alpha", str(project_dir), "--notes", "n"])
        capsys.readouterr()
        rc = cli.main(["projects", "show", "alpha", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["name"] == "alpha"
        assert payload["notes"] == "n"


class TestProjectsCLIRemove:
    def test_remove_dry_run_default(self, project_dir, capsys):
        cli.main(["projects", "add", "alpha", str(project_dir)])
        capsys.readouterr()
        rc = cli.main(["projects", "remove", "alpha"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out.lower() or "would" in out.lower()
        # Entry still exists — dry run did not delete.
        assert pr.find_project("alpha") is not None

    def test_remove_with_yes_deletes(self, project_dir, capsys):
        cli.main(["projects", "add", "alpha", str(project_dir)])
        capsys.readouterr()
        rc = cli.main(["projects", "remove", "alpha", "--yes"])
        assert rc == 0
        assert pr.find_project("alpha") is None

    def test_remove_missing_exits_2(self, capsys):
        rc = cli.main(["projects", "remove", "ghost", "--yes"])
        assert rc == 2

    def test_remove_json(self, project_dir, capsys):
        cli.main(["projects", "add", "alpha", str(project_dir)])
        capsys.readouterr()
        rc = cli.main(["projects", "remove", "alpha", "--yes", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["action"] == "removed"
        assert payload["project"]["name"] == "alpha"


# ──────────────────────────────  CLI dispatch / usage  ──────────────────────────────


class TestProjectsCLIDispatch:
    def test_no_subcommand_prints_usage(self, capsys):
        rc = cli.main(["projects"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "usage" in err.lower()
        assert "add" in err and "list" in err and "show" in err and "remove" in err

    def test_unknown_subcommand_exits_2(self, capsys):
        rc = cli.main(["projects", "delete", "alpha"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "unknown" in err.lower() or "usage" in err.lower()

    def test_works_from_arbitrary_cwd(self, tmp_path, monkeypatch, project_dir, capsys):
        # Acceptance: registry CRUD must not depend on cwd being inside a repo.
        unrelated = tmp_path / "some" / "other" / "place"
        unrelated.mkdir(parents=True)
        monkeypatch.chdir(unrelated)
        rc = cli.main(["projects", "add", "alpha", str(project_dir)])
        assert rc == 0
        assert pr.find_project("alpha") is not None
