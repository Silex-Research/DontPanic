"""Plan 2026-05-24-002 F001 — architecture dashboard view model.

Derives a stable, flow-aware graph/cache shape from the existing
``docs/architecture/architecture.json`` crawler output. The dashboard and
agents consume this view-state instead of scraping
``architecture.html`` or re-walking the snapshot themselves.

Invariants:

* Never mutates ``architecture.json``. Reading only.
* Stable IDs for every lane, node, edge, flow, and step. Same input →
  same output (deterministic ordering, sorted keys on emit).
* No demo flows. Every emitted flow's steps reference nodes/edges that
  exist in the graph or — for authored flows — emit a validation warning
  rather than disappearing silently.
* Missing/stale architecture is represented explicitly via the
  ``freshness`` block (``state`` ∈ {``fresh``, ``stale``, ``absent``,
  ``error``}); shape stays valid so the dashboard can render an empty
  state without crashing.
* Output goes through the same secret-shape guard as the operator
  console cache (``operator_console._assert_no_secret_shapes``).

Schema (top-level keys):

  schema_version        — "1.0"
  project               — {"name": str|None, "display_name": str|None}
                          ("(none)" sentinel for single-repo / current cwd)
  generated_at          — ISO8601 UTC when this view-state was built
  source_path           — repo-relative path to architecture.json
  freshness             — see below
  lanes                 — ordered tuple of {id, title, kind, order}
  nodes                 — list of {id, type, lane_id, title, ...}
  edges                 — list of {id, type, from, to, ...}
  flows                 — list of {id, title, summary, category, source,
                          steps:[{id, title, node_ref, edge_ref?, ...}],
                          warnings:[...]}
  steps                 — flat denormalized view of all flow steps
                          (each carries its flow_id for agent
                          consumption without re-walking flows)
  filters               — {modules:[...], plans:[...], categories:[...]}
                          available filter facets the UI can render
  insights              — small list of derived signals
                          (high-degree nodes, plan_count, etc.)
  validation_warnings   — list of {code, message, ref?} entries

This module is the F001 substrate. F002-F005 add the dashboard shell,
flow map, insights, and evidence on top.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import architecture as _architecture
from dontpanic_orchestrate import architecture_contract as _contract
from dontpanic_orchestrate import architecture_intent as _intent
from dontpanic_orchestrate import architecture_js as _architecture_js
from dontpanic_orchestrate import architecture_levels as _architecture_levels
from dontpanic_orchestrate import operator_console as _operator_console

SCHEMA_VERSION = "1.0"

VIEW_STATE_FILENAME = "architecture-view-state.json"

DEFAULT_FLOWS_REL = Path("docs/architecture/flows.json")
"""Authored-flow input path. Optional — when absent, only derived flows
are emitted."""


# ── Lane model ─────────────────────────────────────────────────────────


# Deterministic lane order. The dashboard renders lanes top-to-bottom in
# this sequence; agents that group nodes by lane should respect ``order``.
LANES: tuple[dict[str, Any], ...] = (
    {
        "id": "lane:actors",
        "title": "Actors",
        "kind": "actor",
        "order": 0,
    },
    {
        "id": "lane:client-surfaces",
        "title": "Client surfaces",
        "kind": "client",
        "order": 1,
    },
    {
        "id": "lane:orchestrator-runtime",
        "title": "Orchestrator runtime",
        "kind": "runtime",
        "order": 2,
    },
    {
        "id": "lane:capabilities-adapters",
        "title": "Capabilities & adapters",
        "kind": "capability",
        "order": 3,
    },
    {
        "id": "lane:data-evidence",
        "title": "Data & evidence",
        "kind": "data",
        "order": 4,
    },
    {
        "id": "lane:external-services",
        "title": "External services",
        "kind": "external",
        "order": 5,
    },
)


_VALID_LANE_IDS: frozenset[str] = frozenset(lane["id"] for lane in LANES)


# Module-path prefix → lane id. Order matters; first match wins. Paths
# are repo-relative as recorded in architecture.json.
_LANE_RULES: tuple[tuple[str, str], ...] = (
    ("dashboard/", "lane:client-surfaces"),
    ("scripts/dontpanic_orchestrate/cli", "lane:client-surfaces"),
    ("scripts/dontpanic_orchestrate/dashboard", "lane:client-surfaces"),
    ("scripts/dontpanic_orchestrate/projects_dashboard", "lane:client-surfaces"),
    ("scripts/dontpanic_orchestrate/operator_console", "lane:client-surfaces"),
    ("scripts/dontpanic_orchestrate/state_cli", "lane:client-surfaces"),
    ("scripts/dontpanic_orchestrate/showcase", "lane:client-surfaces"),
    ("scripts/dontpanic_orchestrate/init", "lane:client-surfaces"),
    ("scripts/dontpanic_orchestrate/capabilities", "lane:capabilities-adapters"),
    ("scripts/dontpanic_orchestrate/adapters", "lane:capabilities-adapters"),
    ("scripts/dontpanic_orchestrate/integrations", "lane:capabilities-adapters"),
    ("scripts/dontpanic_orchestrate/external_refs_sync", "lane:capabilities-adapters"),
    ("claude/shared/schemas", "lane:data-evidence"),
    ("docs/plans", "lane:data-evidence"),
    ("docs/architecture", "lane:data-evidence"),
    ("scripts/dontpanic_orchestrate/", "lane:orchestrator-runtime"),
)


def _classify_module_lane(rel_path: str) -> str:
    for prefix, lane in _LANE_RULES:
        if rel_path.startswith(prefix):
            return lane
    return "lane:orchestrator-runtime"


# ── Node + edge ID helpers (stable) ─────────────────────────────────────


def module_node_id(rel_path: str) -> str:
    return f"module:{rel_path}"


def plan_node_id(plan_id: str) -> str:
    return f"plan:{plan_id}"


def schema_node_id(rel_path: str) -> str:
    return f"schema:{rel_path}"


def command_node_id(name: str) -> str:
    # ``name`` is the operator-facing command words joined with hyphens.
    # Stable: "dontpanic architecture regen" → "command:dontpanic-architecture-regen".
    canonical = name.strip().lower().replace(" ", "-")
    return f"command:{canonical}"


def capability_node_id(capability_id: str) -> str:
    return f"capability:{capability_id}"


def external_node_id(name: str) -> str:
    return f"external:{name.strip().lower().replace(' ', '-')}"


def page_node_id(name: str) -> str:
    return f"page:{name.strip().lower().replace(' ', '-')}"


def metadata_node_id(name: str) -> str:
    return f"metadata:{name.strip().lower().replace(' ', '-')}"


def import_edge_id(from_id: str, to_id: str) -> str:
    return f"edge:import:{from_id}->{to_id}"


def runs_edge_id(from_id: str, to_id: str) -> str:
    return f"edge:runs:{from_id}->{to_id}"


def reads_edge_id(from_id: str, to_id: str) -> str:
    return f"edge:reads:{from_id}->{to_id}"


def writes_edge_id(from_id: str, to_id: str) -> str:
    return f"edge:writes:{from_id}->{to_id}"


def calls_edge_id(from_id: str, to_id: str) -> str:
    return f"edge:calls:{from_id}->{to_id}"


# ── Commands catalog — anchored to real modules ─────────────────────────
#
# Every command listed here must (a) name a real source module that exists
# in architecture.json's module list, and (b) describe an operator-facing
# CLI verb. Flows reference these via ``node_ref="command:<id>"`` plus an
# explicit ``edge_ref`` to the runs-edge. The catalog is curated rather
# than auto-derived so that adding a new command is an explicit code-edit
# (the test ``test_command_catalog_covers_cli_top_level_surface`` enforces
# parity with the printed CLI help so the two cannot drift silently).
#
# ``module_path`` points at the module that owns the command's primary
# logic — usually the same module the CLI dispatcher delegates to. For
# commands whose logic lives in ``cli.py`` itself (gate handling,
# dispatch, doctor, plan/close lifecycle, etc.), ``module_path`` is
# ``cli.py``.

_COMMAND_CATALOG: tuple[dict[str, Any], ...] = (
    # ── dashboard ─────────────────────────────────────────────────────
    {
        "name": "dontpanic dashboard build",
        "module_path": "scripts/dontpanic_orchestrate/dashboard.py",
        "summary": "Build dashboard state + caches into dashboard/state/.",
    },
    {
        "name": "dontpanic dashboard serve",
        "module_path": "scripts/dontpanic_orchestrate/dashboard.py",
        "summary": "Serve the static dashboard from localhost; rebuild on source change.",
    },
    {
        "name": "dontpanic dashboard open",
        "module_path": "scripts/dontpanic_orchestrate/dashboard.py",
        "summary": "Open the most recent dashboard build path in the OS default browser.",
    },
    # ── architecture ──────────────────────────────────────────────────
    {
        "name": "dontpanic architecture regen",
        "module_path": "scripts/dontpanic_orchestrate/architecture.py",
        "summary": "Crawl source + plans into architecture.json (and HTML companion).",
    },
    {
        "name": "dontpanic architecture status",
        "module_path": "scripts/dontpanic_orchestrate/architecture.py",
        "summary": "Report whether architecture.json is fresh vs. the working tree.",
    },
    {
        "name": "dontpanic architecture diff",
        "module_path": "scripts/dontpanic_orchestrate/architecture.py",
        "summary": "Diff the on-disk architecture.json against a freshly crawled view.",
    },
    # ── capabilities ──────────────────────────────────────────────────
    {
        "name": "dontpanic capabilities status",
        "module_path": "scripts/dontpanic_orchestrate/capabilities_status.py",
        "summary": "Show capability readiness across configured adapters.",
    },
    {
        "name": "dontpanic capabilities setup",
        "module_path": "scripts/dontpanic_orchestrate/capabilities_setup.py",
        "summary": "Plan or execute setup steps for one capability.",
    },
    # ── projects ──────────────────────────────────────────────────────
    {
        "name": "dontpanic projects add",
        "module_path": "scripts/dontpanic_orchestrate/projects_registry.py",
        "summary": "Register a project for multi-repo dashboard views.",
    },
    {
        "name": "dontpanic projects list",
        "module_path": "scripts/dontpanic_orchestrate/projects_registry.py",
        "summary": "List projects registered in the local registry.",
    },
    {
        "name": "dontpanic projects show",
        "module_path": "scripts/dontpanic_orchestrate/projects_registry.py",
        "summary": "Show one registered project's resolved paths and metadata.",
    },
    {
        "name": "dontpanic projects remove",
        "module_path": "scripts/dontpanic_orchestrate/projects_registry.py",
        "summary": "Remove a project from the local registry.",
    },
    # ── manifest ──────────────────────────────────────────────────────
    {
        "name": "dontpanic manifest init",
        "module_path": "scripts/dontpanic_orchestrate/agent_manifest.py",
        "summary": "Bootstrap the machine-readable agent manifest file.",
    },
    {
        "name": "dontpanic manifest show",
        "module_path": "scripts/dontpanic_orchestrate/agent_manifest.py",
        "summary": "Print the active agent manifest as JSON.",
    },
    # ── doctor / init / smoke / showcase ──────────────────────────────
    {
        "name": "dontpanic doctor",
        "module_path": "scripts/dontpanic_orchestrate/cli.py",
        "summary": "Run local readiness checks for the orchestrator runtime.",
    },
    {
        "name": "dontpanic init",
        "module_path": "scripts/dontpanic_orchestrate/init/__init__.py",
        "summary": "Interactive installer (default --profile=core).",
    },
    {
        "name": "dontpanic smoke",
        "module_path": "scripts/dontpanic_orchestrate/smoke/__init__.py",
        "summary": "Mocked supervisor-plumbing smoke test (no real CLI).",
    },
    {
        "name": "dontpanic showcase regen",
        "module_path": "scripts/dontpanic_orchestrate/showcase/__init__.py",
        "summary": "Generate showcase artifacts for external repos.",
    },
    # ── reconcile ─────────────────────────────────────────────────────
    {
        "name": "dontpanic reconcile baseline",
        "module_path": "scripts/dontpanic_orchestrate/reconcile.py",
        "summary": "Build (and with `--yes` write) the install-snapshot baseline.",
    },
    {
        "name": "dontpanic reconcile check",
        "module_path": "scripts/dontpanic_orchestrate/reconcile.py",
        "summary": "Compare current capability manifests against the install snapshot.",
    },
    # ── next / state ──────────────────────────────────────────────────
    {
        "name": "dontpanic next",
        "module_path": "scripts/dontpanic_orchestrate/cli.py",
        "summary": "Read-only parallel-readiness recommender (text/JSON, repo|fleet).",
    },
    {
        "name": "dontpanic state snapshot",
        "module_path": "scripts/dontpanic_orchestrate/state_cli.py",
        "summary": "Emit the read-only state projection snapshot.",
    },
    {
        "name": "dontpanic state export-dashboard",
        "module_path": "scripts/dontpanic_orchestrate/state_cli.py",
        "summary": "Export the state projection in dashboard-friendly form.",
    },
    # ── plan lifecycle ────────────────────────────────────────────────
    {
        "name": "dontpanic plan lock",
        "module_path": "scripts/dontpanic_orchestrate/cli.py",
        "summary": "Lock a plan after pre-impl gates pass.",
    },
    {
        "name": "dontpanic plan audit",
        "module_path": "scripts/dontpanic_orchestrate/cli.py",
        "summary": "Run the goal-governed audit gate for a plan.",
    },
    {
        "name": "dontpanic plan close",
        "module_path": "scripts/dontpanic_orchestrate/cli.py",
        "summary": "Close out a plan once all features are signed off.",
    },
    {
        "name": "dontpanic close",
        "module_path": "scripts/dontpanic_orchestrate/closeout.py",
        "summary": "Operator close-out of a stopped_no_progress feature.",
    },
    # ── dispatch + gates ──────────────────────────────────────────────
    {
        "name": "dontpanic dispatch-from-plan",
        "module_path": "scripts/dontpanic_orchestrate/supervisor.py",
        "summary": "Dry-run or confirm feature-by-feature dispatch from a plan.",
    },
    {
        "name": "dontpanic approve",
        "module_path": "scripts/dontpanic_orchestrate/gate_pause.py",
        "summary": "Clear one declared engagement-surface gate.",
    },
    {
        "name": "dontpanic resume",
        "module_path": "scripts/dontpanic_orchestrate/gate_pause.py",
        "summary": "Clear engagement gates by name or --all for bulk-clear.",
    },
    {
        "name": "dontpanic ps",
        "module_path": "scripts/dontpanic_orchestrate/active_supervisors.py",
        "summary": "List active supervisor processes from the local registry.",
    },
    # ── quotas + calibration ──────────────────────────────────────────
    {
        "name": "dontpanic quota-caps init",
        "module_path": "scripts/dontpanic_orchestrate/quota_caps_loader.py",
        "summary": "Initialize the operator quota caps config file.",
    },
    {
        "name": "dontpanic quota-caps show",
        "module_path": "scripts/dontpanic_orchestrate/quota_caps_loader.py",
        "summary": "Print the resolved operator quota caps.",
    },
    {
        "name": "dontpanic calibrate-claude",
        "module_path": "scripts/dontpanic_orchestrate/calibration_loader.py",
        "summary": "Record a dashboard-percentage calibration point for Claude.",
    },
    # ── interactive surface ───────────────────────────────────────────
    {
        "name": "dontpanic claude-touch",
        "module_path": "scripts/dontpanic_orchestrate/interactive_state.py",
        "summary": "Record a human Claude request now to seed interactive backoff.",
    },
    {
        "name": "dontpanic mcp serve",
        "module_path": "scripts/dontpanic_orchestrate/mcp_server.py",
        "summary": "Start the local MCP server.",
    },
    # ── setup + config ────────────────────────────────────────────────
    {
        "name": "dontpanic setup",
        "module_path": "scripts/dontpanic_orchestrate/cli.py",
        "summary": "Preview or write global roles + project runtime defaults.",
    },
    {
        "name": "dontpanic config show",
        "module_path": "scripts/dontpanic_orchestrate/cli.py",
        "summary": "Inspect ~/.dontpanic/config.json.",
    },
    {
        "name": "dontpanic config set",
        "module_path": "scripts/dontpanic_orchestrate/cli.py",
        "summary": "Edit a key in ~/.dontpanic/config.json.",
    },
    {
        "name": "dontpanic project config init",
        "module_path": "scripts/dontpanic_orchestrate/project_config.py",
        "summary": "Inspect a project's runtime defaults file.",
    },
    {
        "name": "dontpanic project config set",
        "module_path": "scripts/dontpanic_orchestrate/project_config.py",
        "summary": "Edit a key in a project's runtime defaults file.",
    },
    # ── models (F015) ─────────────────────────────────────────────────
    {
        "name": "dontpanic models list",
        "module_path": "scripts/dontpanic_orchestrate/models_cli.py",
        "summary": "Discover a harness's model catalog (ollama list / OpenRouter cache / documented pass-through).",
    },
    {
        "name": "dontpanic models aliases",
        "module_path": "scripts/dontpanic_orchestrate/models_cli.py",
        "summary": "Print the merged model_aliases table (global config overlaid by project config).",
    },
    # ── workers + Buzz bridge (F013 / F016 / F008) ─────────────────────
    {
        "name": "dontpanic workers list",
        "module_path": "scripts/dontpanic_orchestrate/workers_cli.py",
        "summary": "List named worker profiles (harness + model + allowed roles).",
    },
    {
        "name": "dontpanic workers add",
        "module_path": "scripts/dontpanic_orchestrate/workers_cli.py",
        "summary": "Create a named worker profile; refuses unknown harnesses and widen-only capability overrides.",
    },
    {
        "name": "dontpanic workers set",
        "module_path": "scripts/dontpanic_orchestrate/workers_cli.py",
        "summary": "Update one field on a worker profile.",
    },
    {
        "name": "dontpanic workers show",
        "module_path": "scripts/dontpanic_orchestrate/workers_cli.py",
        "summary": "Show one profile's effective capabilities and holdable roles.",
    },
    {
        "name": "dontpanic workers buzz-bindings",
        "module_path": "scripts/dontpanic_orchestrate/workers_cli.py",
        "summary": "Display optional Buzz agent → profile → harness+model bindings (off by default; no dispatch).",
    },
    {
        "name": "dontpanic buzz-gate",
        "module_path": "scripts/dontpanic_orchestrate/buzz_gate_bridge.py",
        "summary": "Apply an allowlisted signed Buzz approval to a pending gate (--payload or --poll).",
    },
)


def _command_to_module_edges(
    commands: Iterable[dict[str, Any]],
    module_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build command nodes + runs-edges anchored to real modules.

    Commands whose backing module is absent from ``architecture.json``
    are skipped (no orphan nodes). The skip is silent here; the caller
    can spot it by comparing the catalog length to ``len(nodes)``.
    """

    cmd_nodes: list[dict[str, Any]] = []
    cmd_edges: list[dict[str, Any]] = []
    for cmd in commands:
        module_path = cmd["module_path"]
        mod_id = module_node_id(module_path)
        if mod_id not in module_ids:
            continue
        cmd_id = command_node_id(cmd["name"])
        cmd_nodes.append(
            {
                "id": cmd_id,
                "type": "command",
                "lane_id": "lane:client-surfaces",
                "title": cmd["name"],
                "summary": cmd.get("summary") or "",
                "source_path": module_path,
            }
        )
        cmd_edges.append(
            {
                "id": runs_edge_id(cmd_id, mod_id),
                "type": "runs",
                "from": cmd_id,
                "to": mod_id,
            }
        )
    return cmd_nodes, cmd_edges


