"""Plan 2026-05-23-005 F004 — relevance table + fleet what-now tests.

Coverage map (acceptance items in parentheses):

  * Relevance table — every row of the F004 design table in plan.md
    has an explicit test (acceptance 3, 6).
  * Per-project ActionItem tagging — project-scoped sources surface
    ``project_name``/``display_name`` so the fleet view groups them by
    project (acceptance 1, 2).
  * Fleet what-now aggregator — combines per-project items + build
    warnings + global capability/install items into one envelope
    (acceptance 1, 4).
  * Build-warning persistence — skipped/malformed projects emit
    ActionItems so the dashboard surfaces them (acceptance 4).
  * Stale + quiet states — no items + missing cache produce the right
    behavior (acceptance 5, 6).
  * No-secret invariant — fleet envelope passes the operator_console
    secret guard (acceptance 6).
  * Synthetic 8-project fixture — exercises grouping with
    needs_action / advisory / ready / inactive / stale / missing-repo
    mix (acceptance 6).

Run targeted:
  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_dashboard_relevance_f004.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import dashboard_relevance as rel  # noqa: E402
from dontpanic_orchestrate import global_config as gc  # noqa: E402
from dontpanic_orchestrate import operator_console as oc  # noqa: E402
from dontpanic_orchestrate import projects_dashboard as pd  # noqa: E402
from dontpanic_orchestrate import projects_registry as pr  # noqa: E402

_FIXED_ISO = "2026-05-23T12:00:00Z"


# ── 1. Relevance table — every row of the plan.md F004 table ────────────


class TestRelevanceTable:
    """Every relevance rule from plan.md F004 design table has an
    explicit test below. Adding a new blocker class is a deliberate
    addition to :func:`is_item_relevant_to_project` — the test for it
    lives here, not buried in a hidden default branch."""

    def _capability_item(
        self, capability_id: str, *, band: oc.Band = oc.Band.NEEDS_ACTION
    ) -> oc.ActionItem:
        return oc.ActionItem(
            id=f"capability:{capability_id}",
            source=oc.SOURCE_CAPABILITY,
            band=band,
            title=f"Capability {capability_id} needs setup",
            detail=None,
            exact_command=f"dontpanic capabilities status {capability_id}",
            automatable=False,
            human_required_reason="capability setup incomplete",
            evidence_uri=None,
            updated_at=_FIXED_ISO,
        )

    def _reconcile_item(self, kind: str) -> oc.ActionItem:
        return oc.ActionItem(
            id=f"reconcile:{kind}",
            source=oc.SOURCE_RECONCILE,
            band=oc.Band.NEEDS_ACTION,
            title=f"Reconcile drift: {kind}",
            detail=None,
            exact_command="dontpanic reconcile baseline --yes",
            automatable=False,
            human_required_reason="capability set diverged from baseline",
            evidence_uri=None,
            updated_at=_FIXED_ISO,
        )

    def test_row1_capability_relevant_when_declared(self) -> None:
        """Capability not installed/configured — relevant only when the
        selected project's plans declare ``requires_capabilities[]``."""
        item = self._capability_item("firebase-dashboard")
        decl = rel.ProjectDeclarations(
            project_name="alpha",
            required_capability_ids=frozenset({"firebase-dashboard"}),
        )
        assert rel.is_item_relevant_to_project(item, decl) is True

    def test_row1_capability_irrelevant_when_not_declared(self) -> None:
        item = self._capability_item("firebase-dashboard")
        decl = rel.ProjectDeclarations(project_name="alpha")
        assert rel.is_item_relevant_to_project(item, decl) is False

    def test_row1_capability_relevant_via_external_ref(self) -> None:
        """``external_refs[].capability_id`` is loaded into
        ``required_capability_ids`` by :func:`load_project_declarations`,
        so the same rule fires."""
        item = self._capability_item("linear-pp")
        decl = rel.ProjectDeclarations(
            project_name="alpha",
            required_capability_ids=frozenset({"linear-pp"}),
        )
        assert rel.is_item_relevant_to_project(item, decl) is True

    @pytest.mark.parametrize(
        "cap_id", sorted(rel.GLOBAL_DOCTOR_CAPABILITIES)
    )
    def test_row2_doctor_blocker_relevant_to_every_project(self, cap_id: str) -> None:
        """Doctor/install blocker (Python, schema, install, git) —
        relevant to every project, regardless of declarations."""
        item = self._capability_item(cap_id)
        decl = rel.ProjectDeclarations(project_name="alpha")
        assert rel.is_item_relevant_to_project(item, decl) is True

    @pytest.mark.parametrize(
        "kind",
        [
            "new_capabilities",
            "removed_capabilities",
            "changed_capabilities",
            "missing_snapshot",
            "stale_status_cache",
        ],
    )
    def test_row3_install_drift_relevant_to_every_project(self, kind: str) -> None:
        """DontPanic install drift — every project shares the operator's
        one install, so every reconcile-source item is universally
        relevant."""
        item = self._reconcile_item(kind)
        decl = rel.ProjectDeclarations(project_name="alpha")
        assert rel.is_item_relevant_to_project(item, decl) is True

    def test_row4_architecture_relevant_only_to_owning_project(self) -> None:
        """Architecture stale/missing — relevant only to the selected
        project. Project-scoped items carry ``project_name`` and the
        rule short-circuits to string equality."""
        item = oc.ActionItem(
            id="architecture:stale",
            source=oc.SOURCE_ARCHITECTURE,
            band=oc.Band.ADVISORY,
            title="Architecture stale",
            detail=None,
            exact_command="dontpanic architecture regen",
            automatable=True,
            human_required_reason=None,
            evidence_uri=None,
            updated_at=_FIXED_ISO,
            project_name="alpha",
            display_name="Alpha",
        )
        decl_alpha = rel.ProjectDeclarations(project_name="alpha")
        decl_beta = rel.ProjectDeclarations(project_name="beta")
        assert rel.is_item_relevant_to_project(item, decl_alpha) is True
        assert rel.is_item_relevant_to_project(item, decl_beta) is False

    def test_row5_adapter_relevant_via_category(self) -> None:
        """Adapter not configured — relevant when the project references
        the adapter category, even without naming the capability id."""
        item = self._capability_item("realtime-firebase")
        decl = rel.ProjectDeclarations(
            project_name="alpha",
            referenced_adapter_categories=frozenset({"dashboard-realtime"}),
        )
        cap_categories = {"realtime-firebase": "dashboard-realtime"}
        assert (
            rel.is_item_relevant_to_project(
                item, decl, capability_categories=cap_categories
            )
            is True
        )
        # Without the category map, capability rule falls through to
        # "not declared" → False.
        assert rel.is_item_relevant_to_project(item, decl) is False

    def test_row6_build_warning_relevant_only_to_affected_project(self) -> None:
        """Dashboard build warning — relevant to the affected project."""
        items = rel.build_warning_action_items(
            project_name="alpha",
            display_name="Alpha",
            warnings=["plan parse failed"],
            skipped=False,
            skipped_reason=None,
            now_iso=_FIXED_ISO,
        )
        assert len(items) == 1
        warning_item = items[0]
        # Warning items carry project_name → rule 1 short-circuits.
        decl_alpha = rel.ProjectDeclarations(project_name="alpha")
        decl_beta = rel.ProjectDeclarations(project_name="beta")
        assert rel.is_item_relevant_to_project(warning_item, decl_alpha) is True
        assert rel.is_item_relevant_to_project(warning_item, decl_beta) is False


