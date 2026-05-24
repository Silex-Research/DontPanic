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
  if (selected !== ALL_PROJECTS_VALUE && byProject != null) {
    const scoped = byProject[selected];
    if (scoped != null) return scoped;
  }
  return opts.single != null ? opts.single : null;
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
      ${renderFreshnessBannerHTML(envelope)}
      ${renderInsightsStripHTML(envelope)}
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
        <div class="arch-explorer-canvas-wrap" data-canvas-wrap>
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
