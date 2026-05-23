"""Plan 2026-05-23-004 F003 — dashboard CLI tests.

Acceptance coverage:

  (1) ``dontpanic dashboard build`` writes dashboard/state files plus
      the what-now cache.
  (2) ``dontpanic dashboard open`` builds and prints a usable local
      URL/path.
  (3) ``dontpanic dashboard serve`` binds localhost by default and
      refreshes without manual rebuild; non-loopback host is rejected
      unless ``--allow-remote`` is set.
  (4) No Firebase config is required or mentioned as a V0 requirement.
  (5) Tests cover build/open/serve safety and missing optional inputs.

Plus: ``--help`` text exercises argparse plumbing so future renames
break loud rather than silently.
"""

from __future__ import annotations

import http.client
import json
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from dontpanic_orchestrate import dashboard
from dontpanic_orchestrate import operator_console as oc

# ─── helpers ───────────────────────────────────────────────────────────


def _make_min_plan(plans_root: Path, plan_id: str) -> Path:
    """Minimal plan_loader-compatible plan dir.

    state_projection requires plan.md frontmatter (title + status), and
    features.json. Any plan with declared human_gates that aren't cleared
    will surface as a gate ActionItem.
    """

    plan_dir = plans_root / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "plan.md").write_text(
        f"""---
id: {plan_id}
title: Test plan {plan_id}
description: Synthetic dashboard CLI test fixture.
type: feat
tier: cross-cutting
status: active
date: "2026-05-23"
goal_type: new_feature
agents_required:
  - claude
human_gates:
  - pre_impl
---

# Test plan

## Motivation
Synthetic test fixture; do not dispatch.

## Target

```yaml
target_env: dev
target_project: none
```

## Boundaries
In scope: tests only.
Out of scope: production work.
"""
    )
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "task_id": plan_id,
                "schema_version": "1.0",
                "features": [
                    {
                        "id": "F001",
                        "category": "infra",
                        "phase": 1,
                        "description": "Tiny test feature for the dashboard CLI fixture.",
                        "steps": ["noop"],
                        "acceptance": "noop",
                        "passes": False,
                        "depends_on": [],
                    }
                ],
            }
        )
    )
    (plan_dir / "decisions.jsonl").write_text("")
    (plan_dir / "audit").mkdir(exist_ok=True)
    (plan_dir / "evidence").mkdir(exist_ok=True)
    return plan_dir


@contextmanager
def _running_server(handle: dashboard.ServeHandle):
    try:
        yield handle
    finally:
        handle.shutdown()


