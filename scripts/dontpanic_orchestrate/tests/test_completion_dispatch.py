"""Plan F2 F002 — cross-vendor goal-audit dispatcher tests.

Covers F002's acceptance items (1)–(11):

  - dispatch_completion_audit happy path (stub dispatch returns valid
    JSON; agree → status='agree'; transcript + envelope written).
  - SameVendorRefused fail-fast preserves F1's cross-vendor invariant.
  - DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR override path.
  - DONTPANIC_GOAL_AUDITOR_OFFLINE produces synthetic envelope without
    invoking any executor.
  - Malformed JSON → single 'dispatch_response_malformed' disposition,
    no raise.
  - Auditor disagrees with ≥1 finding → status='disagree'.
  - Audit envelope + transcript filenames match
    'audit-<auditor>-<iter>.{json,transcript.txt}' pattern.
  - Auditor prompt content includes contract + features + findings +
    manifest blocks (greppable).
  - Cross-vendor default — implementer=claude resolves auditor=codex
    via the real F1 resolver path (no project config).
  - Production path uses the resolved agent — stub registry confirms
    the resolved name is the one invoked.

Run::

    PYTHONPATH=scripts python3 -m pytest \\
        scripts/dontpanic_orchestrate/tests/test_completion_dispatch.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import completion_dispatch as cd  # noqa: E402
from dontpanic_orchestrate.completion_auditor import (  # noqa: E402
    CompletionFinding,
    run_completion_audit,
)
from dontpanic_orchestrate.completion_dispatch import (  # noqa: E402
    CompletionAuditTranscript,
    CompletionDispatchError,
    DispatchFn,
    FindingDisposition,
    SameVendorRefused,
    dispatch_completion_audit,
)
from dontpanic_orchestrate.executors.base import (  # noqa: E402
    BaseExecutor,
    DispatchResult,
    DispatchTask,
)
from dontpanic_orchestrate.sufficiency_auditor import (  # noqa: E402
    SufficiencyAuditError,
)

# ──────────────────────────────  fixture helpers  ──────────────────────────────


_VALID_CONTRACT: dict[str, Any] = {
    "goal_type": "parity",
    "source_of_truth": "Some prior plan / curated reference",
    "user_journeys": [
        {
            "name": "onboarding",
            "description": (
                "User opens the app, completes the welcome flow, and lands on "
                "the home screen with their workspace loaded."
            ),
            "surfaces": ["ios", "android"],
            "acceptance_signals": [
                "welcome screen renders within 2 seconds",
            ],
        },
        {
            "name": "publish-flow",
            "description": (
                "Creator drafts a post, attaches a tracked link, and publishes "
                "to the configured channel with disclosure rendered."
            ),
        },
    ],
    "required_evidence": [
        "screenshot-onboarding-welcome",
        "log-publish-flow-dispatched",
    ],
    "completion_test": (
        "Both onboarding and publish-flow run end-to-end without operator intervention."
    ),
}


_DEFAULT_FRONTMATTER = {
    "id": "2026-05-06-999-feat-dispatch-fixture",
    "title": "fixture plan",
    "type": "feat",
    "tier": "local",
    "status": "active",
    "date": "2026-05-06",
    "goal_type": "parity",
    "links": {"objective_contract": "./objective_contract.json"},
    "description": "synthetic fixture plan for completion_dispatch tests",
}


def _write_plan(plan_dir: Path, *, contract: dict | None = None) -> Path:
    """Write a synthetic plan dir with plan.md + objective_contract.json
    + features.json. Mirrors the F001 test helper."""
    plan_dir.mkdir(parents=True)
    contract_data = contract if contract is not None else _VALID_CONTRACT
    (plan_dir / "objective_contract.json").write_text(json.dumps(contract_data))

    import yaml as _yaml

    plan_md = (
        "---\n" + _yaml.safe_dump(_DEFAULT_FRONTMATTER, sort_keys=False) + "---\n\n# fixture\n"
    )
    (plan_dir / "plan.md").write_text(plan_md)
    (plan_dir / "features.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "task_id": "fixture",
                "features": [
                    {
                        "id": "F001",
                        "category": "tooling",
                        "phase": 1,
                        "description": "fixture feature for completion_dispatch testing",
                        "steps": ["a"],
                        "acceptance": "fixture",
                        "passes": True,
                        "depends_on": [],
                        "evidence_refs": [],
                    }
                ],
            }
        )
    )
    return plan_dir


def _write_artifact(
    plan_dir: Path, source: str, journey: str, filename: str, payload: bytes
) -> Path:
    """Write a synthetic captured artifact under
    ``evidence/goal-governance/post_impl/<source>/<journey>/<filename>``."""
    out = plan_dir / "evidence" / "goal-governance" / "post_impl" / source / journey / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    return out


def _seed_findings(plan_dir: Path) -> list[CompletionFinding]:
    """Run the real F001 auditor against the fixture so the dispatcher
    receives realistic CompletionFinding objects."""
    return run_completion_audit(plan_dir)


@pytest.fixture(autouse=True)
def _scrub_env(monkeypatch):
    """Make every test start with a known env state. Tests that need an
    override env explicitly set it through the same monkeypatch."""
    monkeypatch.delenv("DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR", raising=False)
    monkeypatch.delenv("DONTPANIC_GOAL_AUDITOR_OFFLINE", raising=False)
    yield


# ──────────────────────────────  envelope shape  ──────────────────────────────


class TestEnvelopeShape:
    def test_finding_disposition_extra_forbidden(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FindingDisposition.model_validate(
                {
                    "finding_id": "F2C-001",
                    "agree": True,
                    "severity_disposition": "agree",
                    "comment": "ok",
                    "stranger_field": "nope",
                }
            )

    def test_finding_disposition_severity_enum_pinned(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FindingDisposition.model_validate(
                {
                    "finding_id": "F2C-001",
                    "agree": True,
                    "severity_disposition": "catastrophic",
                    "comment": "ok",
                }
            )

    def test_transcript_extra_forbidden(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CompletionAuditTranscript.model_validate(
                {
                    "auditor_agent": "codex",
                    "status": "agree",
                    "iteration": 1,
                    "findings_dispositions": [],
                    "transcript_path": "/tmp/x.txt",
                    "envelope_path": "/tmp/x.json",
                    "generated_at": "2026-05-06T12:00:00+00:00",
                    "stranger_field": "nope",
                }
            )

    def test_transcript_status_enum_pinned(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CompletionAuditTranscript.model_validate(
                {
                    "auditor_agent": "codex",
                    "status": "passed",  # not in literal
                    "iteration": 1,
                    "findings_dispositions": [],
                    "transcript_path": "/tmp/x.txt",
                    "envelope_path": "/tmp/x.json",
                    "generated_at": "2026-05-06T12:00:00+00:00",
                }
            )


# ──────────────────────────────  cross-vendor resolution  ──────────────────────────────


class TestCrossVendorResolution:
    """Acceptance #9 — implementer=claude resolves auditor=codex by
    default via the real F1 resolver."""

    def test_default_resolver_returns_codex_for_claude_implementer(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")
        _write_artifact(plan_dir, "ios", "onboarding", "screenshot-onboarding-welcome.png", b"x")

        captured: dict[str, Any] = {}

        def stub(auditor: str, prompt: str) -> str:
            captured["auditor"] = auditor
            return "[]"

        findings = _seed_findings(plan_dir)
        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="claude",
            dispatch=stub,
        )

        assert captured["auditor"] == "codex"
        assert transcript.auditor_agent == "codex"
        assert transcript.implementer_agent == "claude"

    def test_same_vendor_refused_when_implementer_matches_auditor(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")

        called = {"n": 0}

        def stub(auditor: str, prompt: str) -> str:
            called["n"] += 1
            return "[]"

        with pytest.raises(SameVendorRefused) as exc_info:
            dispatch_completion_audit(
                plan_dir,
                findings=[],
                implementer_agent="codex",  # default auditor is also codex
                dispatch=stub,
            )

        assert called["n"] == 0, "stub must NOT have been called — fail-fast"
        assert "cross-vendor invariant" in str(exc_info.value).lower()
        assert isinstance(exc_info.value, SufficiencyAuditError), (
            "SameVendorRefused must subclass SufficiencyAuditError so callers can catch the F1 base"
        )

    def test_same_vendor_override_env_unblocks(self, tmp_path, monkeypatch):
        plan_dir = _write_plan(tmp_path / "plan")
        _write_artifact(plan_dir, "ios", "onboarding", "screenshot-onboarding-welcome.png", b"x")

        monkeypatch.setenv("DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR", "1")

        captured: dict[str, Any] = {}

        def stub(auditor: str, prompt: str) -> str:
            captured["auditor"] = auditor
            return json.dumps(
                [
                    {
                        "finding_id": f.finding_id,
                        "agree": True,
                        "severity_disposition": "agree",
                        "comment": "override-mode auditor agrees",
                    }
                    for f in findings
                ]
            )

        findings = _seed_findings(plan_dir)
        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="codex",  # same as default auditor
            dispatch=stub,
        )

        assert captured["auditor"] == "codex"
        assert transcript.auditor_agent == "codex"
        assert transcript.status == "agree"

    def test_unknown_resolver_failure_is_not_translated_to_same_vendor(self, tmp_path, monkeypatch):
        """Non-vendor resolver failures (e.g. missing roles config)
        must propagate as SufficiencyAuditError, NOT SameVendorRefused."""
        plan_dir = _write_plan(tmp_path / "plan")

        from dontpanic_orchestrate import completion_dispatch as cd_mod

        def fake_resolver(plan_dir, implementer_agent=None):
            raise SufficiencyAuditError("no goal auditor configured: empty 'auditor'")

        monkeypatch.setattr(cd_mod, "_resolve_goal_auditor_agent", fake_resolver)

        with pytest.raises(SufficiencyAuditError) as exc_info:
            dispatch_completion_audit(
                plan_dir,
                findings=[],
                implementer_agent="claude",
                dispatch=lambda a, p: "[]",
            )

        assert not isinstance(exc_info.value, SameVendorRefused)


# ──────────────────────────────  offline mode  ──────────────────────────────


class TestOfflineMode:
    def test_offline_env_emits_synthetic_envelope(self, tmp_path, monkeypatch):
        plan_dir = _write_plan(tmp_path / "plan")
        monkeypatch.setenv("DONTPANIC_GOAL_AUDITOR_OFFLINE", "1")

        called = {"n": 0}

        def stub(auditor: str, prompt: str) -> str:
            called["n"] += 1
            return "[]"

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=[],
            implementer_agent="claude",
            iteration=1,
            dispatch=stub,
        )

        assert called["n"] == 0, "offline mode MUST NOT invoke dispatch"
        assert transcript.status == "dispatch_skipped_offline"
        assert transcript.findings_dispositions == []
        assert Path(transcript.transcript_path).exists()
        assert Path(transcript.envelope_path).exists()
        envelope = json.loads(Path(transcript.envelope_path).read_text())
        assert envelope["status"] == "dispatch_skipped_offline"

    def test_offline_envelope_files_use_correct_filename_pattern(self, tmp_path, monkeypatch):
        plan_dir = _write_plan(tmp_path / "plan")
        monkeypatch.setenv("DONTPANIC_GOAL_AUDITOR_OFFLINE", "1")

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=[],
            implementer_agent="claude",
            iteration=2,
        )

        assert Path(transcript.envelope_path).name == "audit-codex-2.json"
        assert Path(transcript.transcript_path).name == "audit-codex-2.transcript.txt"


# ──────────────────────────────  filename pattern  ──────────────────────────────


class TestFilenamePattern:
    """Acceptance #6 — audit-<auditor>-<iter>.{json,transcript.txt}."""

    def test_envelope_and_transcript_filenames(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")
        _write_artifact(plan_dir, "ios", "onboarding", "screenshot-onboarding-welcome.png", b"x")
        findings = _seed_findings(plan_dir)

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="claude",
            iteration=3,
            dispatch=lambda a, p: "[]",
        )

        env_p = Path(transcript.envelope_path)
        tr_p = Path(transcript.transcript_path)
        assert env_p.name == "audit-codex-3.json"
        assert tr_p.name == "audit-codex-3.transcript.txt"
        assert env_p.parent.name == "audit"
        assert env_p.parent.parent.name == "post_impl"
        assert env_p.exists() and tr_p.exists()