# ── 2. ProjectDeclarations loader ───────────────────────────────────────


class TestProjectDeclarationsLoader:
    def test_loads_requires_capabilities_from_plan_frontmatter(self, tmp_path) -> None:
        plans = tmp_path / "plans"
        plan = plans / "2026-05-23-001-test-plan"
        plan.mkdir(parents=True)
        (plan / "plan.md").write_text(
            "---\n"
            "id: 2026-05-23-001-test-plan\n"
            "title: t\n"
            "requires_capabilities:\n"
            "  - python\n"
            "  - firebase-dashboard\n"
            "---\n# body\n"
        )
        decl = rel.load_project_declarations("alpha", plans)
        assert "python" in decl.required_capability_ids
        assert "firebase-dashboard" in decl.required_capability_ids

    def test_loads_external_ref_capability_bindings(self, tmp_path) -> None:
        plans = tmp_path / "plans"
        plan = plans / "2026-05-23-002-other"
        plan.mkdir(parents=True)
        (plan / "plan.md").write_text(
            "---\n"
            "id: 2026-05-23-002-other\n"
            "title: t\n"
            "external_refs:\n"
            "  - uri: https://linear.app/x/issue/X-1\n"
            "    capability_id: linear-pp\n"
            "---\n"
        )
        decl = rel.load_project_declarations("alpha", plans)
        assert "linear-pp" in decl.required_capability_ids

    def test_tolerates_missing_plans_dir(self, tmp_path) -> None:
        decl = rel.load_project_declarations("alpha", tmp_path / "nonexistent")
        assert decl.required_capability_ids == frozenset()
        assert decl.referenced_adapter_categories == frozenset()

    def test_tolerates_malformed_frontmatter(self, tmp_path) -> None:
        plans = tmp_path / "plans"
        plan = plans / "bad-plan"
        plan.mkdir(parents=True)
        # Unclosed frontmatter delimiter.
        (plan / "plan.md").write_text(
            "---\nrequires_capabilities: [python\n"
        )
        decl = rel.load_project_declarations("alpha", plans)
        assert decl.required_capability_ids == frozenset()


