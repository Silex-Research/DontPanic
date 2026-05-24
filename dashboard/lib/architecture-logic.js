// ── Architecture Logic — Pure HTML builders for the Architecture tab ──
// Plan: 2026-05-24-002-feat-dashboard-architecture-explorer-v1.
//
// F001 wrote `dashboard/state/architecture-view-state.json` with lanes,
// nodes, edges, flows, steps, filters, insights, and validation_warnings.
// F002 owned the shell (nav, value-first copy, empty states, regen copy
// button). F003 (this module) owns the *interactive flow explorer*:
//
//   - deterministic swimlane SVG layout (rows = lanes, nodes sorted by id)
//   - typed edges (import / runs / calls / writes)
//   - persistent legend by node category
//   - right-side flow list with selected state + clear-selection
//   - numbered step markers on the selected flow path
//   - scrollable step inspector matching the highlighted markers
//   - search + lane + type + edge-type filters
//   - click-to-detail panel with related nodes, source metadata, plans
//   - hover labels (title attributes on every node) and zoom/pan/reset
//   - validation warnings are visible but non-fatal
//
// All exports are pure: same input → same string output, no DOM access.
// DOM wiring (selection state, search input, zoom transform, copy
// button) lives in `pages/architecture/architecture.js`.

import { esc } from './html-escape.js';
import {
  ALL_PROJECTS_VALUE,
  renderScopeBadgeHTML,
} from './project-selector-logic.js';
import { renderProvenanceFooterHTML } from './provenance.js';

const ARCH_SOURCE = 'dashboard/state/architecture-view-state.json';
const ARCH_REFRESH = 'dontpanic architecture regen --with-html';
const ARCH_BUILD = 'dontpanic dashboard build';

export const FRESHNESS_STATES = Object.freeze([
  'fresh',
  'stale',
  'absent',
  'error',
  'missing',
]);

export const FRESHNESS_HEADLINES = Object.freeze({
  fresh:   'System map is up to date',
  stale:   'System map is out of date',
  absent:  'No system map yet',
  missing: 'No system map yet',
  error:   'System map could not be read',
});

export const FRESHNESS_IMPACT = Object.freeze({
  fresh:
    'The architecture snapshot matches the working tree. Modules, plans, '
    + 'and relationships shown reflect the current code.',
  stale:
    'Files changed since the snapshot was generated. Run the regen '
    + 'command to refresh the map before relying on it for review.',
  absent:
    'The dashboard does not have an architecture snapshot to read. '
    + 'Run the regen command, then rebuild the dashboard state.',
  missing:
    'The dashboard does not have an architecture snapshot to read. '
    + 'Run the regen command, then rebuild the dashboard state.',
  error:
    'The architecture snapshot exists but failed to parse. The page '
    + 'shows the source path and the message from the build so you can '
    + 'inspect and regenerate the file.',
});

export const FRESHNESS_COLORS = Object.freeze({
  fresh:   'green',
  stale:   'yellow',
  absent:  'muted',
  missing: 'muted',
  error:   'red',
});

// Closed set of node categories the legend understands. Any node type
// not in this map falls through to the "other" bucket so the legend
// stays honest when F001 emits something new.
export const NODE_CATEGORIES = Object.freeze({
  module:     { label: 'Module',     color: '#60a5fa', short: 'mod' },
  plan:       { label: 'Plan',       color: '#a78bfa', short: 'plan' },
  capability: { label: 'Capability', color: '#34d399', short: 'cap' },
  command:    { label: 'Command',    color: '#fbbf24', short: 'cmd' },
  schema:     { label: 'Schema',     color: '#22d3ee', short: 'schm' },
  page:       { label: 'Page',       color: '#f472b6', short: 'page' },
  external:   { label: 'External',   color: '#f87171', short: 'ext' },
  metadata:   { label: 'Metadata',   color: '#94a3b8', short: 'meta' },
  other:      { label: 'Other',      color: '#cbd5e1', short: 'other' },
});

export const EDGE_TYPES = Object.freeze({
  import:  { label: 'Import',  color: '#3b82f6' },
  runs:    { label: 'Runs',    color: '#facc15' },
  calls:   { label: 'Calls',   color: '#10b981' },
  writes:  { label: 'Writes',  color: '#f43f5e' },
  other:   { label: 'Other',   color: '#94a3b8' },
});

// ─── Envelope resolution + normalization ─────────────────────────────

export function resolveArchitectureEnvelope(opts = {}) {
  const selected = typeof opts.selectedProject === 'string'
    ? opts.selectedProject
    : ALL_PROJECTS_VALUE;
  const byProject = opts.byProject && typeof opts.byProject === 'object'
    ? opts.byProject
    : null;
  const hasPerProjectCache = byProject != null && Object.keys(byProject).length > 0;
  if (selected !== ALL_PROJECTS_VALUE && hasPerProjectCache) {
    const scoped = byProject[selected];
    if (scoped != null) return scoped;
    // F004 finding #1: when a concrete project is selected and a
    // per-project cache is present but lacks that project, do NOT fall
    // back to opts.single — that would render an unrelated repo's map.
    // Return null so callers branch to an explicit missing-project state.
    return null;
  }
  return opts.single != null ? opts.single : null;
}

/**
 * True when a concrete project is selected and the per-project cache is
 * present but does not have an entry for that project. Used by both
 * `renderArchitectureHTML` and the page module to branch to a
 * missing-project state instead of rendering another project's map.
 */
export function isMissingSelectedProject(opts = {}) {
  const selected = typeof opts.selectedProject === 'string'
    ? opts.selectedProject
    : ALL_PROJECTS_VALUE;
  if (selected === ALL_PROJECTS_VALUE) return false;
  const byProject = opts.byProject && typeof opts.byProject === 'object'
    ? opts.byProject
    : null;
  if (byProject == null) return false;
  if (Object.keys(byProject).length === 0) return false;
  return byProject[selected] == null;
}

function _normalizeFreshnessState(raw) {
  if (raw === 'missing') return 'absent';
  if (raw === 'fresh' || raw === 'stale' || raw === 'absent' || raw === 'error') {
    return raw;
  }
  return 'absent';
}

export function isMissingState(envelope) {
  if (envelope == null) return true;
  if (typeof envelope !== 'object') return true;
  if (!Array.isArray(envelope.lanes)) return true;
  if (!Array.isArray(envelope.nodes)) return true;
  return false;
}

export function normalizeEnvelope(raw) {
  if (isMissingState(raw)) return null;
  const project = raw.project && typeof raw.project === 'object'
    ? raw.project
    : {};
  const freshness = raw.freshness && typeof raw.freshness === 'object'
    ? raw.freshness
    : {};
  return {
    schema_version: typeof raw.schema_version === 'string' ? raw.schema_version : '',
    generated_at:   typeof raw.generated_at === 'string'   ? raw.generated_at   : '',
    source_path:    typeof raw.source_path === 'string'    ? raw.source_path    : '',
    project: {
      name:         typeof project.name === 'string' ? project.name : null,
      display_name: typeof project.display_name === 'string' ? project.display_name : null,
      label:        typeof project.label === 'string' ? project.label : null,
    },
    freshness: {
      state:           _normalizeFreshnessState(freshness.state),
      message:         typeof freshness.message === 'string' ? freshness.message : '',
      regen_command:   typeof freshness.regen_command === 'string' && freshness.regen_command.length > 0
        ? freshness.regen_command
        : ARCH_REFRESH,
      generated_at:    typeof freshness.generated_at === 'string' ? freshness.generated_at : '',
      fingerprint:     typeof freshness.fingerprint === 'string' ? freshness.fingerprint : '',
      stored_fingerprint:  typeof freshness.stored_fingerprint === 'string' ? freshness.stored_fingerprint : '',
      current_fingerprint: typeof freshness.current_fingerprint === 'string' ? freshness.current_fingerprint : '',
      files_count:     typeof freshness.files_count === 'number' ? freshness.files_count : null,
    },
    lanes:               Array.isArray(raw.lanes) ? raw.lanes : [],
    nodes:               Array.isArray(raw.nodes) ? raw.nodes : [],
    edges:               Array.isArray(raw.edges) ? raw.edges : [],
    flows:               Array.isArray(raw.flows) ? raw.flows : [],
    steps:               Array.isArray(raw.steps) ? raw.steps : [],
    filters:             raw.filters && typeof raw.filters === 'object' ? raw.filters : {},
    insights:            Array.isArray(raw.insights) ? raw.insights : [],
    validation_warnings: Array.isArray(raw.validation_warnings) ? raw.validation_warnings : [],
  };
}

export function collectFlowWarnings(envelope) {
  if (envelope == null) return [];
  const out = [];
  for (const flow of envelope.flows || []) {
    if (Array.isArray(flow.warnings)) {
      for (const w of flow.warnings) {
        if (w && typeof w === 'object' && typeof w.message === 'string') {
          out.push({
            flow_id: typeof flow.id === 'string' ? flow.id : '',
            step_id: '',
            message: w.message,
          });
        } else if (typeof w === 'string' && w.length > 0) {
          out.push({
            flow_id: typeof flow.id === 'string' ? flow.id : '',
            step_id: '',
            message: w,
          });
        }
      }
    }
    if (Array.isArray(flow.steps)) {
      for (const step of flow.steps) {
        if (!step || !Array.isArray(step.warnings)) continue;
        for (const w of step.warnings) {
          if (w && typeof w === 'object' && typeof w.message === 'string') {
            out.push({
              flow_id: typeof flow.id === 'string' ? flow.id : '',
              step_id: typeof step.id === 'string' ? step.id : '',
              message: w.message,
            });
          } else if (typeof w === 'string' && w.length > 0) {
            out.push({
              flow_id: typeof flow.id === 'string' ? flow.id : '',
              step_id: typeof step.id === 'string' ? step.id : '',
              message: w,
            });
          }
        }
      }
    }
  }
  for (const w of envelope.validation_warnings || []) {
    if (w && typeof w === 'object' && typeof w.message === 'string') {
      out.push({
        flow_id: typeof w.flow_id === 'string' ? w.flow_id : '',
        step_id: typeof w.step_id === 'string' ? w.step_id : '',
        message: w.message,
      });
    } else if (typeof w === 'string' && w.length > 0) {
      out.push({ flow_id: '', step_id: '', message: w });
    }
  }
  return out;
}

