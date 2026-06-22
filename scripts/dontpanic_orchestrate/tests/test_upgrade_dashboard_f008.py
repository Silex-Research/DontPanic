"""Plan 2026-06-21-001 F008 — dashboard upgrade-status projection + drill-down tests.

Covers the acceptance matrix:

* the always-shown Tools & Setup / Health status row across up_to_date / required-
  pending / last-acknowledged states (incl. the positive up-to-date case, D011);
* the drill-down: probe-pending required -> needs_action with its command, undismissed
  advisory -> advisory, dismissed/satisfied absent (D052 mapping);
* stable ids (upgrade:<release>:<action>) + a stable-key sort;
* projections carry no secret shapes;
* upstream_status is carried and the row reads behind-newest when behind, never
  "up to date" while upstream_status == behind (D031);
* last_seen_commit drives the last-acknowledged display, never installed_commit (D037);
* absent marker -> "never acknowledged" (D042);
* the source vocabulary admits source='upgrade': an upgrade item validates, is not
  dropped by aggregate, and sorts with a stable key in the existing provider path (D052).
"""

from __future__ import annotations

import json

from dontpanic_orchestrate import dashboard
from dontpanic_orchestrate import operator_console as oc
from dontpanic_orchestrate import upgrade_dashboard as ud
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
)

BASELINE = "2026-06-13-pre-experience-readiness"


# ─────────────────────────  fixtures  ─────────────────────────


def _const(satisfied: bool, detail: str = "d", *, evidence: str | None = None):
    def _fn(_ctx: PredicateContext) -> PredicateResult:
        return PredicateResult(satisfied=satisfied, detail=detail, evidence_uri=evidence)

    return _fn


def _registry(*, probes=None, gates=None) -> dict:
    return {"status_probe": dict(probes or {}), "applies_when": dict(gates or {})}


def _required(action_id: str, *, probe: str) -> UpgradeAction:
    return UpgradeAction(
        id=action_id,
        kind=Kind.required,
        severity=Severity.critical,
        title=f"required {action_id}",
        detail="why required",
        status_probe=probe,
        commands=[
            UpgradeCommand(label=CommandLabel.preview, command="dontpanic do --dry-run"),
            UpgradeCommand(label=CommandLabel.apply, command="dontpanic projects backfill-canonical"),
            UpgradeCommand(label=CommandLabel.verify, command="dontpanic doctor"),
        ],
        docs_url="CHANGELOG.md",
    )


def _advisory(action_id: str) -> UpgradeAction:
    return UpgradeAction(
        id=action_id,
        kind=Kind.advisory,
        severity=Severity.optional,
        title=f"advisory {action_id}",
        detail="why advisory",
    )


def _manifest(actions_r1) -> UpgradeManifest:
    return UpgradeManifest(
        baseline_release=BASELINE,
        baseline_date="2026-06-13",
        releases=[
            UpgradeRelease(id="r1", date="2026-06-14", summary="one", actions=actions_r1),
        ],
    )


def _known_marker(release="r1", commit="ackc0de") -> EffectiveMarker:
    m = UpgradeStateMarker(last_seen_release=release, last_seen_commit=commit)
    return EffectiveMarker(
        marker=m,
        marker_state=MarkerState.known,
        file_present=True,
        displayed_last_seen_release=release,
        displayed_last_seen_commit=commit,
    )


def _absent_marker() -> EffectiveMarker:
    return EffectiveMarker(
        marker=UpgradeStateMarker(last_seen_release="r1", last_seen_commit="latestc"),
        marker_state=MarkerState.absent,
        file_present=False,
        displayed_last_seen_release=None,
        displayed_last_seen_commit=None,
    )


def _git(*, head="cur1234", ref="origin/main", upstream_commit="up5678", counts="0\t0"):
    def runner(args):
        a = tuple(args)
        if a[:2] == ("rev-parse", "--short") and a[-1] == "HEAD":
            return head
        if "--abbrev-ref" in a:
            return ref
        if a[:2] == ("rev-parse", "--short") and a[-1] == ref:
            return upstream_commit
        if a and a[0] == "rev-list":
            return counts
        return None

    return ur.GitProbe(runner=runner)


def _assemble(manifest, marker, registry, git):
    return ur.assemble_upgrade_report(manifest, marker, registry, git=git)


# ─────────────────────────  status row across states  ─────────────────────────


def test_status_row_up_to_date_is_always_shown():
    # required satisfied + marker at latest -> no pending anything -> up_to_date.
    manifest = _manifest([_required("req", probe="ok")])
    report = _assemble(manifest, _known_marker(), _registry(probes={"ok": _const(True)}), _git())
    proj = ud.upgrade_status_projection(report)
    assert proj["always_shown"] is True
    assert proj["section"] == ud.UPGRADE_STATUS_SECTION
    assert proj["update_state"] == "up_to_date"
    assert proj["status_line"] == "DontPanic: up to date"
    assert proj["pending_required"] == 0
    assert proj["installed_commit"] == "cur1234"