# ──────────────────────────────  prompt shape  ──────────────────────────────


class TestPromptShape:
    """Acceptance #8 — prompt content includes contract + features +
    findings + manifest blocks."""

    def test_prompt_includes_all_four_context_blocks(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")
        _write_artifact(plan_dir, "ios", "onboarding", "screenshot-onboarding-welcome.png", b"X")
        findings = _seed_findings(plan_dir)

        captured_prompt: dict[str, str] = {}

        def stub(auditor: str, prompt: str) -> str:
            captured_prompt["body"] = prompt
            return "[]"

        dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="claude",
            dispatch=stub,
        )

        body = captured_prompt["body"]
        # Substring assertions over the rendered template.
        assert "## Objective contract" in body
        assert "## Features (as declared)" in body
        assert "## Captured evidence manifest" in body
        assert "## v1 completion findings (your subject of review)" in body
        # Specific contract / features / findings content rendered as JSON.
        assert "publish-flow" in body  # from contract
        assert "fixture feature for completion_dispatch testing" in body  # features
        assert "screenshot-onboarding-welcome" in body  # required_evidence
        # The auditor MUST be told this is a v1 evidence-coverage heuristic.
        # Use whitespace-tolerant regex because the markdown template wraps
        # long sentences across lines; the framing is load-bearing per D002.
        import re

        assert re.search(r"evidence[-\s]+coverage\s+heuristic", body, flags=re.IGNORECASE), (
            "prompt MUST surface the v1 evidence-coverage heuristic framing"
        )
        assert re.search(
            r"NOT\s+a\s+semantic\s+completion\s+proof",
            body,
            flags=re.IGNORECASE,
        ), "prompt MUST tell the auditor this is NOT a semantic completion proof"

    def test_prompt_template_missing_raises(self, tmp_path, monkeypatch):
        plan_dir = _write_plan(tmp_path / "plan")
        monkeypatch.setattr(cd, "_PROMPT_TEMPLATE_PATH", tmp_path / "nonexistent.md")

        with pytest.raises(CompletionDispatchError) as exc_info:
            dispatch_completion_audit(
                plan_dir,
                findings=[],
                implementer_agent="claude",
                dispatch=lambda a, p: "[]",
            )
        assert "prompt template missing" in str(exc_info.value)