def _http_get(handle: dashboard.ServeHandle, path: str = "/") -> tuple[int, bytes]:
    conn = http.client.HTTPConnection(handle.host, handle.port, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


# ─── (1) build writes state + what-now cache ───────────────────────────


def test_build_writes_state_files_and_what_now_cache(tmp_path: Path) -> None:
    plans_root = tmp_path / "plans"
    out_dir = tmp_path / "out"
    _make_min_plan(plans_root, "2026-05-23-001-feat-test")

    report = dashboard.build(plans_root=plans_root, out_dir=out_dir)

    # Acceptance (1): state files + what-now cache exist.
    names = {p.name for p in report.state_files}
    assert "state-snapshot.json" in names
    assert "manifest.json" in names
    for stream in ("plans", "gates", "inbox", "supervisors", "quota", "decisions", "evidence_refs"):
        assert f"{stream}.json" in names

    assert (out_dir / "what-now.json").is_file()
    assert (out_dir / "capabilities-status.json").is_file()
    assert (out_dir / "reconcile-status.json").is_file()
    assert (out_dir / "architecture-status.json").is_file()
    assert report.what_now_cache_path is not None
    assert report.what_now_cache_path.is_file()

    # What-now cache JSON envelope is stable F001 shape.
    envelope = json.loads(report.what_now_cache_path.read_text())
    assert envelope["schema_version"] == oc.SCHEMA_VERSION
    assert isinstance(envelope["items"], list)
    # The fixture has an unmet pre_impl gate → should surface as needs_action.
    bands = {it["band"] for it in envelope["items"]}
    assert "needs_action" in bands

    # Dashboard copy mirrors operator cache contents (same items list).
    dash_copy = json.loads((out_dir / "what-now.json").read_text())
    assert dash_copy["items"] == envelope["items"]


def test_build_tolerates_missing_plans_root(tmp_path: Path) -> None:
    """Acceptance (5): missing optional input — no plans directory at all.

    Operator running ``dashboard build`` before any plan exists must get
    a usable dashboard, not a crash. Missing plans_root → empty state
    streams, no gate items, but the cache and state files still land.
    """

    plans_root = tmp_path / "nonexistent"
    out_dir = tmp_path / "out"
    dashboard.build(plans_root=plans_root, out_dir=out_dir)
    assert (out_dir / "state-snapshot.json").is_file()
    assert (out_dir / "what-now.json").is_file()
    # State export with empty plans is a degenerate-but-valid envelope.
    envelope = json.loads((out_dir / "state-snapshot.json").read_text())
    assert envelope["streams"]["plans"] == []
    assert envelope["streams"]["gates"] == []


def test_build_warnings_are_collected_not_raised(tmp_path: Path, monkeypatch) -> None:
    """Acceptance (5): a failing subsystem (architecture, reconcile, etc.)
    surfaces as a warning string, not a build crash."""

    plans_root = tmp_path / "plans"
    out_dir = tmp_path / "out"
    _make_min_plan(plans_root, "2026-05-23-002-feat-test")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("synthetic architecture failure")

    monkeypatch.setattr(dashboard.architecture, "status", _boom)
    report = dashboard.build(plans_root=plans_root, out_dir=out_dir)
    assert report.architecture_status_path is None
    assert any("architecture" in w for w in report.warnings)
    # And the rest of the build still produced output.
    assert (out_dir / "state-snapshot.json").is_file()
    assert (out_dir / "what-now.json").is_file()


# ─── (2) open builds and prints local path ─────────────────────────────


def test_open_prints_usable_local_path(tmp_path: Path) -> None:
    plans_root = tmp_path / "plans"
    out_dir = tmp_path / "out"
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "index.html").write_text("<html><body>hi</body></html>")
    _make_min_plan(plans_root, "2026-05-23-003-feat-test")

    report = dashboard.build(plans_root=plans_root, out_dir=out_dir)
    printed: list[str] = []
    opener_calls: list[Path] = []

    def fake_opener(target: Path) -> bool:
        opener_calls.append(target)
        return True

    target = dashboard.open_dashboard(
        build_report=report,
        dashboard_dir=dashboard_dir,
        launch=True,
        printer=printed.append,
        opener=fake_opener,
    )
    # Path printed; opener invoked.
    assert target == dashboard_dir / "index.html"
    assert any(str(target) in line for line in printed)
    assert opener_calls == [dashboard_dir / "index.html"]


def test_open_prints_path_even_when_launch_disabled(tmp_path: Path) -> None:
    """Acceptance (2): a sandboxed/headless caller (no GUI opener) still
    gets a printable, usable path."""

    plans_root = tmp_path / "plans"
    out_dir = tmp_path / "out"
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    # No index.html → opener falls back to the directory path itself.
    _make_min_plan(plans_root, "2026-05-23-004-feat-test")
    report = dashboard.build(plans_root=plans_root, out_dir=out_dir)
    printed: list[str] = []

    target = dashboard.open_dashboard(
        build_report=report,
        dashboard_dir=dashboard_dir,
        launch=False,
        printer=printed.append,
    )
    assert target == dashboard_dir
    assert any(str(dashboard_dir) in line for line in printed)


# ─── (3) serve binds localhost by default + watch refresh ──────────────


def test_serve_binds_loopback_by_default(tmp_path: Path) -> None:
    plans_root = tmp_path / "plans"
    out_dir = tmp_path / "out"
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "index.html").write_text("<html>hello</html>")
    _make_min_plan(plans_root, "2026-05-23-005-feat-test")

    handle = dashboard.serve_start(
        host=dashboard.DEFAULT_HOST,
        port=0,
        dashboard_dir=dashboard_dir,
        plans_root=plans_root,
        state_out_dir=out_dir,
        watch=False,
    )
    with _running_server(handle):
        # Acceptance (3): bound to a loopback address.
        assert handle.host == dashboard.DEFAULT_HOST
        # And actually serving the dashboard root.
        status, body = _http_get(handle, "/")
        assert status == 200
        assert b"hello" in body


def test_serve_refuses_non_loopback_without_allow_remote(tmp_path: Path) -> None:
    """Acceptance (3 + 4): default-safe binding. No-remote-exposure is
    enforced at the library boundary so the CLI flag, env, and direct
    library callers all share the same gate."""

    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    plans_root = tmp_path / "plans"
    plans_root.mkdir()

    with pytest.raises(ValueError, match="loopback"):
        dashboard.serve_start(
            host="0.0.0.0",  # noqa: S104 — test asserts the bind is refused
            port=0,
            dashboard_dir=dashboard_dir,
            plans_root=plans_root,
            state_out_dir=tmp_path / "out",
            watch=False,
        )


