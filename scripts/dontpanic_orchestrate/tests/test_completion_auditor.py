"""Plan F2 F001 — completion auditor tests.

Covers F001's acceptance items (1)–(13):

  - Pydantic models: CompletionFinding (extra='forbid';
    gap_class enum); CompletionFindingsEnvelope with
    ``audit_kind: Literal['v1_evidence_coverage_heuristic']``.
  - run_completion_audit happy path: contract w/ N matchers + N
    fixtures, returns 0 findings.
  - missing_evidence: 1 unmatched matcher → 1 finding with
    matcher_string populated.
  - journey_gap: orphan journey → 1 high-severity finding.
  - F0 normalization round-trips through classify_goal_gap_cluster
    without raising.
  - cluster_findings groups by (subsystem, journey).
  - _build_evidence_manifest reconstructs sha256 hashes that match
    direct artifact bytes.
  - matcher edge cases (empty matcher, special chars, note-only match).
  - envelope audit_kind field is load-bearing literal (greppable).
  - module + run_completion_audit docstrings carry coverage-heuristic
    framing (greppable D002).
  - D013 carry-forward — no project-name special cases.

Run:

    PYTHONPATH=scripts python3 -m pytest \
        scripts/dontpanic_orchestrate/tests/test_completion_auditor.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.completion_auditor import (  # noqa: E402
    COMPLETION_AUDIT_KIND,
    COMPLETION_FINDINGS_ARTIFACT,
    COMPLETION_GAP_CLASSES,
    CompletionAuditError,
    CompletionFinding,
    CompletionFindingsEnvelope,
    _build_evidence_manifest,
    _emit_journey_gaps,
    _match_required_evidence,
    cluster_findings,
    make_cluster_context,
    run_completion_audit,
    to_goal_gap_findings,
)
from dontpanic_orchestrate.nested_orchestration import (  # noqa: E402
    classify_goal_gap_cluster,
)

# ──────────────────────────────  fixture helpers  ──────────────────────────────


_VALID_CONTRACT = {
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
                "home screen receives correct workspace",
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


def _write_plan(plan_dir: Path, *, contract: dict | None = None) -> Path:
    plan_dir.mkdir(parents=True)
    contract_data = contract if contract is not None else _VALID_CONTRACT
    (plan_dir / "objective_contract.json").write_text(json.dumps(contract_data))

    fm = {
        "id": "2026-05-06-999-feat-completion-fixture",
        "title": "fixture plan",
        "type": "feat",
        "tier": "local",
        "status": "active",
        "date": "2026-05-06",
        "goal_type": "parity",
        "links": {"objective_contract": "./objective_contract.json"},
        "description": "synthetic fixture plan for completion_auditor tests",
    }
    import yaml as _yaml

    plan_md = "---\n" + _yaml.safe_dump(fm, sort_keys=False) + "---\n\n# fixture\n"
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
                        "description": "fixture feature for completion audit testing",
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
    evidence/goal-governance/post_impl/<source>/<journey>/<filename>."""
    out = plan_dir / "evidence" / "goal-governance" / "post_impl" / source / journey / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    return out


# ──────────────────────────────  Pydantic shape  ──────────────────────────────