// ─── Graph layout (deterministic) ────────────────────────────────────

const LAYOUT_DEFAULTS = Object.freeze({
  nodeWidth:   140,
  nodeHeight:  34,
  nodeGapX:    14,
  nodeGapY:    10,
  cols:        9,
  laneHeader:  44,
  lanePadY:    16,
  paddingX:    32,
  paddingTop:  20,
});

function categoryFor(nodeType) {
  if (NODE_CATEGORIES[nodeType]) return nodeType;
  return 'other';
}

/**
 * Compute a deterministic SVG layout for the architecture view-state.
 * Lanes are stacked vertically in `order` then `id`. Nodes within each
 * lane are sorted by id and wrapped into a fixed-column grid so the
 * same envelope produces the same coordinates every render (required
 * for layout snapshot tests).
 *
 * Returns: { width, height, lanes, nodesById, edges, paths } where:
 *   - lanes[]: {id, title, kind, y, height, nodes: [...]}
 *   - nodesById: Map<id, {id, x, y, w, h, lane_id, category, ...}>
 *   - edges[]: {id, from, to, type, x1, y1, x2, y2, color, missing}
 *   - paths: layout metadata for tests
 */
export function layoutArchitectureGraph(envelope, opts = {}) {
  const cfg = { ...LAYOUT_DEFAULTS, ...opts };
  if (envelope == null) {
    return { width: 0, height: 0, lanes: [], nodesById: new Map(), edges: [] };
  }
  const lanes = [...(envelope.lanes || [])]
    .filter((l) => l && typeof l === 'object' && typeof l.id === 'string')
    .sort((a, b) => {
      const ao = typeof a.order === 'number' ? a.order : 99;
      const bo = typeof b.order === 'number' ? b.order : 99;
      if (ao !== bo) return ao - bo;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    });

  // Bucket nodes by lane_id (sorted deterministically by id within lane).
  const byLane = new Map();
  const orphans = [];
  for (const node of (envelope.nodes || [])) {
    if (!node || typeof node !== 'object' || typeof node.id !== 'string') continue;
    const laneId = typeof node.lane_id === 'string' ? node.lane_id : '';
    if (!laneId || !lanes.some((l) => l.id === laneId)) {
      orphans.push(node);
      continue;
    }
    if (!byLane.has(laneId)) byLane.set(laneId, []);
    byLane.get(laneId).push(node);
  }
  for (const arr of byLane.values()) {
    arr.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  }
  // Stash orphans into a virtual "(unlaned)" lane so the page does not
  // silently drop nodes whose lane_id was lost in a schema mismatch.
  if (orphans.length > 0) {
    lanes.push({ id: 'lane:_unlaned', title: 'Unlaned', kind: 'other', order: 999 });
    byLane.set('lane:_unlaned', orphans.sort((a, b) => (a.id < b.id ? -1 : 1)));
  }

  const cols = cfg.cols;
  const totalWidth = cfg.paddingX * 2 + cols * cfg.nodeWidth + (cols - 1) * cfg.nodeGapX;

  const nodesById = new Map();
  const laidOutLanes = [];
  let cursorY = cfg.paddingTop;

  for (const lane of lanes) {
    const laneNodes = byLane.get(lane.id) || [];
    const rows = Math.max(1, Math.ceil(laneNodes.length / cols));
    const laneHeight = cfg.laneHeader + rows * cfg.nodeHeight + (rows - 1) * cfg.nodeGapY + cfg.lanePadY;
    const laneOut = {
      id: lane.id,
      title: typeof lane.title === 'string' ? lane.title : lane.id,
      kind: typeof lane.kind === 'string' ? lane.kind : 'other',
      y: cursorY,
      height: laneHeight,
      rows,
      nodes: [],
    };
    laneNodes.forEach((node, idx) => {
      const row = Math.floor(idx / cols);
      const col = idx % cols;
      const x = cfg.paddingX + col * (cfg.nodeWidth + cfg.nodeGapX);
      const y = cursorY + cfg.laneHeader + row * (cfg.nodeHeight + cfg.nodeGapY);
      const out = {
        id: node.id,
        title: typeof node.title === 'string' && node.title.length > 0
          ? node.title
          : node.id,
        type: typeof node.type === 'string' ? node.type : 'other',
        category: categoryFor(typeof node.type === 'string' ? node.type : 'other'),
        lane_id: lane.id,
        source_path: typeof node.source_path === 'string' ? node.source_path : '',
        summary: typeof node.summary === 'string' ? node.summary : '',
        fingerprint: typeof node.fingerprint === 'string' ? node.fingerprint : '',
        x,
        y,
        w: cfg.nodeWidth,
        h: cfg.nodeHeight,
      };
      nodesById.set(node.id, out);
      laneOut.nodes.push(out);
    });
    laidOutLanes.push(laneOut);
    cursorY += laneHeight;
  }

  // Edges connect node centers. Missing endpoints (filtered or absent)
  // get `missing: true` so the SVG can omit them deterministically.
  const edgesOut = [];
  for (const edge of (envelope.edges || [])) {
    if (!edge || typeof edge !== 'object' || typeof edge.id !== 'string') continue;
    const from = nodesById.get(edge.from);
    const to = nodesById.get(edge.to);
    if (!from || !to) {
      edgesOut.push({
        id: edge.id,
        from: typeof edge.from === 'string' ? edge.from : '',
        to: typeof edge.to === 'string' ? edge.to : '',
        type: typeof edge.type === 'string' ? edge.type : 'other',
        missing: true,
      });
      continue;
    }
    edgesOut.push({
      id: edge.id,
      from: edge.from,
      to: edge.to,
      type: typeof edge.type === 'string' ? edge.type : 'other',
      x1: from.x + from.w / 2,
      y1: from.y + from.h / 2,
      x2: to.x + to.w / 2,
      y2: to.y + to.h / 2,
      missing: false,
    });
  }
  edgesOut.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));

  return {
    width: totalWidth,
    height: cursorY + cfg.paddingTop,
    lanes: laidOutLanes,
    nodesById,
    edges: edgesOut,
    cfg,
  };
}

/**
 * Collect every node and edge ID that participates in `flowId`. Used by
 * the renderer to apply selection highlighting and dimming. Returns a
 * `{ nodeIds: Set, edgeIds: Set, stepRefs: [...] }` envelope where
 * `stepRefs` is the ordered step descriptors for the inspector.
 */
export function getFlowParticipants(envelope, flowId) {
  const empty = { nodeIds: new Set(), edgeIds: new Set(), stepRefs: [], flow: null };
  if (envelope == null || typeof flowId !== 'string' || flowId.length === 0) {
    return empty;
  }
  const flow = (envelope.flows || []).find((f) => f && f.id === flowId);
  if (!flow) return empty;
  const nodeIds = new Set();
  const edgeIds = new Set();
  const stepRefs = [];
  const steps = Array.isArray(flow.steps) ? flow.steps : [];
  steps.forEach((step, idx) => {
    if (!step || typeof step !== 'object') return;
    const order = typeof step.order === 'number' ? step.order : idx + 1;
    const nodeRef = typeof step.node_ref === 'string' ? step.node_ref : '';
    const edgeRef = typeof step.edge_ref === 'string' ? step.edge_ref : '';
    if (nodeRef) nodeIds.add(nodeRef);
    if (edgeRef) edgeIds.add(edgeRef);
    stepRefs.push({
      id: typeof step.id === 'string' ? step.id : `step:${order}`,
      title: typeof step.title === 'string' ? step.title : `Step ${order}`,
      node_ref: nodeRef,
      edge_ref: edgeRef,
      order,
      warnings: Array.isArray(step.warnings) ? step.warnings : [],
      summary: typeof step.summary === 'string' ? step.summary : '',
    });
  });
  stepRefs.sort((a, b) => a.order - b.order);
  return { nodeIds, edgeIds, stepRefs, flow };
}

// ─── Top-level renderer ──────────────────────────────────────────────

export function renderArchitectureHTML(raw, opts = {}) {
  const selected = typeof opts.selectedProject === 'string'
    ? opts.selectedProject
    : ALL_PROJECTS_VALUE;
  const scope = selected === ALL_PROJECTS_VALUE ? 'fleet' : 'project';

  // F004 — All Projects: when we have per-project caches, render a
  // fleet card grid instead of merging unrelated repo graphs. Each card
  // shows the project's own architecture freshness + an "open map"
  // affordance that switches the selector to that project. Projects
  // without an architecture artifact get an explicit empty card with
  // the regen command for that repo.
  const byProject = opts.byProject && typeof opts.byProject === 'object'
    ? opts.byProject
    : null;
  const fleetSummary = opts.fleetSummary && typeof opts.fleetSummary === 'object'
    ? opts.fleetSummary
    : null;
  if (selected === ALL_PROJECTS_VALUE && _fleetHasPerProjectData(byProject, fleetSummary)) {
    return renderFleetArchitectureHTML({ byProject, fleetSummary });
  }

  // F004 finding #1: a concrete project is selected but byProject has
  // no entry for it. Render an explicit missing-project state with the
  // project's display name + regen instructions for that repo — never
  // silently fall back to another project's map.
  if (isMissingSelectedProject({ selectedProject: selected, byProject })) {
    return renderMissingProjectStateHTML(selected, fleetSummary);
  }

  const envelope = normalizeEnvelope(raw);
  if (envelope == null) {
    return renderMissingStateHTML(scope);
  }
  const state = envelope.freshness.state;
  if (state === 'absent' || state === 'missing') {
    return renderMissingStateHTML(scope, envelope);
  }
  if (state === 'error') {
    return renderErrorStateHTML(scope, envelope);
  }
  return renderPopulatedHTML(envelope, scope, opts);
}

function _fleetHasPerProjectData(byProject, fleetSummary) {
  if (byProject && typeof byProject === 'object'
      && Object.keys(byProject).length > 0) {
    return true;
  }
  if (fleetSummary && Array.isArray(fleetSummary.projects)
      && fleetSummary.projects.length > 0) {
    return true;
  }
  return false;
}