def test_serve_loopback_classifier_rejects_public_ip(tmp_path: Path) -> None:
    """Belt-and-braces: classifier rejects an arbitrary public IP."""

    assert dashboard._is_loopback_host("127.0.0.1") is True
    assert dashboard._is_loopback_host("::1") is True
    assert dashboard._is_loopback_host("localhost") is True
    assert dashboard._is_loopback_host("0.0.0.0") is False  # noqa: S104
    assert dashboard._is_loopback_host("8.8.8.8") is False


def test_serve_watch_loop_rebuilds_on_source_change(tmp_path: Path) -> None:
    """Acceptance (3): the serve loop refreshes state without a manual
    ``build`` invocation when watched sources change."""

    plans_root = tmp_path / "plans"
    out_dir = tmp_path / "out"
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "index.html").write_text("<html>hi</html>")
    _make_min_plan(plans_root, "2026-05-23-006-feat-test")

    handle = dashboard.serve_start(
        host=dashboard.DEFAULT_HOST,
        port=0,
        dashboard_dir=dashboard_dir,
        plans_root=plans_root,
        state_out_dir=out_dir,
        watch=True,
        watch_interval=0.1,
    )
    with _running_server(handle):
        # Capture initial what-now mtime.
        what_now = out_dir / "what-now.json"
        assert what_now.is_file()
        first_mtime = what_now.stat().st_mtime

        # Simulate operator activity: add a new plan dir to bump
        # plans_root mtime. The watcher should pick this up and rebuild.
        time.sleep(0.2)
        _make_min_plan(plans_root, "2026-05-23-007-feat-test")
        # Force plans_root mtime forward in case the test FS coalesces.
        new_time = time.time() + 5
        import os as _os

        _os.utime(plans_root, (new_time, new_time))

        # Poll for rebuild — bounded so a flaky watch loop fails fast.
        deadline = time.time() + 5
        rebuilt = False
        while time.time() < deadline:
            if what_now.stat().st_mtime > first_mtime:
                rebuilt = True
                break
            time.sleep(0.1)
        assert rebuilt, "watch loop did not rebuild what-now cache after source change"


def test_serve_watch_loop_rebuilds_on_existing_plan_file_edit(tmp_path: Path) -> None:
    """Regression for prior i0 audit (medium correctness): editing an
    existing plan source file must retrigger rebuild.

    The earlier implementation only walked plan dirs 1 level deep and
    treated the dir's mtime as the trigger, which most filesystems do
    NOT bump when an inline file edit occurs — so a real-world operator
    saving plan.md / features.json / INBOX.md would never see the
    dashboard refresh until they added a new plan dir.
    """

    plans_root = tmp_path / "plans"
    out_dir = tmp_path / "out"
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "index.html").write_text("<html>hi</html>")
    plan_dir = _make_min_plan(plans_root, "2026-05-23-010-feat-test")
    plan_md = plan_dir / "plan.md"

    handle = dashboard.serve_start(
        host=dashboard.DEFAULT_HOST,
        port=0,
        dashboard_dir=dashboard_dir,
        plans_root=plans_root,
        state_out_dir=out_dir,
        watch=True,
        watch_interval=0.1,
    )
    with _running_server(handle):
        what_now = out_dir / "what-now.json"
        assert what_now.is_file()
        first_mtime = what_now.stat().st_mtime

        time.sleep(0.2)
        # Inline edit of an existing plan source file. Critically we do
        # NOT touch plans_root or plan_dir mtime — only plan.md's.
        import os as _os

        new_time = time.time() + 5
        plan_md.write_text(plan_md.read_text() + "\n<!-- inline edit -->\n")
        _os.utime(plan_md, (new_time, new_time))

        deadline = time.time() + 5
        rebuilt = False
        while time.time() < deadline:
            if what_now.stat().st_mtime > first_mtime:
                rebuilt = True
                break
            time.sleep(0.1)
        assert rebuilt, (
            "watch loop did not rebuild after inline edit to an existing "
            "plan source file (plan.md); watcher must walk plan-dir "
            "contents, not just plan-dir mtime"
        )


