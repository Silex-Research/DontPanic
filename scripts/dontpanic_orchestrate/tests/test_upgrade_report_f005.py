"""Plan 2026-06-21-001 F005 — upgrade-readiness report assembly tests.

Covers the acceptance matrix:

* the report shape {summary{...,upstream{...}}, required[], advisory[],
  migration_status[]};
* update_state count matrix (required_pending | advisories_pending | up_to_date |
  unknown);
* off-git installed_commit == "unknown" and upstream_status == "unknown";
* upstream_status matrix (up_to_date | behind | ahead | diverged | unknown) computed
  with NO network fetch in the default path (asserted: no `fetch` reaches the runner);
* required pending vs satisfied vs not-applicable (marker-independent);
* advisory shown vs dismissed vs first-run (marker-governed);
* last_seen_commit distinct from installed_commit (D023); null on absent marker (D042);
* introduced_commands on BOTH required[] and advisory[] (D022/D033);
* the pinned item shape with ORIGINAL applies_when/status_probe keys (D041/D046);
* migration_status[] pinned fields incl. evidence pointer (D024) and the inclusion
  rule that satisfied/not-applicable items still appear (D051);
* an unknown predicate key surfaces an F003 error detail with the required action
  pending and never crashes assembly (D026).
"""

from __future__ import annotations

import dataclasses

import pytest

from dontpanic_orchestrate import upgrade_report as ur
from dontpanic_orchestrate.upgrade_predicates import PredicateContext, PredicateResult
from dontpanic_orchestrate.upgrade_releases_model import (
    CommandLabel,
    Kind,
    Severity,
    UpgradeAction,
    UpgradeCommand,
    UpgradeManifest,
    UpgradeRelease,
)
from dontpanic_orchestrate.upgrade_state import (
    EffectiveMarker,
    MarkerState,
    UpgradeStateMarker,
    advisory_key,
    read_upgrade_state,
)

BASELINE = "2026-06-13-pre-experience-readiness"


# ─────────────────────────  predicate fakes + registry  ─────────────────────────


def _const(satisfied: bool, detail: str, *, error: bool = False, evidence: str | None = None):
    def _fn(_ctx: PredicateContext) -> PredicateResult:
        return PredicateResult(
            satisfied=satisfied, detail=detail, error=error, evidence_uri=evidence
        )

    return _fn


def _registry(*, probes=None, gates=None) -> dict:
    return {
        "status_probe": dict(probes or {}),
        "applies_when": dict(gates or {}),
    }


# ─────────────────────────  manifest fixtures  ─────────────────────────


def _required_action(
    action_id: str,
    *,
    probe: str = "probe_ok",
    applies_when: str | None = None,
    introduced: list[str] | None = None,
) -> UpgradeAction:
    return UpgradeAction(
        id=action_id,
        kind=Kind.required,
        severity=Severity.critical,
        title=f"required {action_id}",
        detail="why this is required",
        status_probe=probe,
        applies_when=applies_when,
        introduced_commands=introduced,
        commands=[
            UpgradeCommand(label=CommandLabel.preview, command="dontpanic do-thing --dry-run"),
            UpgradeCommand(label=CommandLabel.apply, command="dontpanic do-thing"),
            UpgradeCommand(label=CommandLabel.verify, command="dontpanic doctor"),
        ],
        success_message="done!",
        failure_message="still pending",
        human_next_step="run the apply command",
        docs_url="CHANGELOG.md",
    )


def _advisory(action_id: str, *, introduced: list[str] | None = None) -> UpgradeAction:
    return UpgradeAction(
        id=action_id,
        kind=Kind.advisory,
        severity=Severity.optional,
        title=f"advisory {action_id}",
        detail="why this is advisory",
        introduced_commands=introduced,
    )


def _manifest() -> UpgradeManifest:
    """r1 (first-run advisory + required) < r2 (advisory) < r3 (advisory + required)."""
    return UpgradeManifest(
        baseline_release=BASELINE,
        baseline_date="2026-06-13",
        releases=[
            UpgradeRelease(
                id="r1",
                date="2026-06-14",
                summary="release one",
                show_on_first_run=True,
                actions=[
                    _advisory("a1", introduced=["dontpanic new-thing"]),
                    _required_action("req1", introduced=["dontpanic backfill"]),
                ],
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
                actions=[_advisory("a3"), _required_action("req3", probe="probe_bad")],
            ),
        ],
    )