# ──────────────────────────────  response parsing  ──────────────────────────────


class TestResponseParsing:
    def test_happy_path_agree_yields_status_agree(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")
        _write_artifact(plan_dir, "ios", "onboarding", "screenshot-onboarding-welcome.png", b"x")
        findings = _seed_findings(plan_dir)
        assert findings, "fixture must produce ≥1 finding for agree-path coverage"

        agree_payload = json.dumps(
            [
                {
                    "finding_id": f.finding_id,
                    "agree": True,
                    "severity_disposition": "agree",
                    "comment": "auditor confirms gap is real",
                }
                for f in findings
            ]
        )

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="claude",
            dispatch=lambda a, p: agree_payload,
        )

        assert transcript.status == "agree"
        assert len(transcript.findings_dispositions) == len(findings)

    def test_disagree_path_yields_status_disagree(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")
        _write_artifact(plan_dir, "ios", "onboarding", "screenshot-onboarding-welcome.png", b"x")
        findings = _seed_findings(plan_dir)
        assert findings

        # Auditor disagrees with the FIRST finding; agrees with the rest.
        dispositions = []
        for i, f in enumerate(findings):
            dispositions.append(
                {
                    "finding_id": f.finding_id,
                    "agree": (i != 0),
                    "severity_disposition": "agree" if i != 0 else "no_finding",
                    "comment": "spurious" if i == 0 else "real gap",
                }
            )
        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="claude",
            dispatch=lambda a, p: json.dumps(dispositions),
        )

        assert transcript.status == "disagree"

    def test_malformed_json_yields_dispatch_response_malformed(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")
        _write_artifact(plan_dir, "ios", "onboarding", "screenshot-onboarding-welcome.png", b"x")
        findings = _seed_findings(plan_dir)

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="claude",
            dispatch=lambda a, p: "not-json-at-all",
        )

        assert transcript.status == "dispatch_response_malformed"
        assert len(transcript.findings_dispositions) == 1
        assert transcript.findings_dispositions[0].finding_id == "dispatch_response_malformed"
        # Raw response preserved for operator forensics.
        assert transcript.raw_response == "not-json-at-all"

    def test_non_array_json_yields_dispatch_response_malformed(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")
        findings = []

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="claude",
            dispatch=lambda a, p: '{"agree": true}',  # object, not array
        )

        assert transcript.status == "dispatch_response_malformed"

    def test_unknown_finding_id_yields_malformed(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")
        _write_artifact(plan_dir, "ios", "onboarding", "screenshot-onboarding-welcome.png", b"x")
        findings = _seed_findings(plan_dir)

        bogus = json.dumps(
            [
                {
                    "finding_id": "F2C-NEVER",
                    "agree": True,
                    "severity_disposition": "agree",
                    "comment": "not a real id",
                }
            ]
        )

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="claude",
            dispatch=lambda a, p: bogus,
        )

        assert transcript.status == "dispatch_response_malformed"

    def test_overlay_finding_id_is_accepted(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")
        _write_artifact(plan_dir, "ios", "onboarding", "screenshot-onboarding-welcome.png", b"x")
        findings = _seed_findings(plan_dir)

        # Mix v1 dispositions + an overlay one.
        payload = []
        for f in findings:
            payload.append(
                {
                    "finding_id": f.finding_id,
                    "agree": True,
                    "severity_disposition": "agree",
                    "comment": "ok",
                }
            )
        payload.append(
            {
                "finding_id": "auditor-overlay-001",
                "agree": True,
                "severity_disposition": "higher",
                "comment": "v1 missed this entirely",
            }
        )

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="claude",
            dispatch=lambda a, p: json.dumps(payload),
        )

        assert transcript.status == "agree"
        overlay = [
            d for d in transcript.findings_dispositions if d.finding_id == "auditor-overlay-001"
        ]
        assert len(overlay) == 1

    def test_empty_array_response_yields_status_agree(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=[],
            implementer_agent="claude",
            dispatch=lambda a, p: "[]",
        )

        assert transcript.status == "agree"
        assert transcript.findings_dispositions == []

    def test_fenced_json_response_is_tolerated(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")
        fenced = "```json\n[]\n```"

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=[],
            implementer_agent="claude",
            dispatch=lambda a, p: fenced,
        )

        assert transcript.status == "agree"


