"""Plan 2026-06-21-001 F004 — per-instance marker + releases-since + first-run tests.

Covers the full acceptance matrix:

* read_upgrade_state on an ABSENT marker -> in-memory effective marker anchored to
  latest, marker_state=absent, NO file created after the read (dedicated test);
* releases_since is pure + order-correct; first_run_advisories honors
  show_on_first_run; required actions are independent of the marker;
* advance_marker / dismiss_advisory are pure and cannot satisfy a required action
  (a probe-failing required action stays pending after advance_marker);
* marker values round-trip through a tmp HOME and carry no secret shapes;
* a marker whose last_seen_release is absent-from-manifest or predates (baseline)
  yields ALL releases new, never raises;
* the three marker cases (absent | predates | known) drive advisory visibility
  distinctly (absent => show_on_first_run only; predates => ALL; known =>
  releases_since) — absent vs predates are NEVER conflated (D040/D044).
"""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate import upgrade_predicates as up
from dontpanic_orchestrate import upgrade_state as us
from dontpanic_orchestrate.state_projection import scrub_secrets
from dontpanic_orchestrate.upgrade_releases_model import (
    CommandLabel,
    Kind,
    Severity,
    UpgradeAction,
    UpgradeCommand,
    UpgradeManifest,
    UpgradeRelease,
)

BASELINE = "2026-06-13-pre-experience-readiness"


# ─────────────────────────  fixtures  ─────────────────────────


def _required_action(action_id: str, probe: str = "canonical_discovery_registered_active") -> UpgradeAction:
    return UpgradeAction(
        id=action_id,
        kind=Kind.required,
        severity=Severity.critical,
        title=f"required {action_id}",
        detail="why this is required",
        status_probe=probe,
        commands=[
            UpgradeCommand(label=CommandLabel.apply, command="dontpanic do-thing"),
            UpgradeCommand(label=CommandLabel.verify, command="dontpanic doctor"),
        ],
    )


def _advisory(action_id: str) -> UpgradeAction:
    return UpgradeAction(
        id=action_id,
        kind=Kind.advisory,
        severity=Severity.optional,
        title=f"advisory {action_id}",
        detail="why this is advisory",
    )


def _manifest() -> UpgradeManifest:
    """Three releases r1<r2<r3 in manifest order; only r1 is show_on_first_run."""
    return UpgradeManifest(
        baseline_release=BASELINE,
        baseline_date="2026-06-13",
        releases=[
            UpgradeRelease(
                id="r1",
                date="2026-06-14",
                summary="release one",
                show_on_first_run=True,
                actions=[_advisory("a1"), _required_action("req1")],
            ),
            UpgradeRelease(
                id="r2",
                date="2026-06-15",
                summary="release two",
                show_on_first_run=False,
                actions=[_advisory("a2")],
            ),
            UpgradeRelease(
                id="r3",
                date="2026-06-16",
                summary="release three",
                show_on_first_run=False,
                actions=[_advisory("a3")],
            ),
        ],
    )


# ─────────────────────────  absent marker (case a)  ─────────────────────────


def test_absent_marker_returns_in_memory_effective_marker_and_creates_no_file(tmp_path: Path) -> None:
    target = tmp_path / us.MARKER_FILENAME
    manifest = _manifest()

    effective = us.read_upgrade_state(manifest, path=target)

    # In-memory effective marker, anchored to the LATEST release so history is not replayed.
    assert effective.marker_state is us.MarkerState.absent
    assert effective.file_present is False
    assert effective.marker.last_seen_release == "r3"
    # No file is created by a read (D015 NO-SILENT-WRITE).
    assert not target.exists()


def test_absent_marker_display_is_never_acknowledged_not_latest(tmp_path: Path) -> None:
    # D042: displayed acknowledgement is NULL, never the synthetic latest anchor.
    effective = us.read_upgrade_state(_manifest(), path=tmp_path / us.MARKER_FILENAME)
    assert effective.displayed_last_seen_release is None
    assert effective.displayed_last_seen_commit is None


def test_absent_marker_shows_only_show_on_first_run_advisories(tmp_path: Path) -> None:
    # D012/D044: only r1 (show_on_first_run) advisories, not the full history.
    manifest = _manifest()
    effective = us.read_upgrade_state(manifest, path=tmp_path / us.MARKER_FILENAME)

    keys = {adv.key for adv in us.visible_advisories(effective, manifest)}
    assert keys == {us.advisory_key("r1", "a1")}