# ── Public build entry ─────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class BuildInputs:
    """Inputs needed to derive a view-state.

    The ``architecture`` / ``flows`` / ``status`` fields are decoded
    dictionaries (or ``None``). Callers in ``dashboard.build()`` typically
    construct this via :func:`load_inputs`.
    """

    project_name: str | None
    project_display_name: str | None
    architecture_path: Path
    architecture: dict[str, Any] | None
    flows: dict[str, Any] | None
    flows_path: Path | None
    status: dict[str, Any] | None
    load_error: str | None = None


def load_inputs(
    repo_root: Path,
    *,
    project_name: str | None = None,
    project_display_name: str | None = None,
    architecture_path: Path | None = None,
    flows_path: Path | None = None,
) -> BuildInputs:
    """Read architecture.json / flows.json / status into a BuildInputs.

    Never raises for missing files — absence is represented in the
    returned struct so the dashboard can render an empty state.
    """

    arch_path = architecture_path or (repo_root / _architecture.DEFAULT_OUTPUT_REL)
    flows_target = flows_path or (repo_root / DEFAULT_FLOWS_REL)

    arch_data: dict[str, Any] | None = None
    load_error: str | None = None
    if arch_path.is_file():
        try:
            arch_data = json.loads(arch_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            load_error = f"architecture.json unreadable: {exc}"

    flows_data: dict[str, Any] | None = None
    if flows_target.is_file():
        try:
            flows_data = json.loads(flows_target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # Authored-flow errors are surfaced as validation warnings on
            # build, not as a build-time error. Keep flows_data None so
            # the build still proceeds with derived flows.
            flows_data = {"_load_error": str(exc)}

    status_data: dict[str, Any] | None = None
    try:
        status_data = _architecture.status(repo_root, output_path=arch_path)
    except Exception as exc:  # noqa: BLE001 — status surface is advisory
        if load_error is None:
            load_error = f"architecture status failed: {exc}"

    return BuildInputs(
        project_name=project_name,
        project_display_name=project_display_name,
        architecture_path=arch_path,
        architecture=arch_data,
        flows=flows_data,
        flows_path=flows_target if flows_target.is_file() else None,
        status=status_data,
        load_error=load_error,
    )


def build_view_state(
    inputs: BuildInputs,
    *,
    repo_root: Path,
    generated_at: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Construct the architecture view-state dict.

    Always returns a fully-shaped dict so the dashboard can render. When
    ``architecture.json`` is missing/unreadable, lanes still appear,
    nodes/edges/flows are empty, and ``freshness.state`` reports the
    condition. The dict is validated against the no-secret guard before
    return.
    """

    now = generated_at or _dt.datetime.now(_dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    iso_now = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    source_rel = _rel_to_repo(inputs.architecture_path, repo_root)

    project_label = inputs.project_name or "(none)"
    project_block = {
        "name": inputs.project_name,
        "display_name": inputs.project_display_name or inputs.project_name,
        "label": project_label,
    }

    freshness = _build_freshness_block(inputs)
    validation_warnings: list[dict[str, Any]] = []

    if inputs.architecture is None:
        # Plan C0 — the weak baseline works for ANY repo: even without
        # architecture.json the operator sees the tier-0/1 graph and the
        # tiered coverage block instead of an empty surface.
        from dontpanic_orchestrate import architecture_baseline as _baseline

        baseline = _baseline.build_baseline(repo_root)
        baseline_nodes = list(baseline["graph"]["nodes"])
        baseline_edges = list(baseline["graph"]["edges"])
        _contract.apply_evidence_contract(baseline_nodes, baseline_edges)
        absent_coverage = _contract.compute_coverage(repo_root, baseline_nodes)
        absent_coverage["baseline"] = baseline["coverage"]
        absent_layers = _contract.build_layer_shell(baseline_nodes, baseline_edges)
        # Plan B: ADRs are independent of architecture.json — still surface intent.
        _apply_intent_layers(repo_root, baseline_nodes, absent_coverage, absent_layers)
        view_state = {
            "schema_version": SCHEMA_VERSION,
            "project": project_block,
            "generated_at": iso_now,
            "source_path": source_rel,
            "freshness": freshness,
            "lanes": [dict(lane) for lane in LANES],
            "nodes": baseline_nodes,
            "edges": baseline_edges,
            "clusters": [],
            "levels": [],
            "flows": [],
            "steps": [],
            "filters": _empty_filters(),
            "insights": [],
            "coverage": absent_coverage,
            "layers": absent_layers,
            "validation_warnings": validation_warnings,
        }
        if inputs.load_error:
            validation_warnings.append(
                {
                    "code": "architecture_missing",
                    "message": inputs.load_error,
                }
            )
        else:
            validation_warnings.append(
                {
                    "code": "architecture_missing",
                    "message": (
                        "architecture.json was not found. Run "
                        "`dontpanic architecture regen --with-html` to generate it."
                    ),
                }
            )
        _operator_console._assert_no_secret_shapes(view_state)  # noqa: SLF001
        return view_state

    # Real graph build.
    nodes, edges, filters, node_ids_by_type, module_ids = _build_nodes_and_edges(
        inputs.architecture
    )

    # Commands → modules.
    cmd_nodes, cmd_edges = _command_to_module_edges(_COMMAND_CATALOG, module_ids)
    nodes.extend(cmd_nodes)
    edges.extend(cmd_edges)
    fingerprint_id = metadata_node_id("architecture-fingerprint")
    regen_id = command_node_id("dontpanic architecture regen")
    if any(n["id"] == fingerprint_id for n in nodes) and any(
        n["id"] == regen_id for n in nodes
    ):
        edges.append(
            {
                "id": writes_edge_id(regen_id, fingerprint_id),
                "type": "writes",
                "from": regen_id,
                "to": fingerprint_id,
            }
        )

    # Capabilities, dashboard pages, and external services. These are
    # surfaced from on-disk manifests / directories rather than
    # architecture.json (the crawler does not yet index them) so the
    # dashboard can render the full capability + UI surface.
    cap_nodes, cap_edges, external_nodes = _build_capability_and_external_nodes(
        repo_root, module_ids=module_ids
    )
    page_nodes = _build_dashboard_page_nodes(repo_root)
    nodes.extend(cap_nodes)
    nodes.extend(external_nodes)
    nodes.extend(page_nodes)
    edges.extend(cap_edges)

    # Plan C slice 1 — JavaScript/TS import graph (lifts the javascript ceiling).
    js_nodes, js_edges = _architecture_js.extract_js_modules(repo_root)
    nodes.extend(js_nodes)
    edges.extend(js_edges)

    # Plan C2 — first-party TypeScript/TSX/JSX import graph (source_kind code
    # via the evidence contract; non-product trees excluded at the extractor).
    ts_nodes, ts_edges = _architecture_js.extract_ts_modules(repo_root)
    nodes.extend(ts_nodes)
    edges.extend(ts_edges)

    # Plan C0 — tier-0/1 weak baseline (language-agnostic). The render-truth
    # passthrough acceptance requires these low-confidence/filesystem items
    # to SURVIVE to the final payload.
    from dontpanic_orchestrate import architecture_baseline as _baseline

    baseline = _baseline.build_baseline(repo_root)
    nodes.extend(baseline["graph"]["nodes"])
    edges.extend(baseline["graph"]["edges"])

    # Refresh filter categories to reflect every emitted node type so
    # the UI's facet list stays in sync with what was rendered.
    emitted_types = sorted({n["type"] for n in nodes})
    filters["categories"] = emitted_types

    # Build flow set: derived flows first, then authored.
    derived_flows, derived_warnings = _build_derived_flows(
        node_ids=set(n["id"] for n in nodes),
        edge_ids=set(e["id"] for e in edges),
    )
    source_path_to_node_id: dict[str, str] = {}
    for node in nodes:
        source_path = node.get("source_path")
        if isinstance(source_path, str):
            # Keep the first source-path owner. Module/schema/plan/page
            # nodes are emitted before command nodes, while commands often
            # share a module source_path. Authored source_path resolution
            # should land on the source artifact, not the later command
            # shortcut that happens to execute it.
            source_path_to_node_id.setdefault(source_path, node["id"])

    authored_flows, authored_warnings = _validate_authored_flows(
        inputs.flows,
        node_ids=set(n["id"] for n in nodes),
        edge_ids=set(e["id"] for e in edges),
        source_path_to_node_id=source_path_to_node_id,
        reserved_flow_ids=set(f["id"] for f in derived_flows),
    )
    validation_warnings.extend(derived_warnings)
    validation_warnings.extend(authored_warnings)
    flows = derived_flows + authored_flows
    flows.sort(key=lambda f: f["id"])

    steps = _denormalize_steps(flows)

    insights = _build_insights(nodes, edges, inputs.architecture)

    # Directory-derived cluster tree + per-depth level index. This is the
    # graph model the interactive component map drills through (breadcrumb
    # zoom). The `.mmd` slices written by
    # architecture_levels.export_mermaid_levels are an optional diffable
    # export, never this render source.
    # Defensive: an unresolved-import external and a curated-service external
    # could in principle share an id; keep the first occurrence so the contract
    # stamps each node exactly once.
    nodes = _dedupe_by_id(nodes)
    edges = _dedupe_by_id(edges)

    # F001 — stamp the evidence contract (source_kind / evidence_basis /
    # confidence / provenance) onto every node + edge.
    _contract.apply_evidence_contract(nodes, edges)

    clusters, levels = _architecture_levels.build_clusters_and_levels(nodes)

    coverage = _contract.compute_coverage(repo_root, nodes)
    # Plan D F005 — producer parity: the present branch attaches the SAME
    # already-computed build_baseline coverage block the absent branch carries
    # (value-identical by construction; no detector or coverage-rule change).
    coverage["baseline"] = baseline["coverage"]
    layers = _contract.build_layer_shell(nodes, edges)
    # Plan B — populate the intent + diff layers from ADR/doc intent.
    _apply_intent_layers(repo_root, nodes, coverage, layers)

    view_state = {
        "schema_version": SCHEMA_VERSION,
        "project": project_block,
        "generated_at": iso_now,
        "source_path": source_rel,
        "freshness": freshness,
        "lanes": [dict(lane) for lane in LANES],
        "nodes": nodes,
        "edges": edges,
        "clusters": clusters,
        "levels": levels,
        "flows": flows,
        "steps": steps,
        "filters": filters,
        "insights": insights,
        # F003 — extractor-coverage block (honesty ceiling).
        "coverage": coverage,
        # Plan A F004 layer split, now populated by Plan B (intent + diff).
        "layers": layers,
        "validation_warnings": validation_warnings,
    }
    _operator_console._assert_no_secret_shapes(view_state)  # noqa: SLF001
    return view_state


def render_view_state(view_state: dict[str, Any]) -> str:
    """Stable JSON serializer for the view-state cache."""

    return json.dumps(view_state, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_cache(
    view_state: dict[str, Any],
    *,
    out_dir: Path,
    filename: str = VIEW_STATE_FILENAME,
) -> Path:
    """Write the view-state cache file under ``out_dir``."""

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / filename
    target.write_text(render_view_state(view_state), encoding="utf-8")
    return target


# ── Internals ──────────────────────────────────────────────────────────


def _rel_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def _build_freshness_block(inputs: BuildInputs) -> dict[str, Any]:
    """Map ``architecture.status`` output into the view-state freshness shape.

    States:
      * ``fresh``  — fingerprint matches stored snapshot.
      * ``stale``  — fingerprint differs from stored snapshot.
      * ``absent`` — architecture.json does not exist.
      * ``error``  — architecture.json exists but failed to parse.
    """

    regen_command = "dontpanic architecture regen --with-html"
    if inputs.architecture is None:
        if inputs.load_error and "unreadable" in inputs.load_error:
            return {
                "state": "error",
                "message": inputs.load_error,
                "regen_command": regen_command,
                "generated_at": None,
                "files_count": None,
            }
        return {
            "state": "absent",
            "message": (
                "architecture.json was not found. Run the regen command "
                "to generate it."
            ),
            "regen_command": regen_command,
            "generated_at": None,
            "files_count": None,
        }

    status = inputs.status or {}
    raw_state = status.get("state") or "fresh"
    if raw_state not in ("fresh", "stale", "absent"):
        raw_state = "fresh"
    generated_at = inputs.architecture.get("generated_at") if isinstance(
        inputs.architecture, dict
    ) else None
    fingerprint = None
    fp_block = inputs.architecture.get("source_fingerprint") if isinstance(
        inputs.architecture, dict
    ) else None
    if isinstance(fp_block, dict):
        fingerprint = fp_block.get("file_hashes_root")
    files_count = None
    if isinstance(fp_block, dict):
        files_count = fp_block.get("files_count")

    if raw_state == "stale":
        message = (
            "architecture.json is stale relative to the working tree. "
            "Run the regen command to refresh it."
        )
    else:
        message = "architecture.json matches the working tree."

    return {
        "state": raw_state,
        "message": message,
        "regen_command": regen_command,
        "generated_at": generated_at,
        "fingerprint": fingerprint,
        "files_count": files_count,
        "stored_fingerprint": status.get("stored_fingerprint"),
        "current_fingerprint": status.get("current_fingerprint"),
    }


def _empty_filters() -> dict[str, Any]:
    return {
        "modules": [],
        "plans": [],
        "categories": [],
        "lanes": [
            {"id": lane["id"], "title": lane["title"]} for lane in LANES
        ],
    }


def _apply_intent_layers(
    repo_root: Path,
    nodes: list[dict[str, Any]],
    coverage: dict[str, Any],
    layers: dict[str, Any],
) -> None:
    """Plan B: fill the intent + diff layers Plan A reserved empty, and append the
    ADR extractor's honest coverage status. Mutates ``coverage`` + ``layers``."""
    claims = _intent.extract_adr_claims(repo_root)
    layers["intent"]["claims"] = claims
    layers["intent"]["populated"] = bool(claims)
    layers["diff"] = _intent.reconcile_intent(claims, nodes)
    extractors = coverage.get("extractors")
    if isinstance(extractors, list):
        extractors.append(
            {
                "extractor": "adr_intent_extractor",
                "evidence_kind": "adr",
                "status": "covered" if claims else "not_found",
                "node_count": len(claims),
            }
        )


def _dedupe_by_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first occurrence of each ``id`` (stable order)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        iid = item.get("id")
        if iid in seen:
            continue
        if isinstance(iid, str):
            seen.add(iid)
        out.append(item)
    return out


def _build_nodes_and_edges(
    architecture: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, list[str]],
    set[str],
]:
    """Project architecture.json modules / schemas / plans into nodes + edges.

    Returns ``(nodes, edges, filters, node_ids_by_type, module_ids)``.
    """

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    module_ids: set[str] = set()
    module_name_to_id: dict[str, str] = {}
    module_path_set: set[str] = set()

    modules = architecture.get("modules") or []
    for mod in modules:
        if not isinstance(mod, dict):
            continue
        path = mod.get("path")
        name = mod.get("name") or path
        if not isinstance(path, str) or not path:
            continue
        mid = module_node_id(path)
        nodes.append(
            {
                "id": mid,
                "type": "module",
                "lane_id": _classify_module_lane(path),
                "title": name or path,
                "summary": mod.get("summary") or "",
                "source_path": path,
                "public_symbols": list(mod.get("public_symbols") or []),
            }
        )
        module_ids.add(mid)
        module_path_set.add(path)
        if isinstance(name, str):
            module_name_to_id[name] = mid

    # Import edges. Intra-architecture imports resolve to an in-graph module.
    # Unresolved imports (stdlib / third-party / a first-party ref that did not
    # resolve) are NO LONGER dropped (plan 2026-06-07-001 F002): each is emitted
    # as a low-confidence unresolved edge to a deduped external endpoint so the
    # "missing evidence" is visible rather than silently swallowed.
    first_party_tops = {name.split(".", 1)[0] for name in module_name_to_id}
    unresolved_externals: dict[str, dict[str, Any]] = {}
    for mod in modules:
        if not isinstance(mod, dict):
            continue
        path = mod.get("path")
        if not isinstance(path, str):
            continue
        from_id = module_node_id(path)
        for imp in mod.get("imports") or []:
            if not isinstance(imp, str) or not imp:
                continue
            to_id = module_name_to_id.get(imp)
            if to_id == from_id:
                continue
            if to_id is None:
                kind = _contract.classify_unresolved_endpoint(imp, first_party_tops)
                ext_id = external_node_id(imp)
                ext_node = unresolved_externals.get(ext_id)
                if ext_node is None:
                    ext_node = {
                        "id": ext_id,
                        "type": "external",
                        "lane_id": "lane:external-services",
                        "title": imp,
                        "summary": (
                            "unresolved import — first-party reference that did "
                            "not resolve (missing evidence)"
                            if kind == "unknown"
                            else "unresolved import — stdlib/third-party"
                        ),
                        "source_kind": kind,
                        "evidence_basis": "unresolved",
                        "unresolved": True,
                        "referenced_by": [],
                    }
                    unresolved_externals[ext_id] = ext_node
                ext_node["referenced_by"].append(from_id)
                edges.append(
                    {
                        "id": import_edge_id(from_id, ext_id),
                        "type": "import",
                        "from": from_id,
                        "to": ext_id,
                        "unresolved": True,
                    }
                )
                continue
            edges.append(
                {
                    "id": import_edge_id(from_id, to_id),
                    "type": "import",
                    "from": from_id,
                    "to": to_id,
                }
            )

    # Emit the deduped unresolved external endpoints (deterministic order).
    for ext_id in sorted(unresolved_externals):
        node = unresolved_externals[ext_id]
        node["referenced_by"] = sorted(set(node["referenced_by"]))
        nodes.append(node)

    # Schemas → data-evidence nodes.
    schema_ids: list[str] = []
    for schema in architecture.get("schemas") or []:
        if not isinstance(schema, dict):
            continue
        spath = schema.get("path")
        if not isinstance(spath, str):
            continue
        sid = schema_node_id(spath)
        nodes.append(
            {
                "id": sid,
                "type": "schema",
                "lane_id": "lane:data-evidence",
                "title": schema.get("name") or spath,
                "summary": "",
                "source_path": spath,
                "version": schema.get("version"),
                "validator_present": bool(schema.get("validator_present")),
            }
        )
        schema_ids.append(sid)

    # Plans → data-evidence nodes.
    plan_ids: list[dict[str, str]] = []
    for plan in architecture.get("plans") or []:
        if not isinstance(plan, dict):
            continue
        pid_raw = plan.get("id")
        if not isinstance(pid_raw, str) or not pid_raw:
            continue
        pid = plan_node_id(pid_raw)
        title = plan.get("title") or pid_raw
        status = plan.get("status") or "unknown"
        nodes.append(
            {
                "id": pid,
                "type": "plan",
                "lane_id": "lane:data-evidence",
                "title": title,
                "summary": f"status={status}; features={plan.get('features_count', 0)}",
                "source_path": f"docs/plans/{pid_raw}/plan.md",
                "status": status,
                "features_count": plan.get("features_count") or 0,
            }
        )
        plan_ids.append({"id": pid, "title": title, "status": status})

    fp_block = architecture.get("source_fingerprint")
    if isinstance(fp_block, dict):
        nodes.append(
            {
                "id": metadata_node_id("architecture-fingerprint"),
                "type": "metadata",
                "lane_id": "lane:data-evidence",
                "title": "Architecture fingerprint",
                "summary": (
                    "Source fingerprint used to detect architecture drift "
                    "between the cached map and working tree."
                ),
                "source_path": "docs/architecture/architecture.json",
                "generated_at": architecture.get("generated_at"),
                "computed_at": fp_block.get("computed_at"),
                "files_count": fp_block.get("files_count"),
                "fingerprint": fp_block.get("file_hashes_root"),
                "algorithm": fp_block.get("algo"),
            }
        )

    filters = {
        "modules": sorted(module_path_set),
        "plans": [{"id": p["id"], "title": p["title"]} for p in plan_ids],
        "categories": sorted({"metadata", "module", "schema", "plan", "command"}),
        "lanes": [
            {"id": lane["id"], "title": lane["title"]} for lane in LANES
        ],
    }
    node_ids_by_type: dict[str, list[str]] = {}
    for n in nodes:
        node_ids_by_type.setdefault(n["type"], []).append(n["id"])

    return nodes, edges, filters, node_ids_by_type, module_ids


def _build_capability_and_external_nodes(
    repo_root: Path,
    *,
    module_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Derive capability + external-service nodes from on-disk manifests.

    Walks ``<repo_root>/capabilities/*.json`` directly rather than going
    through the typed ``capabilities`` loader so a malformed or out-of-
    band manifest cannot crash the view-state build. Each manifest emits:

      * one ``capability:<id>`` node in the capabilities-adapters lane.
      * one ``external:<slug>`` node (per distinct ``requires.services``
        entry across all manifests) in the external-services lane.
      * a ``calls`` edge from the capability to each of its externals.

    Returns ``(capability_nodes, capability_edges, external_nodes)``.
    Missing capabilities directory is silently empty — the caller passes
    a synthetic repo in tests where the dir does not exist.
    """

    cap_dir = repo_root / "capabilities"
    if not cap_dir.is_dir():
        return [], [], []

    cap_nodes: list[dict[str, Any]] = []
    cap_edges: list[dict[str, Any]] = []
    externals: dict[str, dict[str, Any]] = {}

    for cap_path in sorted(cap_dir.glob("*.json")):
        try:
            payload = json.loads(cap_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        cap_id = payload.get("id")
        if not isinstance(cap_id, str) or not cap_id:
            continue
        node_id = capability_node_id(cap_id)
        rel_source = _rel_to_repo(cap_path, repo_root)
        cap_nodes.append(
            {
                "id": node_id,
                "type": "capability",
                "lane_id": "lane:capabilities-adapters",
                "title": payload.get("title") or cap_id,
                "summary": payload.get("summary") or "",
                "source_path": rel_source,
                "category": payload.get("category"),
                "kind": payload.get("kind"),
                "setup_required": bool(payload.get("setup_required")),
            }
        )
        requires = payload.get("requires") if isinstance(payload, dict) else None
        services = requires.get("services") if isinstance(requires, dict) else None
        if isinstance(services, list):
            for raw in services:
                if not isinstance(raw, str) or not raw.strip():
                    continue
                ext_id = external_node_id(raw)
                externals.setdefault(
                    ext_id,
                    {
                        "id": ext_id,
                        "type": "external",
                        "lane_id": "lane:external-services",
                        "title": raw,
                        "summary": "",
                        "referenced_by": [],
                    },
                )
                externals[ext_id]["referenced_by"].append(node_id)
                cap_edges.append(
                    {
                        "id": calls_edge_id(node_id, ext_id),
                        "type": "calls",
                        "from": node_id,
                        "to": ext_id,
                    }
                )

    # Sort references for determinism so two builds against the same
    # capabilities dir produce byte-identical output.
    external_nodes: list[dict[str, Any]] = []
    for ext_id in sorted(externals):
        entry = externals[ext_id]
        entry["referenced_by"] = sorted(set(entry["referenced_by"]))
        external_nodes.append(entry)

    return cap_nodes, cap_edges, external_nodes


def _build_dashboard_page_nodes(repo_root: Path) -> list[dict[str, Any]]:
    """Map ``dashboard/pages/<page>/`` directories to ``page`` nodes.

    Each subdirectory under ``dashboard/pages/`` represents one console
    page. The page's directory name is the stable slug. Pages are not
    derived from architecture.json because the crawler indexes Python
    modules, not the static dashboard tree.
    """

    pages_dir = repo_root / "dashboard" / "pages"
    if not pages_dir.is_dir():
        return []

    nodes: list[dict[str, Any]] = []
    for entry in sorted(pages_dir.iterdir()):
        if not entry.is_dir():
            continue
        slug = entry.name
        if slug.startswith("."):
            continue
        rel_source = _rel_to_repo(entry, repo_root)
        nodes.append(
            {
                "id": page_node_id(slug),
                "type": "page",
                "lane_id": "lane:client-surfaces",
                "title": slug.replace("-", " ").replace("_", " ").title(),
                "summary": "",
                "source_path": rel_source,
            }
        )
    return nodes


def _build_derived_flows(
    *,
    node_ids: set[str],
    edge_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Emit a small set of flows whose steps reference real nodes/edges.

    Flows whose every step ties to an existing node are emitted as-is.
    Flows whose steps reference at least one missing node are dropped
    AND surface a validation warning so an operator/agent can see which
    derived flow could not be drawn against the current snapshot — this
    prevents demo-data leakage when modules are renamed or deleted.
    """

    warnings: list[dict[str, Any]] = []
    candidates: tuple[dict[str, Any], ...] = (
        {
            "id": "flow:architecture-regen",
            "title": "Architecture regen",
            "summary": "Operator runs the regen command; the crawler walks source + plans and writes architecture.json (and the HTML companion).",
            "category": "operator",
            "source": "derived",
            "steps": (
                {
                    "id": "step:architecture-regen:invoke",
                    "title": "Operator invokes regen",
                    "node_ref": "command:dontpanic-architecture-regen",
                },
                {
                    "id": "step:architecture-regen:crawl",
                    "title": "Crawler walks source + plans",
                    "node_ref": "module:scripts/dontpanic_orchestrate/architecture.py",
                    "edge_ref": "edge:runs:command:dontpanic-architecture-regen->module:scripts/dontpanic_orchestrate/architecture.py",
                },
                {
                    "id": "step:architecture-regen:render-html",
                    "title": "Render HTML companion",
                    "node_ref": "module:scripts/dontpanic_orchestrate/architecture_html.py",
                },
                {
                    "id": "step:architecture-regen:emit-json",
                    "title": "Write architecture.json",
                    "node_ref": "schema:claude/shared/schemas/v1.0/architecture-snapshot.schema.json",
                },
            ),
        },
        {
            "id": "flow:dashboard-build",
            "title": "Dashboard build",
            "summary": "Operator runs the dashboard build; per-surface helpers compose state, capability, reconcile, and architecture caches.",
            "category": "operator",
            "source": "derived",
            "steps": (
                {
                    "id": "step:dashboard-build:invoke",
                    "title": "Operator invokes dashboard build",
                    "node_ref": "command:dontpanic-dashboard-build",
                },
                {
                    "id": "step:dashboard-build:orchestrate",
                    "title": "Build orchestrator composes surfaces",
                    "node_ref": "module:scripts/dontpanic_orchestrate/dashboard.py",
                    "edge_ref": "edge:runs:command:dontpanic-dashboard-build->module:scripts/dontpanic_orchestrate/dashboard.py",
                },
                {
                    "id": "step:dashboard-build:state-projection",
                    "title": "Project plan state into snapshot",
                    "node_ref": "module:scripts/dontpanic_orchestrate/state_projection.py",
                },
                {
                    "id": "step:dashboard-build:action-items",
                    "title": "Aggregate operator ActionItems",
                    "node_ref": "module:scripts/dontpanic_orchestrate/operator_console.py",
                },
            ),
        },
        {
            "id": "flow:capability-setup",
            "title": "Capability setup",
            "summary": "Operator inspects capability status; the runner walks setup steps for each declared capability.",
            "category": "operator",
            "source": "derived",
            "steps": (
                {
                    "id": "step:capability-setup:status",
                    "title": "Operator runs capability status",
                    "node_ref": "command:dontpanic-capabilities-status",
                },
                {
                    "id": "step:capability-setup:load",
                    "title": "Load capability manifests",
                    "node_ref": "module:scripts/dontpanic_orchestrate/capabilities.py",
                },
                {
                    "id": "step:capability-setup:run",
                    "title": "Run setup steps",
                    "node_ref": "module:scripts/dontpanic_orchestrate/capabilities_setup_runner.py",
                },
            ),
        },
        {
            "id": "flow:project-selection",
            "title": "Project selection",
            "summary": "Operator registers a project; the dashboard build resolves --project to per-project caches.",
            "category": "operator",
            "source": "derived",
            "steps": (
                {
                    "id": "step:project-selection:register",
                    "title": "Register project in registry",
                    "node_ref": "command:dontpanic-projects-add",
                },
                {
                    "id": "step:project-selection:resolve",
                    "title": "Resolve selection at build time",
                    "node_ref": "module:scripts/dontpanic_orchestrate/projects_dashboard.py",
                },
                {
                    "id": "step:project-selection:registry",
                    "title": "Read registry entries",
                    "node_ref": "module:scripts/dontpanic_orchestrate/projects_registry.py",
                },
            ),
        },
    )

    flows: list[dict[str, Any]] = []
    for candidate in candidates:
        flow = _materialize_flow(candidate, node_ids=node_ids, edge_ids=edge_ids)
        if flow["_emit"]:
            flow_clean = {k: v for k, v in flow.items() if not k.startswith("_")}
            flows.append(flow_clean)
        else:
            warnings.append(
                {
                    "code": "flow_dropped_missing_refs",
                    "message": (
                        f"derived flow {candidate['id']} dropped: "
                        f"{', '.join(flow['_missing_refs'])}"
                    ),
                    "ref": candidate["id"],
                }
            )
    return flows, warnings


def _materialize_flow(
    candidate: dict[str, Any],
    *,
    node_ids: set[str],
    edge_ids: set[str],
) -> dict[str, Any]:
    """Validate every step against the live graph; record missing refs.

    Returns the candidate with two helper fields:
      * ``_emit`` — True when every step's ``node_ref`` resolves.
      * ``_missing_refs`` — list of unresolved refs (for warnings).
    """

    missing: list[str] = []
    rebuilt_steps: list[dict[str, Any]] = []
    flow_id = candidate["id"]
    for idx, step in enumerate(candidate["steps"], start=1):
        node_ref = step.get("node_ref")
        edge_ref = step.get("edge_ref")
        step_warnings: list[str] = []
        if not node_ref or node_ref not in node_ids:
            missing.append(f"node_ref={node_ref!r}")
            step_warnings.append(f"missing node {node_ref!r}")
        if edge_ref and edge_ref not in edge_ids:
            # Edge refs are advisory — flows can still highlight if the
            # node is known. Surface as warning, do not drop.
            step_warnings.append(f"missing edge {edge_ref!r}")
        rebuilt_steps.append(
            {
                "id": step["id"],
                "type": "step",
                "title": step["title"],
                "node_ref": node_ref,
                "edge_ref": edge_ref,
                "order": idx,
                "warnings": tuple(step_warnings),
            }
        )
    return {
        "id": flow_id,
        "type": "flow",
        "title": candidate["title"],
        "summary": candidate["summary"],
        "category": candidate["category"],
        "source": candidate["source"],
        "steps": rebuilt_steps,
        "warnings": [],
        "_emit": not missing,
        "_missing_refs": missing,
    }


def _validate_authored_flows(
    flows_doc: dict[str, Any] | None,
    *,
    node_ids: set[str],
    edge_ids: set[str],
    source_path_to_node_id: dict[str, str],
    reserved_flow_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate ``docs/architecture/flows.json`` against the live graph.

    Authored flows must reference either:
      * a node ID present in the graph, or
      * a source path that maps to a node's ``source_path``.

    When a step also carries an ``edge_ref``, that edge must exist in
    the graph's edge set. An unknown ``node_ref`` or ``edge_ref`` emits
    a per-step warning AND a top-level ``validation_warnings`` entry,
    and the step is marked ``valid: False`` so the renderer can dim it.
    The flow itself is still emitted so the operator can see what was
    attempted.
    """

    warnings: list[dict[str, Any]] = []
    if not isinstance(flows_doc, dict):
        return [], warnings

    if "_load_error" in flows_doc:
        warnings.append(
            {
                "code": "authored_flows_load_error",
                "message": str(flows_doc["_load_error"]),
            }
        )
        return [], warnings

    raw_flows = flows_doc.get("flows") if isinstance(flows_doc, dict) else None
    if not isinstance(raw_flows, list):
        warnings.append(
            {
                "code": "authored_flows_shape",
                "message": "flows.json must contain a top-level 'flows' list",
            }
        )
        return [], warnings

    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    reserved_ids = reserved_flow_ids or set()
    for raw in raw_flows:
        if not isinstance(raw, dict):
            warnings.append(
                {
                    "code": "authored_flow_invalid",
                    "message": "flow entries must be objects",
                }
            )
            continue
        fid_raw = raw.get("id")
        if not isinstance(fid_raw, str) or not fid_raw:
            warnings.append(
                {
                    "code": "authored_flow_invalid",
                    "message": "flow entries require an 'id' string",
                }
            )
            continue
        flow_id = fid_raw if fid_raw.startswith("flow:") else f"flow:{fid_raw}"
        if flow_id in seen_ids or flow_id in reserved_ids:
            warnings.append(
                {
                    "code": "authored_flow_duplicate_id",
                    "message": f"duplicate or reserved flow id {flow_id!r}",
                    "ref": flow_id,
                }
            )
            continue
        seen_ids.add(flow_id)
        title = raw.get("title") or fid_raw
        summary = raw.get("summary") or ""
        category = raw.get("category") or "operator"

        raw_steps = raw.get("steps") if isinstance(raw, dict) else None
        if not isinstance(raw_steps, list) or not raw_steps:
            warnings.append(
                {
                    "code": "authored_flow_no_steps",
                    "message": f"flow {flow_id!r} has no steps",
                    "ref": flow_id,
                }
            )
            continue
        rebuilt_steps: list[dict[str, Any]] = []
        seen_step_ids: set[str] = set()
        for idx, step in enumerate(raw_steps, start=1):
            if not isinstance(step, dict):
                warnings.append(
                    {
                        "code": "authored_flow_step_invalid",
                        "message": "step entries must be objects",
                        "ref": flow_id,
                    }
                )
                continue
            sid_raw = step.get("id") or f"{flow_id}:step-{idx}"
            step_id = (
                sid_raw
                if isinstance(sid_raw, str) and sid_raw.startswith("step:")
                else f"step:{sid_raw}"
            )
            step_title = step.get("title") or step_id
            if step_id in seen_step_ids:
                warnings.append(
                    {
                        "code": "authored_flow_duplicate_step_id",
                        "message": (
                            f"flow {flow_id!r} contains duplicate step id "
                            f"{step_id!r}"
                        ),
                        "ref": step_id,
                    }
                )
                continue
            seen_step_ids.add(step_id)
            node_ref = step.get("node_ref")
            edge_ref = step.get("edge_ref")
            source_path = step.get("source_path")
            step_warnings: list[str] = []

            resolved_node = None
            if isinstance(node_ref, str) and node_ref in node_ids:
                resolved_node = node_ref
            elif (
                isinstance(source_path, str)
                and source_path in source_path_to_node_id
            ):
                resolved_node = source_path_to_node_id[source_path]
            elif isinstance(source_path, str) and source_path:
                step_warnings.append(f"unknown source_path {source_path!r}")
                warnings.append(
                    {
                        "code": "authored_flow_unknown_source_path",
                        "message": (
                            f"flow {flow_id!r} step {step_id!r} references "
                            f"unknown source path {source_path!r}"
                        ),
                        "ref": step_id,
                    }
                )
            elif isinstance(node_ref, str) and node_ref:
                step_warnings.append(f"unknown node_ref {node_ref!r}")
                warnings.append(
                    {
                        "code": "authored_flow_unknown_node",
                        "message": (
                            f"flow {flow_id!r} step {step_id!r} references "
                            f"unknown node {node_ref!r}"
                        ),
                        "ref": step_id,
                    }
                )
            else:
                step_warnings.append("missing node_ref or source_path")
                warnings.append(
                    {
                        "code": "authored_flow_step_unresolved",
                        "message": (
                            f"flow {flow_id!r} step {step_id!r} has no "
                            "node_ref or source_path"
                        ),
                        "ref": step_id,
                    }
                )

            # An authored edge_ref must exist in the live edge set. We
            # mark the step invalid (not just warn) because an
            # unresolved edge means the dashboard cannot draw the
            # connection the author intended.
            if isinstance(edge_ref, str) and edge_ref and edge_ref not in edge_ids:
                step_warnings.append(f"unknown edge_ref {edge_ref!r}")
                warnings.append(
                    {
                        "code": "authored_flow_unknown_edge",
                        "message": (
                            f"flow {flow_id!r} step {step_id!r} references "
                            f"unknown edge {edge_ref!r}"
                        ),
                        "ref": step_id,
                    }
                )

            rebuilt_steps.append(
                {
                    "id": step_id,
                    "type": "step",
                    "title": step_title,
                    "node_ref": resolved_node or node_ref,
                    "edge_ref": edge_ref,
                    "source_path": source_path,
                    "order": idx,
                    "warnings": tuple(step_warnings),
                    "valid": not step_warnings,
                }
            )

        out.append(
            {
                "id": flow_id,
                "type": "flow",
                "title": title,
                "summary": summary,
                "category": category,
                "source": "authored",
                "steps": rebuilt_steps,
                "warnings": [],
            }
        )
    return out, warnings


def _denormalize_steps(
    flows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flat step list keyed by ``(flow_id, step_id)``.

    Agents that ingest the view-state for "give me every step in flow
    order" can iterate this instead of nested-walking ``flows``.
    """

    out: list[dict[str, Any]] = []
    for flow in flows:
        flow_id = flow["id"]
        for step in flow.get("steps", []):
            entry = dict(step)
            entry["flow_id"] = flow_id
            out.append(entry)
    return out


def _build_insights(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    architecture: dict[str, Any],
) -> list[dict[str, Any]]:
    """Small set of evidence-backed signals.

    V1 emits: module count, plan count, schema count, top-3 import
    fan-out modules, count of stale-flag warnings (always 0 here —
    fingerprint drift is in freshness, not insights).
    """

    fan_out: dict[str, int] = {}
    for edge in edges:
        if edge.get("type") != "import":
            continue
        fan_out[edge["from"]] = fan_out.get(edge["from"], 0) + 1
    top = sorted(fan_out.items(), key=lambda kv: (-kv[1], kv[0]))[:3]

    plan_count = sum(1 for n in nodes if n["type"] == "plan")
    module_count = sum(1 for n in nodes if n["type"] == "module")
    schema_count = sum(1 for n in nodes if n["type"] == "schema")

    return [
        {
            "id": "insight:module-count",
            "title": "Modules",
            "value": module_count,
            "kind": "count",
        },
        {
            "id": "insight:plan-count",
            "title": "Plans",
            "value": plan_count,
            "kind": "count",
        },
        {
            "id": "insight:schema-count",
            "title": "Schemas",
            "value": schema_count,
            "kind": "count",
        },
        {
            "id": "insight:high-fan-out",
            "title": "Highest import fan-out",
            "value": [
                {"node": node_id, "imports": count} for node_id, count in top
            ],
            "kind": "ranking",
        },
    ]


__all__ = [
    "SCHEMA_VERSION",
    "VIEW_STATE_FILENAME",
    "DEFAULT_FLOWS_REL",
    "LANES",
    "BuildInputs",
    "build_view_state",
    "load_inputs",
    "module_node_id",
    "plan_node_id",
    "schema_node_id",
    "command_node_id",
    "capability_node_id",
    "external_node_id",
    "page_node_id",
    "render_view_state",
    "write_cache",
]
