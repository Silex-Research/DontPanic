"""Plan 2026-06-21-001 F006 — `dontpanic doctor` upgrade-readiness render tests.

Covers the acceptance matrix for the READ-ONLY doctor upgrade surface:

* plain doctor emits exactly one WARN summarizing pending_required +
  pending_advisory (+ an upstream-behind note when known) with the remediation
  command, and an OK when up to date;
* ``--upgrade --json`` emits the machine-readable report (summary incl. upstream
  + required[]/advisory[]/migration_status[]);
* ``--upgrade`` renders the full human report led by the version/update +
  upstream summary;
* NO implicit network fetch in the default path; only ``--check-upstream`` opts
  into a fetch (D016);
* the render path NEVER writes the marker (D015);
* introduced_commands (new CLI surfaces) appear for required AND advisory items
  in both the human report and the JSON output (D022/D033);
* END-TO-END no-mutation: the full plain doctor + the upgrade report path write
  ZERO files anywhere (no backfill/migration/config/registry/evidence/ledger/
  marker) and never call the sole marker writer (D050).
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


def _required_action(action_id: str, *, probe: str, introduced: list[str] | None = None) -> dict:
    return {
        "id": action_id,
        "kind": "required",
        "severity": "critical",
        "title": f"required {action_id}",
        "detail": "why this is required",
        "status_probe": probe,
        "introduced_commands": introduced or [],
        "commands": [
            {"label": "preview", "command": "dontpanic do-thing --dry-run"},
            {"label": "apply", "command": "dontpanic do-thing"},
            {"label": "verify", "command": "dontpanic doctor"},
        ],
        "human_next_step": "run the apply command",
    }


def _advisory_action(action_id: str, *, introduced: list[str] | None = None) -> dict:
    return {
        "id": action_id,
        "kind": "advisory",
        "severity": "optional",
        "title": f"advisory {action_id}",
        "detail": "why this is advisory",
        "introduced_commands": introduced or [],
    }


def _manifest_dict() -> dict:
    """r1 (advisory a1 + required req1, both first-run) < r3 (required req3)."""
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
                    _advisory_action("a1", introduced=["dontpanic new-thing"]),
                    _required_action("req1", probe="probe_ok", introduced=["dontpanic backfill"]),
                ],
            },
            {
                "id": "r3",
                "date": "2026-06-16",
                "summary": "release three",
                "show_on_first_run": True,
                "actions": [
                    _required_action("req3", probe="probe_bad", introduced=["dontpanic migrate"]),
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


# A recording git seam that asserts no `fetch` ever reaches the runner (D016).
def _recording_git(doctor, responses: dict):
    calls: list[tuple] = []

    def runner(args):
        calls.append(tuple(args))
        return responses.get(tuple(args))

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate.upgrade_report import GitProbe
    finally:
        sys.path.pop(0)
    return GitProbe(runner=runner), calls


def _git_behind(doctor):
    return _recording_git(
        doctor,
        {
            ("rev-parse", "--short", "HEAD"): "abc1234",
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): "origin/main",
            ("rev-parse", "--short", "origin/main"): "def5678",
            ("rev-list", "--left-right", "--count", "HEAD...origin/main"): "0\t3",
        },
    )


def _git_off(doctor):
    return _recording_git(doctor, {})


# ─────────────────────────  plain doctor WARN  ─────────────────────────


def test_check_warns_with_counts_and_remediation_when_pending(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    git, _ = _git_off(doctor)
    r = doctor.check_upgrade_readiness(
        manifest_path=mp,
        marker_path=tmp_path / "upgrade-state.json",
        predicate_registry=_probe_registry(),
        git=git,
    )
    assert r.name == "upgrade-readiness"
    assert r.warn is True and r.ok is True  # WARN is a soft signal (ok stays True)
    # req3 (probe_bad) pending; first-run advisories a1 + req-only -> a1 visible.
    assert "1 required" in r.message
    assert "advisory" in r.message
    assert "dontpanic doctor --upgrade" in r.remediation


def test_check_ok_when_nothing_pending(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    git, _ = _git_off(doctor)
    # A marker acknowledging the latest release silences first-run advisories;
    # both probes satisfied -> nothing pending.
    marker = tmp_path / "upgrade-state.json"
    marker.write_text(json.dumps({"last_seen_release": "r3"}), encoding="utf-8")
    reg = _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")})
    r = doctor.check_upgrade_readiness(
        manifest_path=mp, marker_path=marker, predicate_registry=reg, git=git
    )
    assert r.warn is False and r.ok is True
    assert "up to date" in r.message


def test_check_surfaces_upstream_behind_note(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    git, _ = _git_behind(doctor)
    r = doctor.check_upgrade_readiness(
        manifest_path=mp,
        marker_path=tmp_path / "upgrade-state.json",
        predicate_registry=_probe_registry(),
        git=git,
    )
    assert "upstream" in r.message.lower()


# ─────────────────────────  --upgrade --json shape  ─────────────────────────


def test_upgrade_json_shape_includes_summary_upstream_and_lists(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    git, _ = _git_behind(doctor)
    report = doctor.build_upgrade_report(
        manifest_path=mp,
        marker_path=tmp_path / "upgrade-state.json",
        predicate_registry=_probe_registry(),
        git=git,
    )
    payload = json.loads(doctor.render_upgrade_report_json(report))
    assert set(payload) == {"summary", "required", "advisory", "migration_status"}
    summary = payload["summary"]
    for key in ("installed_commit", "latest_release_id", "pending_required", "pending_advisory", "update_state", "upstream"):
        assert key in summary, key
    for key in ("fetched_upstream_commit", "upstream_status", "remediation"):
        assert key in summary["upstream"], key
    assert summary["upstream"]["upstream_status"] == "behind"


def test_upgrade_human_leads_with_version_and_upstream(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    git, _ = _git_behind(doctor)
    report = doctor.build_upgrade_report(
        manifest_path=mp,
        marker_path=tmp_path / "upgrade-state.json",
        predicate_registry=_probe_registry(),
        git=git,
    )
    text = doctor.render_upgrade_report_text(report)
    assert "installed commit:" in text
    assert "Upstream: behind" in text
    assert "Required actions" in text
    assert "Advisory updates" in text


# ─────────────────────────  no implicit fetch / --check-upstream opt-in (D016)  ─────────────────────────


def test_default_path_performs_no_network_fetch(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    git, calls = _git_behind(doctor)
    fetched: list = []

    doctor.build_upgrade_report(
        manifest_path=mp,
        marker_path=tmp_path / "upgrade-state.json",
        predicate_registry=_probe_registry(),
        git=git,
        check_upstream=False,
        fetch_runner=lambda root: fetched.append(root),
    )
    assert fetched == []  # no fetch invoked in the default path
    assert all(call[0] != "fetch" for call in calls)  # no fetch reaches the git runner


def test_check_upstream_opt_in_performs_exactly_one_fetch(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    git, _ = _git_behind(doctor)
    fetched: list = []

    doctor.build_upgrade_report(
        manifest_path=mp,
        marker_path=tmp_path / "upgrade-state.json",
        predicate_registry=_probe_registry(),
        git=git,
        check_upstream=True,
        fetch_runner=lambda root: fetched.append(root),
    )
    assert len(fetched) == 1  # the opt-in is the only path that may fetch


# ─────────────────────────  read-only render (no marker write, D015)  ─────────────────────────


def test_render_path_never_writes_marker(doctor, tmp_path, monkeypatch):
    mp = _write_manifest(tmp_path)
    marker = tmp_path / "upgrade-state.json"
    git, _ = _git_off(doctor)

    # Spy on the SOLE marker writer; it must never be called by a render.
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import upgrade_state as us
    finally:
        sys.path.pop(0)
    writes: list = []
    monkeypatch.setattr(us, "write_upgrade_state", lambda *a, **k: writes.append(a))

    doctor.build_upgrade_report(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=git
    )
    doctor.check_upgrade_readiness(
        manifest_path=mp, marker_path=marker, predicate_registry=_probe_registry(), git=git
    )
    assert not marker.exists()  # no marker file created by a read-only render (D015)
    assert writes == []  # the sole writer is never invoked


# ─────────────────────────  introduced_commands (D022/D033)  ─────────────────────────


def test_introduced_commands_required_in_human_and_json(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    git, _ = _git_off(doctor)
    report = doctor.build_upgrade_report(
        manifest_path=mp,
        marker_path=tmp_path / "upgrade-state.json",
        predicate_registry=_probe_registry(),
        git=git,
    )
    # req3 is the pending required action carrying introduced_commands.
    text = doctor.render_upgrade_report_text(report)
    assert "dontpanic migrate" in text  # required action's new command surface (D022)

    payload = json.loads(doctor.render_upgrade_report_json(report))
    req_intro = [c for item in payload["required"] for c in item["introduced_commands"]]
    assert "dontpanic migrate" in req_intro


def test_introduced_commands_advisory_in_human_and_json(doctor, tmp_path):
    mp = _write_manifest(tmp_path)
    git, _ = _git_off(doctor)
    report = doctor.build_upgrade_report(
        manifest_path=mp,
        marker_path=tmp_path / "upgrade-state.json",
        predicate_registry=_probe_registry(),
        git=git,
    )
    # a1 is a first-run advisory carrying introduced_commands (D033).
    text = doctor.render_upgrade_report_text(report)
    assert "dontpanic new-thing" in text

    payload = json.loads(doctor.render_upgrade_report_json(report))
    adv_intro = [c for item in payload["advisory"] for c in item["introduced_commands"]]
    assert "dontpanic new-thing" in adv_intro


# ─────────────────────────  end-to-end no-mutation (D050)  ─────────────────────────


def _snapshot_tree(root: Path) -> dict[str, float]:
    """Map every file under ``root`` to its mtime (empty when root is absent)."""
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.stat().st_mtime
        for p in root.rglob("*")
        if p.is_file()
    }


def test_end_to_end_plain_doctor_and_upgrade_report_write_nothing(doctor, tmp_path, monkeypatch):
    """D050: the full plain doctor + the upgrade report path mutate nothing —
    no backfill/migration/config/registry/evidence/ledger/marker write — covering
    the whole path, not only the probe (F003) and marker (D015) sub-checks.

    The snapshot spans the ENTIRE isolated temp state (the autouse conftest
    redirects every writable surface — DONTPANIC_HOME / JARVIS_HOME, the marker,
    breaker/quota/registry ledgers, the dashboard dir — under ``tmp_path``), not
    just ``$DONTPANIC_HOME`` (codex-auditor F006-i0): any backfill/migration/
    config/registry/evidence/ledger/marker write would land somewhere under
    ``tmp_path`` and break the before/after equality."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import global_config as gc
        from dontpanic_orchestrate import upgrade_state as us
    finally:
        sys.path.pop(0)

    # The autouse conftest isolation points DONTPANIC_HOME at a per-test tmp dir;
    # this is the fixture "instance" whose state must stay untouched.
    home = gc.dontpanic_home()
    home.mkdir(parents=True, exist_ok=True)

    # Hard guard: the SOLE marker writer must never fire across the whole path.
    marker_writes: list = []
    monkeypatch.setattr(us, "write_upgrade_state", lambda *a, **k: marker_writes.append(a))

    # Snapshot the whole isolated root, not only the home subtree (D050): the
    # marker, ledgers, registry and dashboard surfaces all live under tmp_path.
    before = _snapshot_tree(tmp_path)

    # 1) Full plain doctor (skip auth so no network/CLI auth probes run).
    doctor.run_all_checks(skip_auth=True)
    # 2) The upgrade report path (default, no fetch) against the fixture instance.
    doctor.build_upgrade_report()

    after = _snapshot_tree(tmp_path)

    assert marker_writes == []  # no marker write anywhere on the path (D015/D050)
    assert before == after  # zero file writes anywhere in the isolated state (D050)