export function renderMissingStateHTML(scope = 'project', envelope = null) {
  const freshState = envelope && envelope.freshness && envelope.freshness.state
    ? envelope.freshness.state
    : 'absent';
  const headline = FRESHNESS_HEADLINES[freshState] || FRESHNESS_HEADLINES.absent;
  const impact = FRESHNESS_IMPACT[freshState] || FRESHNESS_IMPACT.absent;
  const regen = envelope && envelope.freshness && envelope.freshness.regen_command
    ? envelope.freshness.regen_command
    : ARCH_REFRESH;
  const sourcePath = envelope && envelope.source_path
    ? envelope.source_path
    : 'docs/architecture/architecture.json';
  const lastGenerated = envelope && envelope.freshness && envelope.freshness.generated_at
    ? envelope.freshness.generated_at
    : null;
  const message = envelope && envelope.freshness && envelope.freshness.message
    ? envelope.freshness.message
    : '';
  return `
    <div class="arch-layout" data-state="missing">
      <section class="panel arch-empty-card"
               data-empty-state="missing"
               data-freshness="${esc(freshState)}">
        <div class="arch-empty-scope">${renderScopeBadgeHTML(scope)}</div>
        <h2 class="arch-empty-title">${esc(headline)}</h2>
        <p class="arch-empty-impact">${esc(impact)}</p>
        ${message ? `<p class="arch-empty-message">${esc(message)}</p>` : ''}
        <div class="arch-empty-meta">
          <span class="arch-meta-row">
            <span class="arch-meta-label">Source</span>
            <code class="arch-meta-value">${esc(sourcePath)}</code>
          </span>
          <span class="arch-meta-row">
            <span class="arch-meta-label">Last generated</span>
            <span class="arch-meta-value">${esc(lastGenerated || '—')}</span>
          </span>
        </div>
        <div class="arch-empty-actions">
          <p class="arch-empty-step">
            1. Regenerate the architecture snapshot:
          </p>
          ${renderCommandHTML(regen)}
          <p class="arch-empty-step">
            2. Rebuild the dashboard state so this tab can read the new map:
          </p>
          ${renderCommandHTML(ARCH_BUILD)}
        </div>
        <p class="arch-empty-note">
          The dashboard is read-only. It will not run these commands for
          you — copy each line and run it in your own terminal.
        </p>
      </section>
      ${buildProvenance(envelope, scope)}
    </div>
  `;
}

/**
 * F004 finding #1: render an explicit missing-project state when a
 * concrete project is selected but its view-state is not present in the
 * per-project cache. Mentions the project by name + display name so the
 * operator can see the dashboard did NOT silently fall back to another
 * repo's architecture graph.
 */
export function renderMissingProjectStateHTML(projectName, fleetSummary = null) {
  const safeName = typeof projectName === 'string' && projectName.length > 0
    ? projectName
    : '(unknown)';
  let displayName = safeName;
  if (fleetSummary && Array.isArray(fleetSummary.projects)) {
    const entry = fleetSummary.projects.find(
      (p) => p && typeof p === 'object' && p.name === safeName,
    );
    if (entry && typeof entry.display_name === 'string'
        && entry.display_name.length > 0) {
      displayName = entry.display_name;
    }
  }
  return `
    <div class="arch-layout" data-state="missing" data-missing-project="${esc(safeName)}">
      <section class="panel arch-empty-card"
               data-empty-state="missing-project"
               data-missing-project="${esc(safeName)}"
               data-freshness="absent">
        <div class="arch-empty-scope">${renderScopeBadgeHTML('project')}</div>
        <h2 class="arch-empty-title">No architecture snapshot for ${esc(displayName)}</h2>
        <p class="arch-empty-impact">
          This project does not have an architecture view-state cached
          yet. The dashboard is not falling back to another project's
          map — run the regen + dashboard build commands inside that
          project's repo to populate this view.
        </p>
        <div class="arch-empty-meta">
          <span class="arch-meta-row">
            <span class="arch-meta-label">Project</span>
            <code class="arch-meta-value">${esc(safeName)}</code>
          </span>
          <span class="arch-meta-row">
            <span class="arch-meta-label">Source</span>
            <code class="arch-meta-value">docs/architecture/architecture.json</code>
          </span>
        </div>
        <div class="arch-empty-actions">
          <p class="arch-empty-step">
            1. Regenerate the architecture snapshot in the project's repo:
          </p>
          ${renderCommandHTML(ARCH_REFRESH)}
          <p class="arch-empty-step">
            2. Rebuild the dashboard state for this project:
          </p>
          ${renderCommandHTML(`dontpanic dashboard build --project ${safeName}`)}
        </div>
        <p class="arch-empty-note">
          The dashboard is read-only. It will not run these commands for
          you — copy each line and run it in your own terminal.
        </p>
      </section>
      ${renderProvenanceFooterHTML({
        source: ARCH_SOURCE,
        lastUpdated: null,
        refreshCommand: ARCH_BUILD,
        note: 'No view-state cache for the selected project. Each project owns its own architecture snapshot — the dashboard does not merge unrelated repos.',
      })}
    </div>
  `;
}

export function renderErrorStateHTML(scope, envelope) {
  const headline = FRESHNESS_HEADLINES.error;
  const impact = FRESHNESS_IMPACT.error;
  const message = envelope.freshness.message
    || 'architecture.json could not be parsed.';
  const regen = envelope.freshness.regen_command || ARCH_REFRESH;
  const sourcePath = envelope.source_path
    || 'docs/architecture/architecture.json';
  const lastGenerated = envelope.freshness.generated_at || null;
  return `
    <div class="arch-layout" data-state="error">
      <section class="panel arch-error-card"
               data-empty-state="error"
               data-freshness="error">
        <div class="arch-empty-scope">${renderScopeBadgeHTML(scope)}</div>
        <div class="arch-error-header">
          <span class="arch-freshness-badge arch-freshness-badge--red">ERROR</span>
          <h2 class="arch-empty-title">${esc(headline)}</h2>
        </div>
        <p class="arch-empty-impact">${esc(impact)}</p>
        <p class="arch-error-message"><code>${esc(message)}</code></p>
        <div class="arch-empty-meta">
          <span class="arch-meta-row">
            <span class="arch-meta-label">Source</span>
            <code class="arch-meta-value">${esc(sourcePath)}</code>
          </span>
          <span class="arch-meta-row">
            <span class="arch-meta-label">Last generated</span>
            <span class="arch-meta-value">${esc(lastGenerated || '—')}</span>
          </span>
        </div>
        <div class="arch-empty-actions">
          <p class="arch-empty-step">
            Regenerate the architecture snapshot once the parse error is fixed:
          </p>
          ${renderCommandHTML(regen)}
        </div>
        <p class="arch-empty-note">
          The dashboard is read-only. Inspect the source file yourself
          and re-run the regen command in your terminal.
        </p>
      </section>
      ${buildProvenance(envelope, scope)}
    </div>
  `;
}

function renderPopulatedHTML(envelope, scope, opts) {
  const warnings = collectFlowWarnings(envelope);
  const layout = layoutArchitectureGraph(envelope);
  return `
    <div class="arch-layout arch-explorer" data-state="${esc(envelope.freshness.state)}">
      ${renderHeaderHTML(envelope, scope)}
      ${renderProjectContextHTML(envelope, scope)}
      ${renderFreshnessBannerHTML(envelope)}
      ${renderSummaryCardsHTML(envelope)}
      ${renderInsightsPanelHTML(envelope)}
      ${renderValidationWarningsHTML(warnings)}
      ${renderExplorerHTML(envelope, layout)}
      ${renderNodeProvenanceHTML(envelope)}
      ${buildProvenance(envelope, scope)}
    </div>
  `;
}

function renderHeaderHTML(envelope, scope) {
  const projectLabel = envelope.project.display_name
    || envelope.project.label
    || envelope.project.name
    || '(none)';
  const fingerprint = envelope.freshness.fingerprint
    ? envelope.freshness.fingerprint.slice(0, 12)
    : '—';
  return `
    <section class="panel arch-header-panel">
      <div class="arch-header-row">
        <h2 class="arch-title">Architecture</h2>
        <div class="arch-header-scope">${renderScopeBadgeHTML(scope)}</div>
        <div class="arch-header-question">How is this system put together, what changed, and where should I look first?</div>
      </div>
      <div class="arch-header-meta">
        <span class="arch-meta-chip">
          <span class="arch-meta-label">Project</span>
          <span class="arch-meta-value">${esc(projectLabel)}</span>
        </span>
        <span class="arch-meta-chip">
          <span class="arch-meta-label">Generated</span>
          <span class="arch-meta-value">${esc(envelope.freshness.generated_at || '—')}</span>
        </span>
        <span class="arch-meta-chip">
          <span class="arch-meta-label">Fingerprint</span>
          <code class="arch-meta-value">${esc(fingerprint)}</code>
        </span>
        <span class="arch-meta-chip">
          <span class="arch-meta-label">Source</span>
          <code class="arch-meta-value">${esc(envelope.source_path || 'docs/architecture/architecture.json')}</code>
        </span>
      </div>
    </section>
  `;
}

function renderFreshnessBannerHTML(envelope) {
  const state = envelope.freshness.state;
  const color = FRESHNESS_COLORS[state] || 'accent';
  const headline = FRESHNESS_HEADLINES[state] || 'System map status';
  const impact = FRESHNESS_IMPACT[state] || '';
  const message = envelope.freshness.message || '';
  const regen = envelope.freshness.regen_command || ARCH_REFRESH;
  const showCommand = state !== 'fresh';
  return `
    <section class="panel arch-freshness-banner arch-freshness-banner--${esc(color)}"
             data-freshness="${esc(state)}">
      <div class="arch-freshness-header">
        <span class="arch-freshness-badge arch-freshness-badge--${esc(color)}">${esc(state.toUpperCase())}</span>
        <span class="arch-freshness-headline">${esc(headline)}</span>
      </div>
      <p class="arch-freshness-impact">${esc(impact)}</p>
      ${message ? `<p class="arch-freshness-message">${esc(message)}</p>` : ''}
      ${showCommand ? `
        <div class="arch-freshness-actions">
          <p class="arch-freshness-cmd-label">Refresh the snapshot:</p>
          ${renderCommandHTML(regen)}
        </div>
      ` : ''}
    </section>
  `;
}

