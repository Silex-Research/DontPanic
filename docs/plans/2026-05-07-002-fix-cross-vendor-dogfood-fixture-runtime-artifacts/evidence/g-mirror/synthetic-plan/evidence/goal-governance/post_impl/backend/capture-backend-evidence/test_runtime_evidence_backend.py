"""Plan G F004 (G4) — backend runtime evidence capture.

Tests cover:

  - generic provider: http_get / log_file / jsonl_stream probes
    produce typed EvidenceRefs with correct content + content-type
    classification (file / log / log).
  - firebase provider: refuses to open without project, refuses
    without auth, refuses non-pointer auth values, raises with
    descriptive message when ``firebase_admin`` SDK is unavailable
    (the v1-deferred path).
  - supabase provider: always raises (slot only per D010); rejects
    non-pointer auth too.
  - skip discipline:
      * empty journey → skip-reason EvidenceRef.
      * unknown provider name → skip-reason.
      * provider open_session failure → skip-reason.
      * unexpected non-BackendProviderError fault → skip-reason.
      * per-probe failure → skip-reason for that probe (others still
        captured).
      * session opened but no probes configured → skip-reason at end.
  - config layering: per-call kwargs > runtime_evidence.backend
    project config > none (D015 — no global tier).
  - typed EvidenceRef fields compatible with G1/G2/G3.
  - doctor framework: backend_firebase / backend_supabase /
    backend_generic registered. firebase warns when SDK absent;
    supabase always warns (slot); generic always passes. None of
    them ever return 'fail'.
  - greppable invariants: D003 evidence path, D004 project-agnostic,
    D005/D014 no credential literals (only pointer regexes), no
    live cloud-call shorthand in source.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_runtime_evidence_backend.py
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
from dontpanic_orchestrate.runtime_evidence import backend as backend_mod  # noqa: E402

_FIXTURE_DIR = HERE.parent / "runtime_evidence" / "_fixture_backend"


@pytest.fixture(autouse=True)
def _isolate_dontpanic_home(tmp_path, monkeypatch):
    monkeypatch.delenv(gc.JARVIS_HOME_ENV, raising=False)
    monkeypatch.setenv(gc.DONTPANIC_HOME_ENV, str(tmp_path / ".dontpanic"))


@pytest.fixture
def plan_dir(tmp_path):
    d = tmp_path / "plan"
    d.mkdir()
    return d


# ──────────────────────────  stub provider/session  ──────────────────────────


class _StubSession:
    """Deterministic in-memory provider session.

    Mapping ``{probe_name: (payload_bytes, EvidenceType)}``. Probe
    names that aren't in the map raise BackendProviderError so the
    collector's per-probe skip path runs. ``raise_on_close`` mirrors
    G2/G3 close-failure swallow tests."""

    def __init__(
        self,
        responses: dict[str, tuple[bytes, backend_mod.EvidenceType]] | None = None,
        *,
        raise_on_close: bool = False,
    ):
        from dontpanic_orchestrate.runtime_evidence.backend import EvidenceType

        self._responses = dict(responses or {})
        self._evidence_type = EvidenceType
        self.raise_on_close = raise_on_close
        self.probes_executed: list[str] = []
        self.closed = False

    def execute_probe(self, probe):
        self.probes_executed.append(probe.name)
        if probe.name not in self._responses:
            raise backend_mod.BackendProviderError(
                f"stub: no response configured for probe {probe.name!r}"
            )
        return self._responses[probe.name]

    def close(self):
        if self.raise_on_close:
            raise backend_mod.BackendProviderError("stub: close failed")
        self.closed = True


class _StubProvider:
    name = "stub-backend-provider"

    def __init__(
        self,
        session: _StubSession | None = None,
        *,
        raise_on_open: backend_mod.BackendProviderError | None = None,
    ):
        self.session = session
        self.raise_on_open = raise_on_open
        self.opens: list[dict] = []

    def open_session(self, *, project, auth, session_config):
        self.opens.append(
            {
                "project": project,
                "auth": auth,
                "provider": session_config.provider,
                "probe_count": len(session_config.probes),
            }
        )
        if self.raise_on_open is not None:
            raise self.raise_on_open
        return self.session


def _fixed_clock():
    return datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)


# ──────────────────────────  generic provider (stdlib only)  ──────────────────────────


class TestGenericProviderHttpGet:
    def test_http_get_writes_typed_evidenceref(self, plan_dir, monkeypatch):
        # Monkeypatch urlopen to return fixture bytes — no live network.
        fixture_bytes = (_FIXTURE_DIR / "http_response.json").read_bytes()

        class _Resp:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def _fake_urlopen(req, timeout=10):
            return _Resp(fixture_bytes)

        from urllib import request

        monkeypatch.setattr(request, "urlopen", _fake_urlopen)

        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="generic",
            probes=[
                backend_mod.BackendProbe(
                    name="healthz",
                    kind="http_get",
                    params={"url": "http://localhost:8080/healthz"},
                ),
            ],
        )
        refs = collector.collect("backend-journey", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "file"
        assert refs[0].uri.startswith("evidence/goal-governance/post_impl/backend/backend-journey/")
        assert refs[0].uri.endswith("probe-healthz.bin")
        assert (plan_dir / refs[0].uri).read_bytes() == fixture_bytes
        assert refs[0].captured_by == "generic-provider"

    def test_http_get_failure_returns_skip(self, plan_dir, monkeypatch):
        from urllib import request
        from urllib.error import URLError

        def _fake_urlopen(req, timeout=10):
            raise URLError("synthetic refusal")

        monkeypatch.setattr(request, "urlopen", _fake_urlopen)

        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="generic",
            probes=[
                backend_mod.BackendProbe(
                    name="dead-endpoint",
                    kind="http_get",
                    params={"url": "http://localhost:9/nope"},
                ),
            ],
        )
        refs = collector.collect("j", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        assert "synthetic refusal" in (refs[0].note or "")

    def test_http_get_missing_url_returns_skip(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="generic",
            probes=[backend_mod.BackendProbe(name="bad", kind="http_get", params={})],
        )
        refs = collector.collect("j", session_config=config)
        assert len(refs) == 1
        assert "missing required param" in (refs[0].note or "")


class TestGenericProviderLogFile:
    def test_log_file_writes_log_evidence(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="generic",
            probes=[
                backend_mod.BackendProbe(
                    name="server",
                    kind="log_file",
                    params={"path": str(_FIXTURE_DIR / "server.log")},
                ),
            ],
        )
        refs = collector.collect("j", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        assert refs[0].uri.endswith("probe-server.log")
        assert b"startup: server bound" in (plan_dir / refs[0].uri).read_bytes()

    def test_log_file_max_bytes_truncates_to_tail(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="generic",
            probes=[
                backend_mod.BackendProbe(
                    name="tail",
                    kind="log_file",
                    params={
                        "path": str(_FIXTURE_DIR / "server.log"),
                        "max_bytes": 50,
                    },
                ),
            ],
        )
        refs = collector.collect("j", session_config=config)
        body = (plan_dir / refs[0].uri).read_bytes()
        assert len(body) <= 50
        # Tail of the file ends with the shutdown line.
        assert body.endswith(b"drain complete\n")

    def test_log_file_missing_path_returns_skip(self, plan_dir, tmp_path):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="generic",
            probes=[
                backend_mod.BackendProbe(
                    name="missing",
                    kind="log_file",
                    params={"path": str(tmp_path / "does-not-exist.log")},
                ),
            ],
        )
        refs = collector.collect("j", session_config=config)
        assert len(refs) == 1
        assert "does not exist" in (refs[0].note or "")


class TestGenericProviderJsonlStream:
    def test_jsonl_stream_validates_each_line(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="generic",
            probes=[
                backend_mod.BackendProbe(
                    name="audit",
                    kind="jsonl_stream",
                    params={"path": str(_FIXTURE_DIR / "audit.jsonl")},
                ),
            ],
        )
        refs = collector.collect("j", session_config=config)
        assert len(refs) == 1
        assert refs[0].type.value == "log"
        body = (plan_dir / refs[0].uri).read_text()
        # 3 valid JSON lines + 1 malformed (commented out).
        valid = [
            ln
            for ln in body.splitlines()
            if ln.startswith("{") and not ln.startswith("# malformed:")
        ]
        malformed = [ln for ln in body.splitlines() if ln.startswith("# malformed:")]
        assert len(valid) == 3
        assert len(malformed) == 1

    def test_jsonl_stream_max_lines_caps_output(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="generic",
            probes=[
                backend_mod.BackendProbe(
                    name="audit-cap",
                    kind="jsonl_stream",
                    params={"path": str(_FIXTURE_DIR / "audit.jsonl"), "max_lines": 2},
                ),
            ],
        )
        refs = collector.collect("j", session_config=config)
        body = (plan_dir / refs[0].uri).read_text()
        non_empty = [ln for ln in body.splitlines() if ln.strip()]
        assert len(non_empty) == 2


class TestGenericProviderUnknownKind:
    def test_unknown_probe_kind_returns_skip(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="generic",
            probes=[
                backend_mod.BackendProbe(name="weird", kind="rpc_call"),
            ],
        )
        refs = collector.collect("j", session_config=config)
        assert len(refs) == 1
        assert "doesn't understand probe.kind" in (refs[0].note or "")


class TestGenericProviderAuthPointerValidation:
    def test_non_pointer_auth_refused(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="generic",
            probes=[
                backend_mod.BackendProbe(name="x", kind="http_get", params={"url": "http://x"})
            ],
        )
        refs = collector.collect(
            "j",
            auth="Bearer abc.def.ghi",  # explicit non-pointer
            session_config=config,
        )
        assert len(refs) == 1
        assert "D014" in (refs[0].note or "")


# ──────────────────────────  firebase provider (deferred)  ──────────────────────────


class TestFirebaseProvider:
    def test_refuses_without_project(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="firebase",
            probes=[backend_mod.BackendProbe(name="x", kind="firestore_doc")],
        )
        refs = collector.collect("j", auth="adc", session_config=config)
        assert len(refs) == 1
        assert "requires 'project'" in (refs[0].note or "")

    def test_refuses_without_auth(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="firebase",
            probes=[backend_mod.BackendProbe(name="x", kind="firestore_doc")],
        )
        refs = collector.collect("j", project="myproj-dev", session_config=config)
        assert len(refs) == 1
        assert "requires 'auth' pointer" in (refs[0].note or "")

    def test_refuses_non_pointer_auth(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="firebase",
            probes=[backend_mod.BackendProbe(name="x", kind="firestore_doc")],
        )
        refs = collector.collect(
            "j",
            project="myproj-dev",
            auth="ghp_abcdefghijklmnopqrstuvwxyz0123456789",  # non-pointer
            session_config=config,
        )
        assert len(refs) == 1
        assert "D014" in (refs[0].note or "") or "pointer shape" in (refs[0].note or "")

    def test_refuses_unknown_probe_kind(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="firebase",
            probes=[backend_mod.BackendProbe(name="x", kind="rpc_call")],
        )
        refs = collector.collect(
            "j",
            project="myproj-dev",
            auth="adc",
            session_config=config,
        )
        assert len(refs) == 1
        assert "doesn't understand probe.kind" in (refs[0].note or "")

    def test_skips_when_sdk_unavailable_or_unwired(self, plan_dir, monkeypatch):
        # Force SDK lookup to fail so we hit the deferred-wiring path.
        from dontpanic_orchestrate.runtime_evidence import backend as bm

        monkeypatch.setattr(bm.importlib.util, "find_spec", lambda name: None)
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="firebase",
            probes=[backend_mod.BackendProbe(name="x", kind="firestore_doc")],
        )
        refs = collector.collect(
            "j",
            project="myproj-dev",
            auth="adc",
            session_config=config,
        )
        assert len(refs) == 1
        assert "firebase_admin SDK not installed" in (refs[0].note or "")


# ──────────────────────────  supabase provider (slot only)  ──────────────────────────


class TestSupabaseProvider:
    def test_always_raises_in_v1(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="supabase",
            probes=[backend_mod.BackendProbe(name="x", kind="any")],
        )
        refs = collector.collect("j", project="myproj", auth="adc", session_config=config)
        assert len(refs) == 1
        assert "Supabase provider is a slot" in (refs[0].note or "")

    def test_refuses_non_pointer_auth(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="supabase",
            probes=[backend_mod.BackendProbe(name="x", kind="any")],
        )
        refs = collector.collect(
            "j",
            project="myproj",
            auth="sk-proj-abcdefghijklmnopqrstuvwxyz",  # non-pointer
            session_config=config,
        )
        assert len(refs) == 1
        assert "D014" in (refs[0].note or "") or "pointer shape" in (refs[0].note or "")


# ──────────────────────────  collector skip discipline  ──────────────────────────


class TestCollectorSkipDiscipline:
    def test_empty_journey_returns_skip(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(plan_dir, clock=_fixed_clock)
        config = backend_mod.BackendSessionConfig(
            provider="generic",
            probes=[
                backend_mod.BackendProbe(name="x", kind="http_get", params={"url": "http://x"})
            ],
        )
        refs = collector.collect("", session_config=config)
        assert len(refs) == 1
        assert "empty journey" in (refs[0].note or "")

    def test_unknown_provider_name_returns_skip(self, plan_dir):
        collector = backend_mod.BackendEvidenceCollector(
            plan_dir, providers={"only-stub": _StubProvider(_StubSession())}, clock=_fixed_clock
        )
        config = backend_mod.BackendSessionConfig(
            provider="firebase",  # not registered in the test collector
            probes=[backend_mod.BackendProbe(name="x", kind="firestore_doc")],
        )
        refs = collector.collect("j", project="myproj", auth="adc", session_config=config)
        assert len(refs) == 1
        assert "unknown provider" in (refs[0].note or "")

    def test_unexpected_provider_fault_returns_skip(self, plan_dir):
        class _Boom:
            name = "boom"

            def open_session(self, **kw):
                raise RuntimeError("non-BackendProviderError fault")

        collector = backend_mod.BackendEvidenceCollector(
            plan_dir, providers={"boom": _Boom()}, clock=_fixed_clock
        )
        config = backend_mod.BackendSessionConfig(
            provider="boom",
            probes=[backend_mod.BackendProbe(name="x", kind="any")],
        )
        refs = collector.collect("j", session_config=config)
        assert len(refs) == 1
        assert "unexpected provider fault" in (refs[0].note or "")
        assert "RuntimeError" in (refs[0].note or "")

    def test_per_probe_failure_skips_only_that_probe(self, plan_dir):
        from dontpanic_orchestrate.runtime_evidence.backend import EvidenceType

        session = _StubSession(
            responses={
                "good": (b"good payload", EvidenceType.log),
                # "bad" intentionally absent → stub raises.
            }
        )
        provider = _StubProvider(session=session)
        collector = backend_mod.BackendEvidenceCollector(
            plan_dir, providers={"stub": provider}, clock=_fixed_clock
        )
        config = backend_mod.BackendSessionConfig(
            provider="stub",
            probes=[
                backend_mod.BackendProbe(name="good", kind="any"),
                backend_mod.BackendProbe(name="bad", kind="any"),
            ],
        )
        refs = collector.collect("j", session_config=config)
        # 1 good artifact + 1 skip for bad.
        assert len(refs) == 2
        good_refs = [r for r in refs if r.uri.endswith("probe-good.log")]
        bad_refs = [r for r in refs if r.note and "bad" in r.note and "skipped" in r.note]
        assert len(good_refs) == 1
        assert len(bad_refs) == 1

    def test_no_probes_configured_returns_skip(self, plan_dir):
        provider = _StubProvider(session=_StubSession())
        collector = backend_mod.BackendEvidenceCollector(
            plan_dir, providers={"stub": provider}, clock=_fixed_clock
        )
        config = backend_mod.BackendSessionConfig(provider="stub", probes=[])
        refs = collector.collect("j", session_config=config)
        assert len(refs) == 1
        assert "no probes were configured" in (refs[0].note or "")

    def test_close_failure_swallowed(self, plan_dir):
        from dontpanic_orchestrate.runtime_evidence.backend import EvidenceType

        session = _StubSession(responses={"x": (b"payload", EvidenceType.log)}, raise_on_close=True)
        provider = _StubProvider(session=session)
        collector = backend_mod.BackendEvidenceCollector(
            plan_dir, providers={"stub": provider}, clock=_fixed_clock
        )
        config = backend_mod.BackendSessionConfig(
            provider="stub",
            probes=[backend_mod.BackendProbe(name="x", kind="any")],
        )
        # Must not raise.
        refs = collector.collect("j", session_config=config)
        assert any(r.uri.endswith("probe-x.log") for r in refs)


# ──────────────────────────  config layering (D015)  ──────────────────────────


class TestConfigLayering:
    def test_per_call_overrides_project_config(self, plan_dir):
        proj_root = plan_dir.parent
        from dontpanic_orchestrate import projects_registry as pr

        pr.add_project(name="proj-x", path=proj_root)
        cfg_path = pc.project_config_path(proj_root)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps(
                {
                    "runtime_evidence": {
                        "backend": {
                            "provider": "supabase",  # project says supabase…
                            "project": "supa-proj",
                            "auth": "env:SUPA_KEY",
                        }
                    }
                }
            )
        )
        provider = _StubProvider(session=_StubSession())
        collector = backend_mod.BackendEvidenceCollector(
            plan_dir, providers={"firebase": provider, "stub": provider}, clock=_fixed_clock
        )
        config = backend_mod.BackendSessionConfig(
            provider="firebase",  # config will overwrite if project says otherwise
            probes=[backend_mod.BackendProbe(name="x", kind="any")],
        )
        # Per-call provider="firebase" overrides project provider="supabase".
        collector.collect(
            "j",
            provider="firebase",
            project="caller-proj",
            auth="adc",
            session_config=config,
        )
        assert provider.opens[0]["project"] == "caller-proj"
        assert provider.opens[0]["auth"] == "adc"

    def test_no_layer_set_passes_none(self, plan_dir):
        provider = _StubProvider(session=_StubSession())
        collector = backend_mod.BackendEvidenceCollector(
            plan_dir, providers={"stub": provider}, clock=_fixed_clock
        )
        config = backend_mod.BackendSessionConfig(
            provider="stub",
            probes=[backend_mod.BackendProbe(name="x", kind="any")],
        )
        # No project / auth supplied at any tier.
        collector.collect("j", session_config=config)
        assert provider.opens[0]["project"] is None
        assert provider.opens[0]["auth"] is None

    def test_global_config_cannot_carry_runtime_evidence(self):
        """D015 sanity — GlobalConfig refuses runtime_evidence even
        though the backend resolver knows about per-project shape."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            gc.GlobalConfig.model_validate(
                {"runtime_evidence": {"backend": {"provider": "firebase"}}}
            )