def _known_marker(release_id: str = BASELINE, commit: str | None = "deadbee") -> EffectiveMarker:
    """A KNOWN/predates marker that shows all releases (last_seen before r1)."""
    m = UpgradeStateMarker(last_seen_release=release_id, last_seen_commit=commit)
    return EffectiveMarker(
        marker=m,
        marker_state=MarkerState.predates if release_id == BASELINE else MarkerState.known,
        file_present=True,
        displayed_last_seen_release=release_id,
        displayed_last_seen_commit=commit,
    )


# A git seam that records every call and asserts no fetch ever happens.
class RecordingGit(ur.GitProbe):
    def __init__(self, responses: dict[tuple[str, ...], str | None]):
        self.calls: list[tuple[str, ...]] = []
        self._responses = responses
        super().__init__(runner=self._runner)

    def _runner(self, args):
        key = tuple(args)
        self.calls.append(key)
        return self._responses.get(key)


def _git_off() -> RecordingGit:
    """Off-git: HEAD rev-parse returns None."""
    return RecordingGit({})


def _git_with_upstream(ahead: int, behind: int) -> RecordingGit:
    return RecordingGit(
        {
            ("rev-parse", "--short", "HEAD"): "abc1234",
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): "origin/main",
            ("rev-parse", "--short", "origin/main"): "def5678",
            ("rev-list", "--left-right", "--count", "HEAD...origin/main"): f"{ahead}\t{behind}",
        }
    )


# ─────────────────────────  report shape  ─────────────────────────


def test_report_shape_top_level_and_summary():
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(),
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(False, "nope")}),
        git=_git_with_upstream(0, 0),
    )
    d = ur.report_to_dict(report)
    assert set(d) == {"summary", "required", "advisory", "migration_status"}
    summary = d["summary"]
    for key in (
        "installed_commit",
        "latest_release_id",
        "last_seen_release",
        "last_seen_commit",
        "pending_required",
        "pending_advisory",
        "update_state",
        "upstream",
    ):
        assert key in summary, key
    for key in ("fetched_upstream_commit", "upstream_status", "remediation"):
        assert key in summary["upstream"], key
    assert summary["latest_release_id"] == "r3"


# ─────────────────────────  update_state matrix  ─────────────────────────


def test_update_state_required_pending():
    # req3 probe_bad unsatisfied -> required pending dominates.
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(),
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(False, "nope")}),
        git=_git_off(),
    )
    assert report.summary.pending_required == 1
    assert report.summary.update_state == ur.UpdateState.required_pending.value


def test_update_state_advisories_pending_when_no_required_pending():
    # Both probes satisfied -> 0 required pending; predates marker shows advisories.
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(),
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
        git=_git_off(),
    )
    assert report.summary.pending_required == 0
    assert report.summary.pending_advisory > 0
    assert report.summary.update_state == ur.UpdateState.advisories_pending.value


def test_update_state_up_to_date_when_nothing_pending():
    # All required satisfied + a known marker at the latest release (no advisories since).
    m = UpgradeStateMarker(last_seen_release="r3", last_seen_commit="cafef00")
    eff = EffectiveMarker(
        marker=m,
        marker_state=MarkerState.known,
        file_present=True,
        displayed_last_seen_release="r3",
        displayed_last_seen_commit="cafef00",
    )
    report = ur.assemble_upgrade_report(
        _manifest(),
        eff,
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
        git=_git_off(),
    )
    assert report.summary.pending_required == 0
    assert report.summary.pending_advisory == 0
    assert report.summary.update_state == ur.UpdateState.up_to_date.value


def test_update_state_unknown_on_empty_manifest():
    empty = UpgradeManifest(baseline_release=BASELINE, baseline_date="2026-06-13", releases=[])
    eff = EffectiveMarker(
        marker=UpgradeStateMarker(),
        marker_state=MarkerState.absent,
        file_present=False,
        displayed_last_seen_release=None,
        displayed_last_seen_commit=None,
    )
    report = ur.assemble_upgrade_report(empty, eff, _registry(), git=_git_off())
    assert report.summary.update_state == ur.UpdateState.unknown.value
    assert report.summary.latest_release_id is None


# ─────────────────────────  installed_commit / upstream (off-git + matrix)  ─────────────────────────


def test_off_git_installed_commit_and_upstream_unknown():
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(),
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
        git=_git_off(),
    )
    assert report.summary.installed_commit == ur.UNKNOWN_COMMIT
    assert report.summary.upstream.upstream_status == ur.UpstreamStatusKind.unknown.value
    assert report.summary.upstream.fetched_upstream_commit is None
    assert report.summary.upstream.remediation


