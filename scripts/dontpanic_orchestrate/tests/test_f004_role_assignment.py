"""Plan 2026-05-30-001 F004 — worker role assignment (``dontpanic roles``).

Covers the role-assignment surface end to end: source-layer resolution for
implementer / auditor / goal_auditor, the ``roles show`` text + ``--json``
dashboard projection, ``roles set`` global / project writes, dry-run preview,
unknown-executor refusal (no write, operator-vs-worker wording), and the
goal_auditor → resolved-auditor fallthrough. No test invokes a real agent CLI
— the executor registry is read for classification only.

Run: PYTHONPATH=scripts pytest \\
  scripts/dontpanic_orchestrate/tests/test_f004_role_assignment.py
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import cli  # noqa: E402
from dontpanic_orchestrate import global_config as gc  # noqa: E402
from dontpanic_orchestrate import project_config as pc  # noqa: E402
from dontpanic_orchestrate import role_assignment as ra  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_dontpanic_home(tmp_path, monkeypatch):
    """Reroute ``$DONTPANIC_HOME`` to a tmp dir so global writes never touch
    the operator's real ~/.dontpanic. Clears ``$JARVIS_HOME`` for
    deterministic resolution."""
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _init_project(project_dir: Path) -> None:
    """Scaffold an empty per-project config so project writes are accepted."""
    project_dir.mkdir(parents=True, exist_ok=True)
    pc.scaffold_empty_config(project_dir)


def _scope(path: Path) -> ra.ProjectScope:
    return ra.ProjectScope(path=path, name=None)


# ──────────────────────────────  resolution + source layers  ──────────────────────────────


def test_resolve_fallback_layer(tmp_path) -> None:
    """No config anywhere → hardcoded fallbacks with source 'fallback'."""
    res = {r.role: r for r in ra.resolve_all(_scope(tmp_path))}
    assert res["implementer"].value == "claude"
    assert res["implementer"].source_layer == "fallback"
    assert res["auditor"].value == "codex"
    assert res["auditor"].source_layer == "fallback"
    # Every fallback role is a real executor → worker-capable.
    assert res["implementer"].worker_capable
    assert res["auditor"].worker_capable


def test_resolve_goal_auditor_inherits_auditor(tmp_path) -> None:
    """goal_auditor with nothing set inherits the resolved auditor (D013)."""
    res = {r.role: r for r in ra.resolve_all(_scope(tmp_path))}
    ga = res["goal_auditor"]
    assert ga.value == "codex"  # inherits the fallback auditor
    assert ga.source_layer == "goal_auditor_inherits_auditor"


def test_resolve_global_roles_layer(tmp_path, monkeypatch) -> None:
    """A global roles.* value resolves with source 'global_roles'."""
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))
    gc.ensure_dontpanic_home()
    gc.config_path().write_text(json.dumps({"roles": {"auditor": "claude"}}))
    res = {r.role: r for r in ra.resolve_all(_scope(tmp_path))}
    assert res["auditor"].value == "claude"
    assert res["auditor"].source_layer == "global_roles"
    # goal_auditor inherits the *resolved* auditor → claude, still inherited.
    assert res["goal_auditor"].value == "claude"
    assert res["goal_auditor"].source_layer == "goal_auditor_inherits_auditor"


def test_resolve_global_legacy_layer(tmp_path, monkeypatch) -> None:
    """A legacy default_implementer resolves with source 'global_legacy'."""
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))
    gc.ensure_dontpanic_home()
    gc.config_path().write_text(json.dumps({"default_implementer": "codex"}))
    res = {r.role: r for r in ra.resolve_all(_scope(tmp_path))}
    assert res["implementer"].value == "codex"
    assert res["implementer"].source_layer == "global_legacy"


def test_resolve_project_roles_wins_over_global(tmp_path, monkeypatch) -> None:
    """Project roles.* beats global roles.* and legacy (source 'project_roles')."""
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))
    gc.ensure_dontpanic_home()
    gc.config_path().write_text(json.dumps({"roles": {"auditor": "claude"}}))
    proj = tmp_path / "repo"
    _init_project(proj)
    pc.project_config_path(proj).write_text(json.dumps({"roles": {"auditor": "codex"}}))
    res = {r.role: r for r in ra.resolve_all(_scope(proj))}
    assert res["auditor"].value == "codex"
    assert res["auditor"].source_layer == "project_roles"


def test_resolve_project_legacy_layer(tmp_path) -> None:
    """A project legacy 'implementer' field resolves with source 'project_legacy'."""
    proj = tmp_path / "repo"
    _init_project(proj)
    pc.project_config_path(proj).write_text(json.dumps({"implementer": "codex"}))
    res = {r.role: r for r in ra.resolve_all(_scope(proj))}
    assert res["implementer"].value == "codex"
    assert res["implementer"].source_layer == "project_legacy"


# ──────────────────────────────  roles show  ──────────────────────────────


def test_roles_show_lists_executors_and_roles(tmp_path, monkeypatch) -> None:
    """Acceptance #1 — show lists worker executors + effective roles + source."""
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run(["roles", "show"])
    assert rc == 0
    assert "AVAILABLE WORKER EXECUTORS" in out
    for name in ra.available_worker_executors():
        assert name in out
    assert "EFFECTIVE ROLES" in out
    assert "implementer: claude" in out
    assert "auditor: codex" in out
    assert "goal_auditor: codex" in out
    # Source layer is surfaced, not just the value.
    assert "source:" in out
    assert "hardcoded fallback" in out