# ──────────────────────────  doctor framework  ──────────────────────────


class TestDoctorRegistration:
    def test_all_three_checks_registered(self):
        backend_mod._register_backend_doctor_checks()
        results = doctor_registry.run_all_checks()
        names = {r.name for r in results}
        assert "backend_firebase" in names
        assert "backend_supabase" in names
        assert "backend_generic" in names

    def test_generic_check_passes(self):
        result = backend_mod._backend_generic_check()
        assert result.status == "pass"

    def test_supabase_check_always_warns(self):
        # Slot in v1 — even when SDK is present we still warn (deferred).
        result = backend_mod._backend_supabase_check()
        assert result.status == "warn"
        assert "slot" in result.detail.lower()

    def test_firebase_check_warns_when_sdk_missing(self, monkeypatch):
        monkeypatch.setattr(backend_mod.importlib.util, "find_spec", lambda name: None)
        result = backend_mod._backend_firebase_check()
        assert result.status == "warn"
        assert "firebase_admin" in result.detail

    def test_firebase_check_passes_when_sdk_present(self, monkeypatch):
        # Pretend find_spec returns a non-None object — we don't actually
        # import the SDK, just probe importability.
        class _FakeSpec:
            pass

        monkeypatch.setattr(backend_mod.importlib.util, "find_spec", lambda name: _FakeSpec())
        result = backend_mod._backend_firebase_check()
        assert result.status == "pass"

    def test_no_check_returns_fail(self, monkeypatch):
        # Across all the failure surfaces (SDK missing, supabase slot,
        # generic always-pass) — none should ever be 'fail'.
        monkeypatch.setattr(backend_mod.importlib.util, "find_spec", lambda name: None)
        for fn in (
            backend_mod._backend_firebase_check,
            backend_mod._backend_supabase_check,
            backend_mod._backend_generic_check,
        ):
            assert fn().status != "fail"