# ── 3. Build-warning ActionItems ────────────────────────────────────────


class TestBuildWarningActionItems:
    def test_skipped_build_emits_single_advisory_item(self) -> None:
        items = rel.build_warning_action_items(
            project_name="alpha",
            display_name="Alpha Mobile",
            warnings=["repo_root does not exist: /tmp/alpha"],
            skipped=True,
            skipped_reason="repo_root missing",
            now_iso=_FIXED_ISO,
        )
        assert len(items) == 1
        assert items[0].band is oc.Band.ADVISORY
        assert items[0].project_name == "alpha"
        assert items[0].display_name == "Alpha Mobile"
        assert items[0].id == "architecture:build-warning:alpha:skipped"

    def test_non_skipped_warnings_emit_one_item_each(self) -> None:
        items = rel.build_warning_action_items(
            project_name="alpha",
            display_name="Alpha",
            warnings=["malformed plan", "another issue"],
            skipped=False,
            skipped_reason=None,
            now_iso=_FIXED_ISO,
        )
        assert len(items) == 2
        for it in items:
            assert it.band is oc.Band.ADVISORY
            assert it.project_name == "alpha"
        ids = {it.id for it in items}
        assert ids == {
            "architecture:build-warning:alpha:0",
            "architecture:build-warning:alpha:1",
        }


# ── 4. Filter by project (per-project view) ─────────────────────────────


