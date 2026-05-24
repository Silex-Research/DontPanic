// ── Architecture Logic — Pure HTML builders for the Architecture tab ──
// Plan: 2026-05-24-002-feat-dashboard-architecture-explorer-v1 (F002 shell).
//
// Consumes the F001 architecture view-state envelope produced by
// `scripts/dontpanic_orchestrate/architecture_view_state.py` and persisted
// at `dashboard/state/architecture-view-state.json`. The envelope shape:
//
//   {
//     schema_version, project: {name, display_name, label},
//     generated_at, source_path,
//     freshness: { state, message, regen_command, generated_at, ... },
//     lanes: [...], nodes: [...], edges: [...], flows: [...], steps: [...],
//     filters: {...}, insights: [...], validation_warnings: [...]
//   }
//
// F002 owns the *shell*: nav-visible tab, value-first labels, missing /
// stale / loading empty states, validation-warning rendering, and the
// exact `dontpanic architecture regen --with-html` command emission with
// a copy affordance. The interactive flow-map canvas, step inspector, and
// filters land in F003 — the shell renders a "Map preview coming in F003"
// placeholder so the tab is non-blank without faking data.
//
// All exports are pure: same input → same string output, no DOM access.
// DOM wiring lives in `pages/architecture/architecture.js`.

import { esc } from './html-escape.js';
import {
  ALL_PROJECTS_VALUE,
  renderScopeBadgeHTML,
} from './project-selector-logic.js';
import { renderProvenanceFooterHTML } from './provenance.js';

// Per-page provenance pointers (Layer 2). Layer 1 stays value-first.
const ARCH_SOURCE = 'dashboard/state/architecture-view-state.json';
const ARCH_REFRESH = 'dontpanic architecture regen --with-html';
const ARCH_BUILD = 'dontpanic dashboard build';

/**
 * Closed set of freshness states surfaced by the shell.
 *
 * F001 emits four states: `fresh|stale|absent|error`. `missing` is a
 * JS-only synonym for `absent` retained for callers that already pass
 * it; both render the same empty card. Dropping unknown values would
 * silently swallow F001's actionable error/absent messaging — instead
 * we accept the full set and let the renderer route each one.
 */
export const FRESHNESS_STATES = Object.freeze([
  'fresh',
  'stale',
  'absent',
  'error',
  'missing',
]);

/** Plain-language headline per freshness state (Layer 1, value-first). */
export const FRESHNESS_HEADLINES = Object.freeze({
  fresh:   'System map is up to date',
  stale:   'System map is out of date',
  absent:  'No system map yet',
  missing: 'No system map yet',
  error:   'System map could not be read',
});

/** One-liner explaining what each state means for the operator. */
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

/** Color tokens — same vocabulary used by other V0 pages. */
export const FRESHNESS_COLORS = Object.freeze({
  fresh:   'green',
  stale:   'yellow',
  absent:  'muted',
  missing: 'muted',
  error:   'red',
});

/**
 * Resolve the effective architecture view-state envelope given the
 * operator's current selection. Plan F001 writes per-project caches at
 * `state/projects/<name>/architecture-view-state.json`; the page must
 * read the project-scoped cache when a specific project is selected
 * and fall back honestly to the single-repo envelope (or null) when
 * the per-project cache has not been built yet.
 *
 * Inputs are raw envelope values — this helper does not normalize.
 *
 * @param {object} opts
 * @param {string} [opts.selectedProject] 'all' or a project name
 * @param {unknown} [opts.single] raw `architectureViewState`
 * @param {Record<string, unknown>|null|undefined} [opts.byProject]
 *   per-project raw view-state map
 * @returns {unknown} raw envelope to feed `renderArchitectureHTML`
 */
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

/**
 * True iff the view-state cache is absent or unusable — no top-level
 * object, or the object is missing the F001 substrate keys.
 * @param {unknown} envelope
 * @returns {boolean}
 */
export function isMissingState(envelope) {
  if (envelope == null) return true;
  if (typeof envelope !== 'object') return true;
  if (!Array.isArray(envelope.lanes)) return true;
  if (!Array.isArray(envelope.nodes)) return true;
  return false;
}

/**
 * Coerce raw JSON into a normalized view-state envelope. Returns `null`
 * when the input does not look like an F001 view-state cache, so the
 * page can render the missing state without throwing.
 * @param {unknown} raw
 */
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
      // Normalize the JS-only `missing` alias to F001's canonical `absent`
      // so downstream consumers branch on the same closed set the F001
      // schema documents. Unknown values clamp to `absent` (vs. `error`)
      // because `absent` represents the safe "no data, run regen" path —
      // surfacing a synthetic `error` would imply a parser fault that
      // isn't actually there.
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

