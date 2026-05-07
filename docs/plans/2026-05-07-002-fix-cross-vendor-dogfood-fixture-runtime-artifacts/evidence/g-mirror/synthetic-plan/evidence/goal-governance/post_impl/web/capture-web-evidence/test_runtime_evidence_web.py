"""Plan G F001 (G1) — web runtime evidence collector tests.

Covers acceptance #1-#8 from features.json:

  1. ``WebEvidenceCollector.collect()`` exists with documented signature.
  2. Captures screenshot + DOM + console + network failures end-to-end
     against the fixture; honors optional trace/video.
  3. **Greppable: no hardcoded http(s):// URLs in `web.py`.**
  4. Skip reason recorded as a typed EvidenceRef when driver can't init —
     collector never raises.
  5. Tests cover happy path + missing config + partial failure.
  6. Ruff + sanitization clean (verified outside pytest).
  7. Zero regressions in cumulative suite (verified outside pytest).
  8. Driver is pluggable: a stub driver passed via the ``driver`` param
     replaces Playwright cleanly.

Plus extras:

  - D003 evidence path discipline (artifacts under
    ``evidence/goal-governance/post_impl/web/<journey>/``).
  - URL composition handles trailing/leading slashes + lets absolute
    URLs pass through (D004 — no schema-prefix hardcoding).
  - Default Playwright driver in v1 returns a skip (production wiring
    deferred to a follow-up plan; the swap seam is the supported path).

Run:

    PYTHONPATH=scripts python3 -m pytest \\
        scripts/dontpanic_orchestrate/tests/test_runtime_evidence_web.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.runtime_evidence.web import (  # noqa: E402
    WebDriverError,
    WebEvidenceCollector,
    WebJourneyStep,
    WebSessionConfig,
    _PlaywrightDriver,
)

FIXTURE_DIR = HERE.parent / "runtime_evidence" / "_fixture_web"


# ──────────────────────────────  stub driver (acceptance #8)  ──────────────────────────────


class _StubSession:
    """Deterministic, fixture-backed session. Records every method
    call on ``calls`` so tests can assert dispatch order. Configurable
    failure injection per method via the constructor."""

    def __init__(
        self,
        *,
        navigate_failures: set[str] | None = None,
        screenshot_failure: bool = False,
        trace_payload: bytes | None = None,
        video_payload: bytes | None = None,
    ) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._navigate_failures = navigate_failures or set()
        self._screenshot_failure = screenshot_failure
        self._trace_payload = trace_payload
        self._video_payload = video_payload
        self._closed = False
        self._dom_html = (FIXTURE_DIR / "sample-dom.html").read_text()
        self._console_lines = [
            line.strip()
            for line in (FIXTURE_DIR / "sample-console.txt").read_text().splitlines()
            if line.strip()
        ]
        self._network_failures = json.loads((FIXTURE_DIR / "sample-network.json").read_text())

    def navigate(self, url: str) -> None:
        self.calls.append(("navigate", url))
        if url in self._navigate_failures:
            raise WebDriverError(f"navigate({url}) failed (injected)")

    def screenshot(self) -> bytes:
        self.calls.append(("screenshot", None))
        if self._screenshot_failure:
            raise WebDriverError("screenshot failed (injected)")
        # Deterministic 4-byte PNG-shaped payload
        return b"\x89PNG"

    def dom_snapshot(self) -> str:
        self.calls.append(("dom_snapshot", None))
        return self._dom_html

    def drain_console_errors(self) -> list[str]:
        self.calls.append(("drain_console_errors", None))
        return list(self._console_lines)

    def drain_network_failures(self) -> list[dict[str, Any]]:
        self.calls.append(("drain_network_failures", None))
        return list(self._network_failures)

    def stop_trace(self) -> bytes | None:
        self.calls.append(("stop_trace", None))
        return self._trace_payload

    def stop_video(self) -> bytes | None:
        self.calls.append(("stop_video", None))
        return self._video_payload

    def close(self) -> None:
        self.calls.append(("close", None))
        self._closed = True


class _StubDriver:
    name = "stub-driver"

    def __init__(self, session: _StubSession | None = None, *, init_error: str | None = None):
        self._session = session if session is not None else _StubSession()
        self._init_error = init_error

    def open_session(self, base_url: str, session_config: WebSessionConfig):
        if self._init_error is not None:
            raise WebDriverError(self._init_error)
        return self._session


# ──────────────────────────────  shared fixtures  ──────────────────────────────


def _fixed_clock() -> datetime:
    return datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def plan_dir(tmp_path: Path) -> Path:
    p = tmp_path / "synthetic-plan"
    p.mkdir()
    return p


@pytest.fixture
def journey_steps() -> list[WebJourneyStep]:
    return [
        WebJourneyStep(name="landing", path="/"),
        WebJourneyStep(name="signup", path="/auth/signup"),
    ]


# ──────────────────────────────  (1) signature + (8) pluggable driver  ──────────────────────────────


def test_collector_init_accepts_driver_param(plan_dir: Path) -> None:
    """Acceptance #1 + #8: documented signature + pluggable driver."""
    stub = _StubDriver()
    collector = WebEvidenceCollector(plan_dir=plan_dir, driver=stub, clock=_fixed_clock)
    assert collector is not None