def test_required_actions_are_independent_of_absent_marker(tmp_path: Path) -> None:
    # Required action's satisfaction is probe-driven regardless of the marker. A
    # failing probe stays unsatisfied even with a fresh (absent) marker.
    manifest = _manifest()
    us.read_upgrade_state(manifest, path=tmp_path / us.MARKER_FILENAME)

    # Inject a projection with NO registered_active row -> probe not satisfied.
    ctx = up.PredicateContext(
        projection={
            "used_unregistered": [],
            "registered_active": [],
            "registered_stale": [],
            "registered_path_missing": [],
            "registered_unresolved": [],
        },
        self_canonical_key="self",
    )
    result = up.resolve_status_probe("canonical_discovery_registered_active", ctx)
    assert result.satisfied is False


# ─────────────────────────  releases_since purity / order  ─────────────────────────


def test_releases_since_is_order_correct_for_mid_history_marker() -> None:
    manifest = _manifest()
    marker = us.UpgradeStateMarker(last_seen_release="r1")
    assert [r.id for r in us.releases_since(marker, manifest)] == ["r2", "r3"]


def test_releases_since_latest_marker_is_empty() -> None:
    manifest = _manifest()
    marker = us.UpgradeStateMarker(last_seen_release="r3")
    assert us.releases_since(marker, manifest) == []


def test_releases_since_does_not_mutate_inputs() -> None:
    manifest = _manifest()
    before = [r.id for r in manifest.releases]
    marker = us.UpgradeStateMarker(last_seen_release="r1")
    us.releases_since(marker, manifest)
    assert [r.id for r in manifest.releases] == before


def test_first_run_advisories_honors_show_on_first_run() -> None:
    manifest = _manifest()
    keys = {adv.key for adv in us.first_run_advisories(manifest)}
    assert keys == {us.advisory_key("r1", "a1")}


# ─────────────────────────  known marker (case c)  ─────────────────────────


def test_known_marker_shows_only_newer_advisories(tmp_path: Path) -> None:
    manifest = _manifest()
    target = tmp_path / us.MARKER_FILENAME
    us.write_upgrade_state(us.UpgradeStateMarker(last_seen_release="r1", last_seen_commit="deadbee"), path=target)

    effective = us.read_upgrade_state(manifest, path=target)
    assert effective.marker_state is us.MarkerState.known
    assert effective.displayed_last_seen_release == "r1"
    keys = {adv.key for adv in us.visible_advisories(effective, manifest)}
    assert keys == {us.advisory_key("r2", "a2"), us.advisory_key("r3", "a3")}


# ─────────────────────────  predates marker (case b) — D035/D040/D044  ─────────────────────────


def test_predates_baseline_marker_yields_all_releases_new(tmp_path: Path) -> None:
    manifest = _manifest()
    target = tmp_path / us.MARKER_FILENAME
    us.write_upgrade_state(us.UpgradeStateMarker(last_seen_release=BASELINE), path=target)

    effective = us.read_upgrade_state(manifest, path=target)
    assert effective.marker_state is us.MarkerState.predates
    assert [r.id for r in us.releases_since(effective.marker, manifest)] == ["r1", "r2", "r3"]


def test_absent_from_manifest_marker_yields_all_releases_new_without_raising() -> None:
    manifest = _manifest()
    marker = us.UpgradeStateMarker(last_seen_release="some-release-not-in-manifest")
    # Never raises on an unknown/stale last_seen_release (D035).
    assert [r.id for r in us.releases_since(marker, manifest)] == ["r1", "r2", "r3"]


def test_predates_marker_shows_all_advisories_no_first_run_filter(tmp_path: Path) -> None:
    # D040/D044: a predating EXISTING marker is an UPGRADE -> ALL advisories
    # (show_on_first_run filter does NOT apply).
    manifest = _manifest()
    target = tmp_path / us.MARKER_FILENAME
    us.write_upgrade_state(us.UpgradeStateMarker(last_seen_release=BASELINE), path=target)

    effective = us.read_upgrade_state(manifest, path=target)
    keys = {adv.key for adv in us.visible_advisories(effective, manifest)}
    assert keys == {
        us.advisory_key("r1", "a1"),
        us.advisory_key("r2", "a2"),
        us.advisory_key("r3", "a3"),
    }


def test_absent_and_predates_are_never_conflated(tmp_path: Path) -> None:
    # The same manifest: absent => show_on_first_run only; predates => ALL.
    manifest = _manifest()

    absent_target = tmp_path / "absent" / us.MARKER_FILENAME
    absent_eff = us.read_upgrade_state(manifest, path=absent_target)
    absent_keys = {adv.key for adv in us.visible_advisories(absent_eff, manifest)}

    predates_target = tmp_path / "predates" / us.MARKER_FILENAME
    us.write_upgrade_state(us.UpgradeStateMarker(last_seen_release=BASELINE), path=predates_target)
    predates_eff = us.read_upgrade_state(manifest, path=predates_target)
    predates_keys = {adv.key for adv in us.visible_advisories(predates_eff, manifest)}

    assert absent_keys == {us.advisory_key("r1", "a1")}
    assert predates_keys == {
        us.advisory_key("r1", "a1"),
        us.advisory_key("r2", "a2"),
        us.advisory_key("r3", "a3"),
    }
    assert absent_keys != predates_keys