@pytest.mark.parametrize(
    ("ahead", "behind", "expected"),
    [
        (0, 0, ur.UpstreamStatusKind.up_to_date.value),
        (0, 3, ur.UpstreamStatusKind.behind.value),
        (2, 0, ur.UpstreamStatusKind.ahead.value),
        (2, 3, ur.UpstreamStatusKind.diverged.value),
    ],
)
def test_upstream_status_matrix_no_fetch(ahead, behind, expected):
    git = _git_with_upstream(ahead, behind)
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(),
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
        git=git,
    )
    assert report.summary.upstream.upstream_status == expected
    assert report.summary.upstream.fetched_upstream_commit == "def5678"
    assert report.summary.installed_commit == "abc1234"
    # NO network fetch in the default path — assert no recorded git call is a fetch/pull.
    assert all(call and call[0] not in {"fetch", "pull", "remote-update"} for call in git.calls)


def test_upstream_unknown_when_no_upstream_ref():
    git = RecordingGit({("rev-parse", "--short", "HEAD"): "abc1234"})
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(),
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
        git=git,
    )
    assert report.summary.upstream.upstream_status == ur.UpstreamStatusKind.unknown.value
    assert report.summary.installed_commit == "abc1234"


def test_upstream_unknown_when_never_fetched():
    git = RecordingGit(
        {
            ("rev-parse", "--short", "HEAD"): "abc1234",
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): "origin/main",
            # ref configured but absent locally -> rev-parse returns None
        }
    )
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(),
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
        git=git,
    )
    assert report.summary.upstream.upstream_status == ur.UpstreamStatusKind.unknown.value
    assert report.summary.upstream.fetched_upstream_commit is None
    assert "fetch" in report.summary.upstream.remediation.lower()


# ─────────────────────────  required pending vs satisfied vs not-applicable  ─────────────────────────


def test_required_satisfied_is_not_pending():
    m = _manifest()
    report = ur.assemble_upgrade_report(
        m,
        _known_marker(),
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
        git=_git_off(),
    )
    assert report.required == []
    assert report.summary.pending_required == 0


def test_required_not_applicable_is_not_pending_but_in_migration_status():
    # req with applies_when that is False -> not pending, but migration_status shows it.
    action = _required_action("reqX", probe="probe_bad", applies_when="gate_off")
    m = UpgradeManifest(
        baseline_release=BASELINE,
        baseline_date="2026-06-13",
        releases=[UpgradeRelease(id="r1", date="2026-06-14", summary="one", actions=[action])],
    )
    report = ur.assemble_upgrade_report(
        m,
        _known_marker(),
        _registry(
            probes={"probe_bad": _const(False, "nope")},
            gates={"gate_off": _const(False, "does not apply")},
        ),
        git=_git_off(),
    )
    assert report.required == []
    assert report.summary.pending_required == 0
    ms = report.migration_status
    assert len(ms) == 1
    assert ms[0].state == ur.MigrationState.not_applicable.value
    assert ms[0].applies is False


def test_required_pending_marker_independent():
    # Even a marker acknowledging the latest release cannot clear a probe-failing required.
    m = UpgradeStateMarker(last_seen_release="r3", last_seen_commit="x")
    eff = EffectiveMarker(
        marker=m,
        marker_state=MarkerState.known,
        file_present=True,
        displayed_last_seen_release="r3",
        displayed_last_seen_commit="x",
    )
    report = ur.assemble_upgrade_report(
        _manifest(),
        eff,
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(False, "nope")}),
        git=_git_off(),
    )
    assert report.summary.pending_required == 1
    assert report.required[0].action_id == "req3"


# ─────────────────────────  advisory shown vs dismissed vs first-run  ─────────────────────────


def test_advisory_first_run_shows_only_show_on_first_run(tmp_path):
    # Absent marker -> first-run policy: only r1 (show_on_first_run) advisory a1.
    eff = read_upgrade_state(_manifest(), path=tmp_path / "upgrade-state.json")
    assert eff.marker_state is MarkerState.absent
    report = ur.assemble_upgrade_report(
        _manifest(),
        eff,
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
        git=_git_off(),
    )
    advisory_ids = {item.action_id for item in report.advisory}
    assert advisory_ids == {"a1"}


def test_advisory_dismissed_is_filtered():
    m = UpgradeStateMarker(
        last_seen_release=BASELINE,
        dismissed_advisories=[advisory_key("r1", "a1")],
    )
    eff = EffectiveMarker(
        marker=m,
        marker_state=MarkerState.predates,
        file_present=True,
        displayed_last_seen_release=BASELINE,
        displayed_last_seen_commit=None,
    )
    report = ur.assemble_upgrade_report(
        _manifest(),
        eff,
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
        git=_git_off(),
    )
    advisory_ids = {item.action_id for item in report.advisory}
    assert "a1" not in advisory_ids
    assert {"a2", "a3"}.issubset(advisory_ids)