class TestCompletionFindingShape:
    def test_extra_forbidden(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CompletionFinding.model_validate(
                {
                    "finding_id": "F2C-001",
                    "gap_class": "missing_evidence",
                    "severity": "high",
                    "title": "X",
                    "narrative": "Y",
                    "subsystem": "web",
                    "journey": "onboarding",
                    "stranger_field": "nope",
                }
            )

    def test_gap_class_enum_pinned(self):
        assert COMPLETION_GAP_CLASSES == (
            "missing_evidence",
            "journey_gap",
            "integration_gap",
        )

    def test_severity_validation(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CompletionFinding.model_validate(
                {
                    "finding_id": "X",
                    "gap_class": "missing_evidence",
                    "severity": "catastrophic",  # not in F0 enum
                    "title": "X",
                    "narrative": "Y",
                    "subsystem": "web",
                    "journey": "onboarding",
                }
            )


class TestCompletionFindingsEnvelopeShape:
    def test_audit_kind_pinned_to_v1_literal(self):
        from pydantic import ValidationError

        # Wrong audit_kind → reject.
        with pytest.raises(ValidationError):
            CompletionFindingsEnvelope.model_validate(
                {
                    "audit_kind": "semantic_completion_proof",  # forbidden
                    "generated_at": "2026-05-06T12:00:00+00:00",
                    "plan_id": "X",
                    "contract_path": "objective_contract.json",
                    "evidence_manifest_uris": [],
                    "findings": [],
                }
            )

    def test_audit_kind_constant_matches_envelope(self):
        # Greppable: the module-level constant matches the Literal.
        env = CompletionFindingsEnvelope(
            audit_kind=COMPLETION_AUDIT_KIND,
            generated_at="2026-05-06T12:00:00+00:00",
            plan_id="X",
            contract_path="objective_contract.json",
            evidence_manifest_uris=[],
            findings=[],
        )
        assert env.audit_kind == "v1_evidence_coverage_heuristic"


# ──────────────────────────────  evidence manifest rebuild  ──────────────────────────────


class TestBuildEvidenceManifest:
    def test_rebuild_hash_matches_artifact_bytes(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        a = _write_artifact(plan, "web", "onboarding", "screenshot-welcome.png", b"png-bytes-1")
        b = _write_artifact(plan, "ios", "publish-flow", "log-published.log", b"log-bytes-2")
        refs = _build_evidence_manifest(plan)
        # Order-stable: refs sorted by uri.
        uris = [r.uri for r in refs]
        assert uris == sorted(uris)
        assert len(refs) == 2

        # Hash matches direct sha256 of artifact bytes.
        for path, expected_payload in [(a, b"png-bytes-1"), (b, b"log-bytes-2")]:
            ref = next(r for r in refs if r.uri.endswith(path.name))
            expected_hash = "sha256:" + hashlib.sha256(expected_payload).hexdigest()
            assert ref.hash == expected_hash

    def test_empty_evidence_dir_returns_empty_list(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        # No artifacts.
        refs = _build_evidence_manifest(plan)
        assert refs == []

    def test_evidence_type_inferred_from_extension(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        _write_artifact(plan, "web", "j", "screenshot-x.png", b"png")
        _write_artifact(plan, "ios", "j", "log-y.log", b"log")
        refs = _build_evidence_manifest(plan)
        # Find by uri suffix.
        screenshot_ref = next(r for r in refs if r.uri.endswith("screenshot-x.png"))
        log_ref = next(r for r in refs if r.uri.endswith("log-y.log"))
        assert screenshot_ref.type.value == "screenshot"
        assert log_ref.type.value == "log"

    def test_does_not_invoke_runtime_evidence_session_classes(self):
        """D009 carry-forward — manifest rebuild is filesystem IO + sha256
        only. No imports of WebDriver / IosDriver / AndroidDriver /
        BackendProvider at module level."""
        src = (HERE.parents[1] / "completion_auditor.py").read_text()
        forbidden_imports = (
            "from dontpanic_orchestrate.runtime_evidence.web import",
            "from dontpanic_orchestrate.runtime_evidence.ios import",
            "from dontpanic_orchestrate.runtime_evidence.android import",
            "from dontpanic_orchestrate.runtime_evidence.backend import",
            "from dontpanic_orchestrate.runtime_evidence.harness import",
        )
        for needle in forbidden_imports:
            assert needle not in src, (
                f"completion_auditor.py imports {needle!r} — D009 violation. "
                "Manifest rebuild must NOT instantiate runtime_evidence sessions."
            )


# ──────────────────────────────  matcher  ──────────────────────────────


class TestMatcher:
    def test_substring_matches_uri(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        _write_artifact(plan, "web", "onboarding", "screenshot-welcome.png", b"x")
        refs = _build_evidence_manifest(plan)
        matched = _match_required_evidence("screenshot-welcome", refs)
        assert len(matched) == 1
        assert matched[0].uri.endswith("screenshot-welcome.png")

    def test_substring_matches_note_when_uri_misses(self, tmp_path):
        # Build a manual EvidenceRef whose note carries the matcher string;
        # uri does not. Bypass _build_evidence_manifest for this case so
        # we exercise note-matching independently of artifact files.
        from dontpanic_orchestrate.completion_auditor import EvidenceRef as _ER
        from dontpanic_orchestrate.completion_auditor import EvidenceType as _ET

        ref = _ER(
            type=_ET.log,
            uri="evidence/goal-governance/post_impl/web/x/file.log",
            hash="sha256:0",
            captured_at="2026-05-06T00:00:00+00:00",
            captured_by="stub",
            note="probe=specific-marker; kind=log",
        )
        matched = _match_required_evidence("specific-marker", [ref])
        assert len(matched) == 1

    def test_no_match_returns_empty(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        _write_artifact(plan, "web", "j", "x.png", b"x")
        refs = _build_evidence_manifest(plan)
        matched = _match_required_evidence("totally-absent-string", refs)
        assert matched == []

    def test_empty_matcher_string_treated_as_no_match(self, tmp_path):
        # Empty matchers are nonsense; document that we treat them as
        # unmatched (they'll surface as missing_evidence findings, prompting
        # the operator to fix the contract). NOT 'matches everything'.
        plan = _write_plan(tmp_path / "plan")
        _write_artifact(plan, "web", "j", "x.png", b"x")
        refs = _build_evidence_manifest(plan)
        matched = _match_required_evidence("", refs)
        assert matched == []


# ──────────────────────────────  journey-gap detection  ──────────────────────────────


class TestEmitJourneyGaps:
    def test_orphan_journey_emits_high_severity_finding(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        # Artifacts only under 'onboarding'; 'publish-flow' is orphan.
        _write_artifact(plan, "web", "onboarding", "x.png", b"x")
        refs = _build_evidence_manifest(plan)

        from dontpanic_orchestrate.completion_auditor import _load_objective_contract

        contract = _load_objective_contract(plan)
        findings = _emit_journey_gaps(contract, refs)
        # publish-flow is orphan; onboarding has coverage.
        gaps = [f for f in findings if f.gap_class == "journey_gap"]
        assert len(gaps) == 1
        assert gaps[0].journey == "publish-flow"
        assert gaps[0].severity == "high"

    def test_no_orphans_emits_no_findings(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        _write_artifact(plan, "web", "onboarding", "x.png", b"x")
        _write_artifact(plan, "ios", "publish-flow", "y.log", b"y")
        refs = _build_evidence_manifest(plan)

        from dontpanic_orchestrate.completion_auditor import _load_objective_contract

        contract = _load_objective_contract(plan)
        findings = _emit_journey_gaps(contract, refs)
        assert findings == []


# ──────────────────────────────  run_completion_audit (composition)  ──────────────────────────────


class TestRunCompletionAudit:
    def test_happy_path_no_findings(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        # Both required_evidence matchers + both journeys covered.
        _write_artifact(plan, "web", "onboarding", "screenshot-onboarding-welcome.png", b"png")
        _write_artifact(plan, "ios", "publish-flow", "log-publish-flow-dispatched.log", b"log")
        findings = run_completion_audit(plan)
        assert findings == []

        # Envelope file written.
        env_path = (
            plan / "evidence" / "goal-governance" / "post_impl" / COMPLETION_FINDINGS_ARTIFACT
        )
        assert env_path.is_file()
        env = json.loads(env_path.read_text())
        assert env["audit_kind"] == COMPLETION_AUDIT_KIND
        assert env["audit_kind"] == "v1_evidence_coverage_heuristic"
        assert env["findings"] == []

    def test_missing_required_evidence_finding(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        # Only one of two matchers covered.
        _write_artifact(plan, "web", "onboarding", "screenshot-onboarding-welcome.png", b"x")
        _write_artifact(plan, "ios", "publish-flow", "unrelated-name.log", b"x")
        findings = run_completion_audit(plan)
        missing = [f for f in findings if f.gap_class == "missing_evidence"]
        assert len(missing) == 1
        assert missing[0].matcher_string == "log-publish-flow-dispatched"

    def test_journey_gap_finding(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        # Only onboarding has artifacts; publish-flow journey is orphan.
        # Cover the onboarding matcher so the missing_evidence finding
        # for that doesn't show up.
        _write_artifact(plan, "web", "onboarding", "screenshot-onboarding-welcome.png", b"x")
        _write_artifact(
            plan,
            "ios",
            "onboarding",
            "log-publish-flow-dispatched.log",  # matches the matcher even though it's under wrong journey
            b"x",
        )
        findings = run_completion_audit(plan)
        gaps = [f for f in findings if f.gap_class == "journey_gap"]
        assert len(gaps) == 1
        assert gaps[0].journey == "publish-flow"

    def test_envelope_lists_evidence_manifest_uris_sorted(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        _write_artifact(plan, "web", "onboarding", "screenshot-onboarding-welcome.png", b"x")
        _write_artifact(plan, "ios", "publish-flow", "log-publish-flow-dispatched.log", b"y")
        run_completion_audit(plan)
        env_path = (
            plan / "evidence" / "goal-governance" / "post_impl" / COMPLETION_FINDINGS_ARTIFACT
        )
        env = json.loads(env_path.read_text())
        uris = env["evidence_manifest_uris"]
        assert uris == sorted(uris)
        assert len(uris) == 2

    def test_missing_contract_raises(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        (plan_dir / "plan.md").write_text("---\nid: x\ngoal_type: parity\n---\n")
        with pytest.raises(CompletionAuditError):
            run_completion_audit(plan_dir)


# ──────────────────────────────  F0 normalization  ──────────────────────────────


class TestF0Adapters:
    def test_to_goal_gap_findings_round_trips(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        # Trigger 1 missing_evidence + 1 journey_gap.
        _write_artifact(plan, "web", "onboarding", "screenshot-onboarding-welcome.png", b"x")
        findings = run_completion_audit(plan)
        gg_findings = to_goal_gap_findings(findings)
        # Pydantic-validated; just assert shape conversion.
        assert len(gg_findings) == len(findings)
        for orig, gg in zip(findings, gg_findings, strict=True):
            assert gg.severity == orig.severity
            assert gg.finding_id == orig.finding_id
            assert gg.subsystem == orig.subsystem
            assert gg.journey == orig.journey

    def test_cluster_findings_groups_by_subsystem_journey(self, tmp_path):
        plan = _write_plan(tmp_path / "plan")
        findings = run_completion_audit(plan)
        clusters = cluster_findings(findings)
        # All findings should be in clusters keyed by (subsystem, journey).
        for key, cluster in clusters.items():
            subsystem, journey = key
            for f in cluster:
                assert f.subsystem == subsystem
                assert f.journey == journey

    def test_classify_goal_gap_cluster_round_trip(self, tmp_path):
        # Build 3 medium-severity findings in one (subsystem, journey)
        # cluster — F0's child_plan trigger.
        from dontpanic_orchestrate.completion_auditor import (
            CompletionFinding as _CF,
        )

        findings = [
            _CF(
                finding_id=f"F2C-{i:03d}",
                gap_class="missing_evidence",
                severity="medium",
                title=f"missing X{i}",
                narrative="Required evidence not captured.",
                subsystem="web",
                journey="onboarding",
                matcher_string=f"matcher-{i}",
                evidence_uris=[],
            )
            for i in range(3)
        ]
        gg_findings = to_goal_gap_findings(findings)
        ctx = make_cluster_context("web", "onboarding")
        triage = classify_goal_gap_cluster(gg_findings, ctx)
        assert triage == "child_plan"


# ──────────────────────────────  greppable invariants  ──────────────────────────────


class TestGreppableInvariants:
    _SRC = (HERE.parents[1] / "completion_auditor.py").read_text()

    def test_module_docstring_carries_coverage_heuristic_framing(self):
        """D002 — load-bearing framing: module + run_completion_audit docstrings
        explicitly state 'evidence-coverage heuristic' AND 'not a semantic
        completion proof'."""
        # Module-level docstring is the file's first triple-quoted block.
        # Use whitespace-tolerant regex matches so docstring line breaks don't
        # cause false negatives on multi-word phrases.
        import re

        assert re.search(r"evidence[-\s]+coverage\s+heuristic", self._SRC, flags=re.IGNORECASE), (
            "completion_auditor.py source must contain the phrase 'evidence-coverage "
            "heuristic' (D002 framing)"
        )
        # Verify the negation framing is present (NOT a semantic completion proof).
        assert re.search(
            r"not\s+a\s+semantic\s+completion\s+proof",
            self._SRC,
            flags=re.IGNORECASE,
        ), (
            "completion_auditor.py source must contain 'not a semantic completion "
            "proof' (case-insensitive) — the load-bearing D002 negation"
        )

    def test_audit_kind_constant_pinned_in_source(self):
        """Greppable D002: the audit_kind literal is pinned in source."""
        assert '"v1_evidence_coverage_heuristic"' in self._SRC, (
            "completion_auditor.py must contain the literal "
            '"v1_evidence_coverage_heuristic" so the envelope shape is '
            "static and downstream-grep-friendly"
        )

    def test_no_project_name_special_cases(self):
        """D013 carry-forward — completion auditor must be project-agnostic."""
        lower = self._SRC.lower()
        for needle in ("spin_dine_", "spin-dine_", "glam_", "creator_hub_"):
            assert needle not in lower, (
                f"completion_auditor.py contains project-specific token "
                f"{needle!r} (D013 / Plan G D004 carry-forward)"
            )
