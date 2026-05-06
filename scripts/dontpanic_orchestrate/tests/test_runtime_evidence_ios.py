"""Plan G F002 (G2) — iOS runtime evidence capture.

Tests cover:

  - per-step capture: screenshot + log slice EvidenceRefs written under
    evidence/goal-governance/post_impl/ios/<journey>/.
  - per-session crash report drain: typed log EvidenceRefs.
  - skip discipline:
      * empty journey → skip-reason EvidenceRef.
      * driver init failure → skip-reason EvidenceRef.
      * activate_step / screenshot / log / crash drain failures →
        skip-reason EvidenceRef plus typed-fallback bytes.
  - config layering: per-call kwargs > project config > nothing
    (D015 — no global tier).
  - typed EvidenceRef fields (type / uri / hash / captured_at /
    captured_by / note) compatible with G1's surface.
  - doctor framework: ``ios_simctl`` registered; result is ``warn``
    (never ``fail``) when xcrun is absent — projects that don't
    target iOS aren't blocked.
  - greppable: no live simulator dependency in pytest (no
    ``subprocess.run``/``check_output`` on ``xcrun``/``simctl`` from
    test bodies; ``shutil.which`` is permitted only inside the
    module, not from a stub session).

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_runtime_evidence_ios.py
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
from dontpanic_orchestrate.runtime_evidence import ios as ios_mod  # noqa: E402

_FIXTURE_DIR = HERE.parent / "runtime_evidence" / "_fixture_ios"


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
    """Deterministic in-memory session backed by static fixtures.
    Mirrors the IosSession Protocol exactly; no I/O against a real
    simulator."""

    def __init__(
        self,
        *,
        screenshot_payload: bytes = b"",
        log_slices: list[bytes] | None = None,
        crashes: list[tuple[str, bytes]] | None = None,
        raise_on_activate: str | None = None,
        raise_on_screenshot: bool = False,
        raise_on_log: bool = False,
        raise_on_crashes: bool = False,
        raise_on_close: bool = False,
    ):
        self.screenshot_payload = screenshot_payload
        self.log_slices = list(log_slices or [])
        self.crashes = list(crashes or [])
        self.raise_on_activate = raise_on_activate
        self.raise_on_screenshot = raise_on_screenshot
        self.raise_on_log = raise_on_log
        self.raise_on_crashes = raise_on_crashes
        self.raise_on_close = raise_on_close
        self.activated_steps: list[str] = []
        self.closed = False

    def activate_step(self, step_name: str) -> None:
        if self.raise_on_activate == step_name:
            raise ios_mod.IosDriverError(f"stub: activate_step({step_name}) failed")
        self.activated_steps.append(step_name)

    def screenshot(self) -> bytes:
        if self.raise_on_screenshot:
            raise ios_mod.IosDriverError("stub: screenshot failed")
        return self.screenshot_payload

    def drain_log_slice(self) -> bytes:
        if self.raise_on_log:
            raise ios_mod.IosDriverError("stub: drain_log_slice failed")
        if not self.log_slices:
            return b""
        return self.log_slices.pop(0)

    def drain_crash_reports(self) -> list[tuple[str, bytes]]:
        if self.raise_on_crashes:
            raise ios_mod.IosDriverError("stub: drain_crash_reports failed")
        return list(self.crashes)

    def close(self) -> None:
        if self.raise_on_close:
            raise ios_mod.IosDriverError("stub: close failed")
        self.closed = True


class _StubDriver:
    name = "stub-ios-driver"

    def __init__(
        self,
        session: _StubSession | None = None,
        *,
        raise_on_open: ios_mod.IosDriverError | None = None,
    ):
        self.session = session
        self.raise_on_open = raise_on_open
        self.opens: list[dict] = []

    def open_session(
        self,
        *,
        simulator,
        scheme,
        app_bundle_id,
        session_config,
    ):
        self.opens.append(
            {
                "simulator": simulator,
                "scheme": scheme,
                "app_bundle_id": app_bundle_id,
                "step_count": len(session_config.journey_steps),
            }
        )
        if self.raise_on_open is not None:
            raise self.raise_on_open
        return self.session


def _fixed_clock():
    return datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)


def _load_fixture(name: str) -> bytes:
    return (_FIXTURE_DIR / name).read_bytes()


# ──────────────────────────  happy path  ──────────────────────────


class TestHappyPath:
    def test_per_step_screenshot_and_log_artifacts_written(self, plan_dir):
        session = _StubSession(
            screenshot_payload=_load_fixture("sample-screenshot.png"),
            log_slices=[
                _load_fixture("sample-simulator.log"),
                b"step2 log slice\n",
            ],
        )
        driver = _StubDriver(session=session)
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)

        config = ios_mod.IosSessionConfig(
            journey_steps=[
                ios_mod.IosJourneyStep(name="launch"),
                ios_mod.IosJourneyStep(name="closet"),
            ],
            capture_simulator_log=True,
            capture_crash_reports=False,
        )
        refs = collector.collect(
            "fixture-journey",
            simulator="iPhone 15",
            scheme="SampleApp",
            app_bundle_id="com.example.sample",
            session_config=config,
        )

        # 2 steps × (screenshot + log) = 4 refs.
        assert len(refs) == 4
        kinds = [r.type.value for r in refs]
        assert kinds.count("screenshot") == 2
        assert kinds.count("log") == 2

        # All artifacts physically exist + are uri-relative to plan_dir.
        for ref in refs:
            assert (plan_dir / ref.uri).is_file()
            assert ref.hash.startswith("sha256:")
            assert ref.captured_by == "stub-ios-driver"
            assert ref.captured_at == _fixed_clock()

        # Stub session saw both steps activated.
        assert session.activated_steps == ["launch", "closet"]
        assert session.closed is True

    def test_evidence_path_under_post_impl_ios_journey(self, plan_dir):
        session = _StubSession(screenshot_payload=b"png-bytes")
        driver = _StubDriver(session=session)
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="home")],
            capture_simulator_log=False,
            capture_crash_reports=False,
        )
        refs = collector.collect(
            "ios-onboarding",
            simulator="iPhone 15",
            session_config=config,
        )
        assert len(refs) == 1
        assert refs[0].uri.startswith("evidence/goal-governance/post_impl/ios/ios-onboarding/")
        assert refs[0].uri.endswith("screenshot-home.png")

    def test_crash_reports_drained_at_session_end(self, plan_dir):
        crash_bytes = _load_fixture("sample-crash.crash")
        session = _StubSession(
            screenshot_payload=b"png",
            log_slices=[b"log1\n"],
            crashes=[("SampleApp_2026-05-06.crash", crash_bytes)],
        )
        driver = _StubDriver(session=session)
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="launch")],
            capture_simulator_log=True,
            capture_crash_reports=True,
        )
        refs = collector.collect(
            "with-crash",
            simulator="iPhone 15",
            session_config=config,
        )
        # screenshot + log + crash = 3.
        assert len(refs) == 3
        crash_refs = [
            r
            for r in refs
            if r.uri.startswith("evidence/goal-governance/post_impl/ios/with-crash/crash-")
        ]
        assert len(crash_refs) == 1
        crash_ref = crash_refs[0]
        assert crash_ref.type.value == "log"
        # Filename derives from the crash report name (sanitized).
        assert "SampleApp_2026-05-06.crash" in crash_ref.uri
        assert (plan_dir / crash_ref.uri).read_bytes() == crash_bytes

    def test_skip_capture_simulator_log_omits_log_artifacts(self, plan_dir):
        session = _StubSession(screenshot_payload=b"png")
        driver = _StubDriver(session=session)
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="login")],
            capture_simulator_log=False,
            capture_crash_reports=False,
        )
        refs = collector.collect("no-log", simulator="iPhone 15", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "screenshot"


# ──────────────────────────  config layering (D015)  ──────────────────────────


class TestConfigLayering:
    def test_per_call_simulator_overrides_project_config(self, plan_dir, monkeypatch):
        # Walk-up project-root resolution: register plan_dir's parent.
        proj_root = plan_dir.parent
        from dontpanic_orchestrate import projects_registry as pr

        pr.add_project(name="proj", path=proj_root)
        cfg_path = pc.project_config_path(proj_root)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps(
                {
                    "runtime_evidence": {
                        "ios": {
                            "scheme": "ProjectScheme",
                            "simulator": "iPhone 14 Pro",
                            "app_bundle_id": "com.project.bundle",
                        }
                    }
                }
            )
        )

        session = _StubSession(screenshot_payload=b"png")
        driver = _StubDriver(session=session)
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="x")],
            capture_simulator_log=False,
            capture_crash_reports=False,
        )
        # Per-call simulator wins; per-call scheme None falls through.
        collector.collect("j", simulator="iPhone 16", session_config=config)
        assert driver.opens[0]["simulator"] == "iPhone 16"
        assert driver.opens[0]["scheme"] == "ProjectScheme"
        assert driver.opens[0]["app_bundle_id"] == "com.project.bundle"

    def test_no_layer_set_passes_none(self, plan_dir):
        # When neither per-call nor project config is set, the driver
        # gets None and is responsible for skip-vs-default behavior.
        session = _StubSession(screenshot_payload=b"png")
        driver = _StubDriver(session=session)
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="x")],
            capture_simulator_log=False,
            capture_crash_reports=False,
        )
        collector.collect("j", session_config=config)
        assert driver.opens[0]["simulator"] is None
        assert driver.opens[0]["scheme"] is None
        assert driver.opens[0]["app_bundle_id"] is None

    def test_global_config_cannot_carry_runtime_evidence(self):
        # D015 sanity: GlobalConfig still refuses runtime_evidence, even
        # though the iOS resolver knows about per-project shape.
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            gc.GlobalConfig.model_validate(
                {"runtime_evidence": {"ios": {"simulator": "iPhone 15"}}}
            )


# ──────────────────────────  skip discipline  ──────────────────────────


class TestSkipDiscipline:
    def test_empty_journey_returns_skip_ref(self, plan_dir):
        driver = _StubDriver(session=_StubSession())
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="x")],
        )
        refs = collector.collect("", simulator="iPhone 15", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        assert "empty journey" in (refs[0].note or "")

    def test_driver_open_failure_returns_skip_ref(self, plan_dir):
        driver = _StubDriver(raise_on_open=ios_mod.IosDriverError("stub: no simulator booted"))
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="x")],
        )
        refs = collector.collect("j", simulator="iPhone 15", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        assert "driver init failed" in (refs[0].note or "")
        assert "no simulator booted" in (refs[0].note or "")

    def test_unexpected_driver_fault_returns_skip_ref(self, plan_dir):
        class _Boom(_StubDriver):
            def open_session(self, **kw):
                raise RuntimeError("non-IosDriverError fault")

        driver = _Boom()
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="x")],
        )
        refs = collector.collect("j", simulator="iPhone 15", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        assert "unexpected driver fault" in (refs[0].note or "")
        assert "RuntimeError" in (refs[0].note or "")

    def test_activate_step_failure_skips_only_that_step(self, plan_dir):
        session = _StubSession(
            screenshot_payload=b"png",
            log_slices=[b"good step log\n"],
            raise_on_activate="bad-step",
        )
        driver = _StubDriver(session=session)
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[
                ios_mod.IosJourneyStep(name="good-step"),
                ios_mod.IosJourneyStep(name="bad-step"),
            ],
            capture_simulator_log=True,
            capture_crash_reports=False,
        )
        refs = collector.collect("j", simulator="iPhone 15", session_config=config)
        # good-step → screenshot + log = 2; bad-step → 1 skip ref.
        assert len(refs) == 3
        assert sum(1 for r in refs if r.type.value == "screenshot") == 1
        assert sum(1 for r in refs if r.type.value == "log") == 2
        skip_refs = [r for r in refs if "activate_step" in (r.note or "")]
        assert len(skip_refs) == 1

    def test_screenshot_failure_writes_empty_artifact_not_raise(self, plan_dir):
        session = _StubSession(
            screenshot_payload=b"unused",
            log_slices=[b"log1\n"],
            raise_on_screenshot=True,
        )
        driver = _StubDriver(session=session)
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="x")],
            capture_simulator_log=True,
            capture_crash_reports=False,
        )
        refs = collector.collect("j", simulator="iPhone 15", session_config=config)
        # Empty screenshot artifact still emitted (typed) plus the log.
        screenshot_refs = [r for r in refs if r.type.value == "screenshot"]
        assert len(screenshot_refs) == 1
        # Empty payload — sha256 of empty bytes.
        empty_sha = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert screenshot_refs[0].hash == empty_sha

    def test_crash_drain_failure_returns_skip_ref(self, plan_dir):
        session = _StubSession(
            screenshot_payload=b"png",
            log_slices=[b"log\n"],
            raise_on_crashes=True,
        )
        driver = _StubDriver(session=session)
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="x")],
            capture_simulator_log=True,
            capture_crash_reports=True,
        )
        refs = collector.collect("j", simulator="iPhone 15", session_config=config)
        skip_refs = [r for r in refs if r.note and "crash report drain failed" in r.note]
        assert len(skip_refs) == 1

    def test_close_failure_swallowed(self, plan_dir):
        # Any IosDriverError raised by close() must NOT bubble up.
        session = _StubSession(
            screenshot_payload=b"png",
            log_slices=[b"log\n"],
            raise_on_close=True,
        )
        driver = _StubDriver(session=session)
        collector = ios_mod.IosEvidenceCollector(plan_dir, driver=driver, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="x")],
            capture_simulator_log=True,
            capture_crash_reports=False,
        )
        # Just must not raise.
        refs = collector.collect("j", simulator="iPhone 15", session_config=config)
        assert len(refs) >= 1


# ──────────────────────────  default driver behavior  ──────────────────────────


class TestDefaultSimctlDriver:
    def test_default_driver_skips_when_xcrun_missing(self, plan_dir, monkeypatch):
        # Force shutil.which to report xcrun absent regardless of host.
        monkeypatch.setattr(ios_mod.shutil, "which", lambda name: None)
        collector = ios_mod.IosEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="x")],
        )
        refs = collector.collect("j", simulator="iPhone 15", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        assert "xcrun not on PATH" in (refs[0].note or "")

    def test_default_driver_skips_when_no_simulator_specified(self, plan_dir, monkeypatch):
        monkeypatch.setattr(ios_mod.shutil, "which", lambda name: "/usr/bin/xcrun")
        collector = ios_mod.IosEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="x")],
        )
        refs = collector.collect("j", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        assert "no simulator specified" in (refs[0].note or "")

    def test_default_driver_skips_when_session_adapter_unwired(self, plan_dir, monkeypatch):
        # xcrun present, simulator named — still raises IosDriverError per
        # Plan G v1 (production wiring deferred to follow-up). Collector
        # writes the skip ref rather than raising.
        monkeypatch.setattr(ios_mod.shutil, "which", lambda name: "/usr/bin/xcrun")
        collector = ios_mod.IosEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="x")],
        )
        refs = collector.collect("j", simulator="iPhone 15", session_config=config)
        assert len(refs) == 1
        assert "session adapter not wired" in (refs[0].note or "")


# ──────────────────────────  doctor framework  ──────────────────────────


class TestDoctorRegistration:
    def test_ios_simctl_check_registered_at_import(self):
        # F006's autouse fixture in test_f006_config_setup_surface.py wipes
        # the registry between tests there. Re-call the iOS module's idempotent
        # registration so the check is present regardless of test order.
        ios_mod._register_ios_doctor_checks()
        results = doctor_registry.run_all_checks()
        assert any(r.name == "ios_simctl" for r in results)

    def test_ios_simctl_returns_warn_when_xcrun_missing(self, monkeypatch):
        monkeypatch.setattr(ios_mod.shutil, "which", lambda name: None)
        result = ios_mod._ios_simctl_check()
        assert result.status == "warn"
        assert "xcrun not on PATH" in result.detail

    def test_ios_simctl_check_never_returns_fail(self, monkeypatch):
        # Critical contract: this check must NEVER hard-fail. A project
        # not targeting iOS must not be blocked by it.
        # Sweep across the failure modes: xcrun missing, subprocess
        # error, non-zero return, all → warn.
        # Case 1: xcrun missing.
        monkeypatch.setattr(ios_mod.shutil, "which", lambda name: None)
        assert ios_mod._ios_simctl_check().status != "fail"
        # Case 2: xcrun present but probe raises.
        monkeypatch.setattr(ios_mod.shutil, "which", lambda name: "/usr/bin/xcrun")

        def _raise(*a, **kw):
            raise OSError("synthetic probe failure")

        monkeypatch.setattr(ios_mod.subprocess, "run", _raise)
        assert ios_mod._ios_simctl_check().status != "fail"


# ──────────────────────────  source-grep invariants  ──────────────────────────


class TestSourceInvariants:
    def test_no_project_name_special_cases_in_module(self):
        """D004: the iOS adapter must be project-agnostic. No spin_dine_,
        glam_, creator_hub_, etc. branching."""
        src = (HERE.parents[1] / "runtime_evidence" / "ios.py").read_text().lower()
        for needle in ("spin_dine_", "spin-dine_", "glam_", "creator_hub_"):
            assert needle not in src, (
                f"runtime_evidence/ios.py contains project-specific token {needle!r} (D004)"
            )

    def test_no_credential_storage_in_module(self):
        """D005: no new credential storage. The iOS adapter relies on
        the operator's existing Xcode runtime; no auth tokens / keys /
        bearer prefixes appear in source."""
        src = (HERE.parents[1] / "runtime_evidence" / "ios.py").read_text()
        forbidden = (
            re.compile(r"password\s*=\s*['\"]", re.IGNORECASE),
            re.compile(r"\bbearer\s+[a-z0-9._\-]+", re.IGNORECASE),
            re.compile(r"api_key\s*=\s*['\"]", re.IGNORECASE),
        )
        for rx in forbidden:
            assert not rx.search(src), (
                f"runtime_evidence/ios.py source contains credential-like literal "
                f"matching {rx.pattern!r} (D005 / D014)"
            )

    def test_evidence_path_uses_ios_subdir(self):
        """D003: artifacts under post_impl/ios/<journey>. Greppable."""
        src = (HERE.parents[1] / "runtime_evidence" / "ios.py").read_text()
        assert 'goal_governance_evidence_path(self._plan_dir, "post_impl", f"ios/{journey}")' in src