def test_serve_watch_loop_ignores_state_out_writes(tmp_path: Path) -> None:
    """Regression for prior i0 audit (medium performance): the watcher
    must not include its own generated output (``state_out_dir``) as a
    watched source, or every rebuild would retrigger itself on the next
    tick — a busy-loop on a quiet system.

    We assert: forcing the state_out_dir files' mtime forward (with no
    other change) does NOT trigger a rebuild. The what-now cache mtime
    must remain at its post-initial-build value across several watch
    ticks.
    """

    plans_root = tmp_path / "plans"
    out_dir = tmp_path / "out"
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "index.html").write_text("<html>hi</html>")
    _make_min_plan(plans_root, "2026-05-23-011-feat-test")

    handle = dashboard.serve_start(
        host=dashboard.DEFAULT_HOST,
        port=0,
        dashboard_dir=dashboard_dir,
        plans_root=plans_root,
        state_out_dir=out_dir,
        watch=True,
        watch_interval=0.1,
    )
    with _running_server(handle):
        what_now = out_dir / "what-now.json"
        snapshot = out_dir / "state-snapshot.json"
        assert what_now.is_file() and snapshot.is_file()
        # Use snapshot as the rebuild signal; we deliberately do NOT
        # touch what-now.json below because doing so would fake the very
        # signal we want to verify the watcher does not produce.
        first_mtime = snapshot.stat().st_mtime

        time.sleep(0.2)
        # Bump every generated state file's mtime — except what-now /
        # snapshot, which we use as rebuild detectors — well into the
        # future. If the watcher incorrectly treats state_out_dir as a
        # source, this bump will trip a rebuild and the build will
        # rewrite snapshot.json with a current-time mtime ≪ future,
        # which the assertion below will detect.
        import os as _os

        future = time.time() + 60
        for path in out_dir.iterdir():
            if path.name in {"state-snapshot.json", "what-now.json"}:
                continue
            _os.utime(path, (future, future))
        _os.utime(out_dir, (future, future))

        # Wait several watch intervals; a correct watcher should NOT
        # rebuild because nothing under plans_root or the static
        # dashboard tree changed.
        time.sleep(0.6)
        assert snapshot.stat().st_mtime == first_mtime, (
            "watch loop rebuilt after only generated state files changed; "
            "state_out_dir must be excluded from watched sources to avoid "
            "rebuild feedback"
        )


def test_serve_watch_loop_rebuilds_on_existing_plan_file_deletion(tmp_path: Path) -> None:
    """Regression for i1 auditor finding: deletions must retrigger.

    A max-mtime watcher can miss deletions because removing the newest
    source file may lower the current max timestamp. The watcher must
    compare a source fingerprint instead, so file-set changes in either
    direction cause a rebuild.
    """

    plans_root = tmp_path / "plans"
    out_dir = tmp_path / "out"
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "index.html").write_text("<html>hi</html>")
    plan_dir = _make_min_plan(plans_root, "2026-05-23-013-feat-test")
    inbox_path = plan_dir / "INBOX.md"
    inbox_path.write_text("# inbox\n")

    handle = dashboard.serve_start(
        host=dashboard.DEFAULT_HOST,
        port=0,
        dashboard_dir=dashboard_dir,
        plans_root=plans_root,
        state_out_dir=out_dir,
        watch=True,
        watch_interval=0.1,
    )
    with _running_server(handle):
        snapshot = out_dir / "state-snapshot.json"
        assert snapshot.is_file()
        first_mtime = snapshot.stat().st_mtime

        time.sleep(0.2)
        inbox_path.unlink()

        deadline = time.time() + 5
        rebuilt = False
        while time.time() < deadline:
            if snapshot.stat().st_mtime > first_mtime:
                rebuilt = True
                break
            time.sleep(0.1)
        assert rebuilt, "watch loop did not rebuild after watched plan file deletion"


