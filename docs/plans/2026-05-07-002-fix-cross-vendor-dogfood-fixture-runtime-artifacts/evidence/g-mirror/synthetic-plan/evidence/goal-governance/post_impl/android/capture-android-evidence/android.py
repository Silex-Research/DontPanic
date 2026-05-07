"""Plan G F003 (G3) — Android runtime evidence capture.

Capture-only adapter (D002). Two operator-selectable modes (D009 —
DontPanic does NOT own Android test orchestration in v1):

- ``passive_observe``: live ``adb``-driven capture against an existing
  device / emulator session. Per step: screenshot + logcat slice. Per
  session: tombstones + ANR reports.
- ``post_hoc_ingest``: read existing Gradle / Espresso / Maestro / CI
  output directory and wrap discovered artifacts as ``EvidenceRef``.
  No live device required.

Public surface:

    AndroidEvidenceCollector(plan_dir, driver=None, clock=None)
        .collect(journey, *, package=None, adb_device_serial=None,
                 session_config) -> list[EvidenceRef]

    AndroidJourneyStep(name: str)
    AndroidSessionConfig(mode, ...)
    AndroidMode (Literal: 'passive_observe' | 'post_hoc_ingest')
    AndroidDriver / AndroidSession (Protocols, passive mode only)
    AndroidDriverError (raised by drivers; wrapped into skip)

**Capture-only (D002):** no audit / scoring. EvidenceRef artifacts are
the contract; F2 consumes them later.

**No test orchestration (D009):** Both modes are *capture* only. We do
NOT build, install, instrument, or invoke an Android test runner.
Operator's existing tooling (Gradle/Espresso/Maestro/CI) does the test
work; we record what's already on the device or in their artifact dir.

**Project-agnostic (D004):** no project-name special cases. The
``package`` / ``adb_device_serial`` / ``artifact_dir`` are operator-
supplied per call OR pulled from per-project ``runtime_evidence.android``
config (D015 — global config never names a default device or artifact
path). No global tier.

**No new credential storage (D005):** adb uses the operator's existing
device pairing; no auth tokens or service accounts.

**Skip discipline:** when ``adb`` isn't on PATH, no device is reachable,
or the operator-supplied ``artifact_dir`` doesn't exist, the collector
writes a typed ``EvidenceRef(type='log', note='skipped: ...')`` rather
than raising. Callers always get a list back.

The doctor check ``android_adb`` (registered at module import via
:mod:`config.doctor_registry`) reports ``warn`` — not ``fail`` — when
adb is missing. Projects that don't target Android see the warn but
aren't blocked from dispatch.
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
from typing import Any, Literal, Protocol

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


AndroidMode = Literal["passive_observe", "post_hoc_ingest"]


@dataclass(frozen=True)
class AndroidJourneyStep:
    """One waypoint in an Android journey (passive_observe mode only).
    The collector relies on the driver's ``activate_step`` hook to bring
    the named step to focus; default is no-op (operator's external test
    driver does the UI work)."""

    name: str


@dataclass
class AndroidSessionConfig:
    """Operator-supplied Android session configuration.

    ``mode`` discriminates between the two capture surfaces:

    - ``passive_observe``: driver is consulted; ``journey_steps`` is
      iterated; ``artifact_dir`` is ignored.
    - ``post_hoc_ingest``: ``artifact_dir`` is scanned; driver is not
      called; ``journey_steps`` is ignored.
    """

    mode: AndroidMode
    journey_steps: list[AndroidJourneyStep] = field(default_factory=list)
    artifact_dir: Path | None = None
    """Required for ``post_hoc_ingest``. Ignored in ``passive_observe``."""

    capture_logcat: bool = True
    capture_tombstones: bool = True
    capture_anr: bool = True

    driver_options: dict[str, Any] = field(default_factory=dict)
    """Driver-specific options (boot timeout, logcat predicate, etc.)."""


class AndroidDriverError(Exception):
    """Raised by drivers when a session can't be opened or a step
    can't capture. The collector wraps this into a skip-reason
    EvidenceRef so callers never see the raw exception."""


class AndroidSession(Protocol):
    """Contract a driver session must satisfy (passive_observe mode).
    Per-step: activate_step → screenshot → drain_logcat_slice. At
    session close: drain_tombstones → drain_anr_reports → close."""

    def activate_step(self, step_name: str) -> None: ...
    def screenshot(self) -> bytes: ...
    def drain_logcat_slice(self) -> bytes: ...
    def drain_tombstones(self) -> list[tuple[str, bytes]]: ...
    def drain_anr_reports(self) -> list[tuple[str, bytes]]: ...
    def close(self) -> None: ...


class AndroidDriver(Protocol):
    """Pluggable driver. Default is :class:`_AdbDriver` (adb-backed);
    tests + operators pass any callable object satisfying this
    protocol. Only consulted in ``passive_observe`` mode."""

    name: str

    def open_session(
        self,
        *,
        package: str | None,
        adb_device_serial: str | None,
        session_config: AndroidSessionConfig,
    ) -> AndroidSession: ...


# ──────────────────────────────  adb default driver  ──────────────────────────────


class _AdbDriver:
    """Default driver — wraps ``adb`` for screenshot / logcat /
    tombstone / ANR capture against an operator-named device.
    Production wiring (``adb shell screencap``, ``adb logcat -d``,
    tombstone enumeration via ``adb pull /data/tombstones``, ANR pull
    from ``/data/anr``) is left as a follow-up; v1 raises
    :class:`AndroidDriverError` so the collector emits a skip when no
    explicit driver is supplied. Operators / tests pass a custom
    driver via ``AndroidEvidenceCollector(driver=...)``.

    The lazy ``adb`` discovery still happens here so the doctor check
    can probe adb availability without forcing the full session-open
    path.
    """

    name = "adb-driver"

    def open_session(
        self,
        *,
        package: str | None,
        adb_device_serial: str | None,
        session_config: AndroidSessionConfig,
    ) -> AndroidSession:
        if shutil.which("adb") is None:
            raise AndroidDriverError(
                "adb not on PATH. Install Android platform-tools to "
                "enable the default Android driver, or pass an explicit "
                "driver to AndroidEvidenceCollector."
            )
        # Production adb session adapter is left as a follow-up. The
        # fixture-driven swap seam (operator-supplied AndroidDriver) is
        # the supported path during Plan G v1.
        raise AndroidDriverError(
            "adb session adapter not wired in Plan G v1. Pass an explicit "
            "driver to AndroidEvidenceCollector for now; production adb "
            "wiring lands in a follow-up plan."
        )


# ──────────────────────────────  post-hoc artifact ingestion  ──────────────────────────────

# Greppable artifact-pattern map (D004 — generic, not project-specific).
# Each tuple: (subdirectory glob, EvidenceRef Type). Operators with
# unconventional layouts can ingest manually; F006/G3 v1 ships the
# common Gradle / Espresso / Maestro / CI shapes.
_ARTIFACT_PATTERNS: tuple[tuple[str, EvidenceType], ...] = (
    ("screenshots/*.png", EvidenceType.screenshot),
    ("screenshots/*.jpg", EvidenceType.screenshot),
    ("screenshots/*.jpeg", EvidenceType.screenshot),
    ("logcat/*.txt", EvidenceType.log),
    ("logcat/*.log", EvidenceType.log),
    ("logs/*.log", EvidenceType.log),
    ("tombstones/*", EvidenceType.log),
    ("anr/*", EvidenceType.log),
    ("test-results/*.xml", EvidenceType.test_output),
    ("test-results/**/*.xml", EvidenceType.test_output),
)


def _classify_artifact(path: Path, root: Path) -> EvidenceType | None:
    """Return the EvidenceType for ``path`` if it matches a known
    pattern relative to ``root``. ``None`` when the file lives in a
    subdir we don't recognize — the collector skips unrecognized
    files rather than guessing."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    rel_str = str(rel).replace("\\", "/")
    for glob, kind in _ARTIFACT_PATTERNS:
        if rel.match(glob.replace("**/", "*/")) or _glob_match(rel_str, glob):
            return kind
    return None