# ──────────────────────────────  envelope on disk  ──────────────────────────────


class TestEnvelopePersistence:
    def test_envelope_and_transcript_round_trip_to_disk(self, tmp_path):
        plan_dir = _write_plan(tmp_path / "plan")
        _write_artifact(plan_dir, "ios", "onboarding", "screenshot-onboarding-welcome.png", b"X")
        findings = _seed_findings(plan_dir)

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="claude",
            dispatch=lambda a, p: "[]",
        )

        env = json.loads(Path(transcript.envelope_path).read_text())
        assert env["auditor_agent"] == "codex"
        assert env["status"] == "dispatch_response_malformed"
        # raw_response is preserved verbatim.
        assert "[]" in Path(transcript.transcript_path).read_text()


# ──────────────────────────────  production path with stub registry  ─────────────


class _StubExecutor(BaseExecutor):
    """In-process stub executor for the production-path test. Mirrors
    F005a's stub pattern; no subprocess invocation."""

    agent_name = "codex"
    cli_binary = "true"  # POSIX: always on PATH
    canned_response = (
        '[{"finding_id": "X", "agree": true, "severity_disposition": "agree", "comment": "ok"}]'
    )

    def __init__(self, *_args, **_kwargs):
        super().__init__()

    def is_available(self) -> bool:  # noqa: D401
        return True

    def dispatch(self, task: DispatchTask) -> DispatchResult:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        # Echo prompt back via raw_response so the test can assert
        # the prompt actually reached the executor.
        return DispatchResult(
            agent="codex",
            agent_role=task.agent_role,
            iteration=task.iteration,
            started_at=now,
            completed_at=now,
            success=True,
            summary="stub dispatch ok",
            raw_response=self.canned_response,
        )