class TestFilterItemsForProject:
    def _make_items(self) -> list[oc.ActionItem]:
        return [
            # Project-scoped: alpha's gate
            oc.ActionItem(
                id="gate:plan-a:pre_impl",
                source=oc.SOURCE_GATE,
                band=oc.Band.NEEDS_ACTION,
                title="alpha gate",
                detail=None,
                exact_command="dontpanic approve plan-a pre_impl",
                automatable=False,
                human_required_reason="gate approval",
                evidence_uri=None,
                updated_at=_FIXED_ISO,
                project_name="alpha",
                display_name="Alpha",
            ),
            # Project-scoped: beta's architecture
            oc.ActionItem(
                id="architecture:stale",
                source=oc.SOURCE_ARCHITECTURE,
                band=oc.Band.ADVISORY,
                title="beta arch stale",
                detail=None,
                exact_command="dontpanic architecture regen",
                automatable=True,
                human_required_reason=None,
                evidence_uri=None,
                updated_at=_FIXED_ISO,
                project_name="beta",
                display_name="Beta",
            ),
            # Global doctor: python
            oc.ActionItem(
                id="capability:python",
                source=oc.SOURCE_CAPABILITY,
                band=oc.Band.NEEDS_ACTION,
                title="Capability python needs setup",
                detail=None,
                exact_command="dontpanic capabilities status python",
                automatable=False,
                human_required_reason="capability setup incomplete",
                evidence_uri=None,
                updated_at=_FIXED_ISO,
            ),
            # Global capability that only alpha declares
            oc.ActionItem(
                id="capability:firebase-dashboard",
                source=oc.SOURCE_CAPABILITY,
                band=oc.Band.NEEDS_ACTION,
                title="Capability firebase-dashboard",
                detail=None,
                exact_command="dontpanic capabilities status firebase-dashboard",
                automatable=False,
                human_required_reason="capability setup incomplete",
                evidence_uri=None,
                updated_at=_FIXED_ISO,
            ),
            # Reconcile (always universally relevant)
            oc.ActionItem(
                id="reconcile:new_capabilities",
                source=oc.SOURCE_RECONCILE,
                band=oc.Band.NEEDS_ACTION,
                title="drift",
                detail=None,
                exact_command="dontpanic reconcile baseline --yes",
                automatable=False,
                human_required_reason="capability set diverged from baseline",
                evidence_uri=None,
                updated_at=_FIXED_ISO,
            ),
        ]

    def test_filter_for_alpha_keeps_owned_plus_global_doctor_plus_declared_cap(
        self,
    ) -> None:
        items = self._make_items()
        decl = rel.ProjectDeclarations(
            project_name="alpha",
            required_capability_ids=frozenset({"firebase-dashboard"}),
        )
        filtered = rel.filter_items_for_project(items, decl)
        ids = {it.id for it in filtered}
        assert ids == {
            "gate:plan-a:pre_impl",  # alpha's own gate
            "capability:python",  # global doctor
            "capability:firebase-dashboard",  # alpha declares it
            "reconcile:new_capabilities",  # universal install drift
        }
        # Beta's architecture is filtered out.
        assert "architecture:stale" not in ids

    def test_filter_for_beta_excludes_alpha_owned_cap(self) -> None:
        items = self._make_items()
        decl = rel.ProjectDeclarations(project_name="beta")
        filtered = rel.filter_items_for_project(items, decl)
        ids = {it.id for it in filtered}
        # beta keeps own arch + python + reconcile; rejects alpha's gate
        # and firebase-dashboard.
        assert "architecture:stale" in ids
        assert "capability:python" in ids
        assert "reconcile:new_capabilities" in ids
        assert "gate:plan-a:pre_impl" not in ids
        assert "capability:firebase-dashboard" not in ids


# ── 5. Fleet what-now aggregator end-to-end ─────────────────────────────


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "alpha-repo"
    d.mkdir()
    (d / "docs").mkdir()
    (d / "docs" / "plans").mkdir()
    return d


@pytest.fixture
def project_dir_b(tmp_path):
    d = tmp_path / "beta-repo"
    d.mkdir()
    (d / "docs").mkdir()
    (d / "docs" / "plans").mkdir()
    return d


