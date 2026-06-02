"""Tests for dashboard Settings/Setup rendering of the F008 inventory — F013.

Covers F013 acceptance:
  (1) `dashboard build` renders the F008 inventory as Settings/Setup cards (the
      same data the CLI `config inventory` shows), not merely a state blob.
  (2) The response-level dashboard_hint auto-detects a running dashboard
      singleton for active_url and falls back to the start command when none
      runs — without the caller passing dashboard_url.
  (3) Exactly one response-level dashboard_hint; item-level cards reference it
      (dashboard_hint_ref) rather than repeating its text.
  (4) Edit affordances (validated safe_command) render distinctly from
      run-actions; build/start/serve commands never render as a card's edit
      command.
  (5) Tests prove cards render for >=10 providers, active/inactive hint
      auto-detection, dashboard-hint dedup, and no build/start edit affordance.

The autouse ``_isolate_jarvis_state`` conftest fixture redirects DONTPANIC_HOME /
JARVIS_HOME to a per-test tmp dir, so each inventory runs against a clean home.
"""
from __future__ import annotations

import json
import os

from dontpanic_orchestrate import config_inventory as ci
from dontpanic_orchestrate import dashboard
from dontpanic_orchestrate import projects_dashboard as pd
from dontpanic_orchestrate import projects_registry as pr

# ─────────────────── helpers ───────────────────


def _force_human_required(monkeypatch) -> None:
    """Force a required-secret gap so collect_inventory emits the dashboard hint.

    The Anthropic auth provider is the one REQUIRED (non-optional) secret; an
    absent one is human_required, which is the trigger for the single
    response-level dashboard hint (AC6). Pinning it absent makes the hint
    deterministic regardless of the test machine's real credentials.
    """
    monkeypatch.setattr(ci, "_anthropic_auth_facts", lambda: (False, True, True))


# ─────────────── (1)+(5) cards render for >=10 providers via build ───────────


def test_dashboard_build_renders_inventory_cards_for_ten_providers(tmp_path):
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    out_dir = tmp_path / "state"

    report = dashboard.build(
        plans_root=plans_root,
        out_dir=out_dir,
        repo_root=tmp_path,
        write_what_now_cache=False,
        write_capabilities_cache=False,
        check_reconcile=False,
        check_architecture=False,
    )

    assert report.config_inventory_path is not None
    assert report.config_inventory_path.is_file()
    state = json.loads(report.config_inventory_path.read_text())

    # Rendered as Settings/Setup cards, not merely a generated state blob (AC1).
    assert state["kind"] == "config_inventory"
    assert "settings_cards" in state and "setup_cards" in state
    total_cards = len(state["settings_cards"]) + len(state["setup_cards"])
    assert total_cards >= 10, f"expected >=10 inventory cards, got {total_cards}"

    # Cards carry the same provider identity the CLI inventory shows.
    card_ids = {c["id"] for c in state["settings_cards"]} | {
        c["id"] for c in state["setup_cards"]
    }
    cli_ids = {i.id for i in ci.collect_inventory().items}
    assert card_ids == cli_ids


def test_to_dashboard_state_renders_at_least_ten_cards():
    state = ci.to_dashboard_state(ci.collect_inventory())
    total = len(state["settings_cards"]) + len(state["setup_cards"])
    assert total >= 10


# ─────────────── (2) active/inactive hint auto-detection ───────────


def test_hint_auto_detects_running_dashboard_for_active_url(monkeypatch):
    _force_human_required(monkeypatch)
    monkeypatch.setattr(
        dashboard, "detect_active_url", lambda *a, **k: "http://127.0.0.1:8732/"
    )

    inv = ci.collect_inventory()
    assert inv.dashboard_hint is not None
    assert inv.dashboard_hint.is_running is True
    assert inv.dashboard_hint.url == "http://127.0.0.1:8732/"

    hint = ci.to_dashboard_state(inv)["dashboard_hint"]
    assert hint["is_running"] is True
    assert hint["active_url"] == "http://127.0.0.1:8732/"
    assert hint["start_command"] is None


def test_hint_falls_back_to_start_command_when_inactive(monkeypatch):
    _force_human_required(monkeypatch)
    monkeypatch.setattr(dashboard, "detect_active_url", lambda *a, **k: None)

    inv = ci.collect_inventory()
    assert inv.dashboard_hint is not None
    assert inv.dashboard_hint.is_running is False

    hint = ci.to_dashboard_state(inv)["dashboard_hint"]
    assert hint["is_running"] is False
    assert hint["active_url"] is None
    assert hint["start_command"] == ci.DASHBOARD_START_COMMAND


def test_caller_does_not_pass_dashboard_url(monkeypatch):
    # AC2: auto-detection means the caller never threads dashboard_url. Prove the
    # active URL flows purely from the singleton detector, not an argument.
    _force_human_required(monkeypatch)
    monkeypatch.setattr(
        dashboard, "detect_active_url", lambda *a, **k: "http://127.0.0.1:5555/"
    )
    inv = ci.collect_inventory()  # NOTE: no dashboard_url passed
    assert inv.dashboard_hint.url == "http://127.0.0.1:5555/"