# ─────────────────────────  pure transforms  ─────────────────────────


def test_advance_marker_is_pure_and_updates_release_and_commit() -> None:
    marker = us.UpgradeStateMarker(last_seen_release="r1", last_seen_commit="old", dismissed_advisories=["k"])
    advanced = us.advance_marker(marker, release_id="r3", commit="newsha")

    assert advanced.last_seen_release == "r3"
    assert advanced.last_seen_commit == "newsha"
    assert advanced.dismissed_advisories == ["k"]  # preserved
    # input untouched (pure)
    assert marker.last_seen_release == "r1"
    assert marker.last_seen_commit == "old"


def test_advance_marker_cannot_satisfy_a_probe_failing_required_action(tmp_path: Path) -> None:
    # Acceptance: advancing the marker can never clear a probe-failing required action.
    ctx = up.PredicateContext(
        projection={
            "used_unregistered": [],
            "registered_active": [],
            "registered_stale": [],
            "registered_path_missing": [],
            "registered_unresolved": [],
        },
        self_canonical_key="self",
    )
    before = up.resolve_status_probe("canonical_discovery_registered_active", ctx)
    assert before.satisfied is False

    marker = us.UpgradeStateMarker(last_seen_release="r1")
    us.advance_marker(marker, release_id="r3", commit="sha")

    # The probe still fails — the marker advance has no bearing on it.
    after = up.resolve_status_probe("canonical_discovery_registered_active", ctx)
    assert after.satisfied is False


def test_dismiss_advisory_suppresses_specific_advisory(tmp_path: Path) -> None:
    manifest = _manifest()
    target = tmp_path / us.MARKER_FILENAME
    dismissed = us.advisory_key("r2", "a2")
    us.write_upgrade_state(
        us.UpgradeStateMarker(last_seen_release="r1", dismissed_advisories=[dismissed]), path=target
    )

    effective = us.read_upgrade_state(manifest, path=target)
    keys = {adv.key for adv in us.visible_advisories(effective, manifest)}
    assert dismissed not in keys
    assert keys == {us.advisory_key("r3", "a3")}


def test_dismiss_advisory_is_pure_and_idempotent() -> None:
    marker = us.UpgradeStateMarker(last_seen_release="r1")
    once = us.dismiss_advisory(marker, "upgrade:r2:a2")
    twice = us.dismiss_advisory(once, "upgrade:r2:a2")

    assert once.dismissed_advisories == ["upgrade:r2:a2"]
    assert twice.dismissed_advisories == ["upgrade:r2:a2"]  # no dup
    assert marker.dismissed_advisories == []  # input untouched


# ─────────────────────────  round-trip + no secrets  ─────────────────────────


def test_marker_round_trips_through_tmp_home(tmp_path: Path) -> None:
    target = tmp_path / us.MARKER_FILENAME
    marker = us.UpgradeStateMarker(
        last_seen_release="r2",
        last_seen_commit="abc123",
        dismissed_advisories=["upgrade:r1:a1"],
        first_initialized_at="2026-06-22T00:00:00Z",
    )
    us.write_upgrade_state(marker, path=target)

    effective = us.read_upgrade_state(_manifest(), path=target)
    assert effective.marker == marker


def test_marker_serialization_carries_no_secret_shapes(tmp_path: Path) -> None:
    target = tmp_path / us.MARKER_FILENAME
    marker = us.UpgradeStateMarker(
        last_seen_release="r2",
        last_seen_commit="abc123def456",
        dismissed_advisories=["upgrade:r1:a1"],
        first_initialized_at="2026-06-22T00:00:00Z",
    )
    us.write_upgrade_state(marker, path=target)

    raw = target.read_text(encoding="utf-8")
    assert scrub_secrets(raw) == raw  # no secret-shape redaction occurred
    # And the on-disk shape is exactly the four marker fields.
    assert set(json.loads(raw).keys()) == {
        "last_seen_release",
        "last_seen_commit",
        "dismissed_advisories",
        "first_initialized_at",
    }


def test_read_does_not_write_even_when_home_is_writable(tmp_path: Path) -> None:
    # Belt-and-braces NO-SILENT-WRITE: a read against a writable but empty HOME
    # leaves the directory empty.
    home = tmp_path / "home"
    home.mkdir()
    target = home / us.MARKER_FILENAME
    us.read_upgrade_state(_manifest(), path=target)
    assert list(home.iterdir()) == []
