"""Plan 2026-06-21-001 F007 — `dontpanic doctor --acknowledge` tests.

The acknowledge path is the ONLY doctor surface that WRITES the upgrade marker
(D015). It advances the marker to the latest release and dismisses the currently-
shown advisories, COMMITS the result via F004's ``write_upgrade_state``, then
re-renders from the committed marker. This module pins:

* marker advance + commit (the marker file is written; last_seen_release/_commit
  reflect the latest release + installed commit);
* advisory silencing (currently-shown advisories disappear after acknowledge);
* the CRITICAL invariant (D004): a required action whose status_probe still fails
  is STILL pending after acknowledge — acknowledge never clears it (dedicated test);
* acknowledge is the SOLE marker writer (the read-only render paths never write);
* legal combinations (D027): acknowledge composes with the upgrade report mode in
  BOTH human and JSON form, and the post-acknowledge report reflects the ADVANCED
  marker (advisories silenced, last_seen_release/_commit updated) while a probe-
  failing required action still shows pending;
* acknowledge ALONE advances + commits the marker and prints a concise confirmation;
* the CLI argparse path routes the three acknowledge modes correctly.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"


def _load_doctor():
    spec = importlib.util.spec_from_file_location("jarvis_doctor", DOCTOR_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jarvis_doctor"] = mod  # register so @dataclass resolves forward refs
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def doctor():
    return _load_doctor()


# ─────────────────────────  manifest fixture (written to disk)  ─────────────────────────

BASELINE = "2026-06-13-pre-experience-readiness"


def _required_action(action_id: str, *, probe: str) -> dict:
    return {
        "id": action_id,
        "kind": "required",
        "severity": "critical",
        "title": f"required {action_id}",
        "detail": "why this is required",
        "status_probe": probe,
        "commands": [
            {"label": "preview", "command": "dontpanic do-thing --dry-run"},
            {"label": "apply", "command": "dontpanic do-thing"},
            {"label": "verify", "command": "dontpanic doctor"},
        ],
        "human_next_step": "run the apply command",
    }


def _advisory_action(action_id: str) -> dict:
    return {
        "id": action_id,
        "kind": "advisory",
        "severity": "optional",
        "title": f"advisory {action_id}",
        "detail": "why this is advisory",
    }


def _manifest_dict() -> dict:
    """r1 (advisory a1 + required req1[probe_ok], first-run) < r3 (required req3[probe_bad])."""
    return {
        "baseline_release": BASELINE,
        "baseline_date": "2026-06-13",
        "releases": [
            {
                "id": "r1",
                "date": "2026-06-14",
                "summary": "release one",
                "show_on_first_run": True,
                "actions": [
                    _advisory_action("a1"),
                    _required_action("req1", probe="probe_ok"),
                ],
            },
            {
                "id": "r3",
                "date": "2026-06-16",
                "summary": "release three",
                "show_on_first_run": True,
                "actions": [
                    _required_action("req3", probe="probe_bad"),
                ],
            },
        ],
    }


def _write_manifest(tmp_path: Path) -> Path:
    p = tmp_path / "releases.json"
    p.write_text(json.dumps(_manifest_dict()), encoding="utf-8")
    return p


def _registry(*, probes=None, gates=None) -> dict:
    return {"status_probe": dict(probes or {}), "applies_when": dict(gates or {})}


def _const(satisfied: bool, detail: str):
    def _fn(_ctx):
        from dontpanic_orchestrate.upgrade_predicates import PredicateResult

        return PredicateResult(satisfied=satisfied, detail=detail)

    return _fn


def _probe_registry():
    return _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(False, "nope")})


def _recording_git(responses: dict):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate.upgrade_report import GitProbe
    finally:
        sys.path.pop(0)
    return GitProbe(runner=lambda args: responses.get(tuple(args)))


def _git_behind():
    return _recording_git(
        {
            ("rev-parse", "--short", "HEAD"): "abc1234",
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): "origin/main",
            ("rev-parse", "--short", "origin/main"): "def5678",
            ("rev-list", "--left-right", "--count", "HEAD...origin/main"): "0\t3",
        }
    )


def _git_off():
    return _recording_git({})


def _read_marker_json(marker: Path) -> dict:
    return json.loads(marker.read_text(encoding="utf-8"))


# ─────────────────────────  marker advance + commit  ─────────────────────────


def test_acknowledge_advances_and_commits_marker(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    marker = tmp_path / "upgrade-state.json"
    assert not marker.exists()  # fresh instance — no marker yet

    result = doctor.acknowledge_upgrade(
        manifest_path=mp,
        marker_path=marker,
        predicate_registry=_probe_registry(),
        git=_git_behind(),
        now="2026-06-22T00:00:00Z",
    )

    # The marker file is COMMITTED to disk, advanced to the latest release with
    # the installed commit recorded + a first-write consent stamp.
    assert marker.exists()
    on_disk = _read_marker_json(marker)
    assert on_disk["last_seen_release"] == "r3"
    assert on_disk["last_seen_commit"] == "abc1234"
    assert on_disk["first_initialized_at"] == "2026-06-22T00:00:00Z"
    # The re-rendered report reflects the advanced acknowledgement.
    assert result.report.summary.last_seen_release == "r3"
    assert result.report.summary.last_seen_commit == "abc1234"
    assert result.acknowledged_release == "r3"


def test_acknowledge_off_git_stores_no_commit(doctor, tmp_path):
    """Off-git the installed commit is the UNKNOWN sentinel — never persisted."""
    mp = _write_manifest(tmp_path)
    marker = tmp_path / "upgrade-state.json"
    result = doctor.acknowledge_upgrade(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=_git_off()
    )
    on_disk = _read_marker_json(marker)
    assert on_disk["last_seen_release"] == "r3"
    assert on_disk["last_seen_commit"] is None  # never the "unknown" sentinel
    assert result.acknowledged_commit is None


def test_acknowledge_preserves_existing_first_initialized_at(doctor, tmp_path):
    """The consent stamp is set ONCE; a re-acknowledge never overwrites it."""
    mp = _write_manifest(tmp_path)
    marker = tmp_path / "upgrade-state.json"
    marker.write_text(
        json.dumps({"last_seen_release": "r1", "first_initialized_at": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    doctor.acknowledge_upgrade(
        manifest_path=mp,
        marker_path=marker,
        predicate_registry=_probe_registry(),
        git=_git_off(),
        now="2026-06-22T00:00:00Z",
    )
    assert _read_marker_json(marker)["first_initialized_at"] == "2026-01-01T00:00:00Z"


# ─────────────────────────  advisory silencing  ─────────────────────────


def test_acknowledge_silences_currently_shown_advisories(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    marker = tmp_path / "upgrade-state.json"

    # Before: a fresh marker shows the first-run advisory a1.
    before = doctor.build_upgrade_report(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=_git_off()
    )
    assert before.summary.pending_advisory == 1
    assert any(item.action_id == "a1" for item in before.advisory)

    result = doctor.acknowledge_upgrade(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=_git_off()
    )

    # After: the currently-shown advisory is silenced (dismissed + marker advanced).
    assert result.silenced == 1
    assert result.report.summary.pending_advisory == 0
    assert result.report.advisory == []
    assert "upgrade:r1:a1" in _read_marker_json(marker)["dismissed_advisories"]


def test_acknowledge_silencing_survives_a_fresh_read(doctor, tmp_path):
    """A subsequent READ of the committed marker shows no advisories (it stuck)."""
    mp = _write_manifest(tmp_path)
    marker = tmp_path / "upgrade-state.json"
    doctor.acknowledge_upgrade(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=_git_off()
    )
    after = doctor.build_upgrade_report(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=_git_off()
    )
    assert after.summary.pending_advisory == 0


# ─────────────────────  CRITICAL invariant: probe-failing required stays pending (D004)  ─────────────────────


def test_acknowledge_does_not_clear_probe_failing_required(doctor, tmp_path):
    """D004: acknowledge advances the marker + silences advisories ONLY — a
    required action whose status_probe still FAILS remains pending afterward."""
    mp = _write_manifest(tmp_path)
    marker = tmp_path / "upgrade-state.json"

    result = doctor.acknowledge_upgrade(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=_git_off()
    )

    # Advisories silenced, marker advanced...
    assert result.report.summary.pending_advisory == 0
    assert result.report.summary.last_seen_release == "r3"
    # ...but req3 (probe_bad) is STILL listed as a pending required action.
    assert result.report.summary.pending_required == 1
    assert any(item.action_id == "req3" for item in result.report.required)


def test_acknowledge_clears_required_only_when_probe_passes(doctor, tmp_path):
    """Control: when the probe PASSES, the required action is not pending — proving
    the pending-ness above comes from the live probe (F003), not the acknowledge."""
    mp = _write_manifest(tmp_path)
    marker = tmp_path / "upgrade-state.json"
    reg = _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "now ok")})
    result = doctor.acknowledge_upgrade(
        manifest_path=mp, marker_path=marker, predicate_registry=reg, git=_git_off()
    )
    assert result.report.summary.pending_required == 0
    assert result.report.required == []


# ─────────────────────────  acknowledge is the SOLE marker writer  ─────────────────────────


def test_acknowledge_is_the_only_path_that_writes_the_marker(doctor, tmp_path, monkeypatch):
    """The read-only render paths never write; the acknowledge path writes exactly
    once via the SOLE writer ``write_upgrade_state`` (D015)."""
    mp = _write_manifest(tmp_path)
    marker = tmp_path / "upgrade-state.json"

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import upgrade_state as us
    finally:
        sys.path.pop(0)

    real_write = us.write_upgrade_state
    writes: list = []

    def _spy(marker_val, *, path=None):
        writes.append(path)
        return real_write(marker_val, path=path)

    monkeypatch.setattr(us, "write_upgrade_state", _spy)

    # Read-only renders: ZERO writes.
    doctor.build_upgrade_report(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=_git_off()
    )
    doctor.check_upgrade_readiness(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=_git_off()
    )
    assert writes == []
    assert not marker.exists()

    # Acknowledge: exactly ONE marker write, and the file lands on disk.
    doctor.acknowledge_upgrade(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=_git_off()
    )
    assert len(writes) == 1
    assert marker.exists()


# ─────────────────────  legal combinations: acknowledge + upgrade report (D027)  ─────────────────────


def test_acknowledge_composes_with_upgrade_human_report(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    marker = tmp_path / "upgrade-state.json"
    result = doctor.acknowledge_upgrade(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=_git_behind()
    )
    text = doctor.render_upgrade_report_text(result.report)
    # The advanced acknowledgement is reflected in the human report...
    assert "last acknowledged:  r3" in text
    assert "pending advisory:   0" in text
    # ...while the probe-failing required action still shows as pending.
    assert "pending required:   1" in text
    assert "req3" in text


def test_acknowledge_composes_with_upgrade_json_report(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    marker = tmp_path / "upgrade-state.json"
    result = doctor.acknowledge_upgrade(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=_git_behind()
    )
    payload = json.loads(doctor.render_upgrade_report_json(result.report))
    summary = payload["summary"]
    assert summary["last_seen_release"] == "r3"
    assert summary["last_seen_commit"] == "abc1234"
    assert summary["pending_advisory"] == 0
    assert payload["advisory"] == []
    # The probe-failing required action remains in the JSON required[] list.
    assert summary["pending_required"] == 1
    assert [item["action_id"] for item in payload["required"]] == ["req3"]


# ─────────────────────────  acknowledge alone → concise confirmation  ─────────────────────────


def test_acknowledge_confirmation_mentions_advance_and_pending_required(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    marker = tmp_path / "upgrade-state.json"
    result = doctor.acknowledge_upgrade(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=_git_off()
    )
    msg = doctor.render_acknowledge_confirmation(result)
    assert "advanced to r3" in msg  # the advance is confirmed
    assert "Silenced 1 advisory" in msg  # the silencing is reported
    assert "STILL pending" in msg  # D004: the probe-failing required is called out
    assert "doctor --upgrade" in msg  # remediation pointer


# ─────────────────────────  CLI argparse routing  ─────────────────────────


def test_cli_main_acknowledge_alone_prints_confirmation(doctor, monkeypatch, capsys):
    sentinel = doctor.AcknowledgeResult(
        report=None, acknowledged_release="r3", acknowledged_commit=None, silenced=2
    )
    captured: dict = {}
    monkeypatch.setattr(doctor, "acknowledge_upgrade", lambda **k: captured.update(k) or sentinel)
    monkeypatch.setattr(doctor, "render_acknowledge_confirmation", lambda r: f"CONFIRM:{r is sentinel}")
    rc = doctor.main(["--acknowledge"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "CONFIRM:True" in out
    assert captured.get("check_upstream") is False


def test_cli_main_acknowledge_upgrade_human(doctor, monkeypatch, capsys):
    sentinel = doctor.AcknowledgeResult(
        report=object(), acknowledged_release="r3", acknowledged_commit=None, silenced=0
    )
    monkeypatch.setattr(doctor, "acknowledge_upgrade", lambda **k: sentinel)
    monkeypatch.setattr(doctor, "render_upgrade_report_text", lambda r: f"HUMAN:{r is sentinel.report}")
    rc = doctor.main(["--acknowledge", "--upgrade"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "HUMAN:True" in out


def test_cli_main_acknowledge_upgrade_json_with_check_upstream(doctor, monkeypatch, capsys):
    sentinel = doctor.AcknowledgeResult(
        report=object(), acknowledged_release="r3", acknowledged_commit=None, silenced=0
    )
    captured: dict = {}
    monkeypatch.setattr(doctor, "acknowledge_upgrade", lambda **k: captured.update(k) or sentinel)
    monkeypatch.setattr(doctor, "render_upgrade_report_json", lambda r: '{"routed": true}')
    rc = doctor.main(["--acknowledge", "--upgrade", "--json", "--check-upstream"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"routed": true' in out
    assert captured.get("check_upstream") is True


def test_cli_wrapper_delegates_acknowledge_to_jd_main(monkeypatch):
    """The public `dontpanic doctor --acknowledge` wrapper delegates the raw argv
    to jd.main (the SOLE marker-write path lives there)."""
    import types

    from dontpanic_orchestrate import cli

    seen: dict = {}
    stub = types.ModuleType("jarvis_doctor")
    stub.main = lambda argv: seen.update({"argv": argv}) or 0
    monkeypatch.setitem(sys.modules, "jarvis_doctor", stub)

    rc = cli._doctor_main(["--acknowledge", "--upgrade", "--json"])
    assert rc == 0
    assert seen["argv"] == ["--acknowledge", "--upgrade", "--json"]