# ─────────────── (3) exactly one hint; items reference it ───────────


def test_exactly_one_dashboard_hint_items_reference_not_repeat(monkeypatch):
    _force_human_required(monkeypatch)
    monkeypatch.setattr(dashboard, "detect_active_url", lambda *a, **k: None)

    inv = ci.collect_inventory()
    state = ci.to_dashboard_state(inv)

    # Exactly one response-level hint object.
    assert state["dashboard_hint"] is not None
    hint_text = state["dashboard_hint"]["text"]

    all_cards = state["settings_cards"] + state["setup_cards"]
    human_cards = [c for c in all_cards if c["human_required"]]
    assert human_cards, "expected at least one human-required card"

    for card in all_cards:
        # No card embeds the full hint text — they reference by id only.
        assert hint_text not in json.dumps(card)
        if card["human_required"]:
            assert card["dashboard_hint_ref"] == ci.DASHBOARD_HINT_ID


# ─────────────── (4) edit vs run-action distinction ───────────


def test_no_build_or_start_command_renders_as_edit_affordance():
    state = ci.to_dashboard_state(ci.collect_inventory())
    all_cards = state["settings_cards"] + state["setup_cards"]

    for card in all_cards:
        edit_cmd = card["edit"]["command"]
        if edit_cmd:
            assert not ci._is_run_action_command(edit_cmd), (
                f"{card['id']}: build/start/serve command {edit_cmd!r} rendered "
                "as an edit affordance"
            )
        # Back-compat flat field must mirror the edit affordance (never a run-action).
        assert card["safe_command"] == edit_cmd


def test_build_and_serve_surfaces_render_as_distinct_run_actions():
    state = ci.to_dashboard_state(ci.collect_inventory())
    cards = {c["id"]: c for c in state["settings_cards"] + state["setup_cards"]}

    dash = cards["dashboard"]
    assert dash["edit"]["command"] is None
    assert dash["run_action"] is not None
    assert dash["run_action"]["command"] == "dontpanic dashboard build"

    mcp = cards["mcp"]
    assert mcp["edit"]["command"] is None
    assert mcp["run_action"]["command"] == "dontpanic mcp serve"


def test_is_run_action_command_classifier():
    assert ci._is_run_action_command("dontpanic dashboard build")
    assert ci._is_run_action_command("dontpanic dashboard serve")
    assert ci._is_run_action_command("dontpanic dashboard open")
    assert ci._is_run_action_command("dontpanic mcp serve")
    # Genuine edits are NOT run-actions.
    assert not ci._is_run_action_command("dontpanic roles set claude implementer")
    assert not ci._is_run_action_command("dontpanic quota-caps init")
    assert not ci._is_run_action_command("dontpanic capabilities setup x --print-steps")
    assert not ci._is_run_action_command(None)


# ─────────────── detection primitive: roundtrip + stale prune ───────────


def test_detect_active_dashboard_roundtrip(tmp_path):
    dash_dir = tmp_path / "dashboard"
    dash_dir.mkdir()
    dashboard._write_singleton_record(
        dashboard_dir=dash_dir,
        host="127.0.0.1",
        port=8123,
        url="http://127.0.0.1:8123/",
        project=None,
    )
    assert dashboard.detect_active_url(dash_dir) == "http://127.0.0.1:8123/"


def test_detect_active_dashboard_prunes_stale_record(tmp_path):
    dash_dir = tmp_path / "dashboard"
    dash_dir.mkdir()
    record_path = dashboard._singleton_record_path(dash_dir)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    # A pid that is guaranteed dead (1 is init, but os.kill(dead, 0) on a freed
    # high pid raises ProcessLookupError) — use an unused high pid.
    dead_pid = 2_000_000_000
    record_path.write_text(
        json.dumps({"pid": dead_pid, "url": "http://127.0.0.1:9/"}) + "\n"
    )
    assert dashboard.detect_active_url(dash_dir) is None
    # Stale record is pruned so it can never advertise a phantom URL again.
    assert not record_path.is_file()


def test_detect_active_dashboard_absent_returns_none(tmp_path):
    assert dashboard.detect_active_url(tmp_path / "nope") is None


def test_serve_rebuilds_config_inventory_with_active_url(tmp_path, monkeypatch):
    # Finding 2 (codex i0): serve_start built state BEFORE binding + recording
    # the singleton, so the first served config-inventory.json fell back to the
    # start command even though the dashboard was live. Prove the served
    # inventory now reflects the active URL once the server is up.
    _force_human_required(monkeypatch)  # so a human-required item attaches a hint
    dash_dir = tmp_path / "dashboard"
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    state_out_dir = dash_dir / "state"
    handle = dashboard.serve_start(
        dashboard_dir=dash_dir,
        plans_root=plans_root,
        state_out_dir=state_out_dir,
        repo_root=tmp_path,
        watch=False,
    )
    try:
        state = json.loads((state_out_dir / "config-inventory.json").read_text())
        hint = state["dashboard_hint"]
        assert hint is not None, "expected a dashboard hint for the human-required item"
        # The FIRST served inventory must show the live URL, not the start command.
        assert hint["is_running"] is True
        assert hint["active_url"] == handle.url
        assert hint["start_command"] is None
    finally:
        handle.shutdown()


