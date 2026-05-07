"""Plan G F005 (G5) — runtime evidence harness.

Tests cover:

  - core dispatch: EvidenceCollector.collect(journey, sources=[...])
    iterates registered sources in order, flattens their lists.
  - per-source failure handling:
      * source returns a typed skip EvidenceRef → passed through.
      * source raises EvidenceSourceError → harness wraps into typed
        skip under post_impl/harness/<journey>/skip-source-<name>.txt.
      * source raises arbitrary exception → harness wraps with
        type-prefixed message.
      * source returns None → harness emits skip.
      * source returns wrong shape → harness emits skip.
  - deterministic ordering: refs come back in source-iteration order;
    within a source, in source-emission order.
  - dedup: refs with identical (uri, hash) collapsed to first
    occurrence; refs with same uri but different hash both pass through
    (caller can flag the conflict).
  - empty journey + empty sources → typed skip EvidenceRef.
  - mixed-source acceptance (the operator's explicit bar): one
    successful source + one typed skip + one provider failure in a
    single journey, all surfacing in the harness output.
  - source-agnostic core (D004 + D006): greppable test asserts the
    EvidenceCollector class body contains NO source-specific tokens
    (web / ios / android / backend / firebase / supabase / playwright
    / simctl / adb).
  - config layering: source-specific kwargs are bound by the adapter
    helpers (web_source / ios_source / android_source / backend_source)
    and never appear in the harness signature.
  - adapter helpers compose with the real G1-G4 collectors using stub
    drivers/providers, end-to-end (no live SDKs).
  - doctor: evidence_harness check registered, always passes.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_runtime_evidence_harness.py
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))

from dontpanic_orchestrate import global_config as gc  # noqa: E402
from dontpanic_orchestrate.config import doctor_registry  # noqa: E402
from dontpanic_orchestrate.runtime_evidence import android as android_mod  # noqa: E402
from dontpanic_orchestrate.runtime_evidence import backend as backend_mod  # noqa: E402
from dontpanic_orchestrate.runtime_evidence import harness as harness_mod  # noqa: E402
from dontpanic_orchestrate.runtime_evidence import ios as ios_mod  # noqa: E402
from dontpanic_orchestrate.runtime_evidence import web as web_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_dontpanic_home(tmp_path, monkeypatch):
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))


@pytest.fixture
def plan_dir(tmp_path):
    d = tmp_path / "plan"
    d.mkdir()
    return d


def _fixed_clock():
    return datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)


# ──────────────────────────  stub source primitives  ──────────────────────────


def _make_ref(plan_dir: Path, rel: str, content: bytes, *, kind="log") -> harness_mod.EvidenceRef:
    """Helper: write a real artifact under plan_dir and return the
    matching EvidenceRef. Stub sources use this so the refs they
    return point at real files (matches the G1-G4 contract)."""
    import hashlib

    out_path = plan_dir / rel
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(content)
    type_map = {
        "log": harness_mod.EvidenceType.log,
        "file": harness_mod.EvidenceType.file,
        "screenshot": harness_mod.EvidenceType.screenshot,
    }
    return harness_mod.EvidenceRef(
        type=type_map[kind],
        uri=rel,
        hash=f"sha256:{hashlib.sha256(content).hexdigest()}",
        captured_at=_fixed_clock(),
        captured_by="stub",
        note=f"stub {kind} from {rel}",
    )


class _StubSource:
    """Bare-minimum EvidenceSource for harness testing.

    ``mode`` discriminates behavior per test:
    - 'success': returns the configured refs.
    - 'typed_skip': returns one typed-log skip EvidenceRef (mirrors
      G1-G4 skip discipline).
    - 'raise_source_error': raises EvidenceSourceError.
    - 'raise_unexpected': raises an arbitrary exception.
    - 'return_none': returns None.
    - 'return_wrong_shape': returns a non-list value.
    """

    def __init__(
        self,
        name: str,
        *,
        mode: str = "success",
        refs: list | None = None,
        plan_dir: Path | None = None,
        skip_reason: str = "skipped: stub typed-skip",
    ):
        self.name = name
        self._mode = mode
        self._refs = list(refs or [])
        self._plan_dir = plan_dir
        self._skip_reason = skip_reason
        self.calls: list[str] = []

    def collect(self, journey: str):
        self.calls.append(journey)
        if self._mode == "success":
            return list(self._refs)
        if self._mode == "typed_skip":
            assert self._plan_dir is not None
            return [
                _make_ref(
                    self._plan_dir,
                    f"evidence/goal-governance/post_impl/{self.name}/{journey}/skip-reason.txt",
                    f"reason: {self._skip_reason}\n".encode(),
                    kind="log",
                ),
            ]
        if self._mode == "raise_source_error":
            raise harness_mod.EvidenceSourceError("stub: source can't proceed")
        if self._mode == "raise_unexpected":
            raise RuntimeError("stub: arbitrary fault")
        if self._mode == "return_none":
            return None
        if self._mode == "return_wrong_shape":
            return "not a list"
        raise AssertionError(f"unknown stub mode {self._mode!r}")


# ──────────────────────────  basic dispatch  ──────────────────────────


class TestBasicDispatch:
    def test_single_source_returns_refs_in_order(self, plan_dir):
        refs = [
            _make_ref(
                plan_dir,
                "evidence/goal-governance/post_impl/web/j/screenshot-a.png",
                b"a",
                kind="screenshot",
            ),
            _make_ref(
                plan_dir,
                "evidence/goal-governance/post_impl/web/j/screenshot-b.png",
                b"b",
                kind="screenshot",
            ),
        ]
        source = _StubSource("web", refs=refs)
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("j", sources=[source])
        assert source.calls == ["j"]
        assert [r.uri for r in result] == [r.uri for r in refs]

    def test_multiple_sources_dispatched_in_order(self, plan_dir):
        web_refs = [
            _make_ref(
                plan_dir,
                "evidence/goal-governance/post_impl/web/j/x.png",
                b"web1",
                kind="screenshot",
            ),
        ]
        ios_refs = [
            _make_ref(
                plan_dir,
                "evidence/goal-governance/post_impl/ios/j/x.png",
                b"ios1",
                kind="screenshot",
            ),
        ]
        backend_refs = [
            _make_ref(
                plan_dir,
                "evidence/goal-governance/post_impl/backend/j/probe.bin",
                b"bk1",
                kind="file",
            ),
        ]
        sources = [
            _StubSource("web", refs=web_refs),
            _StubSource("ios", refs=ios_refs),
            _StubSource("backend", refs=backend_refs),
        ]
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("j", sources=sources)
        # Source-iteration order preserved: web → ios → backend.
        assert [r.uri for r in result] == [
            web_refs[0].uri,
            ios_refs[0].uri,
            backend_refs[0].uri,
        ]
        for src in sources:
            assert src.calls == ["j"]

    def test_empty_source_list_returns_typed_skip(self, plan_dir):
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("j", sources=[])
        assert len(result) == 1
        assert result[0].type.value == "log"
        assert "no sources" in (result[0].note or "")
        # Skip lives under harness/<journey>/, not under any source's subdir.
        assert result[0].uri.startswith("evidence/goal-governance/post_impl/harness/j/")

    def test_empty_journey_returns_typed_skip(self, plan_dir):
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("", sources=[_StubSource("web")])
        assert len(result) == 1
        assert "empty journey" in (result[0].note or "")


# ──────────────────────────  per-source failure handling  ──────────────────────────


class TestPerSourceFailureHandling:
    def test_typed_skip_passes_through_unchanged(self, plan_dir):
        source = _StubSource("ios", mode="typed_skip", plan_dir=plan_dir)
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("j", sources=[source])
        assert len(result) == 1
        assert result[0].type.value == "log"
        # The skip ref came from the source's own subdir; the harness
        # didn't add another one.
        assert "/ios/" in result[0].uri
        assert "/harness/" not in result[0].uri

    def test_evidencesourceerror_wraps_to_harness_skip(self, plan_dir):
        source = _StubSource("backend", mode="raise_source_error")
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("j", sources=[source])
        assert len(result) == 1
        assert result[0].type.value == "log"
        assert "/harness/j/skip-source-backend.txt" in result[0].uri
        assert "source raised" in (result[0].note or "")

    def test_arbitrary_exception_wraps_to_harness_skip(self, plan_dir):
        source = _StubSource("android", mode="raise_unexpected")
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("j", sources=[source])
        assert len(result) == 1
        assert "unexpected source fault" in (result[0].note or "")
        assert "RuntimeError" in (result[0].note or "")

    def test_source_returning_none_wraps_to_harness_skip(self, plan_dir):
        source = _StubSource("custom", mode="return_none")
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("j", sources=[source])
        assert len(result) == 1
        assert "returned None" in (result[0].note or "")

    def test_source_returning_wrong_shape_wraps_to_harness_skip(self, plan_dir):
        source = _StubSource("custom", mode="return_wrong_shape")
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("j", sources=[source])
        assert len(result) == 1
        assert "instead of list" in (result[0].note or "")

    def test_source_with_unsafe_name_sanitized_in_skip_filename(self, plan_dir):
        # An adversarial / careless source name with path-traversal
        # characters must not escape the journey dir.
        source = _StubSource("../escapee", mode="raise_source_error")
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("j", sources=[source])
        # Sanitized — no path traversal. ('/' → '_' then '..' → '_').
        assert "/harness/j/skip-source-__escapee.txt" in result[0].uri
        assert ".." not in result[0].uri.split("/harness/")[1]


# ──────────────────────────  dedup + ordering  ──────────────────────────


class TestDedupAndOrdering:
    def test_duplicate_uri_and_hash_collapsed(self, plan_dir):
        # Same artifact emitted by two sources → one ref in the output.
        ref_a = _make_ref(
            plan_dir, "evidence/goal-governance/post_impl/web/j/x.png", b"X", kind="screenshot"
        )
        # Source B writes (would write) the same file with same content.
        # In real life this shouldn't happen because adapters write to
        # their own subdirs, but the dedup contract says identical
        # (uri, hash) collapses regardless.
        sources = [
            _StubSource("web", refs=[ref_a]),
            _StubSource("web2", refs=[ref_a]),
        ]
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("j", sources=sources)
        assert len(result) == 1
        assert result[0].uri == ref_a.uri

    def test_same_uri_different_hash_both_surface(self, plan_dir):
        # Two sources wrote to the same uri with different content —
        # both refs surface so a downstream consumer (F2) can flag the
        # conflict.
        ref_a = _make_ref(plan_dir, "evidence/goal-governance/post_impl/web/j/conflict.txt", b"AAA")
        # Overwrite with different content.
        ref_b = _make_ref(plan_dir, "evidence/goal-governance/post_impl/web/j/conflict.txt", b"BBB")
        assert ref_a.uri == ref_b.uri
        assert ref_a.hash != ref_b.hash
        sources = [
            _StubSource("source-a", refs=[ref_a]),
            _StubSource("source-b", refs=[ref_b]),
        ]
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("j", sources=sources)
        # NOTE: in this test ref_a was overwritten by ref_b on disk so
        # ref_a's hash no longer matches what's at uri — but the harness
        # doesn't re-hash. It compares by ref.hash (in-memory). Both
        # refs surface because their ``hash`` strings differ.
        assert len(result) == 2

    def test_within_source_ordering_preserved(self, plan_dir):
        refs = [
            _make_ref(
                plan_dir, "evidence/goal-governance/post_impl/web/j/a.png", b"a", kind="screenshot"
            ),
            _make_ref(
                plan_dir, "evidence/goal-governance/post_impl/web/j/b.png", b"b", kind="screenshot"
            ),
            _make_ref(
                plan_dir, "evidence/goal-governance/post_impl/web/j/c.png", b"c", kind="screenshot"
            ),
        ]
        source = _StubSource("web", refs=refs)
        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("j", sources=[source])
        assert [r.uri for r in result] == [r.uri for r in refs]


# ──────────────────────────  the explicit mixed-source acceptance bar  ──────────────────────────


class TestMixedSourceAcceptance:
    """Operator-specified F005 acceptance:

    'A mixed-source fixture, e.g. browser + backend + artifact source
    in one journey, with one successful source, one typed skip, and
    one provider failure. That proves the harness is actually doing
    common orchestration rather than just wrapping one happy path.'
    """

    def test_browser_success_plus_backend_skip_plus_artifact_failure(self, plan_dir):
        # 1. Browser source — success: returns a screenshot + a log ref.
        web_refs = [
            _make_ref(
                plan_dir,
                "evidence/goal-governance/post_impl/web/journey-1/screenshot-landing.png",
                b"png-bytes",
                kind="screenshot",
            ),
            _make_ref(
                plan_dir,
                "evidence/goal-governance/post_impl/web/journey-1/console-landing.log",
                b"console clean\n",
                kind="log",
            ),
        ]
        browser_source = _StubSource("web", mode="success", refs=web_refs)

        # 2. Backend source — typed skip (the source already wrote its
        #    own skip-reason artifact and returned that EvidenceRef).
        backend_source = _StubSource(
            "backend",
            mode="typed_skip",
            plan_dir=plan_dir,
            skip_reason="skipped: provider init failed (no SDK)",
        )

        # 3. Artifact source — provider failure (raises mid-collect).
        artifact_source = _StubSource("android", mode="raise_source_error")

        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect(
            "journey-1",
            sources=[browser_source, backend_source, artifact_source],
        )

        # All three sources contributed. The harness produced a SINGLE
        # flat list with consistent EvidenceRef typing throughout.
        assert len(result) == 4
        assert all(isinstance(r, harness_mod.EvidenceRef) for r in result)

        # Source-iteration order preserved: web (2 refs) → backend
        # (1 typed skip) → android (1 harness skip).
        uris = [r.uri for r in result]
        assert uris[0].startswith("evidence/goal-governance/post_impl/web/journey-1/")
        assert uris[1].startswith("evidence/goal-governance/post_impl/web/journey-1/")
        assert uris[2].startswith("evidence/goal-governance/post_impl/backend/journey-1/")
        assert uris[3].startswith("evidence/goal-governance/post_impl/harness/journey-1/")

        # Browser's success refs are typed correctly (screenshot + log).
        assert result[0].type.value == "screenshot"
        assert result[1].type.value == "log"
        # Backend's typed skip is type=log with the source's own note.
        assert result[2].type.value == "log"
        # Android's raise was wrapped by the harness — type=log,
        # captured_by='evidence-harness'.
        assert result[3].type.value == "log"
        assert result[3].captured_by == "evidence-harness"
        assert "skip-source-android.txt" in result[3].uri

        # Each source called once with the right journey.
        assert browser_source.calls == ["journey-1"]
        assert backend_source.calls == ["journey-1"]
        assert artifact_source.calls == ["journey-1"]


# ──────────────────────────  source-agnostic core invariant (D004 + D006)  ──────────────────────────


class TestSourceAgnosticCore:
    """The harness CORE must not branch on source identity. Source-
    specific knowledge lives ONLY in the adapter helpers (which can
    be removed/replaced without touching the core)."""

    _HARNESS_SRC = (HERE.parents[1] / "runtime_evidence" / "harness.py").read_text()

    def test_core_class_body_contains_no_source_specific_tokens(self):
        # Find the EvidenceCollector class body — everything from
        # `class EvidenceCollector` to the next top-level `class ` /
        # `def ` at column 0.
        src = self._HARNESS_SRC
        marker = "\nclass EvidenceCollector:"
        i = src.index(marker)
        # End of class body: next top-level def/class at column 0
        # (i.e., starting with '\ndef ' or '\nclass '). The class body
        # ends at the next such token after `i`.
        rest = src[i + 1 :]
        next_def = rest.find("\ndef ")
        next_class = rest.find("\nclass ")
        candidates = [x for x in (next_def, next_class) if x != -1]
        end = min(candidates) if candidates else len(rest)
        class_body = rest[:end].lower()

        # Any of these tokens in the harness CORE = D004 violation.
        forbidden_tokens = (
            "web",
            "ios",
            "android",
            "backend",
            "firebase",
            "supabase",
            "playwright",
            "simctl",
            "adb",
            "logcat",
            "tombstone",
        )
        for needle in forbidden_tokens:
            assert needle not in class_body, (
                f"EvidenceCollector class body contains source-specific token "
                f"{needle!r} (D004 + D006 — harness must be source-agnostic)"
            )

    def test_no_credential_storage_in_module(self):
        """D005/D014: harness has no auth at all; assert no credential
        literals anywhere in source."""
        forbidden = (
            re.compile(r"password\s*=\s*['\"]\w", re.IGNORECASE),
            re.compile(r"\bbearer\s+[a-z0-9._\-]+", re.IGNORECASE),
            re.compile(r"^\s*api_key\s*=\s*['\"]\w", re.IGNORECASE | re.MULTILINE),
        )
        for rx in forbidden:
            assert not rx.search(self._HARNESS_SRC), (
                f"runtime_evidence/harness.py contains credential-bearing literal "
                f"matching {rx.pattern!r} (D005/D014)"
            )

    def test_evidence_path_uses_harness_subdir(self):
        """D003: harness-emitted skip refs land under post_impl/harness/."""
        assert (
            'goal_governance_evidence_path(\n            self._plan_dir, "post_impl", f"{_HARNESS_SUBDIR}/{journey}"\n        )'
            in self._HARNESS_SRC
        )

    def test_no_audit_or_scoring_logic(self):
        """D002: harness is capture-only orchestration. Greppable
        assertion that no audit / scoring tokens leak in."""
        forbidden_audit = (
            "passes_check",
            "score(",
            "audit_score",
            "evaluate_pass",
            "scoring_rule",
        )
        lower = self._HARNESS_SRC.lower()
        for needle in forbidden_audit:
            assert needle not in lower, (
                f"runtime_evidence/harness.py contains audit/scoring token "
                f"{needle!r} (D002 — harness is capture-only)"
            )


# ──────────────────────────  config layering separation  ──────────────────────────


class TestConfigLayeringSeparation:
    """Source-specific config (base_url, simulator, package, provider,
    etc.) must NOT appear in the harness signature. Adapter helpers
    own the closure."""

    def test_collector_signature_takes_only_journey_and_sources(self):
        import inspect

        sig = inspect.signature(harness_mod.EvidenceCollector.collect)
        params = list(sig.parameters.keys())
        # 'self', 'journey', and 'sources' (keyword-only) — nothing else.
        assert params == ["self", "journey", "sources"]
        assert sig.parameters["sources"].kind == inspect.Parameter.KEYWORD_ONLY

    def test_collector_init_signature_takes_only_plan_dir_and_clock(self):
        import inspect

        sig = inspect.signature(harness_mod.EvidenceCollector.__init__)
        params = list(sig.parameters.keys())
        assert params == ["self", "plan_dir", "clock"]


# ──────────────────────────  adapter helpers (end-to-end with real G1-G4 collectors)  ──────────────────────────


class _StubWebDriver:
    """Minimal G1 WebDriver/WebSession stub for adapter-helper tests."""

    name = "stub-web-driver"

    def open_session(self, base_url, session_config):
        return _StubWebSession()


class _StubWebSession:
    def navigate(self, url):
        pass

    def screenshot(self):
        return b"web-screenshot"

    def dom_snapshot(self):
        return "<html></html>"

    def drain_console_errors(self):
        return []

    def drain_network_failures(self):
        return []

    def stop_trace(self):
        return None

    def stop_video(self):
        return None

    def close(self):
        pass


class _StubIosDriver:
    name = "stub-ios-driver"

    def open_session(self, *, simulator, scheme, app_bundle_id, session_config):
        return _StubIosSession()


class _StubIosSession:
    def activate_step(self, step_name):
        pass

    def screenshot(self):
        return b"ios-screenshot"

    def drain_log_slice(self):
        return b"ios-log\n"

    def drain_crash_reports(self):
        return []

    def close(self):
        pass


class _StubAndroidDriver:
    name = "stub-android-driver"

    def open_session(self, *, package, adb_device_serial, session_config):
        return _StubAndroidSession()


class _StubAndroidSession:
    def activate_step(self, step_name):
        pass

    def screenshot(self):
        return b"android-screenshot"

    def drain_logcat_slice(self):
        return b"android-logcat\n"

    def drain_tombstones(self):
        return []

    def drain_anr_reports(self):
        return []

    def close(self):
        pass


class _StubBackendProvider:
    name = "stub-backend-provider"

    def open_session(self, *, project, auth, session_config):
        return _StubBackendSession()


class _StubBackendSession:
    def execute_probe(self, probe):
        return (b"backend-probe-payload", backend_mod.EvidenceType.log)

    def close(self):
        pass


class TestAdapterHelpersEndToEnd:
    """The four adapter helpers (web_source / ios_source /
    android_source / backend_source) must compose correctly with the
    real G1-G4 collectors using stub drivers/providers — no live SDKs."""

    def test_all_four_adapters_compose_into_one_journey(self, plan_dir):
        # G1 web collector
        web_collector = web_mod.WebEvidenceCollector(
            plan_dir, driver=_StubWebDriver(), clock=_fixed_clock
        )
        web_cfg = web_mod.WebSessionConfig(
            journey_steps=[web_mod.WebJourneyStep(name="landing", path="/")],
            capture_trace=False,
            capture_video=False,
        )

        # G2 iOS collector
        ios_collector = ios_mod.IosEvidenceCollector(
            plan_dir, driver=_StubIosDriver(), clock=_fixed_clock
        )
        ios_cfg = ios_mod.IosSessionConfig(
            journey_steps=[ios_mod.IosJourneyStep(name="launch")],
            capture_simulator_log=True,
            capture_crash_reports=False,
        )

        # G3 Android collector
        android_collector = android_mod.AndroidEvidenceCollector(
            plan_dir, driver=_StubAndroidDriver(), clock=_fixed_clock
        )
        android_cfg = android_mod.AndroidSessionConfig(
            mode="passive_observe",
            journey_steps=[android_mod.AndroidJourneyStep(name="home")],
            capture_logcat=True,
            capture_tombstones=False,
            capture_anr=False,
        )

        # G4 backend collector
        backend_collector = backend_mod.BackendEvidenceCollector(
            plan_dir,
            providers={"stub": _StubBackendProvider()},
            clock=_fixed_clock,
        )
        backend_cfg = backend_mod.BackendSessionConfig(
            provider="stub",
            probes=[backend_mod.BackendProbe(name="health", kind="any")],
        )

        sources = [
            harness_mod.web_source(
                web_collector, base_url="http://localhost:3000", session_config=web_cfg
            ),
            harness_mod.ios_source(
                ios_collector,
                simulator="iPhone 15",
                scheme="App",
                app_bundle_id="com.example",
                session_config=ios_cfg,
            ),
            harness_mod.android_source(
                android_collector,
                package="com.example.app",
                adb_device_serial="emulator-5554",
                session_config=android_cfg,
            ),
            harness_mod.backend_source(
                backend_collector,
                provider="stub",
                project="my-proj",
                auth="adc",
                session_config=backend_cfg,
            ),
        ]

        harness = harness_mod.EvidenceCollector(plan_dir, clock=_fixed_clock)
        result = harness.collect("compose-test", sources=sources)

        # Each source contributed at least one ref; total ≥ 4.
        assert len(result) >= 4
        uris = " ".join(r.uri for r in result)
        # All four expected source subdirs present.
        assert "/web/compose-test/" in uris
        assert "/ios/compose-test/" in uris
        assert "/android/compose-test/" in uris
        assert "/backend/compose-test/" in uris


# ──────────────────────────  doctor framework  ──────────────────────────


class TestDoctorRegistration:
    def test_evidence_harness_check_registered(self):
        harness_mod._register_harness_doctor_checks()
        results = doctor_registry.run_all_checks()
        assert any(r.name == "evidence_harness" for r in results)

    def test_check_returns_pass(self):
        result = harness_mod._evidence_harness_check()
        assert result.status == "pass"
        assert "harness available" in result.detail

    def test_check_never_returns_fail(self):
        # The harness has no external deps; this should always pass.
        # Defensive sweep just to mirror the never-fail contract from
        # G2/G3/G4.
        assert harness_mod._evidence_harness_check().status != "fail"