# ─────────────────────────  last_seen_commit / D042 null on absent  ─────────────────────────


def test_last_seen_commit_distinct_from_installed_commit():
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(release_id="r1", commit="deadbee"),
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
        git=_git_with_upstream(0, 0),
    )
    assert report.summary.installed_commit == "abc1234"
    assert report.summary.last_seen_commit == "deadbee"
    assert report.summary.installed_commit != report.summary.last_seen_commit


def test_absent_marker_shows_null_acknowledgement(tmp_path):
    eff = read_upgrade_state(_manifest(), path=tmp_path / "upgrade-state.json")
    report = ur.assemble_upgrade_report(
        _manifest(),
        eff,
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
        git=_git_off(),
    )
    assert report.summary.marker_state == MarkerState.absent.value
    assert report.summary.last_seen_release is None
    assert report.summary.last_seen_commit is None


# ─────────────────────────  introduced_commands on BOTH lists (D022/D033)  ─────────────────────────


def test_introduced_commands_on_required_and_advisory():
    # Predates marker -> both a1 (advisory) and req1 (required, pending) visible.
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(),
        _registry(probes={"probe_ok": _const(False, "nope"), "probe_bad": _const(False, "nope")}),
        git=_git_off(),
    )
    req1 = next(i for i in report.required if i.action_id == "req1")
    assert req1.introduced_commands == ["dontpanic backfill"]
    a1 = next(i for i in report.advisory if i.action_id == "a1")
    assert a1.introduced_commands == ["dontpanic new-thing"]


# ─────────────────────────  pinned item shape + original keys (D041/D046)  ─────────────────────────


_ITEM_FIELDS = {
    "item_id",
    "release_id",
    "action_id",
    "kind",
    "severity",
    "title",
    "detail",
    "applies",
    "applies_when_key",
    "applies_detail",
    "applies_error",
    "status_probe_key",
    "commands",
    "success_message",
    "failure_message",
    "human_next_step",
    "docs_url",
    "introduced_commands",
    "satisfied",
    "probe_detail",
    "probe_error",
    "probe_evidence_uri",
}


def test_pinned_item_shape_identical_for_required_and_advisory():
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(),
        _registry(
            probes={"probe_ok": _const(False, "req1 detail"), "probe_bad": _const(False, "x")},
        ),
        git=_git_off(),
    )
    d = ur.report_to_dict(report)
    assert d["required"], "expected a pending required item"
    assert d["advisory"], "expected visible advisory items"
    for item in d["required"] + d["advisory"]:
        assert set(item) == _ITEM_FIELDS

    req1 = next(i for i in report.required if i.action_id == "req1")
    # stable id upgrade:<release>:<action>
    assert req1.item_id == "upgrade:r1:req1"
    # ordered commands carry label + command
    assert [c.label for c in req1.commands] == ["preview", "apply", "verify"]
    assert req1.commands[1].command == "dontpanic do-thing"
    # success/failure copy + next step + docs
    assert req1.success_message == "done!"
    assert req1.failure_message == "still pending"
    assert req1.human_next_step == "run the apply command"
    assert req1.docs_url == "CHANGELOG.md"
    # probed -> satisfied + probe detail populated
    assert req1.satisfied is False
    assert req1.probe_detail == "req1 detail"
    # ORIGINAL keys carried (D046)
    assert req1.status_probe_key == "probe_ok"
    assert req1.applies_when_key is None

    a1 = next(i for i in report.advisory if i.action_id == "a1")
    # advisory has no status_probe -> satisfied/probe_detail null
    assert a1.satisfied is None
    assert a1.probe_detail is None
    assert a1.status_probe_key is None


def test_original_applies_when_key_preserved():
    action = _required_action("reqK", probe="probe_bad", applies_when="has_it")
    m = UpgradeManifest(
        baseline_release=BASELINE,
        baseline_date="2026-06-13",
        releases=[UpgradeRelease(id="r1", date="2026-06-14", summary="one", actions=[action])],
    )
    report = ur.assemble_upgrade_report(
        m,
        _known_marker(),
        _registry(probes={"probe_bad": _const(False, "x")}, gates={"has_it": _const(True, "yes")}),
        git=_git_off(),
    )
    item = report.required[0]
    assert item.applies_when_key == "has_it"
    assert item.applies is True
    assert item.status_probe_key == "probe_bad"


# ─────────────────────────  migration_status pinned fields + D051 inclusion  ─────────────────────────