// Legacy insights strip — kept for backwards compatibility with any
// caller that imports it directly. The populated render uses the
// richer F004 summary-cards + insights-panel renderers below.
function renderInsightsStripHTML(envelope) {
  const counts = (envelope.insights || []).filter((i) => i && i.kind === 'count');
  if (counts.length === 0) return '';
  const chips = counts.map((insight) => `
    <span class="arch-insight-chip">
      <span class="arch-insight-value">${esc(String(insight.value ?? '—'))}</span>
      <span class="arch-insight-label">${esc(insight.title || insight.id || '')}</span>
    </span>
  `).join('');
  return `
    <section class="panel arch-insights-panel">
      <div class="arch-insights-strip">${chips}</div>
    </section>
  `;
}

// ─── F004 summary cards + derived insights ──────────────────────────

/**
 * Summary cards: module/plan/schema count, freshness state, generated
 * timestamp, fingerprint, files_count. Every value comes from the
 * envelope — no fabricated severity scores, no synthesized health
 * percentages. Cards render only when their backing field is present.
 *
 * Pure given a normalized envelope.
 */
export function renderSummaryCardsHTML(envelope) {
  if (envelope == null) return '';
  const counts = new Map(
    (envelope.insights || [])
      .filter((i) => i && i.kind === 'count')
      .map((i) => [String(i.id || ''), i]),
  );
  const fp = envelope.freshness || {};
  const cards = [];

  const moduleInsight = counts.get('insight:module-count');
  if (moduleInsight) {
    cards.push(_summaryCardHTML({
      id: 'modules',
      label: moduleInsight.title || 'Modules',
      value: moduleInsight.value,
      hint: 'Modules indexed in the snapshot.',
    }));
  }
  const planInsight = counts.get('insight:plan-count');
  if (planInsight) {
    cards.push(_summaryCardHTML({
      id: 'plans',
      label: planInsight.title || 'Plans',
      value: planInsight.value,
      hint: 'Plans tracked in docs/plans.',
    }));
  }
  const schemaInsight = counts.get('insight:schema-count');
  if (schemaInsight) {
    cards.push(_summaryCardHTML({
      id: 'schemas',
      label: schemaInsight.title || 'Schemas',
      value: schemaInsight.value,
      hint: 'Schemas governed by agent-conventions.',
    }));
  }

  // Freshness card — qualitative state badge + impact, no score.
  const state = fp.state || 'absent';
  const color = FRESHNESS_COLORS[state] || 'muted';
  const headline = FRESHNESS_HEADLINES[state] || 'Snapshot status';
  cards.push(`
    <article class="arch-summary-card arch-summary-card--freshness" data-card="freshness" data-freshness="${esc(state)}">
      <span class="arch-summary-card-label">Snapshot</span>
      <span class="arch-summary-card-value arch-summary-card-state">
        <span class="arch-freshness-badge arch-freshness-badge--${esc(color)}">${esc(state.toUpperCase())}</span>
      </span>
      <span class="arch-summary-card-hint">${esc(headline)}</span>
    </article>
  `);

  if (typeof fp.generated_at === 'string' && fp.generated_at.length > 0) {
    cards.push(`
      <article class="arch-summary-card" data-card="generated-at">
        <span class="arch-summary-card-label">Generated</span>
        <span class="arch-summary-card-value arch-summary-card-time">${esc(fp.generated_at)}</span>
        <span class="arch-summary-card-hint">Snapshot timestamp.</span>
      </article>
    `);
  }

  if (typeof fp.fingerprint === 'string' && fp.fingerprint.length > 0) {
    cards.push(`
      <article class="arch-summary-card" data-card="fingerprint">
        <span class="arch-summary-card-label">Fingerprint</span>
        <code class="arch-summary-card-value arch-summary-card-fp">${esc(fp.fingerprint.slice(0, 12))}</code>
        <span class="arch-summary-card-hint">First 12 of architecture.json fingerprint.</span>
      </article>
    `);
  }

  if (typeof fp.files_count === 'number' && fp.files_count >= 0) {
    cards.push(`
      <article class="arch-summary-card" data-card="files-count">
        <span class="arch-summary-card-label">Files scanned</span>
        <span class="arch-summary-card-value">${esc(String(fp.files_count))}</span>
        <span class="arch-summary-card-hint">Files the crawler hashed for this snapshot.</span>
      </article>
    `);
  }

  if (cards.length === 0) return '';
  return `
    <section class="panel arch-summary-panel" data-summary="1">
      <div class="arch-summary-grid">${cards.join('')}</div>
    </section>
  `;
}

function _summaryCardHTML({ id, label, value, hint }) {
  const display = value == null ? '—' : String(value);
  return `
    <article class="arch-summary-card" data-card="${esc(id)}">
      <span class="arch-summary-card-label">${esc(label)}</span>
      <span class="arch-summary-card-value">${esc(display)}</span>
      <span class="arch-summary-card-hint">${esc(hint)}</span>
    </article>
  `;
}

/**
 * Evidence-backed derived insights. V1 surfaces:
 *   - High-degree (import fan-out) modules — straight from
 *     `insights[].kind === "ranking"` so we never invent a score.
 *   - Plans touching modules — derived from edges whose endpoint is a
 *     plan or module node, presented as a small directory rather than
 *     a risk score.
 *
 * If an insight slot has no supporting data in the snapshot, the
 * corresponding section is omitted (or labelled "No data"). We never
 * fabricate a number to fill a card.
 */
export function renderInsightsPanelHTML(envelope) {
  if (envelope == null) return '';
  const sections = [];

  const ranking = (envelope.insights || []).find(
    (i) => i && i.id === 'insight:high-fan-out' && i.kind === 'ranking',
  );
  sections.push(_renderHighFanOutSectionHTML(ranking));

  // F004 finding #2: surface evidence-backed freshness / changed-files
  // insights from the data the view-state already carries. We never
  // invent a "files changed" count — when the view-state has no
  // recently-changed listing we say so explicitly.
  sections.push(_renderFreshnessInsightSectionHTML(envelope));
  sections.push(_renderChangedFilesSectionHTML(envelope));

  const planLinks = collectPlanTouchpoints(envelope);
  sections.push(_renderPlanTouchpointsSectionHTML(planLinks));

  const visible = sections.filter((s) => s && s.length > 0);
  if (visible.length === 0) return '';
  return `
    <section class="panel arch-insights-detail-panel" data-insights-detail="1">
      <header class="arch-insights-detail-header">
        <h3 class="arch-insights-detail-title">Architecture insights</h3>
        <p class="arch-insights-detail-hint">
          Evidence-backed signals derived from the current snapshot.
          Counts and rankings come from architecture.json — the
          dashboard does not invent unsupported health numbers beyond
          available data.
        </p>
      </header>
      <div class="arch-insights-detail-grid">${visible.join('')}</div>
    </section>
  `;
}

function _renderHighFanOutSectionHTML(insight) {
  const rows = insight && Array.isArray(insight.value) ? insight.value : [];
  if (rows.length === 0) {
    return `
      <article class="arch-insight-section" data-insight="high-fan-out">
        <header class="arch-insight-section-header">
          <span class="arch-insight-section-title">High-coupling areas</span>
          <span class="arch-insight-section-tag">No data</span>
        </header>
        <p class="arch-insight-section-empty">
          No import fan-out data in the snapshot. Run the regen command
          to populate <code>insights[].high-fan-out</code>.
        </p>
      </article>
    `;
  }
  const items = rows.map((row) => {
    const node = (row && typeof row.node === 'string') ? row.node : '';
    const count = (row && typeof row.imports === 'number') ? row.imports : 0;
    return `
      <li class="arch-insight-row" data-node-ref="${esc(node)}">
        <code class="arch-insight-node">${esc(node)}</code>
        <span class="arch-insight-metric">
          <span class="arch-insight-metric-value">${esc(String(count))}</span>
          <span class="arch-insight-metric-label">imports</span>
        </span>
      </li>
    `;
  }).join('');
  return `
    <article class="arch-insight-section" data-insight="high-fan-out">
      <header class="arch-insight-section-header">
        <span class="arch-insight-section-title">High-coupling areas</span>
        <span class="arch-insight-section-tag">Top ${esc(String(rows.length))}</span>
      </header>
      <p class="arch-insight-section-hint">
        Modules with the most outgoing imports. Counts come from the
        snapshot's edge list — interpret qualitatively, not as a risk
        score.
      </p>
      <ul class="arch-insight-list">${items}</ul>
    </article>
  `;
}

/**
 * F004 finding #2 — Snapshot freshness insight. Surfaces qualitative
 * state + fingerprint drift drawn directly from
 * `envelope.freshness`. No fabricated severity scores: when state is
 * fresh we say so; when stale we show the stored vs current fingerprint
 * pair so an operator can verify drift without leaving the page.
 */
