"""F016 — optional Buzz agent ↔ worker-profile binding (D5/C6).

Contract under test:

  - Off by default: no buzz.json / no ``agent_bindings`` key → empty
    bindings, empty resolution, CLI reports the feature as off. Nothing
    else changes behavior.
  - Config shape: ``agent_bindings`` is an optional buzz.json key mapping
    a Buzz agent id (or display name) to a LOCAL worker-profile id.
    Loading is fail-soft (invalid JSON / wrong-typed block → {}), and
    malformed entries are skipped, never raised.
  - Resolution is DISPLAY-ONLY identity join: Buzz agent → profile →
    harness + model via the F013 profile table (global overlaid by
    project). A binding to an undefined profile, or to a bare harness
    name, resolves as unbound with an operator-fixable problem message.
  - Authority invariant: bindings never CONFER dispatch. A Buzz agent
    name that names no profile stays undispatchable even when bound
    (resolve_worker refuses it); a Buzz key that collides with a profile
    id is dispatchable only because the profile id is — dispatch
    resolves the profile table entry, never the binding target — and
    dispatchability is identical with and without the binding. DontPanic
    remains the dispatch authority; Buzz remains membership/UX
    (D004/D009); model selection stays single-sourced in the profile.
  - Coexistence: notify_buzz (F006 reporter identity) and the F009
    doctor probe both tolerate the extra ``agent_bindings`` key.

Home-dir isolation comes from the conftest autouse fixture that redirects
DONTPANIC_HOME/JARVIS_HOME to per-test tmp dirs.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_f016_buzz_agent_bindings.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import buzz_bindings as bb  # noqa: E402
from dontpanic_orchestrate import global_config as gc  # noqa: E402
from dontpanic_orchestrate import notify_buzz  # noqa: E402
from dontpanic_orchestrate import project_config as pc  # noqa: E402
from dontpanic_orchestrate import worker_profiles as wp  # noqa: E402
from dontpanic_orchestrate.workers_cli import workers_main  # noqa: E402

REPO_ROOT = HERE.parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"

_BASE_BUZZ = {
    "relay_url": "wss://relay.example.com",
    "channels": ["11111111-2222-3333-4444-555555555555"],
    "reporter_key_ref": "env:BUZZ_PRIVATE_KEY",
}

_FIZZ_PROFILE = {
    "display_name": "Fizz",
    "harness": "claude",
    "model": "claude-fable-5",
    "allowed_roles": ["implementer"],
}

_HONEY_PROFILE = {
    "display_name": "Honey",
    "harness": "claude",
    "model": "claude-opus-5",
    "allowed_roles": ["implementer"],
}


@pytest.fixture(autouse=True)
def _no_buzz_config_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DONTPANIC_BUZZ_CONFIG", raising=False)


def _write_buzz_json(payload: dict, path: Path | None = None) -> Path:
    target = path if path is not None else gc.dontpanic_home() / "buzz.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _save_global_profiles(profiles: dict) -> None:
    gc.save_config(gc.GlobalConfig.model_validate({"worker_profiles": profiles}))


# ── Config loading (off by default, fail-soft) ────────────────────────────


def test_off_by_default_without_buzz_json():
    assert bb.load_agent_bindings() == {}
    assert bb.resolve_agent_bindings() == []


def test_off_by_default_without_agent_bindings_key():
    _write_buzz_json(_BASE_BUZZ)
    assert bb.load_agent_bindings() == {}
    assert bb.resolve_agent_bindings() == []


def test_loads_bindings_from_home_buzz_json():
    _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"buzz:fizz": "fizz"}})
    assert bb.load_agent_bindings() == {"buzz:fizz": "fizz"}


def test_env_override_path_respected(tmp_path, monkeypatch: pytest.MonkeyPatch):
    override = tmp_path / "elsewhere" / "buzz.json"
    _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"Honey": "honey"}}, override)
    monkeypatch.setenv("DONTPANIC_BUZZ_CONFIG", str(override))
    assert bb.load_agent_bindings() == {"Honey": "honey"}


@pytest.mark.parametrize(
    "payload",
    [
        "not json at all",
        json.dumps([1, 2]),
        json.dumps({**_BASE_BUZZ, "agent_bindings": "fizz"}),
        json.dumps({**_BASE_BUZZ, "agent_bindings": ["fizz"]}),
    ],
)
def test_fail_soft_on_invalid_shapes(payload: str):
    target = gc.dontpanic_home() / "buzz.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    assert bb.load_agent_bindings() == {}


def test_malformed_entries_skipped_valid_ones_kept():
    _write_buzz_json(
        {
            **_BASE_BUZZ,
            "agent_bindings": {
                "Fizz": "fizz",
                "": "orphan-key",
                "Bumble": "",
                "Honey": 42,
            },
        }
    )
    assert bb.load_agent_bindings() == {"Fizz": "fizz"}


# ── Resolution (display-only identity join) ───────────────────────────────


def test_resolution_joins_profile_harness_and_model():
    _save_global_profiles({"fizz": _FIZZ_PROFILE})
    _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"Fizz": "fizz"}})
    rows = bb.resolve_agent_bindings()
    assert len(rows) == 1
    row = rows[0]
    assert row.buzz_agent == "Fizz"
    assert row.profile_id == "fizz"
    assert row.bound is True
    assert row.display_name == "Fizz"
    assert row.harness == "claude"
    assert row.model == "claude-fable-5"
    assert row.problem is None


def test_resolution_sees_project_layer_profiles(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    cfg = pc.project_config_path(project)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"worker_profiles": {"bumble": {"harness": "codex"}}}))
    _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"Bumble": "bumble"}})
    (unbound,) = bb.resolve_agent_bindings()
    assert unbound.bound is False
    (bound,) = bb.resolve_agent_bindings(project_path=project)
    assert bound.bound is True
    assert bound.harness == "codex"


def test_binding_to_undefined_profile_is_unbound_with_problem():
    _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"Ghost": "nobody"}})
    (row,) = bb.resolve_agent_bindings()
    assert row.bound is False
    assert row.harness is None and row.model is None
    assert row.problem is not None and "worker profile" in row.problem


def test_binding_to_harness_name_is_unbound_not_a_profile():
    _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"Fizz": "claude_cli"}})
    (row,) = bb.resolve_agent_bindings()
    assert row.bound is False
    assert row.problem is not None and "harness" in row.problem


# ── Authority invariant: bindings never grant dispatch ────────────────────


def test_bound_buzz_agent_name_gains_no_dispatch():
    _save_global_profiles({"fizz": _FIZZ_PROFILE})
    _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"Fizz": "fizz"}})
    # The Buzz-side name is NOT dispatchable — only the profile id is.
    assert wp.is_dispatchable_name("Fizz") is False
    with pytest.raises(wp.UnknownWorkerError):
        wp.resolve_worker(None, "implementer", "Fizz")
    # The profile itself is unchanged by the binding.
    resolved = wp.resolve_worker(None, "implementer", "fizz")
    assert resolved.profile_id == "fizz"
    assert resolved.harness == "claude"


def test_buzz_key_colliding_with_profile_id_dispatches_via_profile_only():
    # Auditor i0 regression: a Buzz key equal to a profile id ("fizz" →
    # "fizz") IS dispatchable — because the profile id is, not because a
    # binding exists. Dispatchability must be identical with and without
    # the binding configured.
    _save_global_profiles({"fizz": _FIZZ_PROFILE})
    assert wp.is_dispatchable_name("fizz", role="implementer") is True
    _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"fizz": "fizz"}})
    assert wp.is_dispatchable_name("fizz", role="implementer") is True
    assert wp.resolve_worker(None, "implementer", "fizz").profile_id == "fizz"


def test_colliding_binding_to_another_profile_is_ignored_by_dispatch():
    # Sharper collision: Buzz key "fizz" bound to profile "honey".
    # Dispatching "fizz" must resolve the fizz PROFILE (its own model),
    # never redirect through the binding to honey's harness/model.
    _save_global_profiles({"fizz": _FIZZ_PROFILE, "honey": _HONEY_PROFILE})
    _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"fizz": "honey"}})
    resolved = wp.resolve_worker(None, "implementer", "fizz")
    assert resolved.profile_id == "fizz"
    assert resolved.model == "claude-fable-5"


def test_unbound_buzz_agent_and_undefined_target_stay_undispatchable():
    # Unbound regression: neither the Buzz key nor its undefined target
    # profile id becomes dispatchable by appearing in a binding.
    _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"Ghost": "nobody"}})
    for name in ("Ghost", "nobody"):
        assert wp.is_dispatchable_name(name) is False
        with pytest.raises(wp.UnknownWorkerError):
            wp.resolve_worker(None, "implementer", name)


# ── Coexistence with the F006 notify sink and F009 doctor probe ───────────


def test_notify_sink_tolerates_agent_bindings_key(monkeypatch: pytest.MonkeyPatch):
    path = _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"Fizz": "fizz"}})
    monkeypatch.setenv("DONTPANIC_BUZZ_CONFIG", str(path))
    config = notify_buzz._load_config()
    assert config is not None
    assert config.relay_url == _BASE_BUZZ["relay_url"]


def test_doctor_probe_tolerates_agent_bindings_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DONTPANIC_SKIP_BUZZ", raising=False)
    spec = importlib.util.spec_from_file_location("jarvis_doctor_f016", DOCTOR_PATH)
    assert spec and spec.loader
    doctor = importlib.util.module_from_spec(spec)
    sys.modules["jarvis_doctor_f016"] = spec and doctor
    spec.loader.exec_module(doctor)
    path = _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"Fizz": "fizz"}})
    result = doctor.check_buzz_config(config_path=path)
    assert result.ok is True
    assert "configured" in result.message


# ── CLI: dontpanic workers buzz-bindings ──────────────────────────────────


def test_cli_reports_feature_off_by_default(capsys):
    assert workers_main(["buzz-bindings"]) == 0
    out = capsys.readouterr().out
    assert "off by default" in out


def test_cli_renders_bound_and_unbound_rows(capsys):
    _save_global_profiles({"fizz": _FIZZ_PROFILE})
    _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"Fizz": "fizz", "Ghost": "nobody"}})
    assert workers_main(["buzz-bindings"]) == 0
    out = capsys.readouterr().out
    assert "Fizz" in out and "fizz" in out
    assert "claude" in out and "claude-fable-5" in out
    assert "Ghost" in out and "UNBOUND" in out
    # The status surface states the authority boundary.
    assert "never" in out and "dispatch" in out


def test_cli_json_output(capsys):
    _save_global_profiles({"fizz": _FIZZ_PROFILE})
    _write_buzz_json({**_BASE_BUZZ, "agent_bindings": {"Fizz": "fizz"}})
    assert workers_main(["buzz-bindings", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    rows = payload["agent_bindings"]
    assert rows == [
        {
            "buzz_agent": "Fizz",
            "profile_id": "fizz",
            "bound": True,
            "display_name": "Fizz",
            "harness": "claude",
            "model": "claude-fable-5",
            "problem": None,
        }
    ]
