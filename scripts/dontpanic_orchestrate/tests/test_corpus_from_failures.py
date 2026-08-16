"""Plan 2026-08-09-004 F007 — corpus reconstructed from recorded failures."""

from __future__ import annotations

from dontpanic_orchestrate.smoke.corpus import (
    discover_scenarios,
    provenance_ok,
    run_corpus,
)


class TestCorpusFromFailures:
    def test_every_sourced_scenario_names_incident_and_date(self) -> None:
        sourced = [s for s in discover_scenarios() if s.source_incident]
        assert sourced
        for scenario in sourced:
            assert scenario.source_date
            assert scenario.source_incident

    def test_intended_behavior_is_distinct(self) -> None:
        sourced = [s for s in discover_scenarios() if s.source_incident]
        assert not provenance_ok(sourced)
        for scenario in sourced:
            assert scenario.intended_behavior
            assert scenario.expected_current_behavior
            assert scenario.intended_behavior != scenario.expected_current_behavior

    def test_at_least_one_expected_to_fail(self) -> None:
        flagged = [s for s in discover_scenarios() if s.expected_to_fail]
        assert flagged
        assert all(s.expected_to_fail_reason for s in flagged)

    def test_largest_source_share_is_reported(self) -> None:
        report = run_corpus(execute=False)
        sourced = [r for r in report.rows if r.source_incident]
        assert sourced
        assert 0 < report.largest_source_share <= 1
        assert report.largest_source
        assert f"{report.largest_source_share:.0%}" in report.text

    def test_full_corpus_table_has_no_harness_errors(self) -> None:
        report = run_corpus(execute=True)
        assert report.rows
        assert not any(row.errored for row in report.rows), [
            (row.scenario_id, row.error) for row in report.rows if row.errored
        ]
        assert all(row.scenario_id in report.text for row in report.rows)