function _renderFreshnessInsightSectionHTML(envelope) {
  const fp = (envelope && envelope.freshness) || {};
  const state = typeof fp.state === 'string' ? fp.state : 'absent';
  const headline = FRESHNESS_HEADLINES[state] || FRESHNESS_HEADLINES.absent;
  const stored = typeof fp.stored_fingerprint === 'string' ? fp.stored_fingerprint : '';
  const current = typeof fp.current_fingerprint === 'string' ? fp.current_fingerprint : '';
  const generated = typeof fp.generated_at === 'string' ? fp.generated_at : '';
  const filesCount = typeof fp.files_count === 'number' ? fp.files_count : null;
  const message = typeof fp.message === 'string' ? fp.message : '';
  const isDrift = state === 'stale' && stored.length > 0 && current.length > 0 && stored !== current;
  const rows = [];
  rows.push(`
    <li class="arch-insight-row" data-freshness-field="state">
      <span class="arch-insight-metric-label">State</span>
      <span class="arch-freshness-badge arch-freshness-badge--${esc(FRESHNESS_COLORS[state] || 'muted')}">${esc(state.toUpperCase())}</span>
    </li>
  `);
  if (generated.length > 0) {
    rows.push(`
      <li class="arch-insight-row" data-freshness-field="generated-at">
        <span class="arch-insight-metric-label">Generated</span>
        <code class="arch-insight-node">${esc(generated)}</code>
      </li>
    `);
  }
  if (filesCount != null && filesCount >= 0) {
    rows.push(`
      <li class="arch-insight-row" data-freshness-field="files-count">
        <span class="arch-insight-metric-label">Files scanned</span>
        <span class="arch-insight-metric-value">${esc(String(filesCount))}</span>
      </li>
    `);
  }
  if (isDrift) {
    rows.push(`
      <li class="arch-insight-row" data-freshness-field="stored-fingerprint">
        <span class="arch-insight-metric-label">Stored fp</span>
        <code class="arch-insight-node">${esc(stored.slice(0, 12))}</code>
      </li>
    `);
    rows.push(`
      <li class="arch-insight-row" data-freshness-field="current-fingerprint">
        <span class="arch-insight-metric-label">Current fp</span>
        <code class="arch-insight-node">${esc(current.slice(0, 12))}</code>
      </li>
    `);
  }
  const driftHint = isDrift
    ? `Stored and current fingerprints diverge — the working tree has changed since the snapshot was generated. Run the regen command to refresh.`
    : (state === 'fresh'
      ? `The snapshot matches the working tree as of ${esc(generated || 'the last regen')}.`
      : `Fingerprint comparison not available for this state.`);
  return `
    <article class="arch-insight-section" data-insight="snapshot-freshness">
      <header class="arch-insight-section-header">
        <span class="arch-insight-section-title">Snapshot freshness</span>
        <span class="arch-insight-section-tag">${esc(headline)}</span>
      </header>
      <p class="arch-insight-section-hint">${driftHint}</p>
      ${message ? `<p class="arch-insight-section-empty">${esc(message)}</p>` : ''}
      <ul class="arch-insight-list">${rows.join('')}</ul>
    </article>
  `;
}

/**
 * F004 finding #2 — Recently changed files insight. Renders a list when
 * the view-state has an `insight:recently-changed` insight populated by
 * the crawler; otherwise prints a "No data" tag explaining the snapshot
 * does not carry a per-file diff yet (so we don't fabricate numbers).
 */
function _renderChangedFilesSectionHTML(envelope) {
  const insight = (envelope && Array.isArray(envelope.insights))
    ? envelope.insights.find(
      (i) => i && (i.id === 'insight:recently-changed'
        || i.id === 'insight:changed-files'),
    )
    : null;
  const rows = insight && Array.isArray(insight.value) ? insight.value : [];
  if (rows.length === 0) {
    return `
      <article class="arch-insight-section" data-insight="recently-changed">
        <header class="arch-insight-section-header">
          <span class="arch-insight-section-title">Recently changed files</span>
          <span class="arch-insight-section-tag">No data</span>
        </header>
        <p class="arch-insight-section-empty">
          The current snapshot does not carry a per-file diff. Snapshot
          freshness above surfaces fingerprint drift; a fileset diff
          will appear here once the crawler emits
          <code>insights[].recently-changed</code>.
        </p>
      </article>
    `;
  }
  const items = rows.slice(0, 8).map((row) => {
    const path = (row && typeof row.path === 'string') ? row.path : '';
    const change = (row && typeof row.change === 'string') ? row.change : '';
    return `
      <li class="arch-insight-row" data-change-path="${esc(path)}">
        <code class="arch-insight-node">${esc(path)}</code>
        ${change ? `<span class="arch-insight-metric-label">${esc(change)}</span>` : ''}
      </li>
    `;
  }).join('');
  const overflow = rows.length - 8;
  return `
    <article class="arch-insight-section" data-insight="recently-changed">
      <header class="arch-insight-section-header">
        <span class="arch-insight-section-title">Recently changed files</span>
        <span class="arch-insight-section-tag">${esc(String(rows.length))} files</span>
      </header>
      <p class="arch-insight-section-hint">
        Paths flagged by the crawler as added/modified/removed since the
        prior snapshot. Sourced from the view-state's recently-changed
        insight — no fabricated change scores.
      </p>
      <ul class="arch-insight-list">${items}</ul>
      ${overflow > 0 ? `<p class="arch-insight-section-overflow">+${esc(String(overflow))} more (truncated for readability).</p>` : ''}
    </article>
  `;
}

/**
 * Pure helper: walk edges to find plan nodes that touch a module or
 * schema. Returns a list of `{ plan_id, plan_title, touches: [...] }`
 * sorted by `plan_id`. Snapshot-driven, no fabricated severity.
 */
export function collectPlanTouchpoints(envelope) {
  if (envelope == null) return [];
  const nodesById = new Map(
    (envelope.nodes || [])
      .filter((n) => n && typeof n.id === 'string')
      .map((n) => [n.id, n]),
  );
  const planTouches = new Map();
  for (const edge of (envelope.edges || [])) {
    if (!edge || typeof edge !== 'object') continue;
    const from = nodesById.get(edge.from);
    const to = nodesById.get(edge.to);
    const planNode = from && from.type === 'plan' ? from : (to && to.type === 'plan' ? to : null);
    const otherNode = planNode === from ? to : from;
    if (!planNode || !otherNode) continue;
    const key = planNode.id;
    if (!planTouches.has(key)) {
      planTouches.set(key, {
        plan_id: planNode.id,
        plan_title: planNode.title || planNode.id,
        touches: [],
      });
    }
    planTouches.get(key).touches.push({
      node_id: otherNode.id,
      title: otherNode.title || otherNode.id,
      type: otherNode.type || 'other',
    });
  }
  const out = [...planTouches.values()];
  out.sort((a, b) => (a.plan_id < b.plan_id ? -1 : a.plan_id > b.plan_id ? 1 : 0));
  return out;
}

function _renderPlanTouchpointsSectionHTML(planLinks) {
  if (!Array.isArray(planLinks) || planLinks.length === 0) {
    return `
      <article class="arch-insight-section" data-insight="plans-touching">
        <header class="arch-insight-section-header">
          <span class="arch-insight-section-title">Plans touching selected modules</span>
          <span class="arch-insight-section-tag">No data</span>
        </header>
        <p class="arch-insight-section-empty">
          No plan↔module edges in this snapshot. Plan nodes appear
          once the crawler links plan source paths to their modules.
        </p>
      </article>
    `;
  }
  const visible = planLinks.slice(0, 8);
  const overflow = planLinks.length - visible.length;
  const rows = visible.map((plan) => {
    const touchSummary = plan.touches.slice(0, 4)
      .map((t) => `<code class="arch-insight-touch">${esc(t.title)}</code>`)
      .join(' ');
    return `
      <li class="arch-insight-row" data-plan-id="${esc(plan.plan_id)}">
        <span class="arch-insight-plan">
          <code class="arch-insight-plan-id">${esc(plan.plan_id)}</code>
          <span class="arch-insight-plan-title">${esc(plan.plan_title)}</span>
        </span>
        <span class="arch-insight-touches">
          <span class="arch-insight-metric-value">${esc(String(plan.touches.length))}</span>
          <span class="arch-insight-metric-label">touches</span>
          ${touchSummary}
        </span>
      </li>
    `;
  }).join('');
  return `
    <article class="arch-insight-section" data-insight="plans-touching">
      <header class="arch-insight-section-header">
        <span class="arch-insight-section-title">Plans touching selected modules</span>
        <span class="arch-insight-section-tag">${esc(String(planLinks.length))} plans</span>
      </header>
      <p class="arch-insight-section-hint">
        Plan nodes connected to modules / schemas through the snapshot's
        edges. Use this to spot which areas a plan reaches before
        opening the map.
      </p>
      <ul class="arch-insight-list">${rows}</ul>
      ${overflow > 0 ? `<p class="arch-insight-section-overflow">+${esc(String(overflow))} more plan touchpoints (truncated for readability).</p>` : ''}
    </article>
  `;
}

/**
 * Project / fleet context block. For project scope, surfaces the
 * project label, technical name, source path, and last-generated
 * timestamp. For fleet scope (when shown inline above an aggregated
 * single-repo envelope), explains that the active map is the local
 * repo state. When `project.name` is null we render "(none)" honestly
 * rather than implying a multi-project graph.
 *
 * Pure given a normalized envelope.
 */
export function renderProjectContextHTML(envelope, scope = 'project') {
  if (envelope == null) return '';
  const project = envelope.project || {};
  const label = project.display_name || project.label || project.name || '(none)';
  const name = project.name || '(none)';
  const sourcePath = envelope.source_path || 'docs/architecture/architecture.json';
  const lastGenerated = (envelope.freshness && envelope.freshness.generated_at) || '—';
  const scopeText = scope === 'fleet'
    ? 'Fleet selector falls back to single-repo state when no per-project cache is present.'
    : 'Architecture data is scoped to this project only.';
  return `
    <section class="panel arch-project-context" data-project-context="1" data-scope="${esc(scope)}">
      <div class="arch-project-context-row">
        <div class="arch-project-context-label">
          <span class="arch-meta-label">Project context</span>
          <span class="arch-project-context-name">${esc(label)}</span>
        </div>
        <div class="arch-project-context-meta">
          <span class="arch-meta-chip">
            <span class="arch-meta-label">project_id</span>
            <code class="arch-meta-value">${esc(name)}</code>
          </span>
          <span class="arch-meta-chip">
            <span class="arch-meta-label">source</span>
            <code class="arch-meta-value">${esc(sourcePath)}</code>
          </span>
          <span class="arch-meta-chip">
            <span class="arch-meta-label">last generated</span>
            <span class="arch-meta-value">${esc(lastGenerated)}</span>
          </span>
        </div>
      </div>
      <p class="arch-project-context-note">${esc(scopeText)}</p>
    </section>
  `;
}

// ─── F004 fleet (All Projects) view ─────────────────────────────────

/**
 * Render the All Projects view: a grid of project cards, each with
 * the project's own architecture freshness and an "open map" button.
 * Projects that have no architecture artifact (or no per-project
 * cache yet) get an explicit empty card with the regen instructions
 * for that repo. We never merge unrelated repo graphs into one canvas.
 *
 * Inputs:
 *   - byProject: map of project_name → raw view-state envelope (or null)
 *   - fleetSummary: normalized or raw fleet summary envelope (optional)
 */