def test_status_row_required_pending_counts():
    manifest = _manifest([_required("req", probe="bad")])
    report = _assemble(manifest, _known_marker(), _registry(probes={"bad": _const(False)}), _git())
    proj = ud.upgrade_status_projection(report)
    assert proj["update_state"] == "required_pending"
    assert proj["pending_required"] == 1
    assert "1 upgrade action pending" in proj["status_line"]


def test_status_row_last_acknowledged_renders_release_and_commit():
    manifest = _manifest([_required("req", probe="ok")])
    report = _assemble(manifest, _known_marker(release="r1", commit="ackc0de"),
                       _registry(probes={"ok": _const(True)}), _git())
    proj = ud.upgrade_status_projection(report)
    assert proj["last_acknowledged"] == "Last acknowledged: r1 (commit ackc0de)"


# ─────────────────────────  D037 — last_seen vs installed never conflated  ─────────────────────────


def test_last_acknowledged_uses_last_seen_commit_not_installed_commit():
    manifest = _manifest([_required("req", probe="ok")])
    # marker acknowledged commit 'ackc0de'; current checkout HEAD 'cur1234'.
    report = _assemble(manifest, _known_marker(commit="ackc0de"),
                       _registry(probes={"ok": _const(True)}), _git(head="cur1234"))
    proj = ud.upgrade_status_projection(report)
    assert proj["last_seen_commit"] == "ackc0de"
    assert proj["installed_commit"] == "cur1234"
    # The acknowledgement line renders the ACKNOWLEDGED commit, never the checkout.
    assert "ackc0de" in proj["last_acknowledged"]
    assert "cur1234" not in proj["last_acknowledged"]


# ─────────────────────────  D042 — absent marker -> never acknowledged  ─────────────────────────


def test_absent_marker_renders_never_acknowledged():
    manifest = _manifest([_required("req", probe="ok")])
    report = _assemble(manifest, _absent_marker(), _registry(probes={"ok": _const(True)}), _git())
    proj = ud.upgrade_status_projection(report)
    assert proj["marker_state"] == "absent"
    assert proj["last_acknowledged"] == ud.NEVER_ACKNOWLEDGED
    assert proj["last_seen_release"] is None
    assert proj["last_seen_commit"] is None


# ─────────────────────────  D031 — upstream behind never reads up-to-date  ─────────────────────────


def test_behind_upstream_never_reads_up_to_date():
    manifest = _manifest([_required("req", probe="ok")])
    # No pending manifest actions (update_state would be up_to_date) BUT behind upstream.
    report = _assemble(manifest, _known_marker(), _registry(probes={"ok": _const(True)}),
                       _git(counts="0\t3"))  # ahead=0 behind=3 -> behind
    proj = ud.upgrade_status_projection(report)
    assert proj["update_state"] == "up_to_date"
    assert proj["upstream_status"] == "behind"
    assert proj["behind_upstream"] is True
    assert proj["status_line"] != "DontPanic: up to date"
    assert "up to date" not in proj["status_line"]
    assert "behind the newest DontPanic" in proj["status_line"]


# ─────────────────────────  drill-down ActionItems  ─────────────────────────


def test_required_pending_maps_to_needs_action_with_command():
    manifest = _manifest([_required("req", probe="bad")])
    report = _assemble(manifest, _known_marker(), _registry(probes={"bad": _const(False)}), _git())
    items = ud.provide_upgrade_actions(report)
    assert len(items) == 1
    it = items[0]
    assert it.source == "upgrade"
    assert it.band is oc.Band.NEEDS_ACTION
    assert it.id == "upgrade:r1:req"
    # The real manifest apply command (`dontpanic projects backfill-canonical`) is a
    # validated dontpanic subcommand, so it MUST surface via exact_command — the only
    # command field the What Now drill-down client renders (codex-auditor-F008-i2 high:
    # the operator_command escape hatch is dropped by what-now-logic.js, so an apply
    # command parked there would silently vanish from the drill-down).
    assert it.exact_command == "dontpanic projects backfill-canonical"
    assert it.operator_command is None


def test_undismissed_advisory_maps_to_advisory_band():
    manifest = _manifest([_advisory("adv")])
    # predates marker shows all advisories; none dismissed.
    m = UpgradeStateMarker(last_seen_release=BASELINE, last_seen_commit="c")
    marker = EffectiveMarker(
        marker=m, marker_state=MarkerState.predates, file_present=True,
        displayed_last_seen_release=BASELINE, displayed_last_seen_commit="c",
    )
    report = _assemble(manifest, marker, _registry(), _git())
    items = ud.provide_upgrade_actions(report)
    assert [i.band for i in items] == [oc.Band.ADVISORY]
    assert items[0].id == "upgrade:r1:adv"


def test_dismissed_advisory_is_absent():
    manifest = _manifest([_advisory("adv")])
    m = UpgradeStateMarker(
        last_seen_release=BASELINE,
        last_seen_commit="c",
        dismissed_advisories=[advisory_key("r1", "adv")],
    )
    marker = EffectiveMarker(
        marker=m, marker_state=MarkerState.predates, file_present=True,
        displayed_last_seen_release=BASELINE, displayed_last_seen_commit="c",
    )
    report = _assemble(manifest, marker, _registry(), _git())
    assert ud.provide_upgrade_actions(report) == ()


