"""Plan G F002 (G2) — iOS runtime evidence capture.

Capture-only adapter (D002). Per step: screenshot + simulator log
slice. Per session: crash reports (drained at end). Drives capture via
``xcrun simctl`` when the default driver is in play; tests + operators
pass a custom ``IosDriver`` to swap in.

Public surface:

    IosEvidenceCollector(plan_dir, driver=None, clock=None)
        .collect(journey, *, simulator=None, scheme=None,
                 app_bundle_id=None, session_config) -> list[EvidenceRef]

    IosJourneyStep(name: str)
    IosSessionConfig(...)
    IosDriver / IosSession (Protocols)
    IosDriverError (raised by drivers; wrapped into skip by the collector)

**Capture-only (D002):** no audit / scoring / pass-fail. EvidenceRef
artifacts are the contract; F2 consumes them later.

**Project-agnostic (D004):** no project-name special cases. The scheme
/ simulator / app_bundle_id are operator-supplied per call OR pulled
from per-project ``runtime_evidence.ios`` config (D015 — global config
never names a default device). No global tier.

**No new credential storage (D005):** simctl uses the operator's
existing Xcode runtime; no auth tokens or service accounts.

**Skip discipline:** when ``xcrun`` / ``simctl`` isn't on PATH, or the
simulator isn't bootable, or any per-step capture fails, the collector
writes a typed ``EvidenceRef(type='log', note='skipped: ...')`` rather
than raising. Callers always get a list back.

The doctor check ``ios_simctl`` (registered at module import via
:mod:`config.doctor_registry`) reports ``warn`` — not ``fail`` —
when iOS tooling is unavailable. Projects that don't target iOS see
the warn but aren't blocked from dispatch.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from dontpanic_orchestrate.config import (
    doctor_registry,
)
from dontpanic_orchestrate.config import (
    resolvers as _resolvers,
)
from dontpanic_orchestrate.nested_orchestration import goal_governance_evidence_path

_SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[3] / "claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[3] / ".claude" / "shared" / "schemas" / "v1.0",
    Path(__file__).resolve().parents[4] / "agent-conventions" / "schemas" / "v1.0",
]
for _candidate in _SCHEMA_CANDIDATES:
    if (_candidate / "models").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from models.features_model import EvidenceRef  # noqa: E402
from models.features_model import Type as EvidenceType  # noqa: E402

# ──────────────────────────────  config + driver shapes  ──────────────────────────────


@dataclass(frozen=True)
class IosJourneyStep:
    """One waypoint in an iOS journey. The collector relies on the
    driver's ``activate_step`` hook to bring the named step to focus
    (default: no-op — operator's external test driver does the UI
    work; the collector just captures whatever's on screen)."""

    name: str


@dataclass
class IosSessionConfig:
    """Operator-supplied iOS session configuration."""

    journey_steps: list[IosJourneyStep]
    capture_simulator_log: bool = True
    """Per-step simulator log slice. Drained between steps."""

    capture_crash_reports: bool = True
    """Once-per-session crash report drain at session close."""

    driver_options: dict[str, Any] = field(default_factory=dict)
    """Driver-specific options (boot timeout, log predicate, etc.)."""


class IosDriverError(Exception):
    """Raised by drivers when a session can't be opened or a step
    can't capture. The collector wraps this into a skip-reason
    EvidenceRef so callers never see the raw exception."""


class IosSession(Protocol):
    """Contract a driver session must satisfy. Per-step the collector
    calls activate_step → screenshot → drain_log_slice. At session
    close it calls drain_crash_reports → close."""

    def activate_step(self, step_name: str) -> None: ...
    def screenshot(self) -> bytes: ...
    def drain_log_slice(self) -> bytes: ...
    def drain_crash_reports(self) -> list[tuple[str, bytes]]: ...
    def close(self) -> None: ...


class IosDriver(Protocol):
    """Pluggable driver. Default is :class:`_SimctlDriver` (xcrun
    simctl-backed); tests + operators pass any callable object
    satisfying this protocol."""

    name: str

    def open_session(
        self,
        *,
        simulator: str | None,
        scheme: str | None,
        app_bundle_id: str | None,
        session_config: IosSessionConfig,
    ) -> IosSession: ...


# ──────────────────────────────  simctl default driver  ──────────────────────────────


class _SimctlDriver:
    """Default driver — wraps ``xcrun simctl`` for screenshot / log /
    crash capture against an operator-named simulator. Production
    wiring (booted-device discovery, log predicate hookup, crash log
    enumeration) is left as a follow-up; v1 raises
    :class:`IosDriverError` so the collector emits a skip when no
    explicit driver is supplied. Operators / tests pass a custom
    driver via ``IosEvidenceCollector(driver=...)``.

    The lazy ``xcrun`` discovery still happens here so the doctor
    check can probe simctl availability without forcing the full
    session-open path.
    """

    name = "simctl-driver"

    def open_session(
        self,
        *,
        simulator: str | None,
        scheme: str | None,
        app_bundle_id: str | None,
        session_config: IosSessionConfig,
    ) -> IosSession:
        if shutil.which("xcrun") is None:
            raise IosDriverError(
                "xcrun not on PATH. Install Xcode + Command Line Tools "
                "to enable the default iOS driver, or pass an explicit "
                "driver to IosEvidenceCollector."
            )
        if not simulator:
            raise IosDriverError(
                "no simulator specified. Set runtime_evidence.ios.simulator "
                "in per-project config (`dontpanic project config set "
                "runtime_evidence.ios.simulator <name>`) or pass per-call."
            )
        # Production simctl session adapter is left as a follow-up. The
        # fixture-driven swap seam (operator-supplied IosDriver) is the
        # supported path during Plan G v1.
        raise IosDriverError(
            "simctl session adapter not wired in Plan G v1. Pass an "
            "explicit driver to IosEvidenceCollector for now; production "
            "simctl wiring lands in a follow-up plan."
        )


# ──────────────────────────────  collector  ──────────────────────────────


_DEFAULT_CLOCK = lambda: datetime.now(timezone.utc)  # noqa: E731


class IosEvidenceCollector:
    """Goal Governance V1 G2 — iOS runtime evidence capture.

    Per Plan G D002 (capture-only) + D003 (evidence path) + D004
    (project-agnostic) + D005 (no credential storage) + D015
    (runtime_evidence is project-scoped). Honors per-call overrides
    and falls through to per-project ``runtime_evidence.ios`` config
    via :func:`config.resolvers.resolve_runtime_evidence`.
    """

    def __init__(
        self,
        plan_dir: Path,
        driver: IosDriver | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plan_dir = Path(plan_dir).resolve()
        self._driver: IosDriver = driver if driver is not None else _SimctlDriver()
        self._clock = clock if clock is not None else _DEFAULT_CLOCK

    def collect(
        self,
        journey: str,
        *,
        simulator: str | None = None,
        scheme: str | None = None,
        app_bundle_id: str | None = None,
        session_config: IosSessionConfig,
    ) -> list[EvidenceRef]:
        """Capture iOS evidence for one journey. Returns a list of
        ``EvidenceRef`` instances pointing at artifacts written under
        ``evidence/goal-governance/post_impl/ios/<journey>/``.

        Per-call kwargs (``simulator``, ``scheme``, ``app_bundle_id``)
        win over per-project ``runtime_evidence.ios`` config which
        wins over ``None`` (no global tier per D015). Resolution
        delegated to :func:`config.resolvers.resolve_runtime_evidence`.

        Never raises — driver init failures + per-step failures are
        recorded as skip-reason EvidenceRefs so callers always get a
        list back.
        """
        if not journey:
            return [
                self._write_skip(
                    "_no-journey",
                    "skipped: empty journey identifier passed to collector",
                )
            ]

        # Resolve config layers: per-call > project > none.
        per_call: dict[str, Any] = {}
        if simulator is not None:
            per_call["simulator"] = simulator
        if scheme is not None:
            per_call["scheme"] = scheme
        if app_bundle_id is not None:
            per_call["app_bundle_id"] = app_bundle_id
        resolved = _resolvers.resolve_runtime_evidence(
            self._plan_dir, "ios", per_call=per_call or None
        )
        eff_simulator = resolved.get("simulator")
        eff_scheme = resolved.get("scheme")
        eff_app_bundle_id = resolved.get("app_bundle_id")

        try:
            session = self._driver.open_session(
                simulator=eff_simulator,
                scheme=eff_scheme,
                app_bundle_id=eff_app_bundle_id,
                session_config=session_config,
            )
        except IosDriverError as exc:
            return [self._write_skip(journey, f"skipped: driver init failed: {exc}")]
        except Exception as exc:  # noqa: BLE001 — translate any driver fault to skip
            return [
                self._write_skip(
                    journey,
                    f"skipped: unexpected driver fault: {type(exc).__name__}: {exc}",
                )
            ]

        refs: list[EvidenceRef] = []
        try:
            for step in session_config.journey_steps:
                refs.extend(self._capture_step(session, journey, step, session_config))
            refs.extend(self._capture_crash_reports(session, journey, session_config))
        finally:
            self._safe_close(session)

        return refs

    # ──────────────────────────────  per-step capture  ──────────────────────────────

    def _capture_step(
        self,
        session: IosSession,
        journey: str,
        step: IosJourneyStep,
        session_config: IosSessionConfig,
    ) -> list[EvidenceRef]:
        captured: list[EvidenceRef] = []
        try:
            session.activate_step(step.name)
        except IosDriverError as exc:
            captured.append(
                self._write_skip(
                    journey,
                    f"skipped: activate_step {step.name!r} failed: {exc}",
                    step_name=step.name,
                )
            )
            return captured

        # Screenshot (binary) — type=screenshot.
        captured.append(
            self._write_artifact(
                journey,
                f"screenshot-{step.name}.png",
                self._safe_bytes(session.screenshot, journey, step.name, "screenshot"),
                EvidenceType.screenshot,
                note=f"step={step.name}",
            )
        )
        # Log slice (textual log) — type=log. Per-step.
        if session_config.capture_simulator_log:
            log_bytes = self._safe_bytes(session.drain_log_slice, journey, step.name, "log")
            captured.append(
                self._write_artifact(
                    journey,
                    f"log-{step.name}.log",
                    log_bytes,
                    EvidenceType.log,
                    note=f"step={step.name}; bytes={len(log_bytes)}",
                )
            )
        return captured

    def _capture_crash_reports(
        self,
        session: IosSession,
        journey: str,
        session_config: IosSessionConfig,
    ) -> list[EvidenceRef]:
        if not session_config.capture_crash_reports:
            return []
        try:
            crashes = session.drain_crash_reports()
        except IosDriverError as exc:
            return [
                self._write_skip(
                    journey,
                    f"skipped: crash report drain failed: {exc}",
                    step_name="crashes",
                )
            ]
        out: list[EvidenceRef] = []
        for name, payload in crashes:
            safe_name = name.replace("/", "_").replace("..", "_")
            out.append(
                self._write_artifact(
                    journey,
                    f"crash-{safe_name}",
                    payload if isinstance(payload, bytes) else bytes(payload),
                    EvidenceType.log,
                    note=f"crash={name}",
                )
            )
        return out

    # ──────────────────────────────  artifact + skip writers  ──────────────────────────────

    def _journey_dir(self, journey: str) -> Path:
        return goal_governance_evidence_path(self._plan_dir, "post_impl", f"ios/{journey}")

    def _write_artifact(
        self,
        journey: str,
        filename: str,
        payload: bytes,
        evidence_type: EvidenceType,
        *,
        note: str | None = None,
    ) -> EvidenceRef:
        out_path = self._journey_dir(journey) / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        rel_uri = str(out_path.relative_to(self._plan_dir))
        return EvidenceRef(
            type=evidence_type,
            uri=rel_uri,
            hash=f"sha256:{digest}",
            captured_at=self._clock(),
            captured_by=self._driver.name,
            note=note,
        )

    def _write_skip(
        self,
        journey: str,
        reason: str,
        *,
        step_name: str | None = None,
    ) -> EvidenceRef:
        suffix = f"-{step_name}" if step_name else ""
        filename = f"skip-reason{suffix}.txt"
        body = (
            f"reason: {reason}\n"
            f"driver: {self._driver.name}\n"
            f"journey: {journey}\n"
            f"step: {step_name or '(n/a)'}\n"
        )
        return self._write_artifact(
            journey,
            filename,
            body.encode("utf-8"),
            EvidenceType.log,
            note=reason,
        )

    # ──────────────────────────────  safe driver call wrappers  ──────────────────────────────

    def _safe_bytes(
        self,
        fn: Callable[[], bytes],
        journey: str,
        step: str,
        kind: str,
    ) -> bytes:
        try:
            value = fn()
        except IosDriverError as exc:
            self._write_skip(
                journey,
                f"skipped: {kind} capture for step {step!r} failed: {exc}",
                step_name=f"{step}-{kind}",
            )
            return b""
        return value if isinstance(value, bytes) else bytes(value)

    def _safe_close(self, session: IosSession) -> None:
        try:
            session.close()
        except IosDriverError:
            return


# ──────────────────────────────  doctor check  ──────────────────────────────


def _ios_simctl_check() -> doctor_registry.DoctorResult:
    """Soft availability probe — warns when xcrun / simctl isn't on
    PATH. Per the F006/G2 directive: this MUST be a warn, not a fail,
    so projects that don't target iOS aren't blocked.
    """
    if shutil.which("xcrun") is None:
        return doctor_registry.DoctorResult(
            name="ios_simctl",
            status="warn",
            detail="xcrun not on PATH; iOS evidence capture unavailable",
        )
    try:
        result = subprocess.run(
            ["xcrun", "simctl", "help"],  # noqa: S607  # PATH-relative xcrun invocation per D001
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return doctor_registry.DoctorResult(
            name="ios_simctl",
            status="warn",
            detail=f"xcrun simctl probe failed: {type(exc).__name__}: {exc}",
        )
    if result.returncode != 0:
        return doctor_registry.DoctorResult(
            name="ios_simctl",
            status="warn",
            detail=f"xcrun simctl returned non-zero ({result.returncode})",
        )
    return doctor_registry.DoctorResult(
        name="ios_simctl",
        status="pass",
        detail="xcrun simctl available",
    )


def _register_ios_doctor_checks() -> None:
    """Idempotent — also called from tests after registry resets so the
    iOS check survives F006's per-test ``_reset_for_tests`` autouse."""
    doctor_registry.register_doctor_check("ios_simctl", _ios_simctl_check)


_register_ios_doctor_checks()


__all__ = [
    "IosDriver",
    "IosDriverError",
    "IosEvidenceCollector",
    "IosJourneyStep",
    "IosSession",
    "IosSessionConfig",
]