export function renderFleetArchitectureHTML(opts = {}) {
  const byProject = opts.byProject && typeof opts.byProject === 'object'
    ? opts.byProject
    : {};
  const fleetSummary = opts.fleetSummary && typeof opts.fleetSummary === 'object'
    ? opts.fleetSummary
    : null;

  // Build the deduped, sorted project list: union of byProject keys and
  // fleet summary entries so an unbuilt project still shows up with an
  // explicit "no architecture yet" card.
  const seen = new Map();
  const summaryProjects = Array.isArray(fleetSummary && fleetSummary.projects)
    ? fleetSummary.projects
    : [];
  for (const p of summaryProjects) {
    if (!p || typeof p.name !== 'string') continue;
    seen.set(p.name, {
      name: p.name,
      display_name: typeof p.display_name === 'string' && p.display_name.length > 0
        ? p.display_name
        : p.name,
      active: p.active !== false,
    });
  }
  for (const name of Object.keys(byProject)) {
    if (typeof name !== 'string' || name.length === 0) continue;
    if (!seen.has(name)) {
      const env = byProject[name];
      const display = env && env.project && typeof env.project.display_name === 'string'
        ? env.project.display_name
        : name;
      seen.set(name, { name, display_name: display, active: true });
    }
  }
  const projects = [...seen.values()].sort(
    (a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0),
  );

  const cards = projects.map((p) => {
    const raw = byProject[p.name];
    const env = normalizeEnvelope(raw);
    if (env == null) {
      return _renderFleetEmptyCardHTML(p);
    }
    return _renderFleetProjectCardHTML(p, env);
  }).join('');

  return `
    <div class="arch-layout arch-fleet" data-state="fleet" data-fleet="1">
      <section class="panel arch-fleet-header-panel">
        <div class="arch-header-row">
          <h2 class="arch-title">Architecture</h2>
          <div class="arch-header-scope">${renderScopeBadgeHTML('fleet')}</div>
          <div class="arch-header-question">All Projects view — each project keeps its own map.</div>
        </div>
        <p class="arch-fleet-note">
          Each registered project has its own architecture snapshot.
          Unrelated repos are never merged into a single graph. Pick a
          project below to open its map.
        </p>
      </section>
      ${projects.length === 0 ? _renderFleetEmptyAllHTML() : `
        <section class="panel arch-fleet-grid-panel">
          <div class="arch-fleet-grid">${cards}</div>
        </section>
      `}
      ${renderProvenanceFooterHTML({
        source: ARCH_SOURCE,
        lastUpdated: null,
        refreshCommand: ARCH_BUILD,
        note: 'All Projects view enumerates per-project caches from the fleet summary. Open a project to see its full architecture map.',
      })}
    </div>
  `;
}

function _renderFleetProjectCardHTML(projectInfo, envelope) {
  const fp = envelope.freshness || {};
  const state = fp.state || 'absent';
  const color = FRESHNESS_COLORS[state] || 'muted';
  const headline = FRESHNESS_HEADLINES[state] || 'Snapshot status';
  const generated = fp.generated_at || '—';
  const moduleInsight = (envelope.insights || []).find(
    (i) => i && i.id === 'insight:module-count',
  );
  const planInsight = (envelope.insights || []).find(
    (i) => i && i.id === 'insight:plan-count',
  );
  const moduleCount = moduleInsight && moduleInsight.value != null ? moduleInsight.value : (envelope.nodes || []).filter((n) => n && n.type === 'module').length;
  const planCount = planInsight && planInsight.value != null ? planInsight.value : (envelope.nodes || []).filter((n) => n && n.type === 'plan').length;
  const inactive = projectInfo.active === false;
  return `
    <article class="arch-fleet-card" data-fleet-card="${esc(projectInfo.name)}" data-fleet-state="${esc(state)}">
      <header class="arch-fleet-card-header">
        <span class="arch-fleet-card-name">${esc(projectInfo.display_name || projectInfo.name)}</span>
        <span class="arch-freshness-badge arch-freshness-badge--${esc(color)}">${esc(state.toUpperCase())}</span>
      </header>
      <code class="arch-fleet-card-id">${esc(projectInfo.name)}</code>
      <p class="arch-fleet-card-headline">${esc(headline)}</p>
      <dl class="arch-fleet-card-meta">
        <dt>Modules</dt><dd>${esc(String(moduleCount))}</dd>
        <dt>Plans</dt><dd>${esc(String(planCount))}</dd>
        <dt>Generated</dt><dd>${esc(generated)}</dd>
      </dl>
      ${inactive ? '<p class="arch-fleet-card-inactive">Marked inactive in the registry.</p>' : ''}
      <div class="arch-fleet-card-actions">
        <button type="button"
                class="arch-fleet-open-btn"
                data-arch-open-project="${esc(projectInfo.name)}">
          Open map
        </button>
      </div>
    </article>
  `;
}

function _renderFleetEmptyCardHTML(projectInfo) {
  return `
    <article class="arch-fleet-card arch-fleet-card--empty"
             data-fleet-card="${esc(projectInfo.name)}"
             data-fleet-state="absent">
      <header class="arch-fleet-card-header">
        <span class="arch-fleet-card-name">${esc(projectInfo.display_name || projectInfo.name)}</span>
        <span class="arch-freshness-badge arch-freshness-badge--muted">NO MAP</span>
      </header>
      <code class="arch-fleet-card-id">${esc(projectInfo.name)}</code>
      <p class="arch-fleet-card-headline">No architecture snapshot for this project yet.</p>
      <p class="arch-fleet-card-empty-body">
        Run the regen command inside the project's repo, then rebuild
        the dashboard state for this project:
      </p>
      ${renderCommandHTML(ARCH_REFRESH)}
      ${renderCommandHTML(`dontpanic dashboard build --project ${projectInfo.name}`)}
      <div class="arch-fleet-card-actions">
        <button type="button"
                class="arch-fleet-open-btn"
                data-arch-open-project="${esc(projectInfo.name)}">
          Switch selector
        </button>
      </div>
    </article>
  `;
}

function _renderFleetEmptyAllHTML() {
  return `
    <section class="panel arch-fleet-empty-panel" data-fleet-empty="1">
      <h3 class="arch-fleet-empty-title">No registered projects yet</h3>
      <p class="arch-fleet-empty-body">
        The fleet summary has no registered projects, so there are no
        architecture maps to list. Register a project with the
        dontpanic CLI to populate this view.
      </p>
      ${renderCommandHTML('dontpanic projects add <name> <path>')}
    </section>
  `;
}

function renderValidationWarningsHTML(warnings) {
  if (!Array.isArray(warnings) || warnings.length === 0) return '';
  const rows = warnings.map((w) => {
    const refParts = [];
    if (w.flow_id) refParts.push(w.flow_id);
    if (w.step_id) refParts.push(w.step_id);
    const refLabel = refParts.length > 0 ? refParts.join(' / ') : '—';
    return `
      <li class="arch-warning-row">
        <span class="arch-warning-ref"><code>${esc(refLabel)}</code></span>
        <span class="arch-warning-message">${esc(w.message)}</span>
      </li>
    `;
  }).join('');
  return `
    <section class="panel arch-warnings-panel" data-warnings="1">
      <div class="arch-warnings-header">
        <span class="arch-warnings-badge">FLOW WARNINGS</span>
        <span class="arch-warnings-count">${esc(String(warnings.length))} item${warnings.length === 1 ? '' : 's'}</span>
      </div>
      <p class="arch-warnings-note">
        These flow references do not resolve to a node or edge in the
        current architecture snapshot. The map still renders — the listed
        flows will show a warning instead of a path until the references
        are repaired.
      </p>
      <ul class="arch-warnings-list">${rows}</ul>
    </section>
  `;
}

// ─── F003 interactive explorer ───────────────────────────────────────

function renderExplorerHTML(envelope, layout) {
  const types = Array.from(new Set((envelope.nodes || [])
    .map((n) => (n && typeof n.type === 'string') ? n.type : null)
    .filter((t) => t != null))).sort();
  const lanes = (envelope.lanes || []).map((l) => ({
    id: l && typeof l.id === 'string' ? l.id : '',
    title: l && typeof l.title === 'string' ? l.title : l && l.id,
  })).filter((l) => l.id);
  const edgeTypes = Array.from(new Set((envelope.edges || [])
    .map((e) => (e && typeof e.type === 'string') ? e.type : null)
    .filter((t) => t != null))).sort();
  return `
    <section class="panel arch-explorer-panel" data-explorer="1">
      <div class="arch-explorer-header">
        <h3 class="arch-map-title">System Map</h3>
        <p class="arch-map-hint">
          Select a flow to highlight its path. Non-selected nodes stay
          visible but dimmed. Use search and filters to narrow the
          canvas, or click any node for source detail.
        </p>
      </div>
      <div class="arch-explorer-toolbar" role="toolbar" aria-label="Architecture explorer controls">
        <label class="arch-search">
          <span class="arch-search-label">Search</span>
          <input
            type="search"
            class="arch-search-input"
            data-arch-search
            placeholder="Search modules, plans, capabilities…"
            aria-label="Search nodes by title, id, or source path"
          />
        </label>
        <div class="arch-filter-group" data-filter="type" role="group" aria-label="Type filters">
          <span class="arch-filter-label">Type</span>
          ${types.map((t) => {
            const cat = categoryFor(t);
            const meta = NODE_CATEGORIES[cat] || NODE_CATEGORIES.other;
            return `
              <label class="arch-filter-chip" data-filter-kind="type" data-filter-value="${esc(t)}">
                <input type="checkbox" data-arch-filter="type" value="${esc(t)}" checked />
                <span class="arch-legend-dot" style="background:${esc(meta.color)}"></span>
                <span class="arch-filter-chip-label">${esc(meta.label)}</span>
              </label>
            `;
          }).join('')}
        </div>
        <div class="arch-filter-group" data-filter="lane" role="group" aria-label="Lane filters">
          <span class="arch-filter-label">Lane</span>
          ${lanes.map((l) => `
            <label class="arch-filter-chip" data-filter-kind="lane" data-filter-value="${esc(l.id)}">
              <input type="checkbox" data-arch-filter="lane" value="${esc(l.id)}" checked />
              <span class="arch-filter-chip-label">${esc(l.title)}</span>
            </label>
          `).join('')}
        </div>
        <div class="arch-filter-group" data-filter="edge" role="group" aria-label="Edge filters">
          <span class="arch-filter-label">Edge</span>
          ${edgeTypes.map((t) => {
            const meta = EDGE_TYPES[t] || EDGE_TYPES.other;
            return `
              <label class="arch-filter-chip" data-filter-kind="edge" data-filter-value="${esc(t)}">
                <input type="checkbox" data-arch-filter="edge" value="${esc(t)}" checked />
                <span class="arch-legend-dot arch-legend-dot--line" style="background:${esc(meta.color)}"></span>
                <span class="arch-filter-chip-label">${esc(meta.label)}</span>
              </label>
            `;
          }).join('')}
        </div>
        <div class="arch-zoom-controls" role="group" aria-label="Zoom controls">
          <button type="button" class="arch-zoom-btn" data-arch-zoom="out" aria-label="Zoom out">−</button>
          <button type="button" class="arch-zoom-btn" data-arch-zoom="in" aria-label="Zoom in">+</button>
          <button type="button" class="arch-zoom-btn arch-zoom-btn--reset" data-arch-reset aria-label="Reset view">Reset</button>
        </div>
      </div>
      <div class="arch-explorer-grid">
        <div class="arch-explorer-canvas-wrap" data-canvas-wrap tabindex="0" role="application" aria-label="Architecture map (drag to pan, wheel to zoom, arrow keys to pan when focused)">
          ${renderArchitectureMapSVG(layout)}
          <aside class="arch-detail-panel" data-detail-panel hidden aria-live="polite">
            <button type="button" class="arch-detail-close" data-arch-detail-close aria-label="Close detail panel">×</button>
            <div class="arch-detail-body" data-detail-body></div>
          </aside>
        </div>
        <aside class="arch-flow-rail" data-flow-rail aria-label="Flow inspector">
          ${renderFlowRailHTML(envelope)}
        </aside>
      </div>
      ${renderLegendHTML(envelope)}
    </section>
  `;
}