# ─────────── (codex i1) project/fleet path renders the selected project ───────


def _register_project(tmp_path, name: str = "alpha"):
    """Register a throwaway repo as a dashboard project and return its dir."""
    repo = tmp_path / f"{name}-repo"
    (repo / "docs" / "plans").mkdir(parents=True)
    pr.add_project(name=name, path=str(repo))
    return repo


def test_build_project_mirrors_scoped_inventory_cards(tmp_path):
    # codex i1 (high): `dashboard build --project <name>` must write the focused
    # project's inventory into the served tree at
    # state/projects/<name>/config-inventory.json so the Settings page can load
    # THAT project's cards — not the machine-scope top-level blob.
    _register_project(tmp_path, "alpha")
    state_out_dir = tmp_path / "state"

    result = pd.build_selected("alpha", out_dir=state_out_dir)
    pd.mirror_selection_into_state_dir(result, state_out_dir=state_out_dir)

    mirror = state_out_dir / "projects" / "alpha" / "config-inventory.json"
    assert mirror.is_file(), "per-project inventory mirror was not written"
    state = json.loads(mirror.read_text())
    assert state["kind"] == "config_inventory"
    assert state["project_name"] == "alpha"
    total_cards = len(state["settings_cards"]) + len(state["setup_cards"])
    assert total_cards >= 10, f"expected >=10 project cards, got {total_cards}"


def test_build_all_writes_top_level_inventory_for_default_view(tmp_path):
    # codex F013 i2 (high): the fleet/`all` BUILD path must write the top-level
    # state/config-inventory.json. The dashboard defaults its selection to `all`,
    # whose resolveConfigInventory() reads only that top-level file — so without
    # it the default All-Projects view renders an EMPTY Settings inventory. The
    # serve path already did this; the build path did not (the bug). Drive the
    # real `_build_main` entrypoint, not the lower-level pd.* helpers.
    import argparse

    _register_project(tmp_path, "alpha")
    state_out_dir = tmp_path / "state"
    args = argparse.Namespace(
        project="all",
        out_dir=str(state_out_dir),
        plans_root=None,
        redact_level="default",
        plan_id=None,
    )
    rc = dashboard._build_main(args)
    assert rc == 0
    top = state_out_dir / "config-inventory.json"
    assert top.is_file(), "fleet/all build did not write top-level config-inventory.json"
    state = json.loads(top.read_text())
    assert state["kind"] == "config_inventory"
    total = len(state["settings_cards"]) + len(state["setup_cards"])
    assert total >= 10, f"expected >=10 cards in the default All-Projects view, got {total}"


def test_serve_project_renders_selected_project_inventory_with_active_url(
    tmp_path, monkeypatch
):
    # codex i1 (high + test_coverage): serving a single project must render that
    # project's inventory in Settings AND keep active-url detection. Prove both
    # the served per-project mirror and the top-level fallback carry the focused
    # project's scope plus the live URL (not the start command).
    _force_human_required(monkeypatch)  # so a human-required card attaches a hint
    _register_project(tmp_path, "alpha")
    dash_dir = tmp_path / "dashboard"
    state_out_dir = dash_dir / "state"
    handle = dashboard.serve_start(
        dashboard_dir=dash_dir,
        plans_root=tmp_path / "plans",
        state_out_dir=state_out_dir,
        repo_root=tmp_path,
        watch=False,
        project="alpha",
    )
    try:
        mirror = json.loads(
            (state_out_dir / "projects" / "alpha" / "config-inventory.json").read_text()
        )
        # The served project's mirror is what the UI loads when alpha is
        # selected — it must be scoped to alpha and show the live URL.
        assert mirror["project_name"] == "alpha"
        assert mirror["dashboard_hint"] is not None
        assert mirror["dashboard_hint"]["is_running"] is True
        assert mirror["dashboard_hint"]["active_url"] == handle.url
        assert mirror["dashboard_hint"]["start_command"] is None

        # The top-level fallback must keep the focused project's scope too — not
        # be silently rebuilt at machine scope (project_name=None).
        top = json.loads((state_out_dir / "config-inventory.json").read_text())
        assert top["project_name"] == "alpha"
        assert top["dashboard_hint"]["active_url"] == handle.url
    finally:
        handle.shutdown()


def test_serve_records_and_shutdown_clears_singleton(tmp_path):
    dash_dir = tmp_path / "dashboard"
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    handle = dashboard.serve_start(
        dashboard_dir=dash_dir,
        plans_root=plans_root,
        state_out_dir=dash_dir / "state",
        repo_root=tmp_path,
        watch=False,
    )
    try:
        url = dashboard.detect_active_url(dash_dir)
        assert url == handle.url
        assert os.getpid() == json.loads(
            dashboard._singleton_record_path(dash_dir).read_text()
        )["pid"]
    finally:
        handle.shutdown()
    # Shutdown prunes the singleton so a later detection reports "not running".
    assert dashboard.detect_active_url(dash_dir) is None
