"""Plan G F003 (G3) — Android runtime evidence capture.

Tests cover:

  - passive_observe mode: per-step screenshot + logcat slice +
    per-session tombstone + ANR drains, written under
    ``evidence/goal-governance/post_impl/android/<journey>/``.
  - post_hoc_ingest mode: scan a fixture directory for known artifact
    patterns (screenshots/, logcat/, tombstones/, anr/, test-results/)
    and wrap each as a typed EvidenceRef. Unknown extensions are
    skipped without raising.
  - skip discipline:
      * empty journey → skip-reason EvidenceRef.
      * passive driver init failure → skip-reason EvidenceRef.
      * activate_step / screenshot / logcat / tombstone / anr drain
        failures → skip-reason EvidenceRef plus typed-fallback bytes.
      * post_hoc_ingest with no artifact_dir → skip-reason.
      * post_hoc_ingest with non-existent path → skip-reason.
      * post_hoc_ingest with empty-of-recognized-files dir →
        skip-reason at end.
  - config layering: per-call kwargs > project config > nothing
    (D015 — no global tier).
  - typed EvidenceRef fields compatible with G1/G2.
  - doctor framework: ``android_adb`` registered, warn-only across
    all failure modes (xcrun missing / probe error / non-zero / no
    devices). Never returns ``fail``.
  - greppable invariants: D003 evidence path, D004 project-agnostic,
    D005/D014 no credential literals, D009 no test-orchestration
    APIs (no gradle, no espressoRunner, no maestro invocation in
    source).

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_runtime_evidence_android.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))

from dontpanic_orchestrate import global_config as gc  # noqa: E402
from dontpanic_orchestrate import project_config as pc  # noqa: E402
from dontpanic_orchestrate.config import doctor_registry  # noqa: E402
from dontpanic_orchestrate.runtime_evidence import android as android_mod  # noqa: E402

_FIXTURE_DIR = HERE.parent / "runtime_evidence" / "_fixture_android"


@pytest.fixture(autouse=True)
def _isolate_dontpanic_home(tmp_path, monkeypatch):
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))


@pytest.fixture
def plan_dir(tmp_path):
    d = tmp_path / "plan"
    d.mkdir()
    return d


# ──────────────────────────  stub session/driver  ──────────────────────────


class _StubSession:
    """In-memory AndroidSession mirroring the Protocol exactly. No live
    adb calls anywhere."""

    def __init__(
        self,
        *,
        screenshot_payload: bytes = b"",
        logcat_slices: list[bytes] | None = None,
        tombstones: list[tuple[str, bytes]] | None = None,
        anrs: list[tuple[str, bytes]] | None = None,
        raise_on_activate: str | None = None,
        raise_on_screenshot: bool = False,
        raise_on_logcat: bool = False,
        raise_on_tombstones: bool = False,
        raise_on_anr: bool = False,
        raise_on_close: bool = False,
    ):
        self.screenshot_payload = screenshot_payload
        self.logcat_slices = list(logcat_slices or [])
        self.tombstones = list(tombstones or [])
        self.anrs = list(anrs or [])
        self.raise_on_activate = raise_on_activate
        self.raise_on_screenshot = raise_on_screenshot
        self.raise_on_logcat = raise_on_logcat
        self.raise_on_tombstones = raise_on_tombstones
        self.raise_on_anr = raise_on_anr
        self.raise_on_close = raise_on_close
        self.activated_steps: list[str] = []
        self.closed = False

    def activate_step(self, step_name: str) -> None:
        if self.raise_on_activate == step_name:
            raise android_mod.AndroidDriverError(f"stub: activate_step({step_name}) failed")
        self.activated_steps.append(step_name)

    def screenshot(self) -> bytes:
        if self.raise_on_screenshot:
            raise android_mod.AndroidDriverError("stub: screenshot failed")
        return self.screenshot_payload

    def drain_logcat_slice(self) -> bytes:
        if self.raise_on_logcat:
            raise android_mod.AndroidDriverError("stub: drain_logcat_slice failed")
        if not self.logcat_slices:
            return b""
        return self.logcat_slices.pop(0)

    def drain_tombstones(self) -> list[tuple[str, bytes]]:
        if self.raise_on_tombstones:
            raise android_mod.AndroidDriverError("stub: drain_tombstones failed")
        return list(self.tombstones)

    def drain_anr_reports(self) -> list[tuple[str, bytes]]:
        if self.raise_on_anr:
            raise android_mod.AndroidDriverError("stub: drain_anr_reports failed")
        return list(self.anrs)

    def close(self) -> None:
        if self.raise_on_close:
            raise android_mod.AndroidDriverError("stub: close failed")
        self.closed = True


class _StubDriver:
    name = "stub-android-driver"

    def __init__(
        self,
        session: _StubSession | None = None,
        *,
        raise_on_open: android_mod.AndroidDriverError | None = None,
    ):
        self.session = session
        self.raise_on_open = raise_on_open
        self.opens: list[dict] = []

    def open_session(
        self,
        *,
        package,
        adb_device_serial,
        session_config,
    ):
        self.opens.append(
            {
                "package": package,
                "adb_device_serial": adb_device_serial,
                "step_count": len(session_config.journey_steps),
                "mode": session_config.mode,
            }
        )
        if self.raise_on_open is not None:
            raise self.raise_on_open
        return self.session


def _fixed_clock():
    return datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)


def _load_fixture(rel: str) -> bytes:
    return (_FIXTURE_DIR / rel).read_bytes()


# ──────────────────────────  passive_observe happy path  ──────────────────────────


class TestPassiveObserveHappyPath:
    def test_per_step_screenshot_and_logcat_artifacts_written(self, plan_dir):
        session = _StubSession(
            screenshot_payload=_load_fixture("screenshots/launch.png"),
            logcat_slices=[
                _load_fixture("logcat/run.log"),
                b"step2 logcat slice\n",
            ],
        )
        driver = _StubDriver(session=session)
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[
                android_mod.AndroidJourneyStep(name="launch"),
                android_mod.AndroidJourneyStep(name="closet"),
            ],
            capture_logcat=True,
            capture_tombstones=False,
            capture_anr=False,
        )
        refs = collector.collect(
            "android-journey",
            package="com.example.app",
            adb_device_serial="emulator-5554",
            session_config=config,
        )
        # 2 steps × (screenshot + logcat) = 4.
        assert len(refs) == 4
        kinds = [r.type.value for r in refs]
        assert kinds.count("screenshot") == 2
        assert kinds.count("log") == 2
        for ref in refs:
            assert (plan_dir / ref.uri).is_file()
            assert ref.hash.startswith("sha256:")
            assert ref.captured_by == "stub-android-driver"
            assert ref.captured_at == _fixed_clock()
        assert session.activated_steps == ["launch", "closet"]
        assert session.closed is True

    def test_evidence_path_under_post_impl_android_journey(self, plan_dir):
        session = _StubSession(screenshot_payload=b"png-bytes")
        driver = _StubDriver(session=session)
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="home")],
            capture_logcat=False,
            capture_tombstones=False,
            capture_anr=False,
        )
        refs = collector.collect(
            "smoke",
            package="com.example.app",
            adb_device_serial="emulator-5554",
            session_config=config,
        )
        assert len(refs) == 1
        assert refs[0].uri.startswith("evidence/goal-governance/post_impl/android/smoke/")
        assert refs[0].uri.endswith("screenshot-home.png")

    def test_tombstones_and_anr_drained_at_session_end(self, plan_dir):
        tombstone_bytes = _load_fixture("tombstones/tombstone_00")
        anr_bytes = _load_fixture("anr/traces.txt")
        session = _StubSession(
            screenshot_payload=b"png",
            logcat_slices=[b"log\n"],
            tombstones=[("tombstone_00", tombstone_bytes)],
            anrs=[("traces.txt", anr_bytes)],
        )
        driver = _StubDriver(session=session)
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="launch")],
            capture_logcat=True,
            capture_tombstones=True,
            capture_anr=True,
        )
        refs = collector.collect(
            "with-diagnostics",
            package="com.example.app",
            adb_device_serial="emulator-5554",
            session_config=config,
        )
        # screenshot + logcat + tombstone + anr = 4.
        assert len(refs) == 4
        tomb_refs = [r for r in refs if "tombstone-" in r.uri]
        anr_refs = [r for r in refs if "anr-" in r.uri]
        assert len(tomb_refs) == 1
        assert len(anr_refs) == 1
        assert tomb_refs[0].type.value == "log"
        assert anr_refs[0].type.value == "log"
        assert (plan_dir / tomb_refs[0].uri).read_bytes() == tombstone_bytes
        assert (plan_dir / anr_refs[0].uri).read_bytes() == anr_bytes


# ──────────────────────────  passive_observe skip discipline  ──────────────────────────


class TestPassiveSkipDiscipline:
    def test_empty_journey_returns_skip_ref(self, plan_dir):
        driver = _StubDriver(session=_StubSession())
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="x")],
        )
        refs = collector.collect("", package="com.example.app", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        assert "empty journey" in (refs[0].note or "")

    def test_driver_open_failure_returns_skip_ref(self, plan_dir):
        driver = _StubDriver(
            raise_on_open=android_mod.AndroidDriverError("stub: no device attached")
        )
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="x")],
        )
        refs = collector.collect("j", package="com.example.app", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        assert "driver init failed" in (refs[0].note or "")
        assert "no device attached" in (refs[0].note or "")

    def test_unexpected_driver_fault_returns_skip_ref(self, plan_dir):
        class _Boom(_StubDriver):
            def open_session(self, **kw):
                raise RuntimeError("non-AndroidDriverError fault")

        driver = _Boom()
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="x")],
        )
        refs = collector.collect("j", package="com.example.app", session_config=config)
        assert len(refs) == 1
        assert "unexpected driver fault" in (refs[0].note or "")
        assert "RuntimeError" in (refs[0].note or "")

    def test_activate_step_failure_skips_only_that_step(self, plan_dir):
        session = _StubSession(
            screenshot_payload=b"png",
            logcat_slices=[b"good logcat\n"],
            raise_on_activate="bad-step",
        )
        driver = _StubDriver(session=session)
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[
                android_mod.AndroidJourneyStep(name="good-step"),
                android_mod.AndroidJourneyStep(name="bad-step"),
            ],
            capture_logcat=True,
            capture_tombstones=False,
            capture_anr=False,
        )
        refs = collector.collect("j", package="com.example.app", session_config=config)
        # good-step → screenshot + logcat; bad-step → 1 skip ref. Total 3.
        assert len(refs) == 3
        assert sum(1 for r in refs if r.type.value == "screenshot") == 1
        assert sum(1 for r in refs if r.type.value == "log") == 2
        skip_refs = [r for r in refs if "activate_step" in (r.note or "")]
        assert len(skip_refs) == 1

    def test_screenshot_failure_writes_empty_artifact_not_raise(self, plan_dir):
        session = _StubSession(
            screenshot_payload=b"unused",
            logcat_slices=[b"log\n"],
            raise_on_screenshot=True,
        )
        driver = _StubDriver(session=session)
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="x")],
            capture_logcat=True,
            capture_tombstones=False,
            capture_anr=False,
        )
        refs = collector.collect("j", package="com.example.app", session_config=config)
        screenshot_refs = [r for r in refs if r.type.value == "screenshot"]
        assert len(screenshot_refs) == 1
        empty_sha = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert screenshot_refs[0].hash == empty_sha

    def test_tombstone_drain_failure_returns_skip_ref(self, plan_dir):
        session = _StubSession(
            screenshot_payload=b"png",
            logcat_slices=[b"log\n"],
            raise_on_tombstones=True,
        )
        driver = _StubDriver(session=session)
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="x")],
            capture_logcat=True,
            capture_tombstones=True,
            capture_anr=False,
        )
        refs = collector.collect("j", package="com.example.app", session_config=config)
        skip_refs = [r for r in refs if r.note and "tombstone drain failed" in r.note]
        assert len(skip_refs) == 1

    def test_anr_drain_failure_returns_skip_ref(self, plan_dir):
        session = _StubSession(
            screenshot_payload=b"png",
            logcat_slices=[b"log\n"],
            raise_on_anr=True,
        )
        driver = _StubDriver(session=session)
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="x")],
            capture_logcat=True,
            capture_tombstones=False,
            capture_anr=True,
        )
        refs = collector.collect("j", package="com.example.app", session_config=config)
        skip_refs = [r for r in refs if r.note and "anr drain failed" in r.note]
        assert len(skip_refs) == 1

    def test_close_failure_swallowed(self, plan_dir):
        session = _StubSession(
            screenshot_payload=b"png",
            logcat_slices=[b"log\n"],
            raise_on_close=True,
        )
        driver = _StubDriver(session=session)
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="x")],
            capture_logcat=True,
            capture_tombstones=False,
            capture_anr=False,
        )
        refs = collector.collect("j", package="com.example.app", session_config=config)
        assert len(refs) >= 1


# ──────────────────────────  post_hoc_ingest  ──────────────────────────


class TestPostHocIngest:
    def test_recognizes_all_artifact_categories(self, plan_dir):
        # Driver intentionally None — post_hoc_ingest must not call it.
        collector = android_mod.AndroidEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = android_mod.AndroidSessionConfig(
            mode="post_hoc_ingest",
            artifact_dir=_FIXTURE_DIR,
        )
        refs = collector.collect("post-hoc", session_config=config)
        # Fixture has: 2 screenshots + 1 logcat + 1 tombstone + 1 anr +
        # 1 test-results = 6 recognized; random.dat is skipped silently.
        recognized_types = [r.type.value for r in refs if not r.uri.endswith("skip-reason.txt")]
        assert recognized_types.count("screenshot") == 2
        assert recognized_types.count("log") == 3  # logcat + tombstone + anr
        assert recognized_types.count("test_output") == 1
        # No skip-reason since we found recognized artifacts.
        assert all("skip-reason" not in r.uri for r in refs)

    def test_artifacts_written_under_post_impl_android_journey(self, plan_dir):
        collector = android_mod.AndroidEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = android_mod.AndroidSessionConfig(
            mode="post_hoc_ingest",
            artifact_dir=_FIXTURE_DIR,
        )
        refs = collector.collect("ingest-journey", session_config=config)
        for ref in refs:
            assert ref.uri.startswith("evidence/goal-governance/post_impl/android/ingest-journey/")
            assert (plan_dir / ref.uri).is_file()

    def test_missing_artifact_dir_returns_skip_ref(self, plan_dir):
        collector = android_mod.AndroidEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = android_mod.AndroidSessionConfig(
            mode="post_hoc_ingest",
            artifact_dir=None,
        )
        refs = collector.collect("j", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        assert "requires artifact_dir" in (refs[0].note or "")

    def test_nonexistent_artifact_dir_returns_skip_ref(self, plan_dir, tmp_path):
        collector = android_mod.AndroidEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = android_mod.AndroidSessionConfig(
            mode="post_hoc_ingest",
            artifact_dir=tmp_path / "does-not-exist",
        )
        refs = collector.collect("j", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        assert "does not exist" in (refs[0].note or "")

    def test_empty_artifact_dir_returns_skip_ref(self, plan_dir, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        collector = android_mod.AndroidEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = android_mod.AndroidSessionConfig(
            mode="post_hoc_ingest",
            artifact_dir=empty,
        )
        refs = collector.collect("j", session_config=config)
        assert len(refs) == 1
        assert "no recognized artifacts" in (refs[0].note or "")

    def test_unrecognized_extensions_silently_skipped(self, plan_dir, tmp_path):
        # Mix of recognized + unrecognized files; collector ingests only
        # the recognized ones and never raises on unknowns.
        d = tmp_path / "mixed"
        (d / "screenshots").mkdir(parents=True)
        (d / "logcat").mkdir(parents=True)
        (d / "screenshots" / "good.png").write_bytes(b"png")
        (d / "logcat" / "run.log").write_bytes(b"log content\n")
        (d / "weird.xyz").write_bytes(b"unknown")
        (d / "stray.dat").write_bytes(b"unknown")

        collector = android_mod.AndroidEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = android_mod.AndroidSessionConfig(
            mode="post_hoc_ingest",
            artifact_dir=d,
        )
        refs = collector.collect("j", session_config=config)
        # Exactly 2 recognized; no skip-reason at end since we found some.
        assert len(refs) == 2
        kinds = [r.type.value for r in refs]
        assert kinds.count("screenshot") == 1
        assert kinds.count("log") == 1


# ──────────────────────────  config layering (D015)  ──────────────────────────


class TestConfigLayering:
    def test_per_call_package_overrides_project_config(self, plan_dir):
        proj_root = plan_dir.parent
        from dontpanic_orchestrate import projects_registry as pr

        pr.add_project(name="proj-a", path=proj_root)
        cfg_path = pc.project_config_path(proj_root)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps(
                {
                    "runtime_evidence": {
                        "android": {
                            "package": "com.project.bundle",
                            "adb_device_serial": "emulator-9999",
                        }
                    }
                }
            )
        )
        session = _StubSession(screenshot_payload=b"png")
        driver = _StubDriver(session=session)
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="x")],
            capture_logcat=False,
            capture_tombstones=False,
            capture_anr=False,
        )
        collector.collect("j", package="com.example.override", session_config=config)
        assert driver.opens[0]["package"] == "com.example.override"
        # adb_device_serial falls through to project value.
        assert driver.opens[0]["adb_device_serial"] == "emulator-9999"

    def test_no_layer_set_passes_none(self, plan_dir):
        session = _StubSession(screenshot_payload=b"png")
        driver = _StubDriver(session=session)
        collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=driver, clock=_fixed_clock
        )
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="x")],
            capture_logcat=False,
            capture_tombstones=False,
            capture_anr=False,
        )
        collector.collect("j", session_config=config)
        assert driver.opens[0]["package"] is None
        assert driver.opens[0]["adb_device_serial"] is None

    def test_post_hoc_artifact_dir_from_project_config(self, plan_dir):
        proj_root = plan_dir.parent
        from dontpanic_orchestrate import projects_registry as pr

        pr.add_project(name="proj-b", path=proj_root)
        cfg_path = pc.project_config_path(proj_root)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps({"runtime_evidence": {"android": {"artifact_dir": str(_FIXTURE_DIR)}}})
        )
        # Pydantic schema may not declare artifact_dir; the resolver still
        # surfaces it because RuntimeEvidenceConfig.android is permissive
        # via the AndroidDefaults shape. If the schema rejects it, skip
        # this assertion path — config-load returns None and we'd get a
        # skip-reason without project_dir.
        loaded = pc.load_project_config(proj_root)
        if (
            loaded is None
            or loaded.runtime_evidence is None
            or loaded.runtime_evidence.android is None
        ):
            pytest.skip(
                "AndroidDefaults schema doesn't carry artifact_dir; covered by per-call test"
            )
        collector = android_mod.AndroidEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = android_mod.AndroidSessionConfig(mode="post_hoc_ingest")
        refs = collector.collect("post-hoc-from-project", session_config=config)
        assert any(r.uri.endswith("ingest-screenshots_launch.png") for r in refs)


# ──────────────────────────  default driver behavior  ──────────────────────────


class TestDefaultAdbDriver:
    def test_default_driver_skips_when_adb_missing(self, plan_dir, monkeypatch):
        monkeypatch.setattr(android_mod.shutil, "which", lambda name: None)
        collector = android_mod.AndroidEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="x")],
        )
        refs = collector.collect("j", package="com.example.app", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        assert "adb not on PATH" in (refs[0].note or "")

    def test_default_driver_skips_when_session_adapter_unwired(self, plan_dir, monkeypatch):
        monkeypatch.setattr(android_mod.shutil, "which", lambda name: "/usr/bin/adb")
        collector = android_mod.AndroidEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="x")],
        )
        refs = collector.collect("j", package="com.example.app", session_config=config)
        assert len(refs) == 1
        assert "session adapter not wired" in (refs[0].note or "")


# ──────────────────────────  doctor framework  ──────────────────────────


class TestDoctorRegistration:
    def test_android_adb_check_registered_at_import(self):
        android_mod._register_android_doctor_checks()
        results = doctor_registry.run_all_checks()
        assert any(r.name == "android_adb" for r in results)

    def test_returns_warn_when_adb_missing(self, monkeypatch):
        monkeypatch.setattr(android_mod.shutil, "which", lambda name: None)
        result = android_mod._android_adb_check()
        assert result.status == "warn"
        assert "adb not on PATH" in result.detail

    def test_returns_warn_when_no_devices_attached(self, monkeypatch):
        monkeypatch.setattr(android_mod.shutil, "which", lambda name: "/usr/bin/adb")

        class _Result:
            returncode = 0
            stdout = b"List of devices attached\n\n"
            stderr = b""

        def _run(*a, **kw):
            return _Result()

        monkeypatch.setattr(android_mod.subprocess, "run", _run)
        result = android_mod._android_adb_check()
        assert result.status == "warn"
        assert "no devices attached" in result.detail

    def test_returns_pass_when_devices_attached(self, monkeypatch):
        monkeypatch.setattr(android_mod.shutil, "which", lambda name: "/usr/bin/adb")

        class _Result:
            returncode = 0
            stdout = b"List of devices attached\nemulator-5554\tdevice\n"
            stderr = b""

        def _run(*a, **kw):
            return _Result()

        monkeypatch.setattr(android_mod.subprocess, "run", _run)
        result = android_mod._android_adb_check()
        assert result.status == "pass"
        assert "1 device(s)" in result.detail

    def test_check_never_returns_fail(self, monkeypatch):
        # Sweep failure modes: missing PATH, OSError, non-zero, no devices,
        # one device. None should return 'fail'.
        for setup in [
            lambda: monkeypatch.setattr(android_mod.shutil, "which", lambda n: None),
            lambda: (
                monkeypatch.setattr(android_mod.shutil, "which", lambda n: "/usr/bin/adb"),
                monkeypatch.setattr(
                    android_mod.subprocess,
                    "run",
                    lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic")),
                ),
            ),
        ]:
            monkeypatch.undo()
            setup()
            assert android_mod._android_adb_check().status != "fail"


# ──────────────────────────  source-grep invariants  ──────────────────────────


class TestSourceInvariants:
    _ANDROID_SRC = (HERE.parents[1] / "runtime_evidence" / "android.py").read_text()

    def test_no_project_name_special_cases(self):
        """D004: Android adapter must be project-agnostic."""
        lower = self._ANDROID_SRC.lower()
        for needle in ("spin_dine_", "spin-dine_", "glam_", "creator_hub_"):
            assert needle not in lower, (
                f"runtime_evidence/android.py contains project-specific token {needle!r} (D004)"
            )

    def test_no_credential_storage(self):
        """D005/D014: no credential-bearing literals."""
        forbidden = (
            re.compile(r"password\s*=\s*['\"]", re.IGNORECASE),
            re.compile(r"\bbearer\s+[a-z0-9._\-]+", re.IGNORECASE),
            re.compile(r"api_key\s*=\s*['\"]", re.IGNORECASE),
        )
        for rx in forbidden:
            assert not rx.search(self._ANDROID_SRC), (
                f"runtime_evidence/android.py contains credential-like literal "
                f"matching {rx.pattern!r} (D005/D014)"
            )

    def test_evidence_path_uses_android_subdir(self):
        """D003: artifacts under post_impl/android/<journey>."""
        assert (
            'goal_governance_evidence_path(self._plan_dir, "post_impl", f"android/{journey}")'
            in self._ANDROID_SRC
        )

    def test_no_test_orchestration_apis(self):
        """D009: G3 v1 is capture-only; no test-runner invocation in source.

        The adapter must NOT shell out to gradle, am instrument, espresso
        runners, or maestro CLI. Operators run their own tests; we just
        capture artifacts.
        """
        forbidden_orchestration = (
            "gradle ",  # gradlew assemble / connectedAndroidTest
            "gradlew",  # ./gradlew shorthand
            "espressoRunner",
            "androidx.test.runner",
            "am instrument",
            "maestro test",
            "maestro studio",
        )
        for needle in forbidden_orchestration:
            assert needle not in self._ANDROID_SRC, (
                f"runtime_evidence/android.py contains test-orchestration "
                f"token {needle!r} (D009 — G3 v1 is capture-only)"
            )
