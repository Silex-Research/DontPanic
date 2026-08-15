"""Plan 2026-06-21-001 F010 — end-to-end "after git pull" update journey (D014).

This is the operator-outcome QA proof that the upgrade-readiness layer works as a
JOURNEY through the REAL `dontpanic doctor` + `dontpanic projects` CLI surfaces,
executed OUT-OF-PROCESS (``python -m dontpanic_orchestrate ...``) — not as a pile
of green in-process unit tests. Every journey step shells out to the real console
entrypoint; the apply/verify commands are EXTRACTED FROM THE LIVE REPORT and run
verbatim, so a broken preview/apply/verify command surfaced by the manifest fails
the journey rather than being masked (codex-auditor F010-i0 finding). It reproduces:

    fresh update (no marker, on a known commit)
      -> plain `dontpanic doctor` WARNs with the pending counts
      -> `dontpanic doctor --upgrade --json` shows the summary + the
         canonical-discovery REQUIRED action pending (probe-driven), and does
         NOT flood advisories
      -> the operator runs the REAL APPLY-labeled command taken from the report
         (the state-changing backfill migration) on a DISPOSABLE ISOLATED instance
      -> the REAL VERIFY-labeled command (also taken from the report) PROVES the
         resulting state
      -> a re-run clears the required action, plain doctor no longer WARNs for it,
         and update_state transitions required_pending -> up_to_date.

Decisions enforced here:

* D025/D032/D038 — SINGLE SATISFYING PATH: the ONLY way the journey clears the
  required action is run-APPLY-then-VERIFY against the real command surface. A
  pre-apply VERIFY-alone is asserted NOT to satisfy (verify proves, it does not
  create), and there is no fixture-toggle of the probe outcome anywhere — the
  probe flips solely because the apply command stamped the ledger. A broken apply
  (no state change) OR a broken verify (state not proven) fails the journey.
* D043 — MUTATION ISOLATION: the apply command runs ONLY against a disposable
  isolated instance (its own ``$DONTPANIC_HOME`` + fixture project registry),
  NEVER the operator's real registry; it is torn down after the journey. The live
  read of the REAL instance is limited to the read-only upgrade report capture.
* D048 — close-time evidence capture is a plan-author step, not a pytest
  side effect. These tests write transcripts under tmp_path only. Writing
  into ``docs/plans/.../evidence/`` dirties the working tree on every sweep.

The "real doctor CLI" surface is exercised entirely out-of-process here: the
journey calls genuine ``python -m dontpanic_orchestrate doctor`` / ``... projects``
subprocesses against the isolated instance, and a separate read-only subprocess on
the operator's real instance captures the live evidence report.

ISOLATION SHAPE (out-of-process canonicalization): the fixture instance lives under
a DURABLE, disposable base directory (NOT a /tmp or /var/folders temp path) so the
real canonical-discovery reconcile — which refuses to canonicalize ephemeral temp
checkouts — resolves the fixture project to a stable key out-of-process, exactly as
it would for a real operator repo. The fixture project is ``git init``'d so its
canonical identity resolves to itself; its unborn HEAD makes the upgrade report's
git probe off-git-equivalent (installed_commit=unknown, upstream=unknown), so the
update_state transition is driven purely by the manifest-action readiness.

NOTE: marker write/no-write assertions live in F004/F007; this feature asserts the
CLI journey + the update_state transition only.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"

# The real seeded required action under test (docs/upgrade/releases.json).
CANONICAL_RELEASE = "2026-06-17-001-canonical-discovery"
CANONICAL_ACTION = "backfill-canonical-discovery"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _now_iso() -> str:
    return (
        datetime.datetime.now(tz=datetime.timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _registered_active_keys(discover_payload: dict) -> list[str]:
    return [r["canonical_repo_key"] for r in discover_payload.get("registered_active", [])]


def _argv_from_command(command: str) -> list[str]:
    """Translate a manifest command string (``dontpanic projects discover --json``)
    into the argv passed to ``python -m dontpanic_orchestrate`` (drops the leading
    ``dontpanic`` console-script name). The journey runs the EXACT command the
    report surfaces — never a hand-written substitute (codex-auditor F010-i0)."""
    parts = command.split()
    assert parts and parts[0] == "dontpanic", f"unexpected manifest command: {command!r}"
    return parts[1:]


# ─────────────────────────────  disposable isolated instance  ─────────────────────────────


@pytest.fixture
def isolated_instance():
    """A DISPOSABLE, ISOLATED DontPanic instance at a DURABLE base path (D043).

    Yields ``{base, home, home_env, repo_dir, env}``. ``home`` is the instance's
    ``$DONTPANIC_HOME`` (its own ledger / registry / evidence — never the
    operator's real ~/.dontpanic). ``home_env`` is the instance's ``$HOME`` — an
    isolated, empty home so EVERY ``Path.home()``-based resolution inside the apply
    subprocess (global gitconfig, any ``~/.dontpanic`` fallback) lands in the
    disposable tree, never the operator's real home (D043; codex-auditor F010-i1).
    ``repo_dir`` is a ``git init``'d fixture project used as the CLI's cwd so the
    canonical-discovery reconcile resolves a stable self-identity out-of-process.
    ``env`` is the subprocess environment pinned to this instance. The whole tree is
    removed on teardown.

    Durable (not under /tmp or /var/folders) is REQUIRED: the real reconcile refuses
    to canonicalize ephemeral temp checkouts, so a temp fixture would never reach
    registered_active out-of-process. The base lives under the operator's real home
    in a clearly namespaced, disposable directory — but the subprocess ``$HOME`` is
    repointed at ``home_env`` inside that tree, so the apply path cannot read or
    write the operator's real home/registry. Durability is unaffected: the temp-path
    guard (``_is_temp_path``) keys off ``/tmp``//``/var/folders`` prefixes on
    ``repo_dir``, not off ``$HOME``. The whole tree is torn down after.
    """
    base = Path.home() / f".dontpanic-f010-e2e-{os.getpid()}"
    shutil.rmtree(base, ignore_errors=True)  # clear any stale leftover from a prior crash
    home = base / "home"
    home_env = base / "home-env"
    repo_dir = base / "fixture-project"
    home.mkdir(parents=True, exist_ok=True)
    home_env.mkdir(parents=True, exist_ok=True)
    repo_dir.mkdir(parents=True, exist_ok=True)

    # git init -> the fixture project canonicalizes to ITSELF (C3-1 durable+git) and
    # its unborn HEAD makes the upgrade report's git probe off-git-equivalent.
    subprocess.run(
        ["git", "init", "-q", str(repo_dir)], check=True, capture_output=True, text=True
    )

    env = dict(os.environ)
    # Strip any ambient/conftest isolation so the subprocess is governed solely by
    # THIS instance's $DONTPANIC_HOME (and never the operator's real home).
    for key in (
        "DONTPANIC_DASHBOARD_DIR",
        "JARVIS_BREAKER_HISTORY_PATH",
        "JARVIS_ACTIVE_SUPERVISORS_PATH",
        "JARVIS_INTERACTIVE_STATE_PATH",
        "JARVIS_QUOTA_STATE_PATH",
        "JARVIS_QUOTA_CAPS_PATH",
    ):
        env.pop(key, None)
    env["DONTPANIC_HOME"] = str(home)
    env["JARVIS_HOME"] = str(home)
    # Repoint $HOME at the isolated tree so any Path.home()-based read/write inside
    # the apply subprocess (D043) is contained, never the operator's real home.
    env["HOME"] = str(home_env)
    env["PYTHONPATH"] = str(SCRIPTS_DIR) + os.pathsep + env.get("PYTHONPATH", "")

    try:
        yield {
            "base": base,
            "home": home,
            "home_env": home_env,
            "repo_dir": repo_dir,
            "env": env,
        }
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _run(fx: dict, *args: str) -> subprocess.CompletedProcess:
    """Run ``python -m dontpanic_orchestrate <args>`` out-of-process against the
    isolated instance (cwd = the fixture project so self-identity resolves there)."""
    return subprocess.run(
        [sys.executable, "-m", "dontpanic_orchestrate", *args],
        cwd=str(fx["repo_dir"]),
        env=fx["env"],
        capture_output=True,
        text=True,
    )


def _seed_pending_required(fx: dict, monkeypatch) -> dict:
    """Seed the isolated instance so the canonical-discovery REQUIRED action is
    PENDING: a tracked project (``has_tracked_projects`` applies) plus historical
    invocation-ledger rows that carry NO ``canonical_repo`` yet, and a backfill-
    evidence file mapping those rows to the project's canonical repo.

    Before the backfill the project reconciles to registered_stale (no observed
    canonical usage) -> the OUTCOME probe is NOT satisfied. The real apply command
    stamps the ledger so it reconciles to registered_active -> the probe satisfies.
    Nothing here toggles the probe directly; only the ledger state (changed solely
    by the apply command) drives satisfaction (D038). The seed writers run in-process
    but target ONLY this instance's $DONTPANIC_HOME.
    """
    home = fx["home"]
    repo_dir = fx["repo_dir"]
    # Point in-process loaders at THIS instance's home for the seed writes.
    monkeypatch.setenv("DONTPANIC_HOME", str(home))
    monkeypatch.setenv("JARVIS_HOME", str(home))

    from dontpanic_orchestrate import canonical_backfill as cb
    from dontpanic_orchestrate import global_config as gc
    from dontpanic_orchestrate import invocation_ledger as il
    from dontpanic_orchestrate import projects_registry
    from dontpanic_orchestrate.projects_registry import ProjectEntry, Registry

    assert gc.dontpanic_home() == home, "seed must target the isolated instance home"

    now = _now_iso()

    # The durable, git-init'd fixture project canonicalizes to a stable self key —
    # the SAME key the out-of-process reconcile derives from the cwd + registry path.
    canonical = il.make_path_pair(str(repo_dir))
    assert canonical is not None
    self_key = canonical["path_key"]

    # Registry with the fixture project tracked -> has_tracked_projects applies.
    projects_registry.save_registry(
        Registry(
            projects=[
                ProjectEntry(name="fixture-project", path=str(repo_dir), created_at=now)
            ]
        )
    )

    # Historical ledger rows (observation key "obsA"), NO canonical_repo yet.
    obs_key = "obsA"
    ledger = il.ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "repo": {"path_key": obs_key, "path_display": "<home>/fixture-project"},
            "branch": "main",
            "last_seen": now,
            "result": "ok",
            "command": "dontpanic agent status",
        }
        for _ in range(3)
    ]
    ledger.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
    )

    # Backfill evidence mapping the observation key -> the project's canonical repo.
    # The path_display is a LITERAL (non-scrub-token) path so the backfill can
    # reconstruct + path-key-confirm it.
    canonical_obj = {
        "path_key": self_key,
        "path_display": str(repo_dir),
        "durable_checkout": True,
    }
    evidence = cb.default_evidence_path()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "canonical_repos": {self_key: canonical_obj},
                "observation_path_key_to_canonical": {obs_key: [self_key]},
            }
        ),
        encoding="utf-8",
    )

    return {"self_key": self_key, "obs_key": obs_key, "now": now, "ledger": ledger}


# ───────────────────────────  the end-to-end journey  ───────────────────────────


def test_update_journey_e2e(isolated_instance, monkeypatch, tmp_path):
    """fresh update -> WARN -> report (pending required) -> APPLY -> VERIFY ->
    cleared + WARN gone + update_state transition, through the REAL doctor +
    projects CLIs, executed out-of-process (codex-auditor F010-i0)."""
    fx = isolated_instance
    seed = _seed_pending_required(fx, monkeypatch)
    self_key = seed["self_key"]
    ledger = seed["ledger"]

    transcript: list[str] = [
        "# F010 — after-git-pull update journey (real doctor CLI, out-of-process)\n",
        f"\ninstance home: {fx['home']}\nfixture project (cwd): {fx['repo_dir']}\n",
    ]

    def step(title: str) -> None:
        transcript.append(f"\n## {title}\n")

    def record(proc: subprocess.CompletedProcess, label: str) -> None:
        transcript.append(f"$ {label}\n")
        transcript.append(f"rc={proc.returncode}\n")
        if proc.stdout:
            transcript.append("stdout:\n" + proc.stdout.rstrip("\n") + "\n")
        if proc.stderr.strip():
            transcript.append("stderr:\n" + proc.stderr.rstrip("\n") + "\n")

    # ── 1) fresh update: plain `dontpanic doctor` WARNs with pending counts ──────
    step("1. Fresh update (no marker): plain `dontpanic doctor --skip-auth --json`")
    proc = _run(fx, "doctor", "--skip-auth", "--json")
    record(proc, "python -m dontpanic_orchestrate doctor --skip-auth --json")
    # doctor exit code is the strict 0/1/2 matrix (upgrade-readiness is advisory and
    # does not escalate it); we assert on the parsed JSON, not the code.
    checks = json.loads(proc.stdout)["checks"]
    upgrade_check = next(c for c in checks if c["name"] == "upgrade-readiness")
    assert upgrade_check["warn"] is True
    assert "1 required" in upgrade_check["message"]  # the canonical-discovery required action
    assert "dontpanic doctor --upgrade" in upgrade_check["remediation"]

    # ── 2) upgrade report: summary + required action pending, no advisory flood ──
    step("2. `dontpanic doctor --upgrade --json` (before)")
    proc = _run(fx, "doctor", "--upgrade", "--json")
    record(proc, "python -m dontpanic_orchestrate doctor --upgrade --json")
    assert proc.returncode == 0, f"doctor --upgrade --json failed: {proc.stderr}"
    payload_before = json.loads(proc.stdout)
    sb = payload_before["summary"]
    assert sb["update_state"] == "required_pending"
    assert sb["pending_required"] == 1
    # First run does NOT flood advisories (absent marker -> show_on_first_run only,
    # and every seeded release is show_on_first_run=false).
    assert sb["pending_advisory"] == 0
    assert sb["marker_state"] == "absent"
    required_ids_before = [i["action_id"] for i in payload_before["required"]]
    assert CANONICAL_ACTION in required_ids_before
    # The pending required item is probe-driven and carries its ordered apply/verify
    # commands (the real copyable migration checklist). EXTRACT them and run verbatim.
    item = next(i for i in payload_before["required"] if i["action_id"] == CANONICAL_ACTION)
    labels = [c["label"] for c in item["commands"]]
    assert "apply" in labels and "verify" in labels
    apply_cmd = next(c["command"] for c in item["commands"] if c["label"] == "apply")
    verify_cmd = next(c["command"] for c in item["commands"] if c["label"] == "verify")
    transcript.append(f"\nextracted apply command:  {apply_cmd!r}\n")
    transcript.append(f"extracted verify command: {verify_cmd!r}\n")
    apply_argv = _argv_from_command(apply_cmd)
    verify_argv = _argv_from_command(verify_cmd)

    # ── 2b) VERIFY-ALONE does NOT satisfy (verify proves, it does not create, D038) ──
    step("2b. VERIFY-alone before any apply (must NOT satisfy)")
    proc = _run(fx, *verify_argv)
    record(proc, "python -m dontpanic_orchestrate " + " ".join(verify_argv) + "  (pre-apply)")
    assert proc.returncode == 0
    discover_pre = json.loads(proc.stdout)
    assert self_key not in _registered_active_keys(discover_pre)
    # ...and the doctor probe is still pending after a verify-alone (no state created).
    proc = _run(fx, "doctor", "--upgrade", "--json")
    record(proc, "python -m dontpanic_orchestrate doctor --upgrade --json  (after verify-alone)")
    assert json.loads(proc.stdout)["summary"]["pending_required"] == 1

    # ── 3) run the REAL APPLY-labeled command (the state-changing migration) ─────
    step(f"3. APPLY: `{apply_cmd}` (the real migration, from the report)")
    ledger_before = ledger.read_text(encoding="utf-8")
    proc = _run(fx, *apply_argv)
    record(proc, "python -m dontpanic_orchestrate " + " ".join(apply_argv))
    assert proc.returncode == 0, f"apply command failed: {proc.stderr}"
    # A broken apply that changes nothing fails the journey: the ledger MUST now carry
    # canonical_repo on the historical rows (proof the migration mutated real state).
    ledger_after = ledger.read_text(encoding="utf-8")
    assert ledger_after != ledger_before
    stamped_rows = [json.loads(line) for line in ledger_after.splitlines() if line.strip()]
    assert all(
        r.get("canonical_repo", {}).get("path_key") == self_key for r in stamped_rows
    )

    # ── 4) run the REAL VERIFY-labeled command to PROVE the resulting state ───────
    step(f"4. VERIFY: `{verify_cmd}` (proves the new state, from the report)")
    proc = _run(fx, *verify_argv)
    record(proc, "python -m dontpanic_orchestrate " + " ".join(verify_argv) + "  (post-apply)")
    assert proc.returncode == 0
    discover_post = json.loads(proc.stdout)
    # A broken verify (state not proven) fails the journey.
    assert self_key in _registered_active_keys(discover_post)

    # ── 5) re-run doctor: required cleared, WARN gone, update_state transitions ───
    step("5. Re-run `dontpanic doctor --upgrade --json` + plain doctor (after)")
    proc = _run(fx, "doctor", "--upgrade", "--json")
    record(proc, "python -m dontpanic_orchestrate doctor --upgrade --json")
    assert proc.returncode == 0
    payload_after = json.loads(proc.stdout)
    sa = payload_after["summary"]
    assert sa["pending_required"] == 0
    assert CANONICAL_ACTION not in [i["action_id"] for i in payload_after["required"]]
    # update_state TRANSITION proven by the journey.
    assert sb["update_state"] == "required_pending"
    assert sa["update_state"] == "up_to_date"
    # migration_status now reports the canonical-discovery action as satisfied (D051).
    mig = next(
        m for m in payload_after["migration_status"] if m["action_id"] == CANONICAL_ACTION
    )
    assert mig["state"] == "satisfied"

    proc = _run(fx, "doctor", "--skip-auth", "--json")
    record(proc, "python -m dontpanic_orchestrate doctor --skip-auth --json")
    checks_after = json.loads(proc.stdout)["checks"]
    upgrade_after = next(c for c in checks_after if c["name"] == "upgrade-readiness")
    assert upgrade_after["warn"] is False  # WARN gone for the required action
    assert "up to date" in upgrade_after["message"]

    # Persist the journey transcript under tmp_path — never the plan tree.
    dest = tmp_path / "F010-journey-transcript.md"
    dest.write_text("".join(transcript), encoding="utf-8")
    assert dest.is_file() and dest.stat().st_size > 0


# ─────────────────────  D043: apply hits ONLY the isolated instance  ─────────────────────


def test_apply_runs_only_against_isolated_instance(isolated_instance, monkeypatch):
    """The apply-labeled command (run out-of-process with $DONTPANIC_HOME pinned to
    the disposable isolated instance) targets ONLY that instance, never the
    operator's real ~/.dontpanic registry/ledger (D043)."""
    fx = isolated_instance
    seed = _seed_pending_required(fx, monkeypatch)

    # The subprocess $HOME is repointed at the disposable isolated tree, NOT the
    # operator's real home — so a Path.home() read/write in the apply path is
    # contained (D043; codex-auditor F010-i1). The in-process Path.home() below
    # still resolves the REAL operator home (we never monkeypatch HOME in-process),
    # which is exactly what makes the untouched-registry assertion meaningful.
    real_home = Path.home()
    assert fx["env"]["HOME"] == str(fx["home_env"])
    assert Path(fx["env"]["HOME"]) != real_home
    assert str(fx["base"]) in fx["env"]["HOME"]

    # The real operator registry/ledger lives under the canonical ~/.dontpanic home,
    # distinct from this instance's home (whose ledger the seed just wrote).
    real_dontpanic = real_home / ".dontpanic"
    real_home_ledger = real_dontpanic / seed["ledger"].name
    assert seed["ledger"] != real_home_ledger
    assert str(fx["home"]) in str(seed["ledger"])
    real_dontpanic_existed = real_dontpanic.exists()
    real_ledger_before = (
        real_home_ledger.read_bytes() if real_home_ledger.exists() else None
    )

    # Run the real apply command out-of-process against the isolated instance.
    proc = _run(fx, "projects", "backfill-canonical")
    assert proc.returncode == 0, f"apply failed: {proc.stderr}"

    # The isolated instance's ledger WAS mutated (the apply did real work)...
    stamped = [json.loads(line) for line in seed["ledger"].read_text().splitlines() if line.strip()]
    assert all(r.get("canonical_repo", {}).get("path_key") == seed["self_key"] for r in stamped)
    # ...and the apply wrote into the isolated $HOME tree, never the real one: the
    # operator's real registry/ledger is byte-identical and the apply created no
    # ~/.dontpanic under the real home if none existed before (untouched).
    assert real_dontpanic.exists() == real_dontpanic_existed
    real_ledger_after = (
        real_home_ledger.read_bytes() if real_home_ledger.exists() else None
    )
    assert real_ledger_after == real_ledger_before


# ─────────────────────  live read-only report capture on the REAL instance  ─────────────────────


def test_capture_live_upgrade_report_real_instance(tmp_path):
    """Capture a live `dontpanic doctor --upgrade --json` on the operator's REAL
    instance (read-only) and save it under tmp_path (acceptance + D043).

    Runs out-of-process with the test's isolation env stripped so it resolves the
    real ~/.dontpanic and the real repo identity — the canonical-discovery migration
    item reflects the ACTUAL probe on this machine. The upgrade report path is
    proven zero-write by F006 (D050), so this live read mutates nothing."""
    env = dict(os.environ)
    # Strip the conftest's per-test isolation so the subprocess sees the REAL home.
    for key in (
        "DONTPANIC_HOME",
        "JARVIS_HOME",
        "DONTPANIC_DASHBOARD_DIR",
        "JARVIS_BREAKER_HISTORY_PATH",
        "JARVIS_ACTIVE_SUPERVISORS_PATH",
        "JARVIS_INTERACTIVE_STATE_PATH",
        "JARVIS_QUOTA_STATE_PATH",
        "JARVIS_QUOTA_CAPS_PATH",
    ):
        env.pop(key, None)
    env["PYTHONPATH"] = str(SCRIPTS_DIR) + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        [sys.executable, "-m", "dontpanic_orchestrate", "doctor", "--upgrade", "--json"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"live doctor --upgrade --json failed: {proc.stderr}"
    payload = json.loads(proc.stdout)
    assert set(payload) == {"summary", "required", "advisory", "migration_status"}
    # The canonical-discovery item is present in migration_status, reflecting the
    # live probe outcome on the real instance (satisfied/pending/not_applicable).
    mig_ids = [m["action_id"] for m in payload["migration_status"]]
    assert CANONICAL_ACTION in mig_ids

    dest = tmp_path / "F010-live-upgrade-report.json"
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    assert dest.is_file()
    assert json.loads(dest.read_text()) == payload