def test_collect_returns_list_with_documented_signature(
    plan_dir: Path, journey_steps: list[WebJourneyStep]
) -> None:
    stub = _StubDriver()
    collector = WebEvidenceCollector(plan_dir=plan_dir, driver=stub, clock=_fixed_clock)
    result = collector.collect(
        journey="onboarding",
        base_url="https://fixture.local",
        session_config=WebSessionConfig(journey_steps=journey_steps),
    )
    assert isinstance(result, list)
    assert all(hasattr(ref, "type") and hasattr(ref, "uri") for ref in result)


# ──────────────────────────────  (2) end-to-end happy path  ──────────────────────────────


def test_happy_path_writes_per_step_artifacts(
    plan_dir: Path, journey_steps: list[WebJourneyStep]
) -> None:
    stub_session = _StubSession()
    collector = WebEvidenceCollector(
        plan_dir=plan_dir, driver=_StubDriver(stub_session), clock=_fixed_clock
    )
    refs = collector.collect(
        journey="onboarding",
        base_url="https://fixture.local",
        session_config=WebSessionConfig(journey_steps=journey_steps),
    )
    # Per step: 4 artifacts (screenshot, dom, console, network) × 2 steps = 8
    assert len(refs) == 8

    journey_dir = plan_dir / "evidence" / "goal-governance" / "post_impl" / "web" / "onboarding"
    files = sorted(p.name for p in journey_dir.iterdir())
    assert files == [
        "console-landing.log",
        "console-signup.log",
        "dom-landing.html",
        "dom-signup.html",
        "network-landing.jsonl",
        "network-signup.jsonl",
        "screenshot-landing.png",
        "screenshot-signup.png",
    ]

    # Dispatch order per step: navigate → screenshot → dom → console → network → close (final)
    method_calls = [name for name, _ in stub_session.calls]
    assert method_calls[:5] == [
        "navigate",
        "screenshot",
        "dom_snapshot",
        "drain_console_errors",
        "drain_network_failures",
    ]
    assert method_calls[-1] == "close"


def test_evidence_refs_typed_correctly(plan_dir: Path, journey_steps: list[WebJourneyStep]) -> None:
    """Acceptance #2 sub-bar: EvidenceRef.type from existing v1 enum."""
    collector = WebEvidenceCollector(plan_dir=plan_dir, driver=_StubDriver(), clock=_fixed_clock)
    refs = collector.collect(
        journey="onboarding",
        base_url="https://fixture.local",
        session_config=WebSessionConfig(journey_steps=journey_steps[:1]),
    )
    by_filename = {Path(ref.uri).name: ref for ref in refs}
    assert by_filename["screenshot-landing.png"].type.value == "screenshot"
    assert by_filename["dom-landing.html"].type.value == "file"
    assert by_filename["console-landing.log"].type.value == "log"
    assert by_filename["network-landing.jsonl"].type.value == "log"
    # Hash + captured_at + captured_by populated for every ref
    for ref in refs:
        assert ref.hash is not None and ref.hash.startswith("sha256:")
        assert ref.captured_at == _fixed_clock()
        assert ref.captured_by == "stub-driver"


def test_optional_trace_and_video_honored(
    plan_dir: Path, journey_steps: list[WebJourneyStep]
) -> None:
    """Acceptance #2: optional trace/video honored when session config requests them."""
    stub_session = _StubSession(
        trace_payload=b"PK\x03\x04fake-trace-zip",
        video_payload=b"\x1aE\xdf\xa3fake-webm",
    )
    collector = WebEvidenceCollector(
        plan_dir=plan_dir, driver=_StubDriver(stub_session), clock=_fixed_clock
    )
    refs = collector.collect(
        journey="onboarding",
        base_url="https://fixture.local",
        session_config=WebSessionConfig(
            journey_steps=journey_steps[:1],
            capture_trace=True,
            capture_video=True,
        ),
    )
    by_filename = {Path(ref.uri).name: ref for ref in refs}
    assert "trace.zip" in by_filename
    assert "video.webm" in by_filename
    assert by_filename["trace.zip"].type.value == "file"
    assert by_filename["video.webm"].type.value == "file"