def test_migration_status_pinned_fields_and_evidence_pointer():
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(),
        _registry(
            probes={
                "probe_ok": _const(True, "ok detail", evidence="file:///ev1"),
                "probe_bad": _const(False, "bad detail", evidence="file:///ev2"),
            }
        ),
        git=_git_off(),
    )
    by_action = {m.action_id: m for m in report.migration_status}
    # both probe-backed required actions present (req1 satisfied, req3 pending) — D051
    assert set(by_action) == {"req1", "req3"}
    req1 = by_action["req1"]
    assert req1.state == ur.MigrationState.satisfied.value
    assert req1.satisfied is True
    assert req1.status_probe_key == "probe_ok"
    assert req1.evidence_uri == "file:///ev1"
    assert req1.detail == "ok detail"
    req3 = by_action["req3"]
    assert req3.state == ur.MigrationState.pending.value
    # pinned contract fields present in the serialized form
    d = ur.report_to_dict(report)
    for item in d["migration_status"]:
        assert set(item) == {
            "release_id",
            "action_id",
            "applies",
            "status_probe_key",
            "satisfied",
            "state",
            "detail",
            "evidence_uri",
        }


def test_migration_status_includes_satisfied_item():
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(),
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
        git=_git_off(),
    )
    states = {m.action_id: m.state for m in report.migration_status}
    assert states == {"req1": "satisfied", "req3": "satisfied"}


# ─────────────────────────  unknown predicate key (D026)  ─────────────────────────


def test_unknown_status_probe_key_pending_with_error_detail_no_crash():
    action = _required_action("reqU", probe="totally_unknown_probe")
    m = UpgradeManifest(
        baseline_release=BASELINE,
        baseline_date="2026-06-13",
        releases=[UpgradeRelease(id="r1", date="2026-06-14", summary="one", actions=[action])],
    )
    # registry intentionally lacks the probe key
    report = ur.assemble_upgrade_report(m, _known_marker(), _registry(), git=_git_off())
    assert report.summary.pending_required == 1
    item = report.required[0]
    assert item.satisfied is False
    assert item.probe_error is True
    assert "unknown status_probe key" in item.probe_detail
    # migration_status carries the same error-derived pending state
    assert report.migration_status[0].state == ur.MigrationState.pending.value


def test_unknown_applies_when_key_fails_open_action_shown():
    action = _required_action("reqA", probe="probe_bad", applies_when="totally_unknown_gate")
    m = UpgradeManifest(
        baseline_release=BASELINE,
        baseline_date="2026-06-13",
        releases=[UpgradeRelease(id="r1", date="2026-06-14", summary="one", actions=[action])],
    )
    report = ur.assemble_upgrade_report(
        m, _known_marker(), _registry(probes={"probe_bad": _const(False, "nope")}), git=_git_off()
    )
    # fail-open: applies True -> required pending (never silently hidden)
    assert report.summary.pending_required == 1
    item = report.required[0]
    assert item.applies is True
    # the F003 fail-OPEN error detail is SURFACED, not flattened to the bool (D026)
    assert item.applies_error is True
    assert "unknown applies_when key" in item.applies_detail
    assert item.applies_when_key == "totally_unknown_gate"
    # and it survives serialization to JSON-able output
    d = ur.report_to_dict(report)
    assert d["required"][0]["applies_error"] is True
    assert "unknown applies_when key" in d["required"][0]["applies_detail"]


# ─────────────────────────  no implicit fetch via real default git path  ─────────────────────────


def test_default_git_runner_never_fetches(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))

        class _P:
            returncode = 1
            stdout = ""

        return _P()

    monkeypatch.setattr(ur.subprocess, "run", fake_run)
    # default GitProbe() -> real runner; assemble should issue only read-only git.
    report = ur.assemble_upgrade_report(
        _manifest(),
        _known_marker(),
        _registry(probes={"probe_ok": _const(True, "ok"), "probe_bad": _const(True, "ok")}),
    )
    assert report.summary.installed_commit == ur.UNKNOWN_COMMIT
    assert calls, "expected at least one git invocation"
    for argv in calls:
        assert "fetch" not in argv
        assert "pull" not in argv


def test_assemble_with_real_registry_does_not_crash(tmp_path, monkeypatch):
    # Smoke: default predicate_registry + empty context resolves without raising.
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path / "home"))
    eff = read_upgrade_state(_manifest(), path=tmp_path / "upgrade-state.json")
    report = ur.assemble_upgrade_report(_manifest(), eff, git=_git_off())
    assert isinstance(report, ur.UpgradeReport)
    # everything serializes cleanly
    assert isinstance(ur.report_to_dict(report), dict)
    assert dataclasses.is_dataclass(report)