def test_satisfied_required_is_absent_from_drilldown():
    manifest = _manifest([_required("req", probe="ok")])
    report = _assemble(manifest, _known_marker(), _registry(probes={"ok": _const(True)}), _git())
    assert ud.provide_upgrade_actions(report) == ()


def test_stable_key_sort_orders_by_id():
    manifest = UpgradeManifest(
        baseline_release=BASELINE, baseline_date="2026-06-13",
        releases=[UpgradeRelease(id="r1", date="2026-06-14", summary="one", actions=[
            _required("zeta", probe="bad"),
            _required("alpha", probe="bad"),
        ])],
    )
    report = _assemble(manifest, _known_marker(), _registry(probes={"bad": _const(False)}), _git())
    ids = [i.id for i in ud.provide_upgrade_actions(report)]
    assert ids == sorted(ids)
    assert ids == ["upgrade:r1:alpha", "upgrade:r1:zeta"]


# ─────────────────────────  no secret shapes  ─────────────────────────


def test_projections_carry_no_secret_shapes():
    manifest = _manifest([_required("req", probe="bad"), _advisory("adv")])
    m = UpgradeStateMarker(last_seen_release=BASELINE, last_seen_commit="c")
    marker = EffectiveMarker(
        marker=m, marker_state=MarkerState.predates, file_present=True,
        displayed_last_seen_release=BASELINE, displayed_last_seen_commit="c",
    )
    report = _assemble(manifest, marker, _registry(probes={"bad": _const(False)}), _git())
    # status projection asserts internally; calling it must not raise.
    ud.upgrade_status_projection(report)
    # drill-down items survive the secret-scanning render envelope.
    items = ud.provide_upgrade_actions(report)
    oc.render_envelope(items)


# ─────────────────────────  D052 — source vocabulary admits 'upgrade'  ─────────────────────────


def test_upgrade_source_in_valid_vocabulary():
    assert oc.SOURCE_UPGRADE == "upgrade"
    assert oc.SOURCE_UPGRADE in oc._VALID_SOURCES
    assert oc.SOURCE_UPGRADE in oc._SOURCE_PRIORITY


def test_upgrade_item_validates_and_survives_provider_path():
    manifest = _manifest([_required("req", probe="bad")])
    report = _assemble(manifest, _known_marker(), _registry(probes={"bad": _const(False)}), _git())
    upgrade_items = ud.provide_upgrade_actions(report)
    assert upgrade_items  # constructed without raising at the ActionItem boundary

    # A gate item from a different source, to prove stable cross-source ordering.
    gate = oc.ActionItem(
        id="gate:planX:pre_impl",
        source=oc.SOURCE_GATE,
        band=oc.Band.NEEDS_ACTION,
        title="gate",
        detail=None,
        exact_command=None,
        automatable=False,
        human_required_reason="gate approval",
        evidence_uri=None,
        updated_at="2026-06-22T00:00:00Z",
        dedupe_key="gate:planX:pre_impl",
    )
    aggregated = oc.aggregate(upgrade_items, (gate,))
    ids = [i.id for i in aggregated]
    # upgrade item is not dropped...
    assert "upgrade:r1:req" in ids
    # ...and gate (source priority 0) sorts before upgrade (priority 6) within the
    # same needs_action band — the stable band->source->id key.
    assert ids.index("gate:planX:pre_impl") < ids.index("upgrade:r1:req")


# ─────────────────────  dashboard consumer path (build output)  ─────────────────────


def test_dashboard_build_writes_upgrade_status_sidecar(tmp_path, monkeypatch):
    """The build emits the projection to state/upgrade-status.json so the dashboard
    JS loader (`upgradeStatus`) and the always-shown Health row have a file to read.

    The report seam is monkeypatched to a deterministic up-to-date report so the
    test is hermetic (no dependence on the live checkout / manifest)."""
    manifest = _manifest([_required("req", probe="ok")])
    report = _assemble(manifest, _known_marker(), _registry(probes={"ok": _const(True)}), _git())
    monkeypatch.setattr(ud, "build_dashboard_report", lambda **_kw: report)

    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    out = tmp_path / "build"
    dashboard.build(
        plans_root=plans_root,
        out_dir=out,
        check_reconcile=False,
        check_architecture=False,
        write_what_now_cache=True,
        write_capabilities_cache=False,
        what_now_cache_path_override=out / "_home-what-now.json",
    )

    sidecar = out / "upgrade-status.json"
    assert sidecar.exists(), "build must write state/upgrade-status.json for the Health row"
    proj = json.loads(sidecar.read_text(encoding="utf-8"))
    # The always-shown row's fields are present and the up-to-date case is emitted.
    assert proj["always_shown"] is True
    assert proj["section"] == ud.UPGRADE_STATUS_SECTION
    assert proj["status_line"] == "DontPanic: up to date"
    assert proj["update_state"] == "up_to_date"
    assert "installed_commit" in proj
    # No secret-shaped material leaked into the on-disk sidecar.
    blob = json.dumps(proj)
    assert "ghp_" not in blob
    assert "Bearer " not in blob
