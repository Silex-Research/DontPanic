"""Plan 2026-06-04-003 F002 — append-only evidence writer + render-proof smoke + attest.

Contracts (lock-binding; see plan.md):
- write_integration_evidence() appends one JSONL record per call to a
  per-integration file under the DontPanic-home integrations evidence dir:
  schema_version, integration_id, action_id, captured_at, source
  (smoke|attestation), outcome (passed|failed), sanitized details; 0600/0700.
  A later failed record never rewrites or deletes prior records.
- run_static_dashboard_smoke() runs the REAL dashboard build over the exported
  state and asserts render-proof markers in the BUILT artifact (what-now.json),
  not just parseable state JSON; garbled state → outcome=failed.
- `dontpanic integrations attest` records an operator attestation through the
  same writer (attest-then-read round trip).
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import integration_actions as itg  # noqa: E402


@pytest.fixture()
def evidence_dir(tmp_path):
    return tmp_path / "integrations" / "evidence"


def _records(evidence_dir, integration_id):
    return itg.read_evidence(evidence_dir, integration_id)


class TestEvidenceWriter:
    def test_append_one_record_with_required_fields(self, evidence_dir):
        path = itg.write_integration_evidence(
            evidence_dir,
            "static-dashboard",
            "static-dashboard-smoke",
            source="smoke",
            outcome="passed",
        )
        recs = _records(evidence_dir, "static-dashboard")
        assert len(recs) == 1
        r = recs[0]
        assert r["schema_version"]
        assert r["integration_id"] == "static-dashboard"
        assert r["action_id"] == "static-dashboard-smoke"
        assert r["source"] == "smoke"
        assert r["outcome"] == "passed"
        assert "captured_at" in r
        assert path.name == "static-dashboard.jsonl"

    def test_append_only_never_rewrites_prior_records(self, evidence_dir):
        itg.write_integration_evidence(
            evidence_dir, "firebase-functions-deploy", "firebase-deploy",
            source="attestation", outcome="passed",
        )
        first_bytes = itg.evidence_file(evidence_dir, "firebase-functions-deploy").read_bytes()
        itg.write_integration_evidence(
            evidence_dir, "firebase-functions-deploy", "firebase-deploy",
            source="attestation", outcome="failed",
        )
        recs = _records(evidence_dir, "firebase-functions-deploy")
        assert len(recs) == 2
        # the first record's bytes are still a prefix — nothing rewrote it
        assert itg.evidence_file(
            evidence_dir, "firebase-functions-deploy"
        ).read_bytes().startswith(first_bytes)
        assert recs[0]["outcome"] == "passed" and recs[1]["outcome"] == "failed"
        # floor-from-history: a prior pass survives a later fail
        assert itg.has_passed_evidence(recs, "firebase-deploy")

    def test_secret_values_sanitized_in_details(self, evidence_dir):
        itg.write_integration_evidence(
            evidence_dir, "discord-webhook", "discord-webhook",
            source="attestation", outcome="passed",
            details={"note": "set token=ghp_abcdefghijklmnop0123 then attested"},
        )
        raw = itg.evidence_file(evidence_dir, "discord-webhook").read_text()
        assert "ghp_abcdefghijklmnop0123" not in raw
        assert "[redacted-secret]" in raw

    def test_file_and_dir_modes_tightened(self, evidence_dir):
        itg.write_integration_evidence(
            evidence_dir, "linear-credentials", "linear-creds",
            source="attestation", outcome="passed",
        )
        f = itg.evidence_file(evidence_dir, "linear-credentials")
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
        assert stat.S_IMODE(evidence_dir.stat().st_mode) == 0o700

    def test_outcome_must_be_passed_or_failed(self, evidence_dir):
        with pytest.raises(ValueError):
            itg.write_integration_evidence(
                evidence_dir, "static-dashboard", "static-dashboard-smoke",
                source="smoke", outcome="maybe",
            )

    def test_path_traversal_in_integration_id_is_refused_not_neutralized(self, evidence_dir):
        # PR49 r3408996308: the writer no longer maps a traversal/alias id onto
        # a canonical filename — it refuses before any write, so nothing lands
        # inside OR outside evidence_dir.
        with pytest.raises(ValueError, match="not a catalog integration"):
            itg.write_integration_evidence(
                evidence_dir, "../escape", "x", source="smoke", outcome="passed",
            )
        assert list(evidence_dir.rglob("*.jsonl")) == []


class TestRenderProofSmoke:
    def test_smoke_passes_when_producer_cards_reach_built_artifact(self, tmp_path, evidence_dir):
        # The integration provider always emits cards; the render-proof asserts
        # those producer cards reach the BUILT what-now.json (not just the copied
        # state JSON). A clean build over an empty ledger still renders them.
        plans_root = tmp_path / "plans"
        plans_root.mkdir()

        result = itg.run_static_dashboard_smoke(
            plans_root=plans_root,
            build_dir=tmp_path / "build",
            evidence_dir=evidence_dir,
        )
        assert result.outcome == "passed", result.detail
        # the producer's own static-dashboard card is in the BUILT artifact
        what_now = (tmp_path / "build" / "what-now.json").read_text()
        assert "integration:static-dashboard:static-dashboard-smoke" in what_now
        recs = _records(evidence_dir, "static-dashboard")
        assert recs and recs[-1]["outcome"] == "passed" and recs[-1]["source"] == "smoke"

    def test_smoke_fails_on_silently_empty_render(self, tmp_path, evidence_dir, monkeypatch):
        # Simulate a parseable-but-broken render: the build writes a
        # state-snapshot.json but a what-now.json with an EMPTY items array,
        # while the producer still expects the integration cards. The smoke must
        # catch the dropped cards and record outcome=failed.
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        build_dir = tmp_path / "build"

        from dontpanic_orchestrate import dashboard as _dash

        def _degraded_build(*, out_dir, **_kwargs):
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "state-snapshot.json").write_text(
                json.dumps({"schema_version": "1", "streams": {}})
            )
            (out_dir / "what-now.json").write_text(json.dumps({"items": []}))

        monkeypatch.setattr(_dash, "build", _degraded_build)

        result = itg.run_static_dashboard_smoke(
            plans_root=plans_root,
            build_dir=build_dir,
            evidence_dir=evidence_dir,
        )
        assert result.outcome == "failed"
        assert "silently-empty" in result.detail or "dropped" in result.detail
        recs = _records(evidence_dir, "static-dashboard")
        assert recs and recs[-1]["outcome"] == "failed"

    def test_smoke_fails_when_build_raises(self, tmp_path, evidence_dir, monkeypatch):
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        from dontpanic_orchestrate import dashboard as _dash

        def _boom(**_kwargs):
            raise RuntimeError("export blew up")

        monkeypatch.setattr(_dash, "build", _boom)
        result = itg.run_static_dashboard_smoke(
            plans_root=plans_root,
            build_dir=tmp_path / "build",
            evidence_dir=evidence_dir,
        )
        assert result.outcome == "failed"
        assert "build raised" in result.detail
        recs = _records(evidence_dir, "static-dashboard")
        assert recs and recs[-1]["outcome"] == "failed"