/**
 * Render the deterministic SVG canvas. Pure given a layout object, so
 * the same envelope always produces the same SVG string (snapshot-safe).
 */
export function renderArchitectureMapSVG(layout) {
  if (!layout || !Array.isArray(layout.lanes) || layout.lanes.length === 0) {
    return '<svg class="arch-canvas" data-canvas viewBox="0 0 100 60" role="img" aria-label="Architecture map (empty)" preserveAspectRatio="xMidYMid meet"></svg>';
  }
  const { width, height, lanes, edges } = layout;
  // Group edges by type for layering (imports under runs/calls/writes).
  const edgePaths = edges
    .filter((e) => !e.missing && Number.isFinite(e.x1))
    .map((edge) => {
      const meta = EDGE_TYPES[edge.type] || EDGE_TYPES.other;
      const dx = (edge.x2 - edge.x1) * 0.25;
      // Cubic bezier with horizontal control points keeps edges legible
      // even when source and target sit on the same row.
      const cx1 = edge.x1 + dx;
      const cx2 = edge.x2 - dx;
      const d = `M ${edge.x1} ${edge.y1} C ${cx1} ${edge.y1}, ${cx2} ${edge.y2}, ${edge.x2} ${edge.y2}`;
      return `<path class="arch-edge" data-edge-id="${esc(edge.id)}" data-edge-type="${esc(edge.type)}" data-from="${esc(edge.from)}" data-to="${esc(edge.to)}" d="${d}" stroke="${esc(meta.color)}" fill="none" />`;
    }).join('');
  const laneShapes = lanes.map((lane) => `
    <g class="arch-lane" data-lane-id="${esc(lane.id)}" data-lane-kind="${esc(lane.kind)}">
      <rect class="arch-lane-bg" x="0" y="${lane.y}" width="${width}" height="${lane.height}" rx="6" />
      <text class="arch-lane-label" x="16" y="${lane.y + 24}">${esc(lane.title)}</text>
      <text class="arch-lane-count" x="${width - 16}" y="${lane.y + 24}" text-anchor="end">${esc(String(lane.nodes.length))} nodes</text>
    </g>
  `).join('');
  const nodeShapes = lanes.flatMap((lane) => lane.nodes).map((node) => {
    const meta = NODE_CATEGORIES[node.category] || NODE_CATEGORIES.other;
    const titleAttr = node.summary && node.summary.length > 0
      ? `${node.title} — ${node.summary}`
      : node.title;
    const label = truncateLabel(node.title, 18);
    return `
      <g class="arch-node" data-node-id="${esc(node.id)}" data-node-type="${esc(node.type)}" data-node-category="${esc(node.category)}" data-lane-id="${esc(node.lane_id)}" tabindex="0" role="button" aria-label="${esc(node.title)} (${esc(meta.label)})">
        <title>${esc(titleAttr)}</title>
        <rect class="arch-node-bg" x="${node.x}" y="${node.y}" width="${node.w}" height="${node.h}" rx="6" fill="${esc(meta.color)}" />
        <text class="arch-node-label" x="${node.x + 10}" y="${node.y + node.h / 2 + 4}">${esc(label)}</text>
        <text class="arch-node-cat" x="${node.x + node.w - 10}" y="${node.y + node.h / 2 + 4}" text-anchor="end">${esc(meta.short)}</text>
      </g>
    `;
  }).join('');
  return `
    <svg class="arch-canvas"
         data-canvas
         viewBox="0 0 ${width} ${height}"
         data-canvas-width="${width}"
         data-canvas-height="${height}"
         role="img"
         aria-label="Architecture swimlane map"
         preserveAspectRatio="xMidYMid meet">
      <g data-layer="lanes">${laneShapes}</g>
      <g data-layer="edges">${edgePaths}</g>
      <g data-layer="nodes">${nodeShapes}</g>
      <g data-layer="step-markers" data-step-markers></g>
    </svg>
  `;
}

function truncateLabel(text, max) {
  if (typeof text !== 'string') return '';
  const s = text.replace(/^module:|^plan:|^capability:|^command:|^schema:|^page:|^external:/, '');
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + '…';
}

function renderFlowRailHTML(envelope) {
  const flows = envelope.flows || [];
  if (flows.length === 0) {
    return `
      <div class="arch-flow-rail-empty" data-flow-rail-empty>
        <h3 class="arch-flow-rail-title">Flows</h3>
        <p class="arch-flow-rail-empty-msg">
          No flows resolved against the current snapshot. Authored flow
          input lives at <code>docs/architecture/flows.json</code>;
          derived flows depend on plans + capability data being present
          in the architecture snapshot.
        </p>
      </div>
    `;
  }
  const items = flows.map((flow) => {
    const id = typeof flow.id === 'string' ? flow.id : '';
    const title = typeof flow.title === 'string' && flow.title.length > 0
      ? flow.title
      : id;
    const summary = typeof flow.summary === 'string' ? flow.summary : '';
    const source = typeof flow.source === 'string' ? flow.source : '';
    const stepCount = Array.isArray(flow.steps) ? flow.steps.length : 0;
    const hasWarning = (Array.isArray(flow.warnings) && flow.warnings.length > 0)
      || (Array.isArray(flow.steps) && flow.steps.some((s) => Array.isArray(s?.warnings) && s.warnings.length > 0));
    return `
      <li class="arch-flow-row">
        <button type="button"
                class="arch-flow-row-btn"
                data-arch-flow="${esc(id)}"
                data-has-warning="${hasWarning ? '1' : '0'}"
                aria-pressed="false">
          <span class="arch-flow-row-title">${esc(title)}</span>
          ${source ? `<span class="arch-flow-source-chip">${esc(source)}</span>` : ''}
          ${hasWarning ? `<span class="arch-flow-warning-chip" title="this flow has step warnings">warning</span>` : ''}
          ${summary ? `<span class="arch-flow-row-summary">${esc(summary)}</span>` : ''}
          <span class="arch-flow-row-meta">
            <span class="arch-flow-step-count">${esc(String(stepCount))} step${stepCount === 1 ? '' : 's'}</span>
            <code class="arch-flow-id">${esc(id)}</code>
          </span>
        </button>
      </li>
    `;
  }).join('');
  return `
    <div class="arch-flow-rail-header">
      <h3 class="arch-flow-rail-title">Flows</h3>
      <button type="button" class="arch-flow-clear" data-arch-flow-clear hidden>
        Clear selection
      </button>
    </div>
    <ul class="arch-flow-list" data-flow-list>${items}</ul>
    <div class="arch-step-inspector" data-step-inspector hidden>
      <h4 class="arch-step-inspector-title">Steps</h4>
      <ol class="arch-step-list" data-step-list></ol>
    </div>
  `;
}

function renderLegendHTML(envelope) {
  const types = Array.from(new Set((envelope.nodes || [])
    .map((n) => (n && typeof n.type === 'string') ? n.type : null)
    .filter(Boolean))).sort();
  const edgeTypes = Array.from(new Set((envelope.edges || [])
    .map((e) => (e && typeof e.type === 'string') ? e.type : null)
    .filter(Boolean))).sort();
  return `
    <div class="arch-legend" data-legend>
      <span class="arch-legend-section-label">Nodes</span>
      ${types.map((t) => {
        const cat = categoryFor(t);
        const meta = NODE_CATEGORIES[cat] || NODE_CATEGORIES.other;
        return `
          <span class="arch-legend-item" data-legend-type="${esc(t)}">
            <span class="arch-legend-dot" style="background:${esc(meta.color)}"></span>
            <span class="arch-legend-label">${esc(meta.label)}</span>
          </span>
        `;
      }).join('')}
      <span class="arch-legend-section-label">Edges</span>
      ${edgeTypes.map((t) => {
        const meta = EDGE_TYPES[t] || EDGE_TYPES.other;
        return `
          <span class="arch-legend-item" data-legend-edge="${esc(t)}">
            <span class="arch-legend-dot arch-legend-dot--line" style="background:${esc(meta.color)}"></span>
            <span class="arch-legend-label">${esc(meta.label)}</span>
          </span>
        `;
      }).join('')}
    </div>
  `;
}

/**
 * Build the click-detail panel body for a given node id. Returns the
 * innerHTML for `[data-detail-body]` so `architecture.js` can swap it
 * in on click without re-rendering the entire page.
 */
