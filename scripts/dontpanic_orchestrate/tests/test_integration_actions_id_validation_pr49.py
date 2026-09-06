"""PR49 follow-up (r3408996308): reject non-canonical integration/action ids
at the evidence boundary and filter reads to the exact canonical id.

Before: ``write_integration_evidence(dir, "../static-dashboard", ...)`` wrote a
record into ``static-dashboard.jsonl`` and could advance or clear the REAL
static-dashboard card, because status derivation matched on action_id/outcome
only. After: the writer validates ``(integration_id, action_id)`` against
``INTEGRATION_CATALOG`` before touching disk, and the reader drops records
whose stored id is not the canonical id it was asked for.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import global_config  # noqa: E402
from dontpanic_orchestrate import integration_actions as itg  # noqa: E402
from dontpanic_orchestrate.integrations_cli import integrations_main  # noqa: E402

CANON = "static-dashboard"
ACTION = "static-dashboard-smoke"
ALIAS = "../static-dashboard"  # sanitizes to the SAME filename as CANON


def _write(evidence_dir: Path, integration_id: str, action_id: str = ACTION) -> Path:
    return itg.write_integration_evidence(
        evidence_dir, integration_id, action_id, source="attestation", outcome="passed"
    )


class TestWriterRejectsNonCatalogIds:
    def test_alias_that_collides_with_a_real_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a catalog integration"):
            _write(tmp_path, ALIAS)
        assert not (tmp_path / f"{CANON}.jsonl").exists()
        assert list(tmp_path.glob("*.jsonl")) == []

    def test_unknown_integration_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a catalog integration"):
            _write(tmp_path, "no-such-integration")

    def test_known_integration_with_foreign_action_is_refused(self, tmp_path: Path) -> None:
        # linear-creds is a real action, but of a different integration.
        with pytest.raises(ValueError, match="not a catalog action"):
            _write(tmp_path, CANON, "linear-creds")
        assert not (tmp_path / f"{CANON}.jsonl").exists()

    def test_trigger_attestation_allowed_only_for_gated_rows(self, tmp_path: Path) -> None:
        # The gated Firebase bands (F003) attest the TRIGGER before the
        # credentialed action; that pair is legitimate for rows declaring a
        # trigger_condition and nothing else.
        gated = sorted({a.integration_id for a in itg.INTEGRATION_CATALOG if a.trigger_condition})
        assert gated, "catalog fixture lost its gated rows"
        for iid in gated:
            assert _write(tmp_path, iid, itg.TRIGGER_ACTION_FIREBASE).is_file()
        with pytest.raises(ValueError, match="not a catalog action"):
            _write(tmp_path, CANON, itg.TRIGGER_ACTION_FIREBASE)

    def test_every_catalog_pair_still_writes(self, tmp_path: Path) -> None:
        for action in itg.INTEGRATION_CATALOG:
            path = _write(tmp_path, action.integration_id, action.action_id)
            assert path.is_file()
        statuses = itg.derive_integration_status(tmp_path)
        assert all(s.has_evidence for s in statuses.values())


class TestReaderFiltersToCanonicalId:
    def test_legacy_alias_record_in_canonical_file_is_ignored(self, tmp_path: Path) -> None:
        # A record that pre-dates the writer guard (or was hand-written) and
        # carries the alias as its stored id must not satisfy the real card.
        target = tmp_path / f"{CANON}.jsonl"
        target.write_text(
            json.dumps(
                {
                    "schema_version": itg.EVIDENCE_SCHEMA_VERSION,
                    "integration_id": ALIAS,
                    "action_id": ACTION,
                    "captured_at": "2026-09-05T00:00:00Z",
                    "source": "attestation",
                    "outcome": "passed",
                }
            )
            + "\n"
        )
        assert itg.read_evidence(tmp_path, CANON) == []
        status = itg.derive_integration_status(tmp_path)[CANON]
        assert status.status == itg.STATUS_PENDING
        assert status.has_evidence is False

    def test_canonical_record_is_returned(self, tmp_path: Path) -> None:
        _write(tmp_path, CANON)
        recs = itg.read_evidence(tmp_path, CANON)
        assert len(recs) == 1 and recs[0]["integration_id"] == CANON


class TestAttestCli:
    """Public entry point: ``dontpanic integrations attest``."""

    @staticmethod
    def _evidence_dir() -> Path:
        return global_config.dontpanic_home() / itg.EVIDENCE_SUBDIR

    def test_alias_attest_is_a_usage_error_and_writes_nothing(self, capsys) -> None:
        rc = integrations_main(["attest", ALIAS, "--action", ACTION, "--outcome", "passed"])
        assert rc == 2
        assert "not a catalog integration" in capsys.readouterr().err
        assert not (self._evidence_dir() / f"{CANON}.jsonl").exists()
        assert itg.derive_integration_status(self._evidence_dir())[CANON].has_evidence is False

    def test_foreign_action_attest_is_a_usage_error(self, capsys) -> None:
        rc = integrations_main(["attest", CANON, "--action", "linear-creds", "--outcome", "passed"])
        assert rc == 2
        assert "not a catalog action" in capsys.readouterr().err

    def test_canonical_attest_still_records(self) -> None:
        rc = integrations_main(
            ["attest", "linear-credentials", "--action", "linear-creds", "--outcome", "passed"]
        )
        assert rc == 0
        recs = itg.read_evidence(self._evidence_dir(), "linear-credentials")
        assert recs and recs[-1]["action_id"] == "linear-creds"