def test_optional_trace_skipped_by_default(
    plan_dir: Path, journey_steps: list[WebJourneyStep]
) -> None:
    """Default config does NOT capture trace/video."""
    refs = WebEvidenceCollector(
        plan_dir=plan_dir, driver=_StubDriver(), clock=_fixed_clock
    ).collect(
        journey="onboarding",
        base_url="https://fixture.local",
        session_config=WebSessionConfig(journey_steps=journey_steps[:1]),
    )
    filenames = {Path(ref.uri).name for ref in refs}
    assert "trace.zip" not in filenames
    assert "video.webm" not in filenames


# ──────────────────────────────  (3) greppable: no hardcoded URLs (D004)  ──────────────────────────────


def test_no_hardcoded_urls_in_web_module() -> None:
    """Acceptance #3: greppable assertion that no http(s)://<host> appears
    in web.py source. Operator supplies base URLs at call time only."""
    web_py = Path(__file__).resolve().parents[1] / "runtime_evidence" / "web.py"
    source = web_py.read_text()
    # Pattern matches http:// or https:// followed by a non-empty host token.
    # Bare `://` mentions in error messages / docstrings are allowed
    # (they're discussion of the format, not URL literals).
    matches = re.findall(r"https?://[A-Za-z0-9._-]+", source)
    assert matches == [], f"web.py must not contain hardcoded http(s):// URLs — found: {matches}"


# ──────────────────────────────  (4) skip discipline  ──────────────────────────────


def test_driver_init_failure_returns_skip_reason(plan_dir: Path) -> None:
    """Acceptance #4: driver init failure → typed skip EvidenceRef, no raise."""
    collector = WebEvidenceCollector(
        plan_dir=plan_dir,
        driver=_StubDriver(init_error="no browser binary on this host"),
        clock=_fixed_clock,
    )
    refs = collector.collect(
        journey="onboarding",
        base_url="https://fixture.local",
        session_config=WebSessionConfig(journey_steps=[WebJourneyStep("a", "/a")]),
    )
    assert len(refs) == 1
    skip_ref = refs[0]
    assert skip_ref.type.value == "log"
    assert "skip-reason" in skip_ref.uri
    assert skip_ref.note is not None and "skipped" in skip_ref.note
    skip_path = plan_dir / skip_ref.uri
    body = skip_path.read_text()
    assert "no browser binary on this host" in body
    assert "driver: stub-driver" in body


def test_unexpected_driver_fault_returns_skip_reason(plan_dir: Path) -> None:
    """A driver that raises a non-WebDriverError exception is still
    converted to a skip — collector contract is to never propagate."""

    class _ExplodingDriver:
        name = "exploding-driver"

        def open_session(self, base_url, session_config):
            raise RuntimeError("ungovernable host condition")

    refs = WebEvidenceCollector(
        plan_dir=plan_dir, driver=_ExplodingDriver(), clock=_fixed_clock
    ).collect(
        journey="onboarding",
        base_url="https://fixture.local",
        session_config=WebSessionConfig(journey_steps=[WebJourneyStep("a", "/a")]),
    )
    assert len(refs) == 1
    assert refs[0].type.value == "log"
    assert refs[0].note is not None and "ungovernable host condition" in refs[0].note


def test_missing_base_url_returns_skip_reason(plan_dir: Path) -> None:
    """Acceptance #5: empty base_url is skipped, not raised."""
    refs = WebEvidenceCollector(
        plan_dir=plan_dir, driver=_StubDriver(), clock=_fixed_clock
    ).collect(
        journey="onboarding",
        base_url="",
        session_config=WebSessionConfig(journey_steps=[WebJourneyStep("a", "/a")]),
    )
    assert len(refs) == 1
    assert refs[0].note is not None and "empty base_url" in refs[0].note


def test_missing_journey_returns_skip_reason(plan_dir: Path) -> None:
    refs = WebEvidenceCollector(
        plan_dir=plan_dir, driver=_StubDriver(), clock=_fixed_clock
    ).collect(
        journey="",
        base_url="https://fixture.local",
        session_config=WebSessionConfig(journey_steps=[]),
    )
    assert len(refs) == 1
    assert refs[0].note is not None and "empty journey" in refs[0].note


