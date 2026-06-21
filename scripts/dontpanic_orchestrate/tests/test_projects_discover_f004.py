"""Plan 2026-06-17-001 F004 — ``dontpanic projects discover [--json]`` CLI.

Covers the F004 acceptance matrix on top of the F003 logic core:

  * the pinned ``--json`` field contract (exact field names, value types, and the
    ``suggestion_status`` enum) for all five projection states;
  * the C1 privacy boundary — no raw home path and no reconstructed add-command
    path ever appear in ``--json`` (reuses the no-secret-shape assertion);
  * ``registered_path_missing`` / ``registered_unresolved`` rows carry
    ``canonical_repo_key=null`` + ``registry_name`` + ``registry_path_key`` and NO
    ``observed_count`` / ``last_seen``; ``registered_active`` / ``registered_stale``
    carry ``registry_conflict`` + ``conflicting_registry_names`` and emit
    ``observed_count=0`` / ``last_seen=null`` when no observed row exists;
  * the C5 default policy (``window_days=14`` / ``min_count=2`` / ``last_seen``,
    inclusive) and ``--window-days`` / ``--min-count`` overrides passing through to
    reconcile, with the registered active/stale truth table surfaced in JSON;
  * the isolated (DontPanic absent) vs D010-like (DontPanic registered) fixtures
    producing ``used_unregistered`` vs ``registered_active`` respectively;
  * the human render matrix — home-substituted command, verbatim-literal command,
    and the non-reconstructable ``<path>`` placeholder + needs-manual-path flag;
  * the empty state serializing to empty arrays;
  * the C6 command-blind guarantee and the C7 negative hook guard.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import canonical_discovery_render as render  # noqa: E402
from dontpanic_orchestrate import (  # noqa: E402
    cli,
    global_config,
    projects_registry,
)
from dontpanic_orchestrate import invocation_ledger as il  # noqa: E402

# A fixed "now" cannot be injected through the CLI (it stamps wall-clock UTC), so
# fixtures use a `last_seen` close to real now. We keep recency assertions robust
# by using "just now" vs "long ago" relative to the command's own clock.
_RECENT = None  # filled per-fixture from real now-ish; see _recent_iso()


def _rp(p: str | Path) -> str:
    return os.path.realpath(str(p))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fake $HOME + isolated $DONTPANIC_HOME + deterministic temp prefix so default
    path resolution and ``<home>`` scrubbing are reproducible."""
    synth_temp = tmp_path / "ephemeral"
    synth_temp.mkdir()
    monkeypatch.setattr(il, "_TEMP_PREFIXES", (_rp(synth_temp),))
    home = tmp_path / "home" / "operator"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LOGNAME", "operator")
    monkeypatch.setenv("USER", "operator")
    dphome = tmp_path / "dphome"
    dphome.mkdir()
    monkeypatch.setenv(global_config.DONTPANIC_HOME_ENV, str(dphome))
    return {"tmp": tmp_path, "temp": synth_temp, "home": home, "dphome": dphome}