def _glob_match(rel: str, pattern: str) -> bool:
    """Robust glob match supporting ``**`` recursion. ``Path.match``
    doesn't handle ``**`` in older Python versions cleanly, so we fall
    back to a simple prefix split."""
    if "**" in pattern:
        head, tail = pattern.split("**", 1)
        head = head.rstrip("/")
        tail = tail.lstrip("/")
        if head and not rel.startswith(head):
            return False
        if tail and not rel.endswith(tail.lstrip("*").lstrip(".")):
            # Best-effort: just ensure the file extension portion matches.
            from fnmatch import fnmatch

            return fnmatch(rel, pattern)
        return True
    from fnmatch import fnmatch

    return fnmatch(rel, pattern)


# ──────────────────────────────  collector  ──────────────────────────────


_DEFAULT_CLOCK = lambda: datetime.now(timezone.utc)  # noqa: E731


class AndroidEvidenceCollector:
    """Goal Governance V1 G3 — Android runtime evidence capture.

    Per Plan G D002 (capture-only) + D003 (evidence path) + D004
    (project-agnostic) + D005 (no credential storage) + D009 (no test
    orchestration in v1) + D015 (runtime_evidence is project-scoped).
    Honors per-call overrides and falls through to per-project
    ``runtime_evidence.android`` config via
    :func:`config.resolvers.resolve_runtime_evidence`.
    """

    def __init__(
        self,
        plan_dir: Path,
        driver: AndroidDriver | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plan_dir = Path(plan_dir).resolve()
        self._driver: AndroidDriver = driver if driver is not None else _AdbDriver()
        self._clock = clock if clock is not None else _DEFAULT_CLOCK

    def collect(
        self,
        journey: str,
        *,
        package: str | None = None,
        adb_device_serial: str | None = None,
        artifact_dir: Path | None = None,
        session_config: AndroidSessionConfig,
    ) -> list[EvidenceRef]:
        """Capture Android evidence for one journey. Returns a list of
        ``EvidenceRef`` instances pointing at artifacts written under
        ``evidence/goal-governance/post_impl/android/<journey>/``.

        Per-call kwargs (``package``, ``adb_device_serial``,
        ``artifact_dir``) win over per-project
        ``runtime_evidence.android`` config which wins over None
        (no global tier per D015).

        Mode discrimination via ``session_config.mode``:
        - ``passive_observe`` consults the driver.
        - ``post_hoc_ingest`` consults ``artifact_dir`` and never
          touches the driver.

        Never raises — driver init failures + per-step failures + bad
        artifact dirs are recorded as skip-reason EvidenceRefs so
        callers always get a list back.
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
        if package is not None:
            per_call["package"] = package
        if adb_device_serial is not None:
            per_call["adb_device_serial"] = adb_device_serial
        if artifact_dir is not None:
            per_call["artifact_dir"] = str(artifact_dir)
        resolved = _resolvers.resolve_runtime_evidence(
            self._plan_dir, "android", per_call=per_call or None
        )
        eff_package = resolved.get("package")
        eff_serial = resolved.get("adb_device_serial")
        eff_artifact_dir = resolved.get("artifact_dir")

        if session_config.mode == "passive_observe":
            return self._collect_passive(
                journey,
                package=eff_package,
                adb_device_serial=eff_serial,
                session_config=session_config,
            )
        if session_config.mode == "post_hoc_ingest":
            ad = (
                Path(eff_artifact_dir)
                if eff_artifact_dir is not None
                else session_config.artifact_dir
            )
            return self._collect_post_hoc(journey, ad)

        return [
            self._write_skip(
                journey,
                f"skipped: unknown mode {session_config.mode!r}",
            )
        ]

    # ──────────────────────────────  passive_observe  ──────────────────────────────

    def _collect_passive(
        self,
        journey: str,
        *,
        package: str | None,
        adb_device_serial: str | None,
        session_config: AndroidSessionConfig,
    ) -> list[EvidenceRef]:
        try:
            session = self._driver.open_session(
                package=package,
                adb_device_serial=adb_device_serial,
                session_config=session_config,
            )
        except AndroidDriverError as exc:
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
            refs.extend(self._capture_session_diagnostics(session, journey, session_config))
        finally:
            self._safe_close(session)
        return refs

    def _capture_step(
        self,
        session: AndroidSession,
        journey: str,
        step: AndroidJourneyStep,
        session_config: AndroidSessionConfig,
    ) -> list[EvidenceRef]:
        captured: list[EvidenceRef] = []
        try:
            session.activate_step(step.name)
        except AndroidDriverError as exc:
            captured.append(
                self._write_skip(
                    journey,
                    f"skipped: activate_step {step.name!r} failed: {exc}",
                    step_name=step.name,
                )
            )
            return captured

        captured.append(
            self._write_artifact(
                journey,
                f"screenshot-{step.name}.png",
                self._safe_bytes(session.screenshot, journey, step.name, "screenshot"),
                EvidenceType.screenshot,
                note=f"step={step.name}",
            )
        )
        if session_config.capture_logcat:
            log_bytes = self._safe_bytes(session.drain_logcat_slice, journey, step.name, "logcat")
            captured.append(
                self._write_artifact(
                    journey,
                    f"logcat-{step.name}.log",
                    log_bytes,
                    EvidenceType.log,
                    note=f"step={step.name}; bytes={len(log_bytes)}",
                )
            )
        return captured

    def _capture_session_diagnostics(
        self,
        session: AndroidSession,
        journey: str,
        session_config: AndroidSessionConfig,
    ) -> list[EvidenceRef]:
        out: list[EvidenceRef] = []
        if session_config.capture_tombstones:
            try:
                tombstones = session.drain_tombstones()
            except AndroidDriverError as exc:
                out.append(
                    self._write_skip(
                        journey,
                        f"skipped: tombstone drain failed: {exc}",
                        step_name="tombstones",
                    )
                )
                tombstones = []
            for name, payload in tombstones:
                safe_name = name.replace("/", "_").replace("..", "_")
                out.append(
                    self._write_artifact(
                        journey,
                        f"tombstone-{safe_name}",
                        payload if isinstance(payload, bytes) else bytes(payload),
                        EvidenceType.log,
                        note=f"tombstone={name}",
                    )
                )

        if session_config.capture_anr:
            try:
                anrs = session.drain_anr_reports()
            except AndroidDriverError as exc:
                out.append(
                    self._write_skip(
                        journey,
                        f"skipped: anr drain failed: {exc}",
                        step_name="anr",
                    )
                )
                anrs = []
            for name, payload in anrs:
                safe_name = name.replace("/", "_").replace("..", "_")
                out.append(
                    self._write_artifact(
                        journey,
                        f"anr-{safe_name}",
                        payload if isinstance(payload, bytes) else bytes(payload),
                        EvidenceType.log,
                        note=f"anr={name}",
                    )
                )
        return out

    # ──────────────────────────────  post_hoc_ingest  ──────────────────────────────

    def _collect_post_hoc(
        self,
        journey: str,
        artifact_dir: Path | None,
    ) -> list[EvidenceRef]:
        if artifact_dir is None:
            return [
                self._write_skip(
                    journey,
                    "skipped: post_hoc_ingest requires artifact_dir; supply via "
                    "per-call kwarg or runtime_evidence.android.artifact_dir",
                )
            ]
        artifact_dir = Path(artifact_dir).expanduser().resolve()
        if not artifact_dir.is_dir():
            return [
                self._write_skip(
                    journey,
                    f"skipped: artifact_dir {artifact_dir} does not exist or is not a directory",
                )
            ]

        refs: list[EvidenceRef] = []
        recognized = 0
        for path in sorted(artifact_dir.rglob("*")):
            if not path.is_file():
                continue
            kind = _classify_artifact(path, artifact_dir)
            if kind is None:
                continue
            recognized += 1
            try:
                payload = path.read_bytes()
            except OSError as exc:
                refs.append(
                    self._write_skip(
                        journey,
                        f"skipped: failed to read {path}: {exc}",
                        step_name=path.stem,
                    )
                )
                continue
            rel = path.relative_to(artifact_dir)
            safe = str(rel).replace("/", "_").replace("\\", "_")
            refs.append(
                self._write_artifact(
                    journey,
                    f"ingest-{safe}",
                    payload,
                    kind,
                    note=f"post_hoc_ingest src={rel}",
                )
            )

        if recognized == 0:
            refs.append(
                self._write_skip(
                    journey,
                    f"skipped: no recognized artifacts in {artifact_dir} "
                    f"(looked for screenshots/, logcat/, logs/, tombstones/, anr/, test-results/)",
                )
            )
        return refs

    # ──────────────────────────────  artifact + skip writers  ──────────────────────────────

    def _journey_dir(self, journey: str) -> Path:
        return goal_governance_evidence_path(self._plan_dir, "post_impl", f"android/{journey}")

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
        except AndroidDriverError as exc:
            self._write_skip(
                journey,
                f"skipped: {kind} capture for step {step!r} failed: {exc}",
                step_name=f"{step}-{kind}",
            )
            return b""
        return value if isinstance(value, bytes) else bytes(value)

    def _safe_close(self, session: AndroidSession) -> None:
        try:
            session.close()
        except AndroidDriverError:
            return


# ──────────────────────────────  doctor check  ──────────────────────────────


def _android_adb_check() -> doctor_registry.DoctorResult:
    """Soft availability probe — warns when adb isn't on PATH OR no
    devices are reachable. Per the F006/G3 directive: this MUST be a
    warn, not a fail, so projects that don't target Android aren't
    blocked. Reports capability/readiness only, never gates dispatch.
    """
    if shutil.which("adb") is None:
        return doctor_registry.DoctorResult(
            name="android_adb",
            status="warn",
            detail="adb not on PATH; Android evidence capture unavailable",
        )
    try:
        result = subprocess.run(
            ["adb", "devices"],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return doctor_registry.DoctorResult(
            name="android_adb",
            status="warn",
            detail=f"adb devices probe failed: {type(exc).__name__}: {exc}",
        )
    if result.returncode != 0:
        return doctor_registry.DoctorResult(
            name="android_adb",
            status="warn",
            detail=f"adb devices returned non-zero ({result.returncode})",
        )
    # Count attached devices: each non-header line with a tab marks one.
    out = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    device_lines = [
        line for line in out.splitlines() if "\t" in line and not line.startswith("List of")
    ]
    if not device_lines:
        return doctor_registry.DoctorResult(
            name="android_adb",
            status="warn",
            detail="adb available but no devices attached",
        )
    return doctor_registry.DoctorResult(
        name="android_adb",
        status="pass",
        detail=f"adb available; {len(device_lines)} device(s) attached",
    )


def _register_android_doctor_checks() -> None:
    """Idempotent — also called from tests after registry resets so the
    Android check survives F006's per-test ``_reset_for_tests`` autouse."""
    doctor_registry.register_doctor_check("android_adb", _android_adb_check)


_register_android_doctor_checks()


__all__ = [
    "AndroidDriver",
    "AndroidDriverError",
    "AndroidEvidenceCollector",
    "AndroidJourneyStep",
    "AndroidMode",
    "AndroidSession",
    "AndroidSessionConfig",
]
