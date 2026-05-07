"""Plan G F001 (G1) — web runtime evidence capture.

Pluggable web evidence collector. Default driver is Playwright (lazy-
imported); operators / tests pass an explicit ``driver`` to swap in.
Captures screenshot + DOM snapshot + console errors + network
failures per journey waypoint, plus optional trace and video when
the operator's session config requests them.

Public surface:

    WebEvidenceCollector(plan_dir, driver=None, clock=None)
        .collect(journey, base_url, session_config) -> list[EvidenceRef]

    WebJourneyStep(name: str, path: str)
    WebSessionConfig(...)
    WebDriver (Protocol)
    WebSession (Protocol)
    WebDriverError (raised by drivers; wrapped into skip by the collector)

**Skip discipline (acceptance #4):** when the driver can't initialize
(no browser binary, no operator config, page-load timeout) the
collector returns ``[EvidenceRef(type='log', ..., note='skipped: ...')]``
rather than raising. Callers always get a list back.

**No hardcoded URLs (acceptance #3):** ``base_url`` is operator-
supplied via the ``collect()`` argument; no http:// or https:// string
literal appears anywhere in this module.

**Capture only (D002):** no audit / scoring / pass-fail decisions.
EvidenceRef artifacts are the contract; F2 consumes them later.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from dontpanic_orchestrate.nested_orchestration import goal_governance_evidence_path

# Same agent-conventions schemas-dir bootstrap pattern used by F1's
# sufficiency_auditor.py / sufficiency_gate.py — kept inline so this
# module is independently importable.
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
class WebJourneyStep:
    """One waypoint in a web journey. ``path`` is appended to the
    operator-supplied ``base_url`` at navigation time; absolute URLs
    are accepted as a passthrough when the journey legitimately spans
    domains (e.g. a redirect-flow walk)."""

    name: str
    path: str


@dataclass
class WebSessionConfig:
    """Operator-supplied web session configuration. No defaults that
    would imply a hardcoded base URL or driver-specific behavior."""

    journey_steps: list[WebJourneyStep]
    capture_trace: bool = False
    capture_video: bool = False
    driver_options: dict[str, Any] = field(default_factory=dict)
    """Driver-specific options pass-through (headless, viewport,
    user agent, headers, timeout, ...). Keys are driver-defined."""


class WebDriverError(Exception):
    """Raised by drivers when a session can't be opened or a step
    can't capture. The collector wraps this into a skip-reason
    EvidenceRef so callers never see the raw exception."""


class WebSession(Protocol):
    """Contract a driver session must satisfy. The collector calls
    these methods in order: navigate → screenshot → dom_snapshot →
    drain_console_errors → drain_network_failures, then close at end
    (with optional stop_trace / stop_video before close)."""

    def navigate(self, url: str) -> None: ...
    def screenshot(self) -> bytes: ...
    def dom_snapshot(self) -> str: ...
    def drain_console_errors(self) -> list[str]: ...
    def drain_network_failures(self) -> list[dict[str, Any]]: ...
    def stop_trace(self) -> bytes | None: ...
    def stop_video(self) -> bytes | None: ...
    def close(self) -> None: ...


class WebDriver(Protocol):
    """Pluggable driver. Default is Playwright-backed (see
    :class:`_PlaywrightDriver`); tests + operators pass any callable
    object satisfying this protocol."""

    name: str

    def open_session(self, base_url: str, session_config: WebSessionConfig) -> WebSession: ...


# ──────────────────────────────  Playwright default driver  ──────────────────────────────


class _PlaywrightDriver:
    """Default driver. Lazy-imports Playwright on first
    ``open_session`` call so the module is importable in environments
    without Playwright installed (tests, operators who pass a stub).
    Raises :class:`WebDriverError` from ``open_session`` when the
    import fails — the collector translates that into a skip."""

    name = "playwright-driver"

    def open_session(self, base_url: str, session_config: WebSessionConfig) -> WebSession:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError as exc:
            raise WebDriverError(
                f"playwright not installed: {exc}. Install via "
                "`pip install playwright && playwright install` to enable "
                "the default web driver, or pass an explicit driver to "
                "WebEvidenceCollector."
            ) from exc
        # Production wiring of the Playwright session adapter is left as a
        # follow-up. The fixture-driven swap seam (operator-supplied
        # WebDriver) is the supported path during Plan G v1.
        raise WebDriverError(
            "Playwright session adapter not wired in Plan G v1. Pass an "
            "explicit driver to WebEvidenceCollector for now; production "
            "Playwright wiring lands in a follow-up plan."
        )


# ──────────────────────────────  collector  ──────────────────────────────


_DEFAULT_CLOCK = lambda: datetime.now(timezone.utc)  # noqa: E731


class WebEvidenceCollector:
    """Goal Governance V1 G1 — web runtime evidence capture.

    Per Plan G D002 (capture-only) + D003 (evidence path) + D004
    (project-agnostic) + D005 (no credential storage). All four
    invariants are tested via greppable assertions in the test
    module.
    """

    def __init__(
        self,
        plan_dir: Path,
        driver: WebDriver | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plan_dir = Path(plan_dir).resolve()
        self._driver: WebDriver = driver if driver is not None else _PlaywrightDriver()
        self._clock = clock if clock is not None else _DEFAULT_CLOCK

    def collect(
        self,
        journey: str,
        base_url: str,
        session_config: WebSessionConfig,
    ) -> list[EvidenceRef]:
        """Capture web evidence for one journey. Returns a list of
        ``EvidenceRef`` instances pointing at artifacts written under
        ``evidence/goal-governance/post_impl/web/<journey>/``.

        Never raises — driver init failures + per-step failures are
        recorded as skip-reason EvidenceRefs so callers always get a
        list back (acceptance #4).
        """
        if not journey:
            return [
                self._write_skip(
                    "_no-journey",
                    "skipped: empty journey identifier passed to collector",
                )
            ]
        if not base_url:
            return [
                self._write_skip(
                    journey,
                    "skipped: empty base_url; operator-supplied config is required (D004)",
                )
            ]

        try:
            session = self._driver.open_session(base_url, session_config)
        except WebDriverError as exc:
            return [self._write_skip(journey, f"skipped: driver init failed: {exc}")]
        except Exception as exc:  # noqa: BLE001 — translate any driver fault to skip
            return [
                self._write_skip(
                    journey, f"skipped: unexpected driver fault: {type(exc).__name__}: {exc}"
                )
            ]

        refs: list[EvidenceRef] = []
        try:
            for step in session_config.journey_steps:
                refs.extend(self._capture_step(session, journey, step, base_url))
            refs.extend(self._capture_optional(session, journey, session_config))
        finally:
            self._safe_close(session)

        return refs

    # ──────────────────────────────  per-step capture  ──────────────────────────────

    def _capture_step(
        self,
        session: WebSession,
        journey: str,
        step: WebJourneyStep,
        base_url: str,
    ) -> list[EvidenceRef]:
        url = self._compose_url(base_url, step.path)
        captured: list[EvidenceRef] = []
        try:
            session.navigate(url)
        except WebDriverError as exc:
            captured.append(
                self._write_skip(
                    journey,
                    f"skipped: navigate to step {step.name!r} failed: {exc}",
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
        # DOM snapshot (HTML) — type=file.
        captured.append(
            self._write_artifact(
                journey,
                f"dom-{step.name}.html",
                self._safe_text(session.dom_snapshot, journey, step.name, "dom").encode("utf-8"),
                EvidenceType.file,
                note=f"step={step.name}",
            )
        )
        # Console errors (textual log) — type=log.
        console_lines = self._safe_list(session.drain_console_errors, journey, step.name, "console")
        captured.append(
            self._write_artifact(
                journey,
                f"console-{step.name}.log",
                ("\n".join(console_lines) + "\n").encode("utf-8"),
                EvidenceType.log,
                note=f"step={step.name}; entries={len(console_lines)}",
            )
        )
        # Network failures (JSONL) — type=log (diagnostic record stream).
        failures = self._safe_list(session.drain_network_failures, journey, step.name, "network")
        jsonl_bytes = (
            "\n".join(json.dumps(f, ensure_ascii=False) for f in failures) + "\n"
        ).encode("utf-8")
        captured.append(
            self._write_artifact(
                journey,
                f"network-{step.name}.jsonl",
                jsonl_bytes,
                EvidenceType.log,
                note=f"step={step.name}; entries={len(failures)}",
            )
        )
        return captured

    def _capture_optional(
        self,
        session: WebSession,
        journey: str,
        session_config: WebSessionConfig,
    ) -> list[EvidenceRef]:
        out: list[EvidenceRef] = []
        if session_config.capture_trace:
            try:
                trace_bytes = session.stop_trace()
            except WebDriverError as exc:
                out.append(
                    self._write_skip(
                        journey, f"skipped: trace capture failed: {exc}", step_name="trace"
                    )
                )
                trace_bytes = None
            if trace_bytes is not None:
                out.append(
                    self._write_artifact(
                        journey,
                        "trace.zip",
                        trace_bytes,
                        EvidenceType.file,
                        note="optional trace",
                    )
                )
        if session_config.capture_video:
            try:
                video_bytes = session.stop_video()
            except WebDriverError as exc:
                out.append(
                    self._write_skip(
                        journey, f"skipped: video capture failed: {exc}", step_name="video"
                    )
                )
                video_bytes = None
            if video_bytes is not None:
                out.append(
                    self._write_artifact(
                        journey,
                        "video.webm",
                        video_bytes,
                        EvidenceType.file,
                        note="optional video",
                    )
                )
        return out

    # ──────────────────────────────  artifact + skip writers  ──────────────────────────────

    def _journey_dir(self, journey: str) -> Path:
        return goal_governance_evidence_path(self._plan_dir, "post_impl", f"web/{journey}")

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
        except WebDriverError as exc:
            self._write_skip(
                journey,
                f"skipped: {kind} capture for step {step!r} failed: {exc}",
                step_name=f"{step}-{kind}",
            )
            return b""
        return value if isinstance(value, bytes) else bytes(value)

    def _safe_text(
        self,
        fn: Callable[[], str],
        journey: str,
        step: str,
        kind: str,
    ) -> str:
        try:
            value = fn()
        except WebDriverError as exc:
            self._write_skip(
                journey,
                f"skipped: {kind} capture for step {step!r} failed: {exc}",
                step_name=f"{step}-{kind}",
            )
            return ""
        return value if isinstance(value, str) else str(value)

    def _safe_list(
        self,
        fn: Callable[[], list],
        journey: str,
        step: str,
        kind: str,
    ) -> list:
        try:
            value = fn()
        except WebDriverError as exc:
            self._write_skip(
                journey,
                f"skipped: {kind} capture for step {step!r} failed: {exc}",
                step_name=f"{step}-{kind}",
            )
            return []
        return list(value) if value is not None else []

    def _safe_close(self, session: WebSession) -> None:
        try:
            session.close()
        except WebDriverError:
            # Best-effort close; the collector's contract is to never
            # raise on cleanup. The leak surface is the driver's, not ours.
            return

    # ──────────────────────────────  url composition (no hardcoded URLs)  ──────────────────────────────

    @staticmethod
    def _compose_url(base_url: str, path: str) -> str:
        """Compose `base_url` + `path`. Absolute paths (``://`` present)
        pass through untouched. No hardcoded scheme prefix anywhere in
        this module — operator supplies the full base."""
        scheme_marker = "://"
        if scheme_marker in path:
            return path
        if base_url.endswith("/") and path.startswith("/"):
            return base_url[:-1] + path
        if not base_url.endswith("/") and not path.startswith("/"):
            return f"{base_url}/{path}"
        return base_url + path


__all__ = [
    "WebDriver",
    "WebDriverError",
    "WebEvidenceCollector",
    "WebJourneyStep",
    "WebSession",
    "WebSessionConfig",
]