/**
 * Collect every step-level warning across the envelope's flows.
 * F001 attaches warnings per step; F002 surfaces them on the shell so a
 * malformed authored flow does not crash the page.
 * @param {object} envelope normalized envelope
 * @returns {Array<{flow_id: string, step_id: string, message: string}>}
 */
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
  // Also include envelope-level validation_warnings — F001 may surface
  // build-level issues here (missing schemas, invalid flow input).
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

/**
 * Top-level Architecture page renderer.
 *
 * Branches:
 *   - raw is null / not an envelope → missing-state empty card
 *   - envelope.freshness.state === 'absent' (or 'missing') → missing card
 *   - envelope.freshness.state === 'error' → error card with F001 message
 *   - envelope.freshness.state === 'stale' → populated shell + stale banner
 *   - otherwise → populated shell + fresh banner
 *
 * @param {unknown} raw raw `state.architectureViewState` value
 * @param {object} [opts]
 * @param {string} [opts.selectedProject] selected project name or 'all'
 * @returns {string} innerHTML
 */
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
  return renderPopulatedHTML(envelope, scope);
}

/**
 * Missing-state shell. Honest about what is absent and emits the exact
 * regen + build commands the operator needs to run. The shell tab still
 * renders so the operator can land on Architecture and discover the
 * setup path without flipping back to a docs page.
 *
 * Renders even when `envelope` is null — used both for "no view-state
 * cache at all" and "view-state present but freshness.state in
 * {absent, missing}". `data-empty-state="missing"` is preserved as the
 * legacy hook; new callers can branch on `data-freshness` for the F001
 * canonical state.
 *
 * @param {'project'|'fleet'} [scope]
 * @param {object|null} [envelope] normalized envelope when available
 */
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
 * Error-state shell. F001's `error` state fires when architecture.json
 * exists but failed to parse — distinct from `absent`. We surface the
 * F001 message verbatim, list the source path so the operator can
 * inspect it, and keep the regen command available. The page never
 * crashes on `error` — the populated shell only renders when there is
 * something to draw.
 *
 * @param {'project'|'fleet'} scope
 * @param {object} envelope normalized envelope (non-null)
 */
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