class TestProductionDispatchPath:
    """Acceptance #9 + operator instruction — production path uses
    the resolved agent. Stub the executor registry; assert the
    resolved name is the one invoked, with no real CLI subprocess."""

    def test_production_path_invokes_resolved_executor(self, tmp_path, monkeypatch):
        plan_dir = _write_plan(tmp_path / "plan")
        _write_artifact(plan_dir, "ios", "onboarding", "screenshot-onboarding-welcome.png", b"x")
        findings = _seed_findings(plan_dir)

        invocations: list[str] = []

        class _RecordingStub(_StubExecutor):
            # Override the canned response so the dispatcher's parser
            # can match against the v1 finding_id list.
            def dispatch(self_inner, task: DispatchTask) -> DispatchResult:  # noqa: N805
                invocations.append(self_inner.agent_name)
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc).isoformat()
                payload = json.dumps(
                    [
                        {
                            "finding_id": f.finding_id,
                            "agree": True,
                            "severity_disposition": "agree",
                            "comment": "stub agrees",
                        }
                        for f in findings
                    ]
                )
                return DispatchResult(
                    agent=self_inner.agent_name,
                    agent_role=task.agent_role,
                    iteration=task.iteration,
                    started_at=now,
                    completed_at=now,
                    success=True,
                    summary="ok",
                    raw_response=payload,
                )

        # Patch executor registry so get_executor("codex") returns the stub.
        from dontpanic_orchestrate import completion_dispatch as cd_mod
        from dontpanic_orchestrate import executors as ex_mod

        def fake_get_executor(name: str):
            assert name == "codex", (
                f"resolver returned {name!r} but production path invoked the wrong agent"
            )
            return _RecordingStub()

        monkeypatch.setattr(cd_mod, "get_executor", fake_get_executor)
        # Belt and suspenders — also patch the registry entry directly so
        # any other path that calls into ex_mod sees the same stub.
        monkeypatch.setitem(ex_mod.AGENT_REGISTRY, "codex", _RecordingStub)

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="claude",
            # No dispatch= → production path through registry.
        )

        assert invocations == ["codex"], (
            "production path must invoke exactly the resolved agent, once"
        )
        assert transcript.auditor_agent == "codex"
        assert transcript.status == "agree"

    def test_production_path_refuses_unavailable_executor(self, tmp_path, monkeypatch):
        plan_dir = _write_plan(tmp_path / "plan")
        _write_artifact(plan_dir, "ios", "onboarding", "screenshot-onboarding-welcome.png", b"x")
        findings = _seed_findings(plan_dir)

        class _UnavailableStub(BaseExecutor):
            agent_name = "codex"

            def is_available(self) -> bool:  # noqa: D401
                return False

            def availability_hint(self) -> str:
                return "codex CLI not installed for this test"

            def dispatch(self, task: DispatchTask) -> DispatchResult:
                raise AssertionError("must not be called when is_available() is False")

        from dontpanic_orchestrate import completion_dispatch as cd_mod

        monkeypatch.setattr(cd_mod, "get_executor", lambda name: _UnavailableStub())

        with pytest.raises(CompletionDispatchError) as exc_info:
            dispatch_completion_audit(
                plan_dir,
                findings=findings,
                implementer_agent="claude",
            )
        assert "not available" in str(exc_info.value)