def test_roles_show_json_dashboard_projection(tmp_path, monkeypatch) -> None:
    """Acceptance #7 — JSON projection has everything a UI needs to render
    role pickers + safe mutation commands."""
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run(["roles", "show", "--json"])
    assert rc == 0
    payload = json.loads(out)
    assert set(payload) == {"scope", "available_executors", "roles"}
    assert payload["available_executors"] == ra.available_worker_executors()
    # Scope descriptors point at both config files.
    assert "global_config_path" in payload["scope"]
    assert "project_config_path" in payload["scope"]
    # Each role carries effective value, source layer, dispatchability, and a
    # safe mutation command template for both scopes.
    roles_by_name = {r["role"]: r for r in payload["roles"]}
    assert set(roles_by_name) == set(ra.ROLES)
    impl = roles_by_name["implementer"]
    assert impl["effective"] == "claude"
    assert impl["source_layer"] == "fallback"
    assert impl["worker_capable"] is True
    assert impl["mutation_commands"]["global"] == (
        "dontpanic roles set implementer <executor> --global"
    )
    assert "--project" in impl["mutation_commands"]["project"]


def test_roles_show_no_secret_shapes(tmp_path, monkeypatch) -> None:
    """The dashboard projection emits only agent/role/path data — never secret
    shapes. Inspect the role values + executors + command templates (the
    fields a UI binds to); config *paths* legitimately contain arbitrary
    directory names, so they are excluded from the scan."""
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run(["roles", "show", "--json"])
    assert rc == 0
    payload = json.loads(out)
    # The value-bearing fields a UI binds to — excluding paths and the
    # path-embedding command templates, which legitimately contain arbitrary
    # directory names.
    scanned_parts = list(payload["available_executors"])
    for r in payload["roles"]:
        scanned_parts += [r["effective"], r["source_layer"], r["source_label"]]
    scanned = json.dumps(scanned_parts).lower()
    for needle in ("secret", "token", "bearer", "api_key", "apikey", "password"):
        assert needle not in scanned


def test_dashboard_projection_project_path_with_spaces_is_safe(tmp_path) -> None:
    """Regression (i0 auditor) — a project scope path containing spaces must
    not produce an unsafe copy/paste command. The display command shell-quotes
    the path so it parses as one argv token, and the parallel argv array
    carries the raw, unquoted value for programmatic dispatch."""
    import shlex

    spaced = tmp_path / "my repo"
    spaced.mkdir()
    proj = ra.dashboard_projection(ra.ProjectScope(path=spaced, name=None))
    impl = {r["role"]: r for r in proj["roles"]}["implementer"]

    display = impl["mutation_commands"]["project"]
    # The whole displayed string round-trips through the shell into exactly the
    # expected argv, with the spaced path preserved as a single token.
    assert shlex.split(display) == [
        "dontpanic",
        "roles",
        "set",
        "implementer",
        "<executor>",
        "--project",
        str(spaced),
    ]
    # The argv array carries the raw (unquoted) path verbatim.
    assert impl["mutation_argv"]["project"][-1] == str(spaced)
    assert impl["mutation_argv"]["global"] == [
        "dontpanic",
        "roles",
        "set",
        "implementer",
        "<executor>",
        "--global",
    ]


# ──────────────────────────────  roles set: global  ──────────────────────────────


def test_set_global_writes_global_roles_block(tmp_path, monkeypatch) -> None:
    """Acceptance #3 — `implementer claude --global` writes the global roles block."""
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run(["roles", "set", "implementer", "claude", "--global"])
    assert rc == 0
    assert "roles.implementer → claude" in out
    cfg = json.loads(gc.config_path().read_text())
    assert cfg == {"roles": {"implementer": "claude"}}


def test_set_default_scope_is_global(tmp_path, monkeypatch) -> None:
    """No scope flag defaults to a global write (consistent with register-worker)."""
    monkeypatch.chdir(tmp_path)
    rc, _, _ = _run(["roles", "set", "auditor", "codex"])
    assert rc == 0
    cfg = json.loads(gc.config_path().read_text())
    assert cfg["roles"]["auditor"] == "codex"