function renderPopulatedHTML(envelope, scope) {
  const warnings = collectFlowWarnings(envelope);
  return `
    <div class="arch-layout" data-state="${esc(envelope.freshness.state)}">
      ${renderHeaderHTML(envelope, scope)}
      ${renderFreshnessBannerHTML(envelope)}
      ${renderInsightsStripHTML(envelope)}
      ${renderValidationWarningsHTML(warnings)}
      ${renderMapPlaceholderHTML(envelope)}
      ${renderDetailsTableHTML(envelope)}
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
  // Only stale/missing surface the regen command in the banner. Fresh
  // banners stay quiet — the command is still present in the missing
  // state and in the per-card details for operators who want it.
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

function renderMapPlaceholderHTML(envelope) {
  // F002 owns the shell only. F003 will replace this placeholder with
  // the swimlane SVG canvas and right-rail flow inspector. The shell
  // intentionally renders something credible — lane titles and a count
  // of mapped nodes/edges — so the tab is not blank, but does not fake
  // graph rendering.
  const laneRows = (envelope.lanes || []).map((lane) => {
    if (!lane || typeof lane !== 'object') return '';
    const laneId = typeof lane.id === 'string' ? lane.id : '';
    const title = typeof lane.title === 'string' ? lane.title : laneId;
    const laneNodeCount = (envelope.nodes || []).filter((n) => n && n.lane_id === laneId).length;
    return `
      <li class="arch-lane-row" data-lane-id="${esc(laneId)}">
        <span class="arch-lane-title">${esc(title)}</span>
        <code class="arch-lane-id">${esc(laneId)}</code>
        <span class="arch-lane-count">${esc(String(laneNodeCount))} node${laneNodeCount === 1 ? '' : 's'}</span>
      </li>
    `;
  }).join('');
  const flowCount = (envelope.flows || []).length;
  const edgeCount = (envelope.edges || []).length;
  return `
    <section class="panel arch-map-panel" data-map-state="shell">
      <div class="arch-map-header">
        <h3 class="arch-map-title">System Map</h3>
        <span class="arch-map-hint">Interactive flow map ships in the next iteration. The shell below proves the view-state loaded.</span>
      </div>
      <div class="arch-map-summary">
        <span class="arch-map-summary-chip">${esc(String((envelope.nodes || []).length))} mapped nodes</span>
        <span class="arch-map-summary-chip">${esc(String(edgeCount))} relationships</span>
        <span class="arch-map-summary-chip">${esc(String(flowCount))} flow${flowCount === 1 ? '' : 's'}</span>
      </div>
      <ul class="arch-lane-list">${laneRows}</ul>
    </section>
  `;
}

function renderDetailsTableHTML(envelope) {
  const flows = envelope.flows || [];
  if (flows.length === 0) {
    return `
      <section class="panel arch-flows-panel" data-flows-state="empty">
        <h3 class="arch-flows-title">Flows</h3>
        <p class="arch-flows-empty">
          No flows resolved against the current snapshot. Authored flow
          input lives at <code>docs/architecture/flows.json</code>; derived
          flows depend on plans + capability data being present in the
          architecture snapshot.
        </p>
      </section>
    `;
  }
  const rows = flows.map((flow) => {
    const id = typeof flow.id === 'string' ? flow.id : '';
    const title = typeof flow.title === 'string' && flow.title.length > 0
      ? flow.title
      : id;
    const summary = typeof flow.summary === 'string' ? flow.summary : '';
    const source = typeof flow.source === 'string' ? flow.source : '';
    const stepCount = Array.isArray(flow.steps) ? flow.steps.length : 0;
    const hasWarning = Array.isArray(flow.warnings) && flow.warnings.length > 0
      || (Array.isArray(flow.steps) && flow.steps.some((s) => Array.isArray(s?.warnings) && s.warnings.length > 0));
    return `
      <article class="arch-flow-card" data-flow-id="${esc(id)}" data-has-warning="${hasWarning ? '1' : '0'}">
        <header class="arch-flow-header">
          <span class="arch-flow-title">${esc(title)}</span>
          ${source ? `<span class="arch-flow-source-chip" title="flow source">${esc(source)}</span>` : ''}
          ${hasWarning ? `<span class="arch-flow-warning-chip" title="this flow has step warnings">warning</span>` : ''}
        </header>
        ${summary ? `<p class="arch-flow-summary">${esc(summary)}</p>` : ''}
        <footer class="arch-flow-meta">
          <span class="arch-flow-step-count">${esc(String(stepCount))} step${stepCount === 1 ? '' : 's'}</span>
          <code class="arch-flow-id">${esc(id)}</code>
        </footer>
      </article>
    `;
  }).join('');
  return `
    <section class="panel arch-flows-panel" data-flows-state="populated">
      <div class="arch-flows-header">
        <h3 class="arch-flows-title">Flows</h3>
        <span class="arch-flows-count">${esc(String(flows.length))} flow${flows.length === 1 ? '' : 's'}</span>
      </div>
      <div class="arch-flows-grid">${rows}</div>
    </section>
  `;
}

/**
 * Layer-2 details/provenance panel. Acceptance #2 requires technical
 * IDs (module paths, plan IDs, capability IDs, fingerprints) to remain
 * visible alongside the value-first headlines. We group F001 nodes by
 * type and surface `id` + `source_path` (the module/plan/capability
 * path) for each — these are the IDs reviewers need to cross-reference
 * the source files. Lane and flow IDs are already in the map preview
 * and the freshness header carries the fingerprint; this panel covers
 * the remaining node-level identity surface.
 *
 * Renders nothing when the envelope has no nodes (empty fixture).
 *
 * @param {object} envelope normalized envelope
 */
export function renderNodeProvenanceHTML(envelope) {
  const nodes = (envelope && Array.isArray(envelope.nodes)) ? envelope.nodes : [];
  if (nodes.length === 0) return '';
  // F001 node `type` is the closed set used by the crawler: module,
  // schema, plan, capability, command, page, external, metadata.
  // We surface the four that carry the technical IDs reviewers most
  // commonly need (acceptance #2); other types fall through to a
  // generic "other" bucket so the panel stays honest about coverage.
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
    // Cap visible rows so a 400-module repo does not blow up the page;
    // the count chip remains honest about the full size.
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
  // Mirror the what-now command + copy-button shape so the operator copy
  // affordance is identical across pages. The dashboard never runs the
  // command for the operator (acceptance #5).
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