# ──────────────────────────────  greppable invariants  ──────────────────────────────


class TestGreppableInvariants:
    _SRC = Path(cd.__file__).read_text()

    def test_no_runtime_evidence_imports(self):
        """F2 D009 carry-forward — dispatcher MUST NOT import any
        runtime_evidence session class (capture-only invariant)."""
        forbidden = (
            "from dontpanic_orchestrate.runtime_evidence",
            "from runtime_evidence",
            "import runtime_evidence",
        )
        for token in forbidden:
            assert token not in self._SRC, (
                f"dispatcher imported {token!r} — violates capture-only invariant"
            )

    def test_no_project_name_special_cases(self):
        """D013 carry-forward — no project-name special cases."""
        forbidden = ("spin_dine", "glam", "creator_hub", "moltworker")
        lower = self._SRC.lower()
        for token in forbidden:
            assert token not in lower, f"dispatcher contains project-name token {token!r}"

    def test_module_carries_cross_vendor_invariant_framing(self):
        """The cross-vendor invariant (D003 / GG V1 §5) must be
        explicitly stated in the dispatcher docstring so future readers
        do not mistake the override env for default behavior."""
        import re

        assert re.search(r"cross[-\s]+vendor\s+invariant", self._SRC, flags=re.IGNORECASE)
        assert "DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR" in self._SRC
        assert "DONTPANIC_GOAL_AUDITOR_OFFLINE" in self._SRC


# ──────────────────────────────  smoke for DispatchFn typing  ─────────────────────


def test_dispatch_fn_typing_is_callable():
    """DispatchFn is the test-injection seam type alias; assert it is
    importable and callable-shaped."""

    def fn(_agent: str, _prompt: str) -> str:
        return "[]"

    typed: DispatchFn = fn
    assert typed("codex", "ignore") == "[]"


# ────────────────  D008 codex JSONL streaming-output decoder  ────────────────


_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_CODEX_STREAM_FIXTURE = _FIXTURE_DIR / "codex_stream_dogfood_001.txt"


def _build_stream(events: list[dict]) -> str:
    """Render a list of codex stream events as line-delimited JSON,
    matching the protocol shape captured in the dogfood fixture."""
    return "\n".join(json.dumps(e) for e in events) + "\n"