def _recent_iso() -> str:
    import datetime as _dt

    return (
        (_dt.datetime.now(tz=_dt.timezone.utc) - _dt.timedelta(days=1))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _old_iso() -> str:
    import datetime as _dt

    return (
        (_dt.datetime.now(tz=_dt.timezone.utc) - _dt.timedelta(days=90))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _durable_dir(env, *parts: str) -> Path:
    """A real, durable (non-temp, non-git) directory under the fake $HOME. Its
    canonicalization is self-canonical (C3 case 2), so its canonical_repo_key is
    a stable function of its absolute path."""
    d = env["home"].joinpath(*parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _canonical_for(real_path: Path, **overrides) -> dict:
    pair = il.make_path_pair(real_path)
    obj = {
        "path_key": pair["path_key"],
        "path_display": pair["path_display"],
        "durable_checkout": True,
    }
    obj.update(overrides)
    return obj


def _record(real_path: Path, *, last_seen: str, observed_count: int | None = None,
            command: str = "dontpanic build", **extra) -> dict:
    rec: dict = {
        "repo": {"path_key": "obs-" + il.make_path_pair(real_path)["path_key"],
                 "path_display": "<home>/worktree"},
        "command": command,
        "canonical_repo": _canonical_for(real_path),
        "last_seen": last_seen,
        "result": "ok",
    }
    if observed_count is not None:
        rec["observed_count"] = observed_count
    rec.update(extra)
    return rec


def _seed_ledger(records: list[dict]) -> None:
    path = il.ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
    )


def _register(name: str, path: Path, *, active: bool | None = None) -> None:
    projects_registry.add_project(name=name, path=str(path), active=active)


def _run_json(argv: list[str], capsys) -> dict:
    rc = cli._projects_main(["discover", "--json", *argv])
    assert rc == 0, "discover --json should exit 0"
    out = capsys.readouterr().out
    return json.loads(out)


def _run_text(argv: list[str], capsys) -> str:
    rc = cli._projects_main(["discover", *argv])
    assert rc == 0
    return capsys.readouterr().out


# ──────────────────────────────  empty state  ──────────────────────────────


def test_empty_state_serializes_to_empty_arrays(env, capsys):
    payload = _run_json([], capsys)
    assert payload == {
        "used_unregistered": [],
        "registered_active": [],
        "registered_stale": [],
        "registered_path_missing": [],
        "registered_unresolved": [],
    }


def test_empty_state_human_output_is_concise(env, capsys):
    out = _run_text([], capsys)
    assert "discover:" in out
    assert "nothing to surface" in out


# ──────────────────────────────  pinned --json field contract  ──────────────────────────────


def test_used_unregistered_json_row_has_exact_pinned_fields(env, capsys):
    repo = _durable_dir(env, "src", "DontPanic")
    _seed_ledger([
        _record(repo, last_seen=_recent_iso(), observed_count=5),
    ])
    payload = _run_json([], capsys)
    assert len(payload["used_unregistered"]) == 1
    row = payload["used_unregistered"][0]
    assert set(row.keys()) == {
        "canonical_repo_key",
        "path_display",
        "observed_count",
        "last_seen",
        "suggestion_status",
        "suggested_name",
    }
    assert isinstance(row["canonical_repo_key"], str)
    assert isinstance(row["path_display"], str)
    assert isinstance(row["observed_count"], int)
    assert isinstance(row["last_seen"], str)
    assert row["suggestion_status"] in (
        render.SUGGESTION_CAN_RENDER,
        render.SUGGESTION_NEEDS_MANUAL,
    )
    # suggested_name is safe (regex-shaped).
    assert projects_registry.PROJECT_NAME_PATTERN.fullmatch(row["suggested_name"])
    assert row["suggested_name"] == "dontpanic"


def test_registered_active_json_row_has_exact_pinned_fields(env, capsys):
    repo = _durable_dir(env, "code", "myproj")
    _register("myproj", repo)
    _seed_ledger([_record(repo, last_seen=_recent_iso(), observed_count=4)])
    payload = _run_json([], capsys)
    assert len(payload["registered_active"]) == 1
    row = payload["registered_active"][0]
    assert set(row.keys()) == {
        "canonical_repo_key",
        "registry_name",
        "path_display",
        "observed_count",
        "last_seen",
        "registry_conflict",
        "conflicting_registry_names",
    }
    assert isinstance(row["canonical_repo_key"], str)
    assert row["registry_name"] == "myproj"
    assert row["observed_count"] == 4
    assert isinstance(row["registry_conflict"], bool)
    assert isinstance(row["conflicting_registry_names"], list)


_NULL_KEYED_FIELDS = {
    "canonical_repo_key",
    "registry_name",
    "registry_path_key",
    "path_display",
    "canonicalization_status",
}


def test_registered_path_missing_row_is_null_keyed_with_no_observed_fields(env, capsys):
    # Register against an existing dir, then delete it so the path is missing at
    # discover time -> registered_path_missing (canonical_repo_key=null,
    # registry_name + registry_path_key, NO observed_count/last_seen).
    gone = _durable_dir(env, "gone", "nowhere")
    _register("ghost", gone)
    gone.rmdir()
    (env["home"] / "gone").rmdir()
    payload = _run_json([], capsys)
    assert len(payload["registered_path_missing"]) == 1
    row = payload["registered_path_missing"][0]
    assert set(row.keys()) == _NULL_KEYED_FIELDS
    assert row["canonical_repo_key"] is None
    assert row["registry_name"] == "ghost"
    assert isinstance(row["registry_path_key"], str) and row["registry_path_key"]
    assert row["canonicalization_status"] == "missing"
    assert "observed_count" not in row
    assert "last_seen" not in row


def test_registered_unresolved_row_is_null_keyed(env, capsys):
    # A path that exists but canonicalizes to nothing (a temp-prefix dir, per the
    # fixture's monkeypatched _TEMP_PREFIXES) -> registered_unresolved.
    temp_repo = env["temp"] / "worktree"
    temp_repo.mkdir()
    _register("ephemeral", temp_repo)
    payload = _run_json([], capsys)
    assert len(payload["registered_unresolved"]) == 1
    row = payload["registered_unresolved"][0]
    assert set(row.keys()) == _NULL_KEYED_FIELDS
    assert row["canonical_repo_key"] is None
    assert row["registry_name"] == "ephemeral"
    assert row["canonicalization_status"] == "unresolved"
    assert "observed_count" not in row
    assert "last_seen" not in row


# ──────────────────────────────  C5 truth table surfaced in JSON  ──────────────────────────────


def test_registered_stale_when_no_observed_row_emits_zero_and_null(env, capsys):
    repo = _durable_dir(env, "code", "idle")
    _register("idle", repo)
    _seed_ledger([])  # no observed usage at all
    payload = _run_json([], capsys)
    assert payload["registered_active"] == []
    assert len(payload["registered_stale"]) == 1
    row = payload["registered_stale"][0]
    assert row["registry_name"] == "idle"
    assert row["observed_count"] == 0
    assert row["last_seen"] is None


@pytest.mark.parametrize(
    "observed_count, last_seen_fn, expect_active",
    [
        (4, _recent_iso, True),    # passes both thresholds
        (1, _recent_iso, False),   # low count
        (4, _old_iso, False),      # stale recency
    ],
)
def test_registered_active_vs_stale_truth_table(env, capsys, observed_count, last_seen_fn, expect_active):
    repo = _durable_dir(env, "code", "tt")
    _register("tt", repo)
    _seed_ledger([_record(repo, last_seen=last_seen_fn(), observed_count=observed_count)])
    payload = _run_json([], capsys)
    if expect_active:
        assert [r["registry_name"] for r in payload["registered_active"]] == ["tt"]
        assert payload["registered_stale"] == []
    else:
        assert payload["registered_active"] == []
        assert [r["registry_name"] for r in payload["registered_stale"]] == ["tt"]


def test_registered_stale_on_invalid_timestamp(env, capsys):
    repo = _durable_dir(env, "code", "badts")
    _register("badts", repo)
    _seed_ledger([_record(repo, last_seen="not-a-timestamp", observed_count=9)])
    payload = _run_json([], capsys)
    assert payload["registered_active"] == []
    assert [r["registry_name"] for r in payload["registered_stale"]] == ["badts"]


def test_inactive_registry_entry_is_inventory_only(env, capsys):
    repo = _durable_dir(env, "code", "off")
    _register("off", repo, active=False)
    _seed_ledger([_record(repo, last_seen=_recent_iso(), observed_count=9)])
    payload = _run_json([], capsys)
    # No active/stale row; also it is registered so not a used_unregistered suggestion.
    assert payload["registered_active"] == []
    assert payload["registered_stale"] == []
    assert payload["used_unregistered"] == []


def test_registry_conflict_surfaced_in_json(env, capsys):
    # Two active registry entries canonicalizing to the SAME durable repo.
    repo = _durable_dir(env, "code", "dupe")
    _register("alpha", repo)
    _register("bravo", repo)
    _seed_ledger([_record(repo, last_seen=_recent_iso(), observed_count=5)])
    payload = _run_json([], capsys)
    assert len(payload["registered_active"]) == 1
    row = payload["registered_active"][0]
    assert row["registry_name"] == "alpha"  # lexicographically first wins
    assert row["registry_conflict"] is True
    assert row["conflicting_registry_names"] == ["alpha", "bravo"]


# ──────────────────────────────  C5 defaults + overrides  ──────────────────────────────


def test_default_policy_min_count_two(env, capsys):
    # observed_count=1 fails the default min_count=2 -> not a candidate.
    repo = _durable_dir(env, "src", "lonely")
    _seed_ledger([_record(repo, last_seen=_recent_iso(), observed_count=1)])
    payload = _run_json([], capsys)
    assert payload["used_unregistered"] == []


def test_min_count_override_passes_through(env, capsys):
    repo = _durable_dir(env, "src", "lonely")
    _seed_ledger([_record(repo, last_seen=_recent_iso(), observed_count=1)])
    payload = _run_json(["--min-count", "1"], capsys)
    assert [r["path_display"] for r in payload["used_unregistered"]] == ["<home>/src/lonely"]


def test_window_days_override_passes_through(env, capsys):
    # last_seen 90 days ago fails default window (14) but passes --window-days 365.
    repo = _durable_dir(env, "src", "vintage")
    _seed_ledger([_record(repo, last_seen=_old_iso(), observed_count=4)])
    assert _run_json([], capsys)["used_unregistered"] == []
    payload = _run_json(["--window-days", "365"], capsys)
    assert [r["path_display"] for r in payload["used_unregistered"]] == ["<home>/src/vintage"]


# ──────────────────────────────  isolated vs D010-like fixtures  ──────────────────────────────


def test_isolated_registry_dontpanic_absent_yields_one_used_unregistered(env, capsys):
    repo = _durable_dir(env, "src", "DontPanic")
    # Registry has an unrelated project; DontPanic is NOT registered.
    _register("other", _durable_dir(env, "code", "other"))
    _seed_ledger([_record(repo, last_seen=_recent_iso(), observed_count=6)])
    payload = _run_json([], capsys)
    assert len(payload["used_unregistered"]) == 1
    assert payload["used_unregistered"][0]["suggested_name"] == "dontpanic"


def test_d010_like_registry_dontpanic_registered_yields_active_not_unregistered(env, capsys):
    repo = _durable_dir(env, "src", "DontPanic")
    _register("dontpanic", repo)
    _seed_ledger([_record(repo, last_seen=_recent_iso(), observed_count=6)])
    payload = _run_json([], capsys)
    assert payload["used_unregistered"] == []
    assert [r["registry_name"] for r in payload["registered_active"]] == ["dontpanic"]


# ──────────────────────────────  C1 privacy boundary  ──────────────────────────────


def test_no_raw_home_path_in_json(env, capsys):
    repo = _durable_dir(env, "src", "DontPanic")
    _register("idle", _durable_dir(env, "code", "idle"))
    _seed_ledger([_record(repo, last_seen=_recent_iso(), observed_count=6)])
    rc = cli._projects_main(["discover", "--json"])
    assert rc == 0
    raw = capsys.readouterr().out
    assert str(env["home"]) not in raw  # no raw home path
    assert "<home>" in raw  # scrubbed display IS present


def test_raw_home_in_projection_is_scrubbed_at_json_boundary(env, capsys, monkeypatch):
    # Defense-in-depth regression for the C1 emit boundary: even if an upstream
    # reconcile row slips through carrying a RAW current-home path_display (the
    # F003 adapters tokenize, but --json is the privacy boundary and must not
    # trust that), the JSON emit layer re-scrubs it so no raw home path is ever
    # serialized. `_assert_no_secret_shapes` alone does NOT catch home paths.
    from dontpanic_orchestrate import canonical_discovery as cd

    raw_leak = str(env["home"]) + "/raw/leak/DontPanic"

    def _leaky_reconcile(registered, observed, now, policy):
        return {
            "used_unregistered": [
                {
                    "canonical_repo_key": "sha256:deadbeef",
                    "path_display": raw_leak,  # RAW home path injected on purpose
                    "observed_count": 5,
                    "last_seen": _recent_iso(),
                    "suggested_name": "dontpanic",
                }
            ],
            "registered_active": [],
            "registered_stale": [],
            "registered_path_missing": [],
            "registered_unresolved": [],
        }

    monkeypatch.setattr(cd, "reconcile", _leaky_reconcile)
    rc = cli._projects_main(["discover", "--json"])
    assert rc == 0
    raw = capsys.readouterr().out
    assert str(env["home"]) not in raw  # raw home path was scrubbed out
    assert raw_leak not in raw
    payload = json.loads(raw)
    assert payload["used_unregistered"][0]["path_display"] == "<home>/raw/leak/DontPanic"


def test_no_reconstructed_add_command_path_in_json(env, capsys):
    repo = _durable_dir(env, "src", "DontPanic")
    _seed_ledger([_record(repo, last_seen=_recent_iso(), observed_count=6)])
    rc = cli._projects_main(["discover", "--json"])
    assert rc == 0
    raw = capsys.readouterr().out
    # The human-only reconstructed command never leaks into JSON.
    assert "projects add" not in raw
    assert str(env["home"]) not in raw


# ──────────────────────────────  human render matrix (C1 rules)  ──────────────────────────────


def test_home_display_yields_home_substituted_command_in_human_only(env, capsys):
    repo = _durable_dir(env, "src", "DontPanic")
    _seed_ledger([_record(repo, last_seen=_recent_iso(), observed_count=6)])
    out = _run_text([], capsys)
    expected_path = str(env["home"]) + "/src/DontPanic"
    assert f"dontpanic projects add dontpanic {expected_path}" in out


def test_canonical_outside_home_yields_verbatim_literal_command(env, capsys):
    # A literal (no scrub token) display reconstructs verbatim. We exercise the
    # render layer directly since a path outside the fake $HOME is environment-
    # dependent; this pins C1 rule (b).
    cmd = render.render_add_command("widget", "/opt/widgets/widget")
    assert cmd == "dontpanic projects add widget /opt/widgets/widget"
    assert render.suggestion_status_for("/opt/widgets/widget") == render.SUGGESTION_CAN_RENDER


def test_non_reconstructable_display_yields_placeholder_and_needs_manual():
    display = "<operator>/secret/repo"
    assert render.suggestion_status_for(display) == render.SUGGESTION_NEEDS_MANUAL
    assert render.reconstruct_add_path(display) is None
    cmd = render.render_add_command("repo", display)
    assert cmd == "dontpanic projects add repo <path>"


def test_reconstructed_path_with_spaces_is_shell_quoted():
    # A valid reconstructable path containing spaces/metacharacters must be
    # shell-quoted so the copy-paste add command stays a single argument.
    cmd = render.render_add_command("my repo", "/opt/My Repos/my repo")
    assert cmd == "dontpanic projects add 'my repo' '/opt/My Repos/my repo'"
    # The non-reconstructable placeholder stays a literal token, never quoted.
    assert render.render_add_command("repo", "<operator>/x") == (
        "dontpanic projects add repo <path>"
    )


def test_human_output_lists_candidates_and_stale(env, capsys):
    used = _durable_dir(env, "src", "DontPanic")
    stale = _durable_dir(env, "code", "idle")
    _register("idle", stale)
    _seed_ledger([_record(used, last_seen=_recent_iso(), observed_count=6)])
    out = _run_text([], capsys)
    assert "used but unregistered" in out
    assert "registered but stale" in out
    assert "idle" in out


# ──────────────────────────────  C6 command-blind  ──────────────────────────────


def test_command_field_never_surfaced_in_any_output(env, capsys):
    sentinel = "SENTINEL-NARRATIVE-OVERRIDE-DO-NOT-SURFACE"
    repo = _durable_dir(env, "src", "DontPanic")
    _seed_ledger([_record(repo, last_seen=_recent_iso(), observed_count=6, command=sentinel)])
    json_out = json.dumps(_run_json([], capsys))
    text_out = _run_text([], capsys)
    assert sentinel not in json_out
    assert sentinel not in text_out


# ──────────────────────────────  C7 negative hook guard  ──────────────────────────────


def test_command_does_not_touch_git_hooks(env, tmp_path, capsys):
    # Run discover inside a real git repo and prove the .git/hooks directory is
    # byte-identical afterward — the CLI path never installs/modifies/reads a hook.
    import subprocess

    repo = tmp_path / "hookrepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    hooks = repo / ".git" / "hooks"
    sentinel = hooks / "pre-commit"
    sentinel.write_text("#!/bin/sh\necho original\n")

    def _snapshot() -> dict:
        return {p.name: p.read_text() for p in hooks.iterdir() if p.is_file()}

    before = _snapshot()

    _durable = _durable_dir(env, "src", "DontPanic")
    _seed_ledger([_record(_durable, last_seen=_recent_iso(), observed_count=6)])

    cwd = os.getcwd()
    os.chdir(repo)
    try:
        rc = cli._projects_main(["discover", "--json"])
    finally:
        os.chdir(cwd)
    assert rc == 0
    capsys.readouterr()
    assert _snapshot() == before
    assert sentinel.read_text() == "#!/bin/sh\necho original\n"