# ──────────────────────────────  (5) partial failure  ──────────────────────────────


def test_partial_navigate_failure_records_skip_for_failed_step(
    plan_dir: Path, journey_steps: list[WebJourneyStep]
) -> None:
    """Acceptance #5: a step-level navigate failure records partial
    artifacts + a skip-reason for the failed step. Other steps unaffected."""
    stub_session = _StubSession(navigate_failures={"https://fixture.local/auth/signup"})
    collector = WebEvidenceCollector(
        plan_dir=plan_dir, driver=_StubDriver(stub_session), clock=_fixed_clock
    )
    refs = collector.collect(
        journey="onboarding",
        base_url="https://fixture.local",
        session_config=WebSessionConfig(journey_steps=journey_steps),
    )
    # landing step: 4 artifacts. signup step: navigate fails → 1 skip.
    assert len(refs) == 5
    by_kind = {Path(ref.uri).name: ref for ref in refs}
    assert "screenshot-landing.png" in by_kind
    assert "skip-reason-signup.txt" in by_kind
    skip = by_kind["skip-reason-signup.txt"]
    assert "navigate to step 'signup' failed" in (skip.note or "")


# ──────────────────────────────  D003 evidence path discipline  ──────────────────────────────


def test_artifacts_written_under_post_impl_web_path(
    plan_dir: Path, journey_steps: list[WebJourneyStep]
) -> None:
    """D003 verification: artifacts land under
    ``evidence/goal-governance/post_impl/web/<journey>/...``."""
    refs = WebEvidenceCollector(
        plan_dir=plan_dir, driver=_StubDriver(), clock=_fixed_clock
    ).collect(
        journey="onboarding",
        base_url="https://fixture.local",
        session_config=WebSessionConfig(journey_steps=journey_steps[:1]),
    )
    expected_prefix = "evidence/goal-governance/post_impl/web/onboarding"
    for ref in refs:
        assert ref.uri.startswith(expected_prefix), ref.uri
        # Materialized on disk, not just referenced.
        assert (plan_dir / ref.uri).is_file()


# ──────────────────────────────  url composition (D004)  ──────────────────────────────


def test_compose_url_handles_slash_normalization() -> None:
    compose = WebEvidenceCollector._compose_url
    # base trailing slash + path leading slash → single slash
    assert compose("https://x.test/", "/a") == "https://x.test/a"
    # base + path with no slashes → joined with single slash
    assert compose("https://x.test", "a") == "https://x.test/a"
    # base trailing slash, path no leading → unchanged join
    assert compose("https://x.test/", "a") == "https://x.test/a"
    # base no trailing, path leading → unchanged join
    assert compose("https://x.test", "/a") == "https://x.test/a"


def test_compose_url_passes_absolute_through() -> None:
    compose = WebEvidenceCollector._compose_url
    # If path looks absolute (contains ://), return path as-is.
    assert compose("https://x.test", "https://other.test/redirect") == "https://other.test/redirect"


# ──────────────────────────────  default Playwright driver — v1 skip  ──────────────────────────────


def test_default_driver_skips_in_v1(plan_dir: Path) -> None:
    """In Plan G v1 the default Playwright driver intentionally skips:
    production session adapter is a follow-up. The swap-seam path is
    the supported route. Verify the default driver path returns a skip
    rather than raising."""
    collector = WebEvidenceCollector(plan_dir=plan_dir, clock=_fixed_clock)
    refs = collector.collect(
        journey="onboarding",
        base_url="https://fixture.local",
        session_config=WebSessionConfig(journey_steps=[WebJourneyStep("a", "/a")]),
    )
    assert len(refs) == 1
    assert refs[0].type.value == "log"
    assert refs[0].note is not None and "skipped" in refs[0].note


def test_default_driver_name_is_playwright_driver() -> None:
    """Driver identity is recorded as captured_by — ensure the default
    driver advertises itself by name."""
    assert _PlaywrightDriver().name == "playwright-driver"


# ──────────────────────────────  cleanup discipline  ──────────────────────────────


def test_session_close_called_even_on_partial_failure(
    plan_dir: Path, journey_steps: list[WebJourneyStep]
) -> None:
    stub_session = _StubSession(navigate_failures={"https://fixture.local/auth/signup"})
    WebEvidenceCollector(
        plan_dir=plan_dir, driver=_StubDriver(stub_session), clock=_fixed_clock
    ).collect(
        journey="onboarding",
        base_url="https://fixture.local",
        session_config=WebSessionConfig(journey_steps=journey_steps),
    )
    assert ("close", None) in stub_session.calls