class TestCodexStreamingDecoder:
    """D008 conservatism — `_extract_codex_streaming_payload()` is
    format-tolerant but conservative.

    Plan 2026-05-07-001 lock-time properties:
      (a) shape-gated recognition — only treats input as a codex stream
          when at least one recognized event ``type`` is present;
      (b) last complete assistant message wins — extraction confined to
          ``item.completed`` events whose ``item.type == 'agent_message'``;
          partial events and non-agent_message item types ignored;
      (c) deterministic ambiguity — multiple ``agent_message`` items →
          last in stream order, asserted by identity not superset;
      (d) malformed input → existing raw failure path with useful error,
          NOT silent empty: helper returning None never short-circuits;
          downstream raw-JSON path runs on the original ``response``;
          on failure ``status='dispatch_response_malformed'`` with
          ``raw_response`` preserving original bytes.
    """

    # ──────  (a) shape-gated recognition  ──────

    def test_helper_is_exposed(self):
        """White-box: the conservative extractor is a real attribute on
        the module so the integration point is exercisable in tests
        independent of dispatch_completion_audit's full plumbing."""
        assert hasattr(cd, "_extract_codex_streaming_payload"), (
            "D008 helper `_extract_codex_streaming_payload` must exist on "
            "completion_dispatch module"
        )

    def test_arbitrary_jsonl_without_codex_shape_returns_none(self):
        """Two valid JSON objects per line, but neither carries a
        recognized codex ``type``. Helper must NOT misidentify this as
        a codex stream."""
        arbitrary = '{"foo":"bar"}\n{"baz":42}\n'
        assert cd._extract_codex_streaming_payload(arbitrary) is None

    def test_arbitrary_jsonl_falls_through_to_existing_raw_path(self, tmp_path):
        """End-to-end (a)+(d): non-codex JSONL input → helper None →
        raw-JSON path runs on original → ``dispatch_response_malformed``
        envelope with original bytes preserved verbatim. NO silent empty
        result."""
        plan_dir = _write_plan(tmp_path / "plan")
        non_codex = '{"foo":"bar"}\n{"baz":42}\n'
        transcript = dispatch_completion_audit(
            plan_dir,
            findings=[],
            implementer_agent="claude",
            dispatch=lambda a, p: non_codex,
        )
        assert transcript.status == "dispatch_response_malformed"
        assert transcript.raw_response == non_codex
        assert transcript.findings_dispositions[0].finding_id == "dispatch_response_malformed"

    def test_recognized_stream_with_no_agent_message_returns_none(self):
        """Stream shape recognized but no ``agent_message`` item — helper
        returns None per D008(a)+(b). Falls through to raw path."""
        stream = _build_stream(
            [
                {"type": "thread.started"},
                {"type": "turn.started"},
                {"type": "turn.completed"},
            ]
        )
        assert cd._extract_codex_streaming_payload(stream) is None

    # ──────  (b) last complete assistant message wins  ──────

    def test_only_non_agent_message_item_types_returns_none(self):
        """``tool_use`` / ``reasoning`` / ``command_execution`` items are
        NOT extracted from. Only ``item.type == 'agent_message'`` counts."""
        stream = _build_stream(
            [
                {"type": "thread.started"},
                {
                    "type": "item.completed",
                    "item": {"id": "item_0", "type": "tool_use", "text": "[{}]"},
                },
                {
                    "type": "item.completed",
                    "item": {"id": "item_1", "type": "reasoning", "text": "[{}]"},
                },
                {"type": "turn.completed"},
            ]
        )
        assert cd._extract_codex_streaming_payload(stream) is None

    def test_partial_item_started_without_completed_is_ignored(self):
        """Mid-stream ``item.started`` for an agent_message that was
        never followed by ``item.completed`` MUST NOT be extracted."""
        stream = _build_stream(
            [
                {"type": "thread.started"},
                {
                    "type": "item.started",
                    "item": {"id": "item_0", "type": "agent_message", "text": "[{}]"},
                },
            ]
        )
        # No item.completed agent_message → no candidate text → None.
        assert cd._extract_codex_streaming_payload(stream) is None

    # ──────  (c) deterministic ambiguity resolution — last wins  ──────

    def test_multiple_agent_messages_returns_last_text_identity(self):
        """When multiple ``item.completed`` agent_messages appear in one
        stream, the LAST one's text is chosen — not the first, not the
        longest. Asserted by identity (``==``), not superset."""
        stream = _build_stream(
            [
                {"type": "thread.started"},
                {
                    "type": "item.completed",
                    "item": {"id": "item_0", "type": "agent_message", "text": "FIRST"},
                },
                {
                    "type": "item.completed",
                    "item": {"id": "item_1", "type": "agent_message", "text": "MIDDLE"},
                },
                {
                    "type": "item.completed",
                    "item": {"id": "item_2", "type": "agent_message", "text": "LAST"},
                },
                {"type": "turn.completed"},
            ]
        )
        result = cd._extract_codex_streaming_payload(stream)
        assert result == "LAST", (
            "D008(c) deterministic ambiguity — last-in-stream-order agent_message wins"
        )

    # ──────  (d) malformed input → raw failure path with useful error  ──────

    def test_truncated_stream_yields_dispatch_response_malformed_with_raw(self, tmp_path):
        """Recognized stream prefix but truncated mid-event in the final
        line — final line cannot parse as JSON. No agent_message text
        was completed. Helper returns None; raw path runs on the original
        truncated bytes; envelope is ``dispatch_response_malformed`` and
        ``raw_response`` is preserved verbatim. NO silent empty."""
        plan_dir = _write_plan(tmp_path / "plan")
        truncated = (
            '{"type":"thread.started"}\n'
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message",'
            '"text":"[{\\"truncate'
        )
        transcript = dispatch_completion_audit(
            plan_dir,
            findings=[],
            implementer_agent="claude",
            dispatch=lambda a, p: truncated,
        )
        assert transcript.status == "dispatch_response_malformed"
        assert transcript.raw_response == truncated, (
            "raw_response must preserve the truncated input verbatim for diagnosis"
        )

    # ──────  per-line malformed tolerance (helper does not abort scan)  ──────

    def test_mid_stream_malformed_line_is_skipped_scan_continues(self):
        """An unparseable line mid-stream MUST NOT abort the scan —
        subsequent lines still register and the agent_message is still
        extracted. (Real codex streams have occasionally emitted
        partial-write lines under load.)"""
        stream = (
            '{"type":"thread.started"}\n'
            "this is not valid JSON at all\n"
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message",'
            '"text":"OK"}}\n'
            '{"type":"turn.completed"}\n'
        )
        assert cd._extract_codex_streaming_payload(stream) == "OK"

    # ──────  empty / whitespace-only agent_message text  ──────

    def test_empty_agent_message_text_returns_none(self):
        """An ``agent_message`` whose ``text`` is empty or whitespace-only
        is treated as non-extractable — helper returns None and the raw
        path runs on the original."""
        stream = _build_stream(
            [
                {"type": "thread.started"},
                {
                    "type": "item.completed",
                    "item": {"id": "item_0", "type": "agent_message", "text": ""},
                },
                {"type": "turn.completed"},
            ]
        )
        assert cd._extract_codex_streaming_payload(stream) is None

    # ──────  fenced agent_message text passes through strip-fence  ──────

    def test_fenced_agent_message_text_is_strip_fenced(self, tmp_path):
        """Codex sometimes wraps the JSON payload in ```json fences inside
        its agent_message ``text``. The existing strip-fence path must
        still kick in after streaming extraction."""
        plan_dir = _write_plan(tmp_path / "plan")
        stream = _build_stream(
            [
                {"type": "thread.started"},
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_0",
                        "type": "agent_message",
                        "text": "```json\n[]\n```",
                    },
                },
                {"type": "turn.completed"},
            ]
        )
        transcript = dispatch_completion_audit(
            plan_dir,
            findings=[],
            implementer_agent="claude",
            dispatch=lambda a, p: stream,
        )
        # Empty array against empty findings → "agree" (existing behavior).
        assert transcript.status == "agree"

    # ──────  fixture-driven happy path (acceptance #4)  ──────

    def test_fixture_dogfood_extracts_full_disposition_list(self, tmp_path):
        """End-to-end fixture-driven assertion. Reads the captured-from-
        dogfood transcript at
        ``tests/fixtures/codex_stream_dogfood_001.txt`` (origin: parent
        plan ``2026-05-06-003`` close-out commit ``616ad94``) and
        asserts the parser extracts the disposition payload intact.

        Fixture truth: 12 v1 finding_ids ``F2C-E001..F2C-E012`` plus 1
        ``auditor-overlay-001`` = 13 dispositions total. Plan F001
        acceptance bar item (4) cited 14 (12 v1 + 2 overlays) — that
        prose, inherited from the parent close-out memo, was a
        fixture-citation artifact; the captured transcript actually
        contains 13. This test asserts what the fixture truly contains."""
        assert _CODEX_STREAM_FIXTURE.is_file(), f"D003 fixture missing at {_CODEX_STREAM_FIXTURE}"
        fixture_text = _CODEX_STREAM_FIXTURE.read_text()

        plan_dir = _write_plan(tmp_path / "plan")
        # Construct findings whose finding_ids match the fixture's
        # disposition payload so the parser's valid_finding_ids gate
        # accepts each v1 disposition. The auditor-overlay-* prefix is
        # accepted regardless via the dispatcher's existing prefix rule.
        findings = [
            CompletionFinding(
                finding_id=f"F2C-E{i:03d}",
                gap_class="missing_evidence",
                severity="high",
                title=f"v1 fixture finding {i}",
                narrative="seeded for codex_stream_dogfood_001 fixture-driven test",
                subsystem="goal-governance",
                journey="configure-runtime-evidence",
            )
            for i in range(1, 13)
        ]

        transcript = dispatch_completion_audit(
            plan_dir,
            findings=findings,
            implementer_agent="claude",
            dispatch=lambda a, p: fixture_text,
        )

        # Most load-bearing property: status is no longer
        # dispatch_response_malformed once the parser understands the
        # streaming format.
        assert transcript.status != "dispatch_response_malformed", (
            "parser must recognize codex streaming output as the dogfood transcript"
        )
        # 12 v1 + 1 auditor-overlay-001 = 13 (fixture truth, not the 14
        # cited in plan acceptance — see test docstring for context).
        assert len(transcript.findings_dispositions) == 13
        v1_ids = sorted(
            d.finding_id
            for d in transcript.findings_dispositions
            if not d.finding_id.startswith("auditor-overlay-")
        )
        assert v1_ids == [f"F2C-E{i:03d}" for i in range(1, 13)]
        overlay_ids = sorted(
            d.finding_id
            for d in transcript.findings_dispositions
            if d.finding_id.startswith("auditor-overlay-")
        )
        assert overlay_ids == ["auditor-overlay-001"]

    # ──────  backward-compat regression for raw-JSON inputs  ──────

    def test_raw_json_array_input_falls_through_unchanged(self, tmp_path):
        """D004 — non-streaming raw-JSON inputs (the legacy stub
        contract) must still parse via the existing path. The bare list
        does not parse line-by-line into a recognized codex shape —
        ``saw_recognized_shape`` stays False — helper returns None —
        existing strip-fence + raw-JSON parse runs unchanged."""
        plan_dir = _write_plan(tmp_path / "plan")
        bare_json = json.dumps(
            [
                {
                    "finding_id": "auditor-overlay-001",
                    "agree": True,
                    "severity_disposition": "agree",
                    "comment": "ok",
                }
            ]
        )
        transcript = dispatch_completion_audit(
            plan_dir,
            findings=[],
            implementer_agent="claude",
            dispatch=lambda a, p: bare_json,
        )
        assert transcript.status == "agree"
        assert len(transcript.findings_dispositions) == 1