# ──────────────────────────  source-grep invariants  ──────────────────────────


class TestSourceInvariants:
    _SRC = (HERE.parents[1] / "runtime_evidence" / "backend.py").read_text()

    def test_no_project_name_special_cases(self):
        """D004: backend adapter must be project-agnostic."""
        lower = self._SRC.lower()
        for needle in ("spin_dine_", "spin-dine_", "glam_", "creator_hub_"):
            assert needle not in lower, (
                f"runtime_evidence/backend.py contains project-specific token {needle!r} (D004)"
            )

    def test_no_credential_storage(self):
        """D005/D014: no credential-bearing literals (allow only the
        pointer regex constants and the supabase/firebase doc strings
        that mention 'sk-' / 'ghp_' / 'Bearer' as forbidden patterns)."""
        # Exclude the lines that ARE the pointer regex / docstrings.
        forbidden = (
            re.compile(r"password\s*=\s*['\"]\w", re.IGNORECASE),
            re.compile(r"^\s*api_key\s*=\s*['\"]\w", re.IGNORECASE | re.MULTILINE),
        )
        for rx in forbidden:
            assert not rx.search(self._SRC), (
                f"runtime_evidence/backend.py contains credential-bearing literal "
                f"matching {rx.pattern!r} (D005/D014)"
            )

    def test_evidence_path_uses_backend_subdir(self):
        """D003: artifacts under post_impl/backend/<journey>."""
        assert (
            'goal_governance_evidence_path(self._plan_dir, "post_impl", f"backend/{journey}")'
            in self._SRC
        )

    def test_no_live_cloud_subprocess_invocations(self):
        """G4 v1 must NOT shell out to gcloud / firebase-tools / supabase
        CLI from this module. Operators wire those via custom providers."""
        forbidden_shells = (
            "gcloud logging read",
            "gcloud firestore",
            "firebase deploy",
            "firebase emulators",
            "supabase db",
            "supabase migration",
        )
        for needle in forbidden_shells:
            assert needle not in self._SRC, (
                f"runtime_evidence/backend.py contains live-cloud shell token "
                f"{needle!r} — operators wire this via a custom provider"
            )