class TestFleetWhatNowAggregator:
    def test_writes_envelope_to_canonical_path(self, project_dir, project_dir_b) -> None:
        ctx_a = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        ctx_b = pd.project_context_from_entry(
            pr.add_project(name="beta", path=str(project_dir_b))
        )
        reports = [pd.build_project_state(ctx_a), pd.build_project_state(ctx_b)]
        out_path = pd.build_fleet_what_now(reports)
        assert out_path == pd.fleet_what_now_path()
        assert out_path == gc.dontpanic_home() / "dashboard" / pd.FLEET_WHAT_NOW_FILENAME
        payload = json.loads(out_path.read_text())
        assert payload["schema_version"] == pd.FLEET_WHAT_NOW_SCHEMA_VERSION
        # Each registered project surfaces in the summaries list so the
        # All-Projects view can render a section header even when the
        # project has no action items.
        names = [p["name"] for p in payload["projects"]]
        assert names == ["alpha", "beta"]

    def test_skipped_project_emits_build_warning_action_item(self, project_dir) -> None:
        pr.add_project(name="alpha", path=str(project_dir), active=False)
        ctx = pd.project_context_from_entry(pr.find_project("alpha"))
        report = pd.build_project_state(ctx)
        out_path = pd.build_fleet_what_now([report])
        payload = json.loads(out_path.read_text())
        # The skipped build surfaces as one architecture-source warning
        # ActionItem (per build_warning_action_items contract).
        items = payload["items"]
        skipped_items = [
            it for it in items if it["id"].startswith("architecture:build-warning:")
        ]
        assert len(skipped_items) == 1
        assert skipped_items[0]["project_name"] == "alpha"
        assert skipped_items[0]["band"] == "advisory"

    def test_missing_repo_emits_build_warning_action_item(
        self, project_dir
    ) -> None:
        pr.add_project(name="alpha", path=str(project_dir))
        # Delete repo after registration.
        for p in sorted(project_dir.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
        project_dir.rmdir()
        ctx = pd.project_context_from_entry(pr.find_project("alpha"))
        report = pd.build_project_state(ctx)
        out_path = pd.build_fleet_what_now([report])
        payload = json.loads(out_path.read_text())
        # Missing repo → at least one skipped advisory item carrying the
        # project tag, so the dashboard's project filter and All-Projects
        # grouping can both surface it under alpha's section.
        skipped = [
            it
            for it in payload["items"]
            if it["id"].startswith("architecture:build-warning:alpha:")
        ]
        assert len(skipped) >= 1
        assert any("does not exist" in (it.get("detail") or "") for it in skipped)

    def test_no_secret_shapes_in_envelope(self, project_dir) -> None:
        pr.add_project(name="alpha", path=str(project_dir))
        ctx = pd.project_context_from_entry(pr.find_project("alpha"))
        report = pd.build_project_state(ctx)
        out_path = pd.build_fleet_what_now([report])
        text = out_path.read_text()
        for needle in ("AKIA", "BEGIN PRIVATE KEY", "ghp_"):
            assert needle not in text

    def test_secret_shape_in_warning_refuses_write(
        self, project_dir, monkeypatch
    ) -> None:
        ctx = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        # Forge a report with a secret-shape warning. The fleet aggregator
        # turns it into ActionItem.detail, which the no-secret guard must
        # reject before writing.
        forged = pd.ProjectBuildReport(
            context=ctx,
            build_report=None,
            build_warnings_path=ctx.dashboard_cache_path
            / pd.BUILD_WARNINGS_FILENAME,
            warnings=("AKIAIOSFODNN7EXAMPLE leaked",),
            skipped=False,
            skipped_reason=None,
        )
        with pytest.raises(ValueError, match="secret pattern"):
            pd.build_fleet_what_now([forged])


# ── 6. Synthetic 8-project fixture (acceptance 6) ───────────────────────


class TestSyntheticEightProjectFixture:
    """Set up eight registered projects mixing every project state F004
    cares about, then verify the fleet what-now envelope groups them as
    the dashboard expects.

    Project name → state mapping (per plan §F004 acceptance 6):

      alpha   — active, healthy (no plans)
      bravo   — active, declares firebase-dashboard capability
      charlie — inactive (active=False → skipped: inactive)
      delta   — active but repo deleted (skipped: repo_root missing)
      echo    — active, declares git/python (every project anyway)
      foxtrot — active, no declarations (no capability blockers
                surface into its filter)
      golf    — inactive
      hotel   — active, declares linear-pp via external_refs
    """

    def _make_projects(self, tmp_path) -> dict[str, Path]:
        roots: dict[str, Path] = {}
        for name in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"):
            root = tmp_path / f"{name}-repo"
            root.mkdir()
            (root / "docs").mkdir()
            (root / "docs" / "plans").mkdir()
            roots[name] = root
        # Bravo declares firebase-dashboard.
        bravo_plan = roots["bravo"] / "docs" / "plans" / "2026-05-23-100-bravo-plan"
        bravo_plan.mkdir()
        (bravo_plan / "plan.md").write_text(
            "---\nid: 2026-05-23-100-bravo-plan\ntitle: t\n"
            "requires_capabilities:\n  - firebase-dashboard\n---\n"
        )
        # Echo declares git + python.
        echo_plan = roots["echo"] / "docs" / "plans" / "2026-05-23-101-echo-plan"
        echo_plan.mkdir()
        (echo_plan / "plan.md").write_text(
            "---\nid: 2026-05-23-101-echo-plan\ntitle: t\n"
            "requires_capabilities:\n  - git\n  - python\n---\n"
        )
        # Hotel declares linear-pp via external_refs.
        hotel_plan = roots["hotel"] / "docs" / "plans" / "2026-05-23-102-hotel-plan"
        hotel_plan.mkdir()
        (hotel_plan / "plan.md").write_text(
            "---\nid: 2026-05-23-102-hotel-plan\ntitle: t\n"
            "external_refs:\n  - uri: https://linear.app/x\n    capability_id: linear-pp\n---\n"
        )
        return roots

    def test_eight_project_fleet_envelope_groups_warnings_by_project(
        self, tmp_path
    ) -> None:
        roots = self._make_projects(tmp_path)
        # Register each project, with charlie + golf inactive.
        pr.add_project(name="alpha", path=str(roots["alpha"]))
        pr.add_project(name="bravo", path=str(roots["bravo"]))
        pr.add_project(name="charlie", path=str(roots["charlie"]), active=False)
        pr.add_project(name="delta", path=str(roots["delta"]))
        pr.add_project(name="echo", path=str(roots["echo"]))
        pr.add_project(name="foxtrot", path=str(roots["foxtrot"]))
        pr.add_project(name="golf", path=str(roots["golf"]), active=False)
        pr.add_project(name="hotel", path=str(roots["hotel"]))

        # Delete delta's repo to trigger missing-repo skip.
        for p in sorted(roots["delta"].rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
        roots["delta"].rmdir()

        ctxs = pd.load_project_contexts()
        reports = [pd.build_project_state(c) for c in ctxs]
        ctx_by_name = {report.context.name: report.context for report in reports}

        def write_project_cache(name: str, items: list[dict[str, object]]) -> None:
            cache_dir = ctx_by_name[name].dashboard_cache_path
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "what-now-cache.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "captured_at": _FIXED_ISO,
                        "items": items,
                    }
                )
            )

        # Seed explicit per-project what-now states so the synthetic
        # fixture exercises the full F004 mix, not only skipped-project
        # build warnings.
        write_project_cache(
            "alpha",
            [
                {
                    "id": "supervisor:ready",
                    "source": oc.SOURCE_SUPERVISOR,
                    "band": oc.Band.READY.value,
                    "title": "Alpha ready",
                    "automatable": True,
                    "updated_at": _FIXED_ISO,
                }
            ],
        )
        write_project_cache(
            "bravo",
            [
                {
                    "id": "architecture:stale",
                    "source": oc.SOURCE_ARCHITECTURE,
                    "band": oc.Band.ADVISORY.value,
                    "title": "Bravo architecture stale",
                    "exact_command": "dontpanic architecture regen",
                    "automatable": True,
                    "updated_at": _FIXED_ISO,
                }
            ],
        )
        write_project_cache(
            "hotel",
            [
                {
                    "id": "gate:review",
                    "source": oc.SOURCE_GATE,
                    "band": oc.Band.NEEDS_ACTION.value,
                    "title": "Hotel review gate",
                    "exact_command": "dontpanic approve hotel pre_merge",
                    "automatable": False,
                    "human_required_reason": "approval",
                    "updated_at": _FIXED_ISO,
                }
            ],
        )
        envelope_path = pd.build_fleet_what_now(reports)
        payload = json.loads(envelope_path.read_text())

        # Eight project entries.
        names = [p["name"] for p in payload["projects"]]
        assert names == [
            "alpha",
            "bravo",
            "charlie",
            "delta",
            "echo",
            "foxtrot",
            "golf",
            "hotel",
        ]
        # charlie + golf are inactive — they surface as skipped + carry a
        # build-warning ActionItem so the All-Projects view shows them.
        skipped_inactive = {
            it["project_name"]
            for it in payload["items"]
            if it["id"].endswith(":skipped") and "inactive" in (it.get("detail") or "")
        }
        assert skipped_inactive >= {"charlie", "golf"}
        # delta is missing its repo on disk — also skipped with reason.
        delta_skipped = [
            it
            for it in payload["items"]
            if it["project_name"] == "delta" and it["id"].endswith(":skipped")
        ]
        assert len(delta_skipped) == 1
        assert "does not exist" in (delta_skipped[0].get("detail") or "")

        by_project = {
            (it.get("project_name"), it["id"]): it
            for it in payload["items"]
            if it.get("project_name")
        }
        assert by_project[("alpha", "supervisor:ready")]["band"] == oc.Band.READY.value
        assert (
            by_project[("bravo", "architecture:stale")]["band"]
            == oc.Band.ADVISORY.value
        )
        assert (
            by_project[("hotel", "gate:review")]["band"]
            == oc.Band.NEEDS_ACTION.value
        )

        # No-secret invariant holds across the full envelope.
        text = envelope_path.read_text()
        for needle in ("AKIA", "BEGIN PRIVATE KEY", "ghp_"):
            assert needle not in text