def test_serve_once_flag_returns_immediately(tmp_path: Path, capsys) -> None:
    """Acceptance (3): ``--once`` lets tests verify the bind path without
    blocking the test runner on serve_forever."""

    plans_root = tmp_path / "plans"
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "index.html").write_text("<html>hi</html>")
    _make_min_plan(plans_root, "2026-05-23-008-feat-test")

    rc = dashboard.main(
        [
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--dashboard-dir",
            str(dashboard_dir),
            "--plans-root",
            str(plans_root),
            "--state-out",
            str(tmp_path / "state"),
            "--no-watch",
            "--once",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "dashboard serving at http://127.0.0.1:" in out


def test_serve_cli_rejects_remote_host_without_flag(tmp_path: Path, capsys) -> None:
    """CLI surface mirrors the library refusal — acceptance (3 + 4).

    Operator must explicitly pass ``--allow-remote`` to bind a public
    host. Without it, exit code is 2 and stderr names ``loopback``.
    """

    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "index.html").write_text("<html>x</html>")
    plans_root = tmp_path / "plans"
    plans_root.mkdir()

    rc = dashboard.main(
        [
            "serve",
            "--host",
            "0.0.0.0",  # noqa: S104
            "--port",
            "0",
            "--dashboard-dir",
            str(dashboard_dir),
            "--plans-root",
            str(plans_root),
            "--no-watch",
            "--once",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "loopback" in err


# ─── (4) no Firebase requirement ───────────────────────────────────────


def test_dashboard_help_does_not_require_firebase(capsys) -> None:
    """Acceptance (4): V0 console must not require or document Firebase
    as a runtime dependency.

    We assert two things:
      1. The top-level help string never says "Firebase required".
      2. The CLI help mentions ``localhost`` + ``serve`` so the
         operator's first read points them at the local-only path.
    """

    with pytest.raises(SystemExit):
        dashboard.main(["--help"])
    out = capsys.readouterr().out
    lower = out.lower()
    assert "firebase" not in lower
    assert "localhost" in lower or "loopback" in lower
    assert "build" in lower
    assert "serve" in lower
    assert "open" in lower


def test_dashboard_module_source_never_imports_firebase() -> None:
    """Belt-and-braces: import-time safety. If anyone ever wires the
    Firebase client into the dashboard module, this test fails before
    they ship — preserving acceptance (4)."""

    source = Path(dashboard.__file__).read_text()
    assert "firebase" not in source.lower(), (
        "dashboard module must not depend on Firebase per V0 acceptance (4)"
    )


def test_build_excludes_realtime_dashboard_capabilities(tmp_path: Path) -> None:
    """Regression for prior i0 audit (high correctness): the V0 console
    must not surface realtime-dashboard capability setup
    (e.g. ``firebase-dashboard``) as console action work.

    Acceptance (4) — "no Firebase config required" — is operationally
    violated if the dashboard's what-now cache promotes the
    ``firebase-dashboard`` capability's ``needs_setup`` state to a
    ``needs_action`` item the operator must clear before progress.
    """

    plans_root = tmp_path / "plans"
    out_dir = tmp_path / "out"
    _make_min_plan(plans_root, "2026-05-23-012-feat-test")

    report = dashboard.build(plans_root=plans_root, out_dir=out_dir)

    # Dashboard copy of capabilities cache must not include realtime
    # adapters.
    dash_caps_path = out_dir / "capabilities-status.json"
    assert dash_caps_path.is_file()
    dash_caps = json.loads(dash_caps_path.read_text())
    dash_ids = {c["capability_id"] for c in dash_caps["capabilities"]}
    # No capability_id whose source manifest is in an excluded category
    # should appear in the dashboard copy. firebase-dashboard is the
    # canonical example (category: dashboard-realtime).
    assert "firebase-dashboard" not in dash_ids, (
        "V0 dashboard capability cache must exclude dashboard-realtime "
        "category capabilities (e.g. firebase-dashboard); see "
        "dashboard.V0_DASHBOARD_EXCLUDED_CATEGORIES"
    )

    # What-now action items must not surface any firebase-dashboard
    # source either — neither needs_action nor advisory.
    assert report.what_now_cache_path is not None
    envelope = json.loads(report.what_now_cache_path.read_text())
    for item in envelope["items"]:
        assert "firebase-dashboard" not in item.get("id", ""), (
            f"what-now item leaked excluded capability: {item}"
        )
        assert "firebase-dashboard" not in (item.get("title") or ""), (
            f"what-now item leaked excluded capability in title: {item}"
        )


# ─── help text + subcommand wiring ─────────────────────────────────────


def test_build_help_text_includes_all_three_subcommands(capsys) -> None:
    with pytest.raises(SystemExit):
        dashboard.main(["--help"])
    out = capsys.readouterr().out
    for sub in ("build", "open", "serve"):
        assert sub in out


def test_main_with_no_subcommand_prints_help_and_exits_2(capsys) -> None:
    rc = dashboard.main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "build" in err
    assert "serve" in err


def test_build_main_writes_via_cli(tmp_path: Path, capsys) -> None:
    plans_root = tmp_path / "plans"
    out_dir = tmp_path / "out"
    _make_min_plan(plans_root, "2026-05-23-009-feat-test")

    rc = dashboard.main(
        [
            "build",
            "--plans-root",
            str(plans_root),
            "--out",
            str(out_dir),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "wrote" in out
    assert (out_dir / "state-snapshot.json").is_file()
    assert (out_dir / "what-now.json").is_file()
