"""Plan 2026-05-24-002 F001 — architecture view-state tests.

Covers acceptance items (1)-(7):
  (1) stable view-state shape with lanes/nodes/edges/flows/steps/insights
  (2) authored flow input is validated against the live graph
  (3) dashboard.build writes the cache without mutating architecture.json
  (4) missing/stale architecture is represented explicitly
  (5) IDs are stable and typed
  (6) emitted flows are backed by local architecture state
  (7) project-scoped output, no-secret guarantee, graph shape snapshot

Run targeted:
  PYTHONPATH=scripts pytest \
    scripts/dontpanic_orchestrate/tests/test_architecture_view_state_f001.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import architecture_view_state as avs  # noqa: E402
from dontpanic_orchestrate import dashboard  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────


def _minimal_architecture() -> dict:
    """Hand-built snapshot covering the real surfaces this F001 derives.

    Includes architecture.py, architecture_html.py, dashboard.py,
    state_projection.py, operator_console.py, capabilities.py,
    capabilities_setup_runner.py, projects_registry.py,
    projects_dashboard.py — so every derived flow can validate.
    """

    def mod(path: str, name: str, imports=(), summary: str = "") -> dict:
        return {
            "path": path,
            "name": name,
            "public_symbols": [],
            "imports": list(imports),
            "summary": summary,
        }

    return {
        "schema_version": "1.0",
        "generated_at": "2026-05-24T00:00:00Z",
        "source_fingerprint": {
            "algo": "sha256",
            "files_count": 9,
            "file_hashes_root": "a" * 64,
            "file_hashes": {},
            "computed_at": "2026-05-24T00:00:00Z",
        },
        "modules": [
            mod(
                "scripts/dontpanic_orchestrate/architecture.py",
                "dontpanic_orchestrate.architecture",
                summary="crawler",
            ),
            mod(
                "scripts/dontpanic_orchestrate/architecture_html.py",
                "dontpanic_orchestrate.architecture_html",
                imports=["dontpanic_orchestrate.architecture"],
                summary="html",
            ),
            mod(
                "scripts/dontpanic_orchestrate/dashboard.py",
                "dontpanic_orchestrate.dashboard",
                imports=[
                    "dontpanic_orchestrate.architecture",
                    "dontpanic_orchestrate.state_projection",
                ],
                summary="dashboard build",
            ),
            mod(
                "scripts/dontpanic_orchestrate/state_projection.py",
                "dontpanic_orchestrate.state_projection",
                summary="state",
            ),
            mod(
                "scripts/dontpanic_orchestrate/operator_console.py",
                "dontpanic_orchestrate.operator_console",
                summary="operator console",
            ),
            mod(
                "scripts/dontpanic_orchestrate/capabilities.py",
                "dontpanic_orchestrate.capabilities",
                summary="capabilities",
            ),
            mod(
                "scripts/dontpanic_orchestrate/capabilities_setup_runner.py",
                "dontpanic_orchestrate.capabilities_setup_runner",
                summary="capabilities setup",
            ),
            mod(
                "scripts/dontpanic_orchestrate/capabilities_status.py",
                "dontpanic_orchestrate.capabilities_status",
                summary="capabilities status",
            ),
            mod(
                "scripts/dontpanic_orchestrate/projects_dashboard.py",
                "dontpanic_orchestrate.projects_dashboard",
                summary="multi-repo",
            ),
            mod(
                "scripts/dontpanic_orchestrate/projects_registry.py",
                "dontpanic_orchestrate.projects_registry",
                summary="registry",
            ),
        ],
        "schemas": [
            {
                "path": "claude/shared/schemas/v1.0/architecture-snapshot.schema.json",
                "name": "architecture-snapshot",
                "version": "1.0.0",
                "validator_present": True,
            }
        ],
        "plans": [
            {
                "id": "2026-05-24-002-feat-dashboard-architecture-explorer-v1",
                "title": "Dashboard architecture explorer v1",
                "status": "active",
                "features_count": 5,
            }
        ],
    }


def _write_arch(repo: Path, doc: dict) -> Path:
    target = repo / "docs" / "architecture" / "architecture.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return target


@pytest.fixture
def populated_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_arch(repo, _minimal_architecture())
    return repo


# ── (1) view-state shape ─────────────────────────────────────────────────


class TestViewStateShape:
    def test_required_keys_present(self, populated_repo):
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        for key in (
            "schema_version",
            "project",
            "generated_at",
            "source_path",
            "freshness",
            "lanes",
            "nodes",
            "edges",
            "flows",
            "steps",
            "filters",
            "insights",
            "validation_warnings",
        ):
            assert key in view_state, f"missing top-level key {key}"

    def test_schema_version_pinned(self, populated_repo):
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        assert view_state["schema_version"] == "1.0"

    def test_lanes_are_deterministic_and_complete(self, populated_repo):
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        lane_ids = [lane["id"] for lane in view_state["lanes"]]
        assert lane_ids == [
            "lane:actors",
            "lane:client-surfaces",
            "lane:orchestrator-runtime",
            "lane:capabilities-adapters",
            "lane:data-evidence",
            "lane:external-services",
        ]

    def test_render_is_byte_stable(self, populated_repo):
        from datetime import datetime, timezone

        clock = datetime(2026, 5, 24, 0, 0, 0, tzinfo=timezone.utc)
        inputs = avs.load_inputs(populated_repo)
        a = avs.build_view_state(inputs, repo_root=populated_repo, generated_at=clock)
        b = avs.build_view_state(inputs, repo_root=populated_repo, generated_at=clock)
        assert avs.render_view_state(a) == avs.render_view_state(b)


# ── (5) stable IDs + types ──────────────────────────────────────────────


class TestStableIds:
    def test_module_node_id_format(self):
        assert avs.module_node_id("scripts/foo/bar.py") == "module:scripts/foo/bar.py"

    def test_plan_node_id_format(self):
        assert avs.plan_node_id("2026-05-24-002") == "plan:2026-05-24-002"

    def test_command_node_id_canonicalizes_whitespace(self):
        assert avs.command_node_id("dontpanic Architecture Regen") == (
            "command:dontpanic-architecture-regen"
        )

    def test_node_ids_are_typed_and_prefixed(self, populated_repo):
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        seen_types = set()
        for node in view_state["nodes"]:
            assert ":" in node["id"], f"id {node['id']} missing prefix"
            prefix = node["id"].split(":", 1)[0]
            seen_types.add(node["type"])
            assert prefix in {
                "module",
                "plan",
                "schema",
                "command",
                "capability",
                "external",
                "page",
                "metadata",
                # Plan C0 — tier-0 filesystem inventory + tier-1 heuristic targets.
                "fs",
                "heuristic",
            }, f"unexpected prefix {prefix}"
        assert "module" in seen_types
        assert "plan" in seen_types
        assert "command" in seen_types

    def test_edge_ids_carry_type_and_endpoints(self, populated_repo):
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        for edge in view_state["edges"]:
            assert edge["id"].startswith("edge:")
            assert "->" in edge["id"]
            assert edge["from"] != edge["to"]

    def test_command_nodes_only_emitted_when_module_exists(self, populated_repo):
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        command_nodes = [n for n in view_state["nodes"] if n["type"] == "command"]
        assert command_nodes, "expected at least one command node"
        # Every command node must point to a real module via its
        # source_path field.
        module_paths = {
            n["source_path"]
            for n in view_state["nodes"]
            if n["type"] == "module"
        }
        for cmd in command_nodes:
            assert cmd["source_path"] in module_paths


# ── (6) flows are backed by real architecture state ─────────────────────


class TestDerivedFlows:
    def test_every_derived_step_refs_an_existing_node(self, populated_repo):
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        node_ids = {n["id"] for n in view_state["nodes"]}
        derived = [f for f in view_state["flows"] if f["source"] == "derived"]
        assert derived, "expected at least one derived flow"
        for flow in derived:
            for step in flow["steps"]:
                assert step["node_ref"] in node_ids, (
                    f"flow {flow['id']} step {step['id']} refs missing node "
                    f"{step['node_ref']}"
                )

    def test_step_ordering_matches_emitted_order(self, populated_repo):
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        for flow in view_state["flows"]:
            orders = [s["order"] for s in flow["steps"]]
            assert orders == list(range(1, len(orders) + 1))

    def test_flow_dropped_when_module_missing(self, tmp_path):
        """A derived flow whose backing module is absent must be dropped
        AND emit a validation warning — never silently become demo data.
        """

        repo = tmp_path / "stripped"
        repo.mkdir()
        doc = _minimal_architecture()
        # Remove the capabilities surface so the capability-setup flow
        # loses every step it references.
        doc["modules"] = [
            m
            for m in doc["modules"]
            if "capabilities" not in m["path"]
        ]
        _write_arch(repo, doc)
        inputs = avs.load_inputs(repo)
        view_state = avs.build_view_state(inputs, repo_root=repo)
        flow_ids = {f["id"] for f in view_state["flows"]}
        assert "flow:capability-setup" not in flow_ids
        warning_codes = {w["code"] for w in view_state["validation_warnings"]}
        assert "flow_dropped_missing_refs" in warning_codes


# ── (2) authored flow input validation ──────────────────────────────────


class TestAuthoredFlows:
    def test_authored_flow_with_valid_node_ref_is_emitted(self, populated_repo):
        flows_path = populated_repo / "docs" / "architecture" / "flows.json"
        flows_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "flows": [
                        {
                            "id": "custom-audit",
                            "title": "Audit/signoff",
                            "summary": "Operator inspects a plan's audit dir.",
                            "category": "operator",
                            "steps": [
                                {
                                    "id": "audit:open-plan",
                                    "title": "Open plan",
                                    "node_ref": (
                                        "plan:2026-05-24-002-feat-dashboard-"
                                        "architecture-explorer-v1"
                                    ),
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        authored = [f for f in view_state["flows"] if f["source"] == "authored"]
        assert len(authored) == 1
        assert authored[0]["id"] == "flow:custom-audit"
        assert authored[0]["steps"][0]["valid"] is True

    def test_authored_flow_with_unknown_node_ref_emits_warning(self, populated_repo):
        flows_path = populated_repo / "docs" / "architecture" / "flows.json"
        flows_path.write_text(
            json.dumps(
                {
                    "flows": [
                        {
                            "id": "bad-ref",
                            "title": "Bad ref",
                            "steps": [
                                {
                                    "id": "bad-ref:step1",
                                    "title": "Step 1",
                                    "node_ref": "module:does/not/exist.py",
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        codes = {w["code"] for w in view_state["validation_warnings"]}
        assert "authored_flow_unknown_node" in codes
        # Flow is still emitted so the operator can see what was attempted.
        authored = [f for f in view_state["flows"] if f["source"] == "authored"]
        assert len(authored) == 1
        assert authored[0]["steps"][0]["valid"] is False

    def test_authored_flow_resolves_via_source_path(self, populated_repo):
        flows_path = populated_repo / "docs" / "architecture" / "flows.json"
        flows_path.write_text(
            json.dumps(
                {
                    "flows": [
                        {
                            "id": "by-path",
                            "title": "Resolved via path",
                            "steps": [
                                {
                                    "id": "by-path:step1",
                                    "title": "Step 1",
                                    "source_path": (
                                        "scripts/dontpanic_orchestrate/dashboard.py"
                                    ),
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        authored = [f for f in view_state["flows"] if f["source"] == "authored"]
        assert authored
        step = authored[0]["steps"][0]
        assert step["node_ref"] == "module:scripts/dontpanic_orchestrate/dashboard.py"
        assert step["valid"] is True

    def test_authored_flow_resolves_non_module_source_path(self, populated_repo):
        flows_path = populated_repo / "docs" / "architecture" / "flows.json"
        schema_path = "claude/shared/schemas/v1.0/architecture-snapshot.schema.json"
        flows_path.write_text(
            json.dumps(
                {
                    "flows": [
                        {
                            "id": "schema-by-path",
                            "title": "Schema by path",
                            "steps": [
                                {
                                    "id": "schema-by-path:step1",
                                    "title": "Schema step",
                                    "source_path": schema_path,
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        authored = [f for f in view_state["flows"] if f["source"] == "authored"]
        assert authored
        step = authored[0]["steps"][0]
        assert step["node_ref"] == f"schema:{schema_path}"
        assert step["valid"] is True

    def test_authored_flow_unknown_source_path_is_invalid(self, populated_repo):
        flows_path = populated_repo / "docs" / "architecture" / "flows.json"
        flows_path.write_text(
            json.dumps(
                {
                    "flows": [
                        {
                            "id": "bad-source-path",
                            "title": "Bad source path",
                            "steps": [
                                {
                                    "id": "bad-source-path:step1",
                                    "title": "Bad path step",
                                    "source_path": "does/not/exist.py",
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        codes = {w["code"] for w in view_state["validation_warnings"]}
        assert "authored_flow_unknown_source_path" in codes
        authored = [f for f in view_state["flows"] if f["source"] == "authored"]
        assert authored[0]["steps"][0]["valid"] is False

    def test_authored_flow_id_cannot_collide_with_derived_flow(
        self, populated_repo
    ):
        flows_path = populated_repo / "docs" / "architecture" / "flows.json"
        flows_path.write_text(
            json.dumps(
                {
                    "flows": [
                        {
                            "id": "dashboard-build",
                            "title": "Collides with derived flow",
                            "steps": [
                                {
                                    "id": "dashboard-build:step1",
                                    "title": "Step 1",
                                    "source_path": (
                                        "scripts/dontpanic_orchestrate/dashboard.py"
                                    ),
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        codes = {w["code"] for w in view_state["validation_warnings"]}
        assert "authored_flow_duplicate_id" in codes
        matching = [
            f for f in view_state["flows"] if f["id"] == "flow:dashboard-build"
        ]
        assert len(matching) == 1
        assert matching[0]["source"] == "derived"

    def test_authored_flow_duplicate_step_id_warns_and_drops_duplicate(
        self, populated_repo
    ):
        flows_path = populated_repo / "docs" / "architecture" / "flows.json"
        flows_path.write_text(
            json.dumps(
                {
                    "flows": [
                        {
                            "id": "duplicate-steps",
                            "title": "Duplicate steps",
                            "steps": [
                                {
                                    "id": "same",
                                    "title": "First",
                                    "source_path": (
                                        "scripts/dontpanic_orchestrate/dashboard.py"
                                    ),
                                },
                                {
                                    "id": "same",
                                    "title": "Second",
                                    "source_path": (
                                        "scripts/dontpanic_orchestrate/"
                                        "state_projection.py"
                                    ),
                                },
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        codes = {w["code"] for w in view_state["validation_warnings"]}
        assert "authored_flow_duplicate_step_id" in codes
        authored = [
            f
            for f in view_state["flows"]
            if f["id"] == "flow:duplicate-steps"
        ]
        assert authored
        assert [s["id"] for s in authored[0]["steps"]] == ["step:same"]

    def test_malformed_flows_json_surfaces_warning_not_crash(self, populated_repo):
        flows_path = populated_repo / "docs" / "architecture" / "flows.json"
        flows_path.write_text("{this is not json", encoding="utf-8")
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        codes = {w["code"] for w in view_state["validation_warnings"]}
        assert "authored_flows_load_error" in codes


# ── (4) missing / stale architecture is represented explicitly ──────────


class TestMissingAndStaleStates:
    def test_absent_architecture_produces_baseline_graph_with_warning(self, tmp_path):
        # Plan C0: absent architecture.json no longer means an empty surface —
        # the weak tier-0/1 baseline renders for ANY repo. The warning and
        # freshness state are unchanged.
        repo = tmp_path / "empty"
        repo.mkdir()
        inputs = avs.load_inputs(repo)
        view_state = avs.build_view_state(inputs, repo_root=repo)
        assert view_state["freshness"]["state"] == "absent"
        assert view_state["freshness"]["regen_command"] == (
            "dontpanic architecture regen --with-html"
        )
        assert any(n["id"] == "fs:." for n in view_state["nodes"]), (
            "C0 baseline: even an empty repo renders the repo-root node"
        )
        assert "baseline" in view_state["coverage"]
        assert view_state["flows"] == []
        codes = {w["code"] for w in view_state["validation_warnings"]}
        assert "architecture_missing" in codes

    def test_stale_architecture_freshness_reports_stale(self, tmp_path, monkeypatch):
        repo = tmp_path / "stale"
        repo.mkdir()
        _write_arch(repo, _minimal_architecture())
        # Stub status() to assert stale without re-walking source.
        from dontpanic_orchestrate import architecture as arch_mod

        def fake_status(repo_root, *, output_path=None):
            return {
                "state": "stale",
                "stored_fingerprint": "old",
                "current_fingerprint": "new",
                "output_path": str(output_path),
            }

        monkeypatch.setattr(arch_mod, "status", fake_status)
        inputs = avs.load_inputs(repo)
        view_state = avs.build_view_state(inputs, repo_root=repo)
        assert view_state["freshness"]["state"] == "stale"
        assert (
            view_state["freshness"]["regen_command"]
            == "dontpanic architecture regen --with-html"
        )

    def test_unreadable_architecture_reports_error_state(self, tmp_path):
        repo = tmp_path / "broken"
        repo.mkdir()
        target = repo / "docs" / "architecture" / "architecture.json"
        target.parent.mkdir(parents=True)
        target.write_text("{not json", encoding="utf-8")
        inputs = avs.load_inputs(repo)
        view_state = avs.build_view_state(inputs, repo_root=repo)
        assert view_state["freshness"]["state"] == "error"
        codes = {w["code"] for w in view_state["validation_warnings"]}
        assert "architecture_missing" in codes


# ── (7) no-secret guard ─────────────────────────────────────────────────


class TestNoSecretOutput:
    def test_secret_in_authored_flow_raises_before_write(self, populated_repo):
        flows_path = populated_repo / "docs" / "architecture" / "flows.json"
        # Synthetic AKIA-prefixed string matches the OSS sanitization grep.
        flows_path.write_text(
            json.dumps(
                {
                    "flows": [
                        {
                            "id": "secret-leak",
                            "title": "AKIAIOSFODNN7EXAMPLE",
                            "steps": [
                                {
                                    "id": "secret-leak:step1",
                                    "title": "Step 1",
                                    "node_ref": (
                                        "module:scripts/dontpanic_orchestrate/"
                                        "dashboard.py"
                                    ),
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        inputs = avs.load_inputs(populated_repo)
        with pytest.raises(ValueError, match="secret pattern"):
            avs.build_view_state(inputs, repo_root=populated_repo)


# ── (3) dashboard.build wires the view-state cache; never mutates JSON ──


class TestDashboardBuildIntegration:
    def test_build_writes_view_state_cache(self, tmp_path, populated_repo):
        plans_root = populated_repo / "docs" / "plans"
        plans_root.mkdir(parents=True, exist_ok=True)
        out_dir = tmp_path / "state-out"

        # capture architecture.json content + mtime before build
        arch_path = populated_repo / "docs" / "architecture" / "architecture.json"
        original_text = arch_path.read_text(encoding="utf-8")
        original_mtime = arch_path.stat().st_mtime_ns

        report = dashboard.build(
            plans_root=plans_root,
            out_dir=out_dir,
            repo_root=populated_repo,
            write_what_now_cache=False,
            write_capabilities_cache=False,
            check_reconcile=False,
        )

        # view-state cache landed in out_dir
        view_cache = out_dir / avs.VIEW_STATE_FILENAME
        assert view_cache.is_file()
        assert report.architecture_view_state_path == view_cache

        # architecture.json untouched
        assert arch_path.read_text(encoding="utf-8") == original_text
        assert arch_path.stat().st_mtime_ns == original_mtime

        # cache shape is the view-state shape
        payload = json.loads(view_cache.read_text(encoding="utf-8"))
        assert payload["schema_version"] == avs.SCHEMA_VERSION
        assert "flows" in payload
        assert "lanes" in payload

    def test_build_emits_view_state_even_when_architecture_missing(
        self, tmp_path
    ):
        repo = tmp_path / "empty-repo"
        repo.mkdir()
        plans_root = repo / "docs" / "plans"
        plans_root.mkdir(parents=True)
        out_dir = tmp_path / "state-out"
        report = dashboard.build(
            plans_root=plans_root,
            out_dir=out_dir,
            repo_root=repo,
            write_what_now_cache=False,
            write_capabilities_cache=False,
            check_reconcile=False,
        )
        view_cache = out_dir / avs.VIEW_STATE_FILENAME
        assert view_cache.is_file()
        payload = json.loads(view_cache.read_text(encoding="utf-8"))
        # Plan 2026-06-06-003 F001 — the build now self-heals a missing map into
        # the cache, so the tab reads a current ("fresh") map instead of an
        # "absent" state whose only remedy was a human "run regen" command.
        assert payload["freshness"]["state"] == "fresh"
        assert isinstance(payload["nodes"], list)  # a real (possibly tiny) map, not absent
        # Build itself should not have surfaced a fatal warning.
        assert report.architecture_view_state_path == view_cache


# ── project-scoped cache layout ─────────────────────────────────────────


class TestProjectScopedCache:
    def test_per_project_build_writes_view_state_under_project_cache(
        self, tmp_path, populated_repo, monkeypatch
    ):
        from dontpanic_orchestrate import (
            projects_dashboard as pd,
            projects_registry as pr,
        )

        monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path / "dontpanic_home"))
        # Ensure plans dir exists for the project build.
        (populated_repo / "docs" / "plans").mkdir(parents=True, exist_ok=True)

        pr.add_project(name="alpha", path=str(populated_repo))
        ctx = pd.project_context_from_entry(pr.find_project("alpha"))
        report = pd.build_project_state(ctx)
        assert report.build_report is not None
        view_cache = ctx.dashboard_cache_path / avs.VIEW_STATE_FILENAME
        assert view_cache.is_file()
        payload = json.loads(view_cache.read_text(encoding="utf-8"))
        assert payload["freshness"]["state"] in ("fresh", "stale", "absent")


# ── graph snapshot ──────────────────────────────────────────────────────


class TestGraphSnapshot:
    def test_graph_shape_snapshot(self, populated_repo):
        """Lock the broad shape: every node has id/type/lane_id/title,
        every edge has id/type/from/to, and at least one flow is emitted.
        """

        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)

        for node in view_state["nodes"]:
            assert {"id", "type", "lane_id", "title"} <= set(node.keys())
            assert node["lane_id"] in {lane["id"] for lane in view_state["lanes"]}

        for edge in view_state["edges"]:
            assert {"id", "type", "from", "to"} <= set(edge.keys())

        assert view_state["flows"], "expected at least one flow"
        for flow in view_state["flows"]:
            assert {"id", "type", "title", "steps", "category", "source"} <= set(
                flow.keys()
            )
            assert flow["type"] == "flow"
            for step in flow["steps"]:
                assert {"id", "type", "title", "node_ref", "order"} <= set(
                    step.keys()
                )
                assert step["type"] == "step"

        # filters expose modules + lanes + categories so the UI can build
        # them without re-deriving.
        filters = view_state["filters"]
        assert "modules" in filters and filters["modules"]
        assert "lanes" in filters
        assert "categories" in filters

        # insights has the four V1 entries.
        insight_ids = {i["id"] for i in view_state["insights"]}
        assert {
            "insight:module-count",
            "insight:plan-count",
            "insight:schema-count",
            "insight:high-fan-out",
        } <= insight_ids

    def test_steps_denormalize_carries_flow_id(self, populated_repo):
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        for step in view_state["steps"]:
            assert "flow_id" in step
            assert step["flow_id"].startswith("flow:")


class TestDriftMetadataGraph:
    """Audit follow-up — drift/fingerprint data is graph-addressable,
    not only hidden in the freshness summary."""

    def test_fingerprint_metadata_node_and_regen_edge_are_emitted(
        self, populated_repo
    ):
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)

        metadata_nodes = [
            n
            for n in view_state["nodes"]
            if n["id"] == "metadata:architecture-fingerprint"
        ]
        assert metadata_nodes
        assert metadata_nodes[0]["type"] == "metadata"
        assert metadata_nodes[0]["files_count"] == 9

        writes_edges = [
            e
            for e in view_state["edges"]
            if e["type"] == "writes"
            and e["to"] == "metadata:architecture-fingerprint"
        ]
        assert writes_edges
        assert writes_edges[0]["from"] == "command:dontpanic-architecture-regen"


# ── audit-driven follow-up: i0 findings ─────────────────────────────────


def _seed_capability_manifests(repo: Path) -> None:
    """Seed two minimal capability manifests so the view-state build
    can synthesize ``capability`` and ``external`` nodes from disk."""

    cap_dir = repo / "capabilities"
    cap_dir.mkdir(parents=True, exist_ok=True)
    (cap_dir / "discord-notify.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "id": "discord-notify",
                "title": "Discord notification sink",
                "kind": "notification_sink",
                "category": "notification-sink",
                "summary": "Send NotifyEvent to Discord webhook.",
                "setup_required": True,
                "requires": {"services": ["Discord webhook"]},
            }
        ),
        encoding="utf-8",
    )
    (cap_dir / "linear.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "id": "linear",
                "title": "Linear ticket pull",
                "kind": "data_source",
                "category": "issue-tracker",
                "summary": "Read Linear issues into the dashboard inbox.",
                "setup_required": True,
                "requires": {"services": ["Linear API"]},
            }
        ),
        encoding="utf-8",
    )


def _seed_dashboard_pages(repo: Path, page_slugs: tuple[str, ...]) -> None:
    pages_dir = repo / "dashboard" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for slug in page_slugs:
        (pages_dir / slug).mkdir(exist_ok=True)


class TestPerProjectLabelling:
    """Finding 1 — per-project caches must record the project identity
    instead of the ``(none)`` sentinel."""

    def test_project_name_threaded_into_view_state(
        self, tmp_path, populated_repo, monkeypatch
    ):
        from dontpanic_orchestrate import (
            projects_dashboard as pd,
            projects_registry as pr,
        )

        monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path / "dontpanic_home"))
        (populated_repo / "docs" / "plans").mkdir(parents=True, exist_ok=True)

        pr.add_project(name="alpha", path=str(populated_repo), display_name="Alpha repo")
        ctx = pd.project_context_from_entry(pr.find_project("alpha"))
        pd.build_project_state(ctx)

        view_cache = ctx.dashboard_cache_path / avs.VIEW_STATE_FILENAME
        payload = json.loads(view_cache.read_text(encoding="utf-8"))
        assert payload["project"]["name"] == "alpha"
        assert payload["project"]["display_name"] == "Alpha repo"
        assert payload["project"]["label"] == "alpha"


class TestAuthoredFlowEdgeRefValidation:
    """Finding 2 — authored ``edge_ref`` must be validated against the
    live graph; unknown edges produce a warning and mark the step
    invalid."""

    def test_unknown_edge_ref_emits_warning_and_invalid_step(self, populated_repo):
        flows_path = populated_repo / "docs" / "architecture" / "flows.json"
        flows_path.write_text(
            json.dumps(
                {
                    "flows": [
                        {
                            "id": "edge-check",
                            "title": "Edge check",
                            "steps": [
                                {
                                    "id": "edge-check:step1",
                                    "title": "Step 1",
                                    "node_ref": (
                                        "module:scripts/dontpanic_orchestrate/"
                                        "dashboard.py"
                                    ),
                                    "edge_ref": "edge:missing:a->b",
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)

        codes = {w["code"] for w in view_state["validation_warnings"]}
        assert "authored_flow_unknown_edge" in codes

        authored = [f for f in view_state["flows"] if f["source"] == "authored"]
        assert authored
        step = authored[0]["steps"][0]
        assert step["valid"] is False
        assert any("unknown edge_ref" in w for w in step["warnings"])

    def test_known_edge_ref_keeps_step_valid(self, populated_repo):
        inputs = avs.load_inputs(populated_repo)
        prebuild = avs.build_view_state(inputs, repo_root=populated_repo)
        # Pick any real edge so we can author a flow that references it.
        edges = prebuild["edges"]
        assert edges, "fixture must emit at least one edge"
        sample_edge = edges[0]["id"]
        # Anchor the step to the edge's source node so node_ref also resolves.
        sample_node = edges[0]["from"]

        flows_path = populated_repo / "docs" / "architecture" / "flows.json"
        flows_path.write_text(
            json.dumps(
                {
                    "flows": [
                        {
                            "id": "edge-ok",
                            "title": "Edge OK",
                            "steps": [
                                {
                                    "id": "edge-ok:step1",
                                    "title": "Step 1",
                                    "node_ref": sample_node,
                                    "edge_ref": sample_edge,
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)
        codes = {w["code"] for w in view_state["validation_warnings"]}
        assert "authored_flow_unknown_edge" not in codes
        authored = [f for f in view_state["flows"] if f["source"] == "authored"]
        assert authored[0]["steps"][0]["valid"] is True


class TestCapabilityPageExternalNodes:
    """Finding 3 — capability manifests, dashboard pages, and external
    service references must surface as graph nodes."""

    def test_capability_nodes_emitted_from_manifests(self, populated_repo):
        _seed_capability_manifests(populated_repo)
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)

        cap_nodes = [n for n in view_state["nodes"] if n["type"] == "capability"]
        cap_ids = {n["id"] for n in cap_nodes}
        assert {"capability:discord-notify", "capability:linear"} <= cap_ids
        for node in cap_nodes:
            assert node["lane_id"] == "lane:capabilities-adapters"
            assert node["source_path"].startswith("capabilities/")

    def test_external_nodes_emitted_from_capability_services(self, populated_repo):
        _seed_capability_manifests(populated_repo)
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)

        external_nodes = [n for n in view_state["nodes"] if n["type"] == "external"]
        ext_titles = {n["title"] for n in external_nodes}
        assert "Discord webhook" in ext_titles
        assert "Linear API" in ext_titles
        for node in external_nodes:
            assert node["lane_id"] == "lane:external-services"

    def test_calls_edges_connect_capability_to_external(self, populated_repo):
        _seed_capability_manifests(populated_repo)
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)

        calls_edges = [e for e in view_state["edges"] if e["type"] == "calls"]
        assert calls_edges, "expected at least one capability→external edge"
        for edge in calls_edges:
            assert edge["from"].startswith("capability:")
            assert edge["to"].startswith("external:")

    def test_page_nodes_emitted_from_dashboard_pages_dir(self, populated_repo):
        _seed_dashboard_pages(populated_repo, ("what-now", "capabilities"))
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)

        page_nodes = [n for n in view_state["nodes"] if n["type"] == "page"]
        page_ids = {n["id"] for n in page_nodes}
        assert {"page:what-now", "page:capabilities"} <= page_ids
        for node in page_nodes:
            assert node["lane_id"] == "lane:client-surfaces"
            assert node["source_path"].startswith("dashboard/pages/")

    def test_filters_categories_reflect_emitted_node_types(self, populated_repo):
        _seed_capability_manifests(populated_repo)
        _seed_dashboard_pages(populated_repo, ("what-now",))
        inputs = avs.load_inputs(populated_repo)
        view_state = avs.build_view_state(inputs, repo_root=populated_repo)

        categories = set(view_state["filters"]["categories"])
        assert {"capability", "external", "page"} <= categories


class TestCommandCatalogCoversCliSurface:
    """Audit i0 follow-up — the command catalog must keep parity with the
    operator-facing CLI surface declared in ``_print_top_level_help`` so
    the architecture graph mirrors what an operator can actually invoke.

    Failure mode this guards against: a new CLI verb ships in cli.py but
    the catalog isn't updated, so the architecture explorer silently
    drops the command from the graph.
    """

    def test_command_catalog_covers_cli_top_level_surface(self):
        from dontpanic_orchestrate import cli as cli_mod

        # Hard-code the expected surface (one entry per operator-facing
        # verb, including each declared subcommand). Mirrors the help
        # block printed by ``_print_top_level_help``. When a new verb is
        # added there, this list MUST grow in lockstep — that's exactly
        # the drift we want to surface.
        expected = {
            "dontpanic dashboard build",
            "dontpanic dashboard serve",
            "dontpanic dashboard open",
            "dontpanic architecture regen",
            "dontpanic architecture status",
            "dontpanic architecture diff",
            "dontpanic capabilities status",
            "dontpanic capabilities setup",
            "dontpanic projects add",
            "dontpanic projects list",
            "dontpanic projects show",
            "dontpanic projects remove",
            "dontpanic manifest init",
            "dontpanic manifest show",
            "dontpanic doctor",
            "dontpanic init",
            "dontpanic smoke",
            "dontpanic showcase regen",
            "dontpanic reconcile baseline",
            "dontpanic reconcile check",
            "dontpanic next",
            "dontpanic state snapshot",
            "dontpanic state export-dashboard",
            "dontpanic plan lock",
            "dontpanic plan audit",
            "dontpanic plan close",
            "dontpanic close",
            "dontpanic dispatch-from-plan",
            "dontpanic approve",
            "dontpanic resume",
            "dontpanic ps",
            "dontpanic quota-caps init",
            "dontpanic quota-caps show",
            "dontpanic calibrate-claude",
            "dontpanic claude-touch",
            "dontpanic mcp serve",
            "dontpanic setup",
            "dontpanic config show",
            "dontpanic config set",
            "dontpanic project config init",
            "dontpanic project config set",
            "dontpanic models list",
            "dontpanic models aliases",
        }
        catalog_names = {entry["name"] for entry in avs._COMMAND_CATALOG}
        missing = expected - catalog_names
        assert not missing, (
            f"command catalog is missing CLI surfaces: {sorted(missing)}. "
            "Add an entry per missing verb so the architecture graph "
            "reflects the real local command surface."
        )

        # And cross-check that every catalog command's verb prefix is
        # one the CLI dispatcher actually recognises (catches typos like
        # "dontpanic plnn lock"). We accept a verb if EITHER the help
        # text or the dispatcher source mentions it — some verbs (e.g.
        # ``claude-touch``) are first-class in ``main()`` but only
        # documented in the module docstring, not the printed help.
        import inspect

        # The flat dispatch table lives in ``_run_cli`` (``main`` is the F003
        # invocation-ledger wrapper around it).
        dispatch_source = inspect.getsource(cli_mod._run_cli)
        for entry in avs._COMMAND_CATALOG:
            tokens = entry["name"].split()
            assert tokens[0] == "dontpanic"
            top_verb = tokens[1]
            in_dispatch = (
                f'== "{top_verb}"' in dispatch_source
                or f"== '{top_verb}'" in dispatch_source
            )
            assert in_dispatch, (
                f"catalog entry {entry['name']!r} references top-level "
                f"verb {top_verb!r} not handled by cli.main() — typo?"
            )

    def test_every_catalog_command_resolves_to_real_module_in_repo(self):
        """The module_path on every catalog entry must point at a real
        source file in the repository so that command nodes can be
        anchored when running against the live architecture.json."""

        repo_root = Path(__file__).resolve().parents[3]
        for entry in avs._COMMAND_CATALOG:
            module_path = repo_root / entry["module_path"]
            assert module_path.is_file(), (
                f"catalog entry {entry['name']!r} points at "
                f"{entry['module_path']!r} which does not exist on disk"
            )