# ── 7. Quiet + stale state coverage ─────────────────────────────────────


class TestQuietAndStaleState:
    def test_quiet_fleet_envelope_when_no_projects(self) -> None:
        # Empty registry — no project reports, no items.
        out_path = pd.build_fleet_what_now([])
        payload = json.loads(out_path.read_text())
        assert payload["projects"] == []
        assert payload["items"] == []

    def test_same_id_across_projects_is_not_deduped(self, project_dir, project_dir_b) -> None:
        """Auditor finding (medium, F004-i0): the merge step previously
        coalesced by raw ``it.id`` which dropped per-project items whose
        id collided across the fleet (e.g. ``architecture:stale``). The
        new key is ``(project_name || "__global__", id)``.
        """
        ctx_a = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        ctx_b = pd.project_context_from_entry(
            pr.add_project(name="beta", path=str(project_dir_b))
        )
        # Forge two per-project what-now-cache.json files that share the
        # exact same ``architecture:stale`` id — pre-fix this would
        # collapse to one item, losing one project's signal.
        for ctx in (ctx_a, ctx_b):
            ctx.dashboard_cache_path.mkdir(parents=True, exist_ok=True)
            (ctx.dashboard_cache_path / "what-now-cache.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "architecture:stale",
                                "source": "architecture",
                                "band": "advisory",
                                "title": f"Architecture stale ({ctx.name})",
                                "exact_command": "dontpanic architecture regen",
                                "automatable": True,
                                "updated_at": _FIXED_ISO,
                            }
                        ]
                    }
                )
            )
        reports = [
            pd.ProjectBuildReport(
                context=ctx_a,
                build_report=None,
                build_warnings_path=ctx_a.dashboard_cache_path / pd.BUILD_WARNINGS_FILENAME,
                warnings=(),
                skipped=False,
                skipped_reason=None,
            ),
            pd.ProjectBuildReport(
                context=ctx_b,
                build_report=None,
                build_warnings_path=ctx_b.dashboard_cache_path / pd.BUILD_WARNINGS_FILENAME,
                warnings=(),
                skipped=False,
                skipped_reason=None,
            ),
        ]
        out_path = pd.build_fleet_what_now(reports)
        payload = json.loads(out_path.read_text())
        arch_items = [
            it for it in payload["items"] if it["id"] == "architecture:stale"
        ]
        # Both projects must surface their architecture:stale item — no
        # cross-project collapse.
        assert len(arch_items) == 2
        owners = {it.get("project_name") for it in arch_items}
        assert owners == {"alpha", "beta"}

    def test_stale_per_project_cache_does_not_crash_fleet_build(
        self, project_dir, monkeypatch
    ) -> None:
        """When a per-project what-now-cache.json is malformed, the fleet
        aggregator must skip it rather than crash the whole build."""
        ctx = pd.project_context_from_entry(
            pr.add_project(name="alpha", path=str(project_dir))
        )
        # Forge a malformed cache.
        ctx.dashboard_cache_path.mkdir(parents=True, exist_ok=True)
        (ctx.dashboard_cache_path / "what-now-cache.json").write_text("{not json}")
        forged = pd.ProjectBuildReport(
            context=ctx,
            build_report=None,
            build_warnings_path=ctx.dashboard_cache_path
            / pd.BUILD_WARNINGS_FILENAME,
            warnings=(),
            skipped=False,
            skipped_reason=None,
        )
        out_path = pd.build_fleet_what_now([forged])
        payload = json.loads(out_path.read_text())
        # No items derived from the malformed cache; the project still
        # appears in the summary list so the All-Projects view can show
        # it muted.
        assert any(p["name"] == "alpha" for p in payload["projects"])