export function renderNodeDetailHTML(envelope, nodeId) {
  if (envelope == null || typeof nodeId !== 'string' || nodeId.length === 0) {
    return '';
  }
  const node = (envelope.nodes || []).find((n) => n && n.id === nodeId);
  if (!node) {
    return `<p class="arch-detail-empty">No detail available for <code>${esc(nodeId)}</code>.</p>`;
  }
  const cat = categoryFor(typeof node.type === 'string' ? node.type : 'other');
  const meta = NODE_CATEGORIES[cat] || NODE_CATEGORIES.other;
  const incoming = (envelope.edges || []).filter((e) => e && e.to === nodeId);
  const outgoing = (envelope.edges || []).filter((e) => e && e.from === nodeId);
  const linkedPlans = (envelope.flows || [])
    .filter((f) => Array.isArray(f.steps) && f.steps.some((s) => s && (s.node_ref === nodeId)))
    .map((f) => ({
      id: typeof f.id === 'string' ? f.id : '',
      title: typeof f.title === 'string' ? f.title : f.id,
    }));
  const relatedRows = (relType, list) => {
    if (list.length === 0) return '';
    return `
      <details class="arch-detail-section" open>
        <summary>${esc(relType)} (${esc(String(list.length))})</summary>
        <ul class="arch-detail-list">
          ${list.slice(0, 12).map((e) => `
            <li class="arch-detail-list-row">
              <code class="arch-detail-id">${esc(relType === 'Incoming' ? e.from : e.to)}</code>
              <span class="arch-detail-edge-type">${esc(e.type || 'other')}</span>
            </li>
          `).join('')}
          ${list.length > 12 ? `<li class="arch-detail-overflow">+${esc(String(list.length - 12))} more</li>` : ''}
        </ul>
      </details>
    `;
  };
  return `
    <header class="arch-detail-header">
      <span class="arch-detail-dot" style="background:${esc(meta.color)}"></span>
      <span class="arch-detail-cat">${esc(meta.label)}</span>
      <h3 class="arch-detail-title">${esc(node.title || node.id)}</h3>
    </header>
    ${node.summary ? `<p class="arch-detail-summary">${esc(node.summary)}</p>` : ''}
    <dl class="arch-detail-meta">
      <dt>Node ID</dt><dd><code>${esc(node.id)}</code></dd>
      <dt>Lane</dt><dd><code>${esc(node.lane_id || '—')}</code></dd>
      ${node.source_path ? `<dt>Source path</dt><dd><code>${esc(node.source_path)}</code></dd>` : ''}
      ${node.fingerprint ? `<dt>Fingerprint</dt><dd><code>${esc(String(node.fingerprint).slice(0, 16))}</code></dd>` : ''}
    </dl>
    ${relatedRows('Incoming', incoming)}
    ${relatedRows('Outgoing', outgoing)}
    ${linkedPlans.length > 0 ? `
      <details class="arch-detail-section" open>
        <summary>Flows touching this (${esc(String(linkedPlans.length))})</summary>
        <ul class="arch-detail-list">
          ${linkedPlans.map((p) => `
            <li class="arch-detail-list-row">
              <code class="arch-detail-id">${esc(p.id)}</code>
              <span class="arch-detail-flow-title">${esc(p.title)}</span>
            </li>
          `).join('')}
        </ul>
      </details>
    ` : ''}
  `;
}

/**
 * Build the inner HTML for the step inspector when a flow is selected.
 */
export function renderStepInspectorHTML(envelope, flowId) {
  const { stepRefs, flow } = getFlowParticipants(envelope, flowId);
  if (flow == null) return '';
  return stepRefs.map((step) => {
    const node = (envelope.nodes || []).find((n) => n && n.id === step.node_ref);
    const nodeTitle = node && node.title ? node.title : (step.node_ref || '—');
    const warnings = Array.isArray(step.warnings) ? step.warnings : [];
    const warningRow = warnings.length > 0
      ? `<span class="arch-step-warning">${esc(warnings.map((w) => typeof w === 'string' ? w : (w && w.message) || '').filter(Boolean).join('; '))}</span>`
      : '';
    return `
      <li class="arch-step-row" data-step-id="${esc(step.id)}" data-step-order="${esc(String(step.order))}" data-node-ref="${esc(step.node_ref || '')}">
        <span class="arch-step-num">${esc(String(step.order))}</span>
        <span class="arch-step-body">
          <span class="arch-step-title">${esc(step.title)}</span>
          <span class="arch-step-node">${esc(nodeTitle)}</span>
          ${step.node_ref ? `<code class="arch-step-noderef">${esc(step.node_ref)}</code>` : ''}
          ${warningRow}
        </span>
      </li>
    `;
  }).join('');
}

export function renderNodeProvenanceHTML(envelope) {
  const nodes = (envelope && Array.isArray(envelope.nodes)) ? envelope.nodes : [];
  if (nodes.length === 0) return '';
  const groups = {
    module:     { title: 'Modules',     idLabel: 'Module path',     nodes: [] },
    plan:       { title: 'Plans',       idLabel: 'Plan ID',         nodes: [] },
    capability: { title: 'Capabilities',idLabel: 'Capability ID',   nodes: [] },
    schema:     { title: 'Schemas',     idLabel: 'Schema path',     nodes: [] },
    command:    { title: 'Commands',    idLabel: 'Source',          nodes: [] },
    page:       { title: 'Pages',       idLabel: 'Page path',       nodes: [] },
    external:   { title: 'External',    idLabel: 'External ID',     nodes: [] },
    metadata:   { title: 'Metadata',    idLabel: 'Source',          nodes: [] },
  };
  const others = [];
  for (const node of nodes) {
    if (!node || typeof node !== 'object') continue;
    const t = typeof node.type === 'string' ? node.type : '';
    if (groups[t]) groups[t].nodes.push(node);
    else others.push(node);
  }
  const renderRow = (node, label) => {
    const id = typeof node.id === 'string' ? node.id : '';
    const title = typeof node.title === 'string' && node.title.length > 0
      ? node.title
      : id;
    const sourcePath = typeof node.source_path === 'string' ? node.source_path : '';
    const fingerprint = typeof node.fingerprint === 'string' ? node.fingerprint : '';
    return `
      <li class="arch-prov-row" data-node-id="${esc(id)}" data-node-type="${esc(node.type || '')}">
        <span class="arch-prov-title">${esc(title)}</span>
        <span class="arch-prov-id">
          <span class="arch-prov-id-label">${esc(label)}</span>
          <code class="arch-prov-id-value">${esc(id)}</code>
        </span>
        ${sourcePath ? `
          <span class="arch-prov-source">
            <span class="arch-prov-id-label">Source path</span>
            <code class="arch-prov-id-value">${esc(sourcePath)}</code>
          </span>
        ` : ''}
        ${fingerprint ? `
          <span class="arch-prov-fp">
            <span class="arch-prov-id-label">Fingerprint</span>
            <code class="arch-prov-id-value">${esc(fingerprint.slice(0, 16))}</code>
          </span>
        ` : ''}
      </li>
    `;
  };
  const sections = [];
  for (const [type, group] of Object.entries(groups)) {
    if (group.nodes.length === 0) continue;
    const visible = group.nodes.slice(0, 10);
    const rows = visible.map((n) => renderRow(n, group.idLabel)).join('');
    const overflow = group.nodes.length - visible.length;
    sections.push(`
      <details class="arch-prov-section"
               data-prov-type="${esc(type)}"
               data-prov-count="${esc(String(group.nodes.length))}"
               ${type === 'module' || type === 'plan' || type === 'capability' ? 'open' : ''}>
        <summary class="arch-prov-summary">
          <span class="arch-prov-title">${esc(group.title)}</span>
          <span class="arch-prov-count">${esc(String(group.nodes.length))}</span>
        </summary>
        <ul class="arch-prov-list">${rows}</ul>
        ${overflow > 0 ? `<p class="arch-prov-overflow">+${esc(String(overflow))} more (truncated for readability — full set lives in the source snapshot).</p>` : ''}
      </details>
    `);
  }
  if (others.length > 0) {
    const visible = others.slice(0, 5);
    const rows = visible.map((n) => renderRow(n, 'Node ID')).join('');
    const overflow = others.length - visible.length;
    sections.push(`
      <details class="arch-prov-section" data-prov-type="other" data-prov-count="${esc(String(others.length))}">
        <summary class="arch-prov-summary">
          <span class="arch-prov-title">Other</span>
          <span class="arch-prov-count">${esc(String(others.length))}</span>
        </summary>
        <ul class="arch-prov-list">${rows}</ul>
        ${overflow > 0 ? `<p class="arch-prov-overflow">+${esc(String(overflow))} more.</p>` : ''}
      </details>
    `);
  }
  if (sections.length === 0) return '';
  return `
    <section class="panel arch-provenance-panel" data-provenance="1">
      <div class="arch-provenance-header">
        <h3 class="arch-provenance-title">Details &amp; Provenance</h3>
        <span class="arch-provenance-hint">
          Technical IDs and source paths for the nodes in the snapshot —
          the references reviewers use to cross-check the value-first
          labels above against the actual code.
        </span>
      </div>
      <div class="arch-provenance-body">${sections.join('')}</div>
    </section>
  `;
}

function renderCommandHTML(command) {
  return `
    <div class="arch-card-command">
      <pre class="arch-cmd"><code>${esc(command)}</code></pre>
      <button type="button"
              class="arch-copy-btn"
              data-command="${esc(command)}"
              aria-label="Copy regen command to clipboard">copy</button>
    </div>
  `;
}

function buildProvenance(envelope, scope) {
  const lastUpdated = envelope && typeof envelope.generated_at === 'string' && envelope.generated_at.length > 0
    ? envelope.generated_at
    : (envelope && envelope.freshness && envelope.freshness.generated_at) || null;
  const note = scope === 'fleet'
    ? 'Architecture view-state is built per project. The fleet selector falls back to single-repo state when no per-project cache is present.'
    : 'Architecture view-state is read from the dashboard state cache. The dashboard never auto-regenerates it.';
  return renderProvenanceFooterHTML({
    source: ARCH_SOURCE,
    lastUpdated,
    refreshCommand: ARCH_BUILD,
    note,
  });
}