def test_end_to_end_public_cli_main_doctor_paths_write_nothing(tmp_path, monkeypatch):
    """D050 (codex-auditor F006-i2): the FULL public doctor path writes nothing.

    The sibling test above drives ``doctor.run_all_checks`` /
    ``doctor.build_upgrade_report`` directly, which skips ``cli.main`` and the
    invocation-ledger wrapper that records every real invocation. This test runs
    the genuine public entry point — ``cli.main(["doctor", "--skip-auth"])`` and
    ``cli.main(["doctor", "--upgrade", "--json"])`` — exactly as an operator
    would, then asserts ZERO files were created or modified anywhere under the
    isolated writable roots (DONTPANIC_HOME/JARVIS_HOME, the marker, the
    breaker/quota/registry ledgers, the dashboard dir, AND the invocation ledger
    the wrapper would otherwise append). It also hard-guards the SOLE marker
    writer across the whole path. This covers backfill/migration/config/registry/
    evidence/ledger/marker writes on the real wrapper, not just the probe/marker
    sub-checks."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import cli
        from dontpanic_orchestrate import global_config as gc
        from dontpanic_orchestrate import invocation_ledger as il
        from dontpanic_orchestrate import upgrade_state as us
    finally:
        sys.path.pop(0)

    # The autouse conftest isolation points DONTPANIC_HOME at a per-test tmp dir;
    # this is the fixture "instance" whose state must stay untouched.
    home = gc.dontpanic_home()
    home.mkdir(parents=True, exist_ok=True)

    # Hard guard: the SOLE marker writer must never fire across the whole path.
    marker_writes: list = []
    monkeypatch.setattr(us, "write_upgrade_state", lambda *a, **k: marker_writes.append(a))

    # Snapshot the whole isolated root AFTER the home dir exists so a lazily
    # created (empty) home does not register as a write. The invocation ledger
    # lives under this root too, so a stray wrapper append would break equality.
    before = _snapshot_tree(tmp_path)

    # The genuine public surface: plain doctor, then the upgrade report mode.
    rc_plain = cli.main(["doctor", "--skip-auth"])
    rc_upgrade = cli.main(["doctor", "--upgrade", "--json"])

    after = _snapshot_tree(tmp_path)

    assert rc_plain in (0, 1)  # WARN (1) or all-PASS (0); never a crash/usage err
    assert rc_upgrade == 0  # the read-only report mode succeeds
    assert marker_writes == []  # no marker write anywhere on the real path (D015/D050)
    assert not il.ledger_path().exists()  # the wrapper records no ledger line (D050)
    assert before == after  # zero file writes anywhere in the isolated state (D050)


# ─────────────────────────  CLI wiring (argparse / public surface)  ─────────────────────────
#
# The helper-level tests above drive build_upgrade_report / check_upgrade_readiness
# directly; these exercise the real argparse path through doctor.main() and the
# public `python -m dontpanic_orchestrate doctor` wrapper, which is where the
# plain `--check-upstream` no-op escaped (codex-auditor F006-i0). They assert the
# three render modes route correctly AND that --check-upstream threads into the
# probe even WITHOUT --upgrade.


def test_cli_main_plain_threads_check_upstream(doctor, monkeypatch):
    """Plain `doctor --check-upstream` must reach run_all_checks (not be a no-op)."""
    seen: dict = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return [doctor._ok("upgrade-readiness", "stub")]

    monkeypatch.setattr(doctor, "run_all_checks", fake_run)
    doctor.main(["--skip-auth", "--check-upstream"])
    assert seen.get("check_upstream") is True


def test_cli_main_plain_default_no_check_upstream(doctor, monkeypatch):
    """Default plain doctor never opts into the fetch (D016)."""
    seen: dict = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return [doctor._ok("upgrade-readiness", "stub")]

    monkeypatch.setattr(doctor, "run_all_checks", fake_run)
    doctor.main(["--skip-auth"])
    assert seen.get("check_upstream") is False


def test_cli_main_upgrade_human_render(doctor, monkeypatch, capsys):
    """`doctor --upgrade` routes to the human renderer; default = no fetch."""
    sentinel = object()
    captured: dict = {}
    monkeypatch.setattr(
        doctor, "build_upgrade_report", lambda **k: captured.update(k) or sentinel
    )
    monkeypatch.setattr(
        doctor, "render_upgrade_report_text", lambda r: f"HUMAN:{r is sentinel}"
    )
    rc = doctor.main(["--upgrade"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "HUMAN:True" in out  # routed to the human renderer with the built report
    assert captured.get("check_upstream") is False


def test_cli_main_upgrade_json_render_with_check_upstream(doctor, monkeypatch, capsys):
    """`doctor --upgrade --json --check-upstream` routes to JSON + opts into fetch."""
    sentinel = object()
    captured: dict = {}
    monkeypatch.setattr(
        doctor, "build_upgrade_report", lambda **k: captured.update(k) or sentinel
    )
    monkeypatch.setattr(
        doctor, "render_upgrade_report_json", lambda r: '{"routed": true}'
    )
    rc = doctor.main(["--upgrade", "--json", "--check-upstream"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"routed": true' in out  # routed to the JSON renderer
    assert captured.get("check_upstream") is True


def test_cli_wrapper_plain_threads_check_upstream(monkeypatch):
    """The public `dontpanic doctor --check-upstream` wrapper threads the opt-in
    into run_all_checks too (it delegates --upgrade to jd.main, but owns the
    plain battery itself)."""
    import types

    from dontpanic_orchestrate import cli

    seen: dict = {}
    stub = types.ModuleType("jarvis_doctor")
    stub.run_all_checks = lambda **kwargs: seen.update(kwargs) or []
    stub.render_text = lambda results: "rendered"
    stub.render_json = lambda results: "[]"
    stub.compute_strict_exit = lambda results: 0
    monkeypatch.setitem(sys.modules, "jarvis_doctor", stub)

    cli._doctor_main(["--check-upstream"])
    assert seen.get("check_upstream") is True


def test_cli_wrapper_default_no_check_upstream(monkeypatch):
    """Default public wrapper plain doctor never opts into the fetch (D016)."""
    import types

    from dontpanic_orchestrate import cli

    seen: dict = {}
    stub = types.ModuleType("jarvis_doctor")
    stub.run_all_checks = lambda **kwargs: seen.update(kwargs) or []
    stub.render_text = lambda results: "rendered"
    stub.render_json = lambda results: "[]"
    stub.compute_strict_exit = lambda results: 0
    monkeypatch.setitem(sys.modules, "jarvis_doctor", stub)

    cli._doctor_main([])
    assert seen.get("check_upstream") is False


# ─────────────────────  public CLI wrapper writes no ledger line (D050)  ─────────────────────
#
# The end-to-end no-mutation test above drives the doctor helpers directly and so
# never crosses the public `dontpanic doctor` wrapper (cli.main), which records
# every invocation in the F003 invocation ledger. That ledger write — an append to
# `<dontpanic_home>/invocations.jsonl` — is a write D050 forbids on the read-only
# doctor path (codex-auditor F006-i1). These tests pin the wrapper-level invariant.


def test_invocation_ledger_skips_doctor_command():
    """`start_recording` returns a no-op recorder for the read-only doctor command
    so no ledger line is appended (D050)."""
    from dontpanic_orchestrate import invocation_ledger as il

    assert il.is_zero_write_command(["doctor"]) is True
    assert il.is_zero_write_command(["doctor", "--upgrade", "--json"]) is True
    assert il.is_zero_write_command(["--skip-auth", "doctor"]) is True
    assert il.is_zero_write_command(["orchestrate", "run"]) is False
    rec = il.start_recording(["doctor", "--upgrade", "--json"])
    assert type(rec).__name__ == "_NullRecorder"


def test_cli_main_doctor_writes_no_ledger_line(monkeypatch, tmp_path):
    """The public `dontpanic doctor` wrapper (cli.main) appends NOTHING to the
    invocation ledger across the whole read-only path (D050)."""
    from dontpanic_orchestrate import cli
    from dontpanic_orchestrate import invocation_ledger as il

    # Stub the actual command body so the test stays fast and offline; the ledger
    # wrapping in cli.main is what we exercise.
    monkeypatch.setattr(cli, "_run_cli", lambda argv: 0)

    ledger = il.ledger_path()
    assert not ledger.exists()  # isolated home starts clean (autouse conftest)

    rc = cli.main(["doctor", "--upgrade", "--json"])
    assert rc == 0
    assert not ledger.exists()  # no ledger line written for the read-only doctor path

    # Sanity contrast: a non-doctor command DOES record (ledger seam still live).
    cli.main(["ps"])
    assert ledger.exists()  # the wrapper records normal commands as before