# ──────────────────────────────  roles set: project  ──────────────────────────────


def test_set_project_writes_project_block_only(tmp_path, monkeypatch) -> None:
    """Acceptance #2 — `auditor codex --project <repo>` writes the project roles
    block and leaves global config untouched."""
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "myrepo"
    _init_project(proj)
    rc, out, _ = _run(["roles", "set", "auditor", "codex", "--project", str(proj)])
    assert rc == 0
    assert "roles.auditor → codex" in out
    proj_cfg = json.loads(pc.project_config_path(proj).read_text())
    assert proj_cfg["roles"]["auditor"] == "codex"
    # Global config was never created.
    assert not gc.config_path().exists(), "project write must not touch global config"


def test_set_project_unresolvable_refuses(tmp_path, monkeypatch) -> None:
    """An unregistered, non-existent --project identifier refuses with exit 2."""
    monkeypatch.chdir(tmp_path)
    rc, _, err = _run(
        ["roles", "set", "auditor", "codex", "--project", "no-such-project-xyz"]
    )
    assert rc == 2
    assert "could not resolve" in err
    assert not gc.config_path().exists()


# ──────────────────────────────  dry-run  ──────────────────────────────


def test_set_dry_run_previews_exact_change_no_write(tmp_path, monkeypatch) -> None:
    """Acceptance #4 — dry-run previews the exact file + value change, writes nothing."""
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run(["roles", "set", "implementer", "codex", "--global", "--dry-run"])
    assert rc == 0
    assert "DRY-RUN" in out
    assert "roles.implementer → codex" in out
    assert str(gc.config_path()) in out
    assert not gc.config_path().exists()


def test_set_dry_run_project_names_project_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "repo"
    _init_project(proj)
    rc, out, _ = _run(
        ["roles", "set", "auditor", "codex", "--project", str(proj), "--dry-run"]
    )
    assert rc == 0
    assert "DRY-RUN" in out
    assert str(pc.project_config_path(proj)) in out
    # The project config still has no roles block (write was skipped).
    assert json.loads(pc.project_config_path(proj).read_text()) == {}


# ──────────────────────────────  unknown executor refusal  ──────────────────────────────


def test_set_unknown_executor_refused_before_write(tmp_path, monkeypatch) -> None:
    """Acceptance #5 — Grok-Builder is refused before any write."""
    monkeypatch.chdir(tmp_path)
    rc, _, err = _run(["roles", "set", "auditor", "Grok-Builder", "--global"])
    assert rc == 3
    assert "REFUSED" in err
    assert not gc.config_path().exists(), "no config written on refusal"


def test_set_unknown_executor_explains_operator_vs_worker(tmp_path, monkeypatch) -> None:
    """Acceptance #6 — refusal wording distinguishes operator-only from
    worker-capable (can operate DontPanic, cannot be assigned as a worker)."""
    monkeypatch.chdir(tmp_path)
    rc, _, err = _run(["roles", "set", "implementer", "grok", "--global"])
    assert rc == 3
    assert "can operate DontPanic" in err
    assert "dispatchable workers" in err
    # Names the real executors so the operator knows the valid set.
    for name in ra.available_worker_executors():
        assert name in err


def test_set_unknown_executor_refused_even_with_project(tmp_path, monkeypatch) -> None:
    """The executor guard runs before project resolution — an unknown executor
    is refused (exit 3) even when a valid --project is supplied."""
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "repo"
    _init_project(proj)
    rc, _, err = _run(["roles", "set", "auditor", "grok", "--project", str(proj)])
    assert rc == 3
    assert "REFUSED" in err
    assert json.loads(pc.project_config_path(proj).read_text()) == {}


# ──────────────────────────────  usage / unknown subcommand  ──────────────────────────────


def test_roles_help_exits_0() -> None:
    rc, out, _ = _run(["roles", "--help"])
    assert rc == 0
    assert "worker role assignment" in out.lower()


def test_roles_no_arg_exits_2() -> None:
    rc, _, err = _run(["roles"])
    assert rc == 2
    assert "usage" in err.lower()


def test_roles_unknown_subcommand_exits_2(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rc, _, err = _run(["roles", "frobnicate"])
    assert rc == 2
    assert "unknown subcommand" in err


# ──────────────────────────────  manifest advertises roles  ──────────────────────────────


def test_manifest_supported_commands_includes_roles() -> None:
    from dontpanic_orchestrate import agent_manifest as am

    m = am.bootstrap_manifest(install_source="source", cli_path="/x")
    assert "roles" in m.supported_commands
