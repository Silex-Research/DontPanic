// ── Capabilities Logic — Pure, DOM-free data transformations + HTML builders ──
// Drives the Capability Center page. Consumes the V0b
// `dontpanic capabilities status --format=json` envelope as written to
// `dashboard/state/capabilities-status.json`. Schema reference:
// scripts/dontpanic_orchestrate/capabilities_status.py (StatusEnvelope).
//
// All exports are pure: same input → same string output, no DOM access.
// The page module (`pages/capabilities/capabilities.js`) is responsible
// for wiring this output into `Jarvis.getPageEl('capabilities').innerHTML`.

import { esc } from './html-escape.js';
import { renderScopeBadgeHTML } from './project-selector-logic.js';

/** Closed set of per-capability status values (mirrors V0b). */
export const CAPABILITY_STATUSES = Object.freeze([
  'ready',
  'needs_setup',
  'blocked',
  'not_installed',
  'optional',
]);

export const STATUS_LABELS = Object.freeze({
  ready:         'READY',
  needs_setup:   'NEEDS SETUP',
  blocked:       'BLOCKED',
  not_installed: 'NOT INSTALLED',
  optional:      'OPTIONAL',
});

/** Maps to the same color tokens used elsewhere in core.css. */
export const STATUS_COLORS = Object.freeze({
  ready:         'green',
  needs_setup:   'yellow',
  blocked:       'red',
  not_installed: 'muted',
  optional:      'accent',
});

/** Human label for each owner_boundary bucket. */
export const OWNER_BOUNDARY_LABELS = Object.freeze({
  dontpanic_core: 'core',
  adapter:        'adapter',
  operator:       'operator',
});

/**
 * Returns true if the envelope is absent — either because the state file
 * was never written or the loaded value is the empty default.
 * @param {object|null|undefined} envelope
 * @returns {boolean}
 */
export function isMissingState(envelope) {
  if (envelope == null) return true;
  if (typeof envelope !== 'object') return true;
  if (!Array.isArray(envelope.capabilities)) return true;
  return false;
}

/**
 * Coerces a raw fetched JSON value into the shape expected by the page.
 * Returns `null` if the input is not a recognisable status envelope.
 * Tolerates missing optional fields by filling sensible defaults so
 * render code can stay branch-light.
 * @param {unknown} raw
 * @returns {null | {
 *   schema_version: string,
 *   generated_at: string,
 *   advisory_notes: string[],
 *   capabilities: Array<object>,
 * }}
 */
export function normalizeEnvelope(raw) {
  if (raw == null || typeof raw !== 'object') return null;
  if (!Array.isArray(raw.capabilities)) return null;

  return {
    schema_version: typeof raw.schema_version === 'string' ? raw.schema_version : '',
    generated_at:   typeof raw.generated_at === 'string'   ? raw.generated_at   : '',
    advisory_notes: Array.isArray(raw.advisory_notes) ? raw.advisory_notes.filter(s => typeof s === 'string') : [],
    capabilities:   raw.capabilities.map(normalizeCapability),
  };
}

function normalizeCapability(raw) {
  const c = (raw && typeof raw === 'object') ? raw : {};
  const status = CAPABILITY_STATUSES.includes(c.status) ? c.status : 'optional';
  return {
    capability_id:   typeof c.capability_id === 'string' ? c.capability_id : '(unknown)',
    status,
    owner_boundary:  normalizeOwnerBoundary(c.owner_boundary),
    configured:      Array.isArray(c.configured) ? c.configured.filter(s => typeof s === 'string') : [],
    missing:         Array.isArray(c.missing)    ? c.missing.filter(s => typeof s === 'string')    : [],
    automatable:     Array.isArray(c.automatable)     ? c.automatable.filter(Boolean)     : [],
    human_required:  Array.isArray(c.human_required)  ? c.human_required.filter(Boolean)  : [],
    pending_probes:  Array.isArray(c.pending_probes)  ? c.pending_probes.filter(Boolean)  : [],
    next_actions:    Array.isArray(c.next_actions)    ? c.next_actions.filter(Boolean)    : [],
    advisory_notes:  Array.isArray(c.advisory_notes)  ? c.advisory_notes.filter(s => typeof s === 'string') : [],
  };
}

function normalizeOwnerBoundary(raw) {
  const ob = (raw && typeof raw === 'object') ? raw : {};
  return {
    dontpanic_core: Array.isArray(ob.dontpanic_core) ? ob.dontpanic_core.filter(s => typeof s === 'string') : [],
    adapter:        Array.isArray(ob.adapter)        ? ob.adapter.filter(s => typeof s === 'string')        : [],
    operator:       Array.isArray(ob.operator)       ? ob.operator.filter(s => typeof s === 'string')       : [],
  };
}

/**
 * Returns one chip descriptor per non-empty owner_boundary bucket.
 * @param {{dontpanic_core: string[], adapter: string[], operator: string[]}} ownerBoundary
 * @returns {Array<{role: string, label: string, tokens: string[]}>}
 */
export function buildOwnerBoundaryChips(ownerBoundary) {
  if (!ownerBoundary || typeof ownerBoundary !== 'object') return [];
  const chips = [];
  for (const role of ['dontpanic_core', 'adapter', 'operator']) {
    const tokens = Array.isArray(ownerBoundary[role]) ? ownerBoundary[role] : [];
    if (tokens.length > 0) {
      chips.push({ role, label: OWNER_BOUNDARY_LABELS[role] ?? role, tokens });
    }
  }
  return chips;
}

/**
 * Returns counts by status across the envelope.
 * @param {Array<{status: string}>} capabilities
 * @returns {Record<string, number> & {total: number}}
 */
export function summarizeByStatus(capabilities) {
  const summary = {
    total:         0,
    ready:         0,
    needs_setup:   0,
    blocked:       0,
    not_installed: 0,
    optional:      0,
  };
  if (!Array.isArray(capabilities)) return summary;
  for (const cap of capabilities) {
    summary.total++;
    const key = CAPABILITY_STATUSES.includes(cap?.status) ? cap.status : null;
    if (key) summary[key]++;
  }
  return summary;
}

/**
 * Stable sort order: ready first only when no other capability needs
 * attention; otherwise blocking states float to the top so operators see
 * what needs work without scrolling.
 *
 *   blocked > needs_setup > not_installed > optional > ready
 *
 * Ties broken by capability_id ascending.
 * @param {Array<object>} capabilities
 * @returns {Array<object>}
 */
export function sortByAttention(capabilities) {
  const RANK = { blocked: 0, needs_setup: 1, not_installed: 2, optional: 3, ready: 4 };
  if (!Array.isArray(capabilities)) return [];
  return [...capabilities].sort((a, b) => {
    const ra = RANK[a?.status] ?? 99;
    const rb = RANK[b?.status] ?? 99;
    if (ra !== rb) return ra - rb;
    return String(a?.capability_id ?? '').localeCompare(String(b?.capability_id ?? ''));
  });
}

/**
 * @typedef {{ id?: string, what?: string, command_template?: string|null, human_required_reason?: string|null }} NextAction
 */

/**
 * Returns the action lists already partitioned by the status writer.
 * Mirrors V0b's `automatable` and `human_required` arrays — we trust the
 * writer's classification rather than re-deriving it here.
 * @param {{ automatable?: NextAction[], human_required?: NextAction[] }} cap
 * @returns {{ automatable: NextAction[], humanRequired: NextAction[] }}
 */
export function partitionNextActions(cap) {
  const automatable = Array.isArray(cap?.automatable) ? cap.automatable : [];
  const humanRequired = Array.isArray(cap?.human_required) ? cap.human_required : [];
  return { automatable, humanRequired };
}

/**
 * @param {string} status
 * @returns {{ label: string, color: string }}
 */
export function getStatusBadge(status) {
  return {
    label: STATUS_LABELS[status] ?? String(status ?? 'UNKNOWN').toUpperCase(),
    color: STATUS_COLORS[status] ?? 'accent',
  };
}

// ─────────────────────────────────────────────────────────────────────────
// HTML builders — pure string output, no DOM access.
// ─────────────────────────────────────────────────────────────────────────

/**
 * Top-level page renderer. Returns the innerHTML for the Capability
 * Center page given the raw `state.capabilities` value. Falls back to
 * the empty-state when the envelope is missing or malformed.
 * @param {unknown} raw
 * @returns {string}
 */
export function renderCapabilityCenterHTML(raw) {
  const envelope = normalizeEnvelope(raw);
  if (isMissingState(envelope)) {
    return renderEmptyStateHTML();
  }
  return renderPopulatedHTML(envelope);
}

/** Empty-state HTML shown when no status file is on disk. */
export function renderEmptyStateHTML() {
  return `
    <div class="cap-empty-state">
      <div class="cap-empty-scope">${renderScopeBadgeHTML('global')}</div>
      <div class="cap-empty-title">No capability snapshot yet</div>
      <div class="cap-empty-body">
        Run the local CLI to produce <code>dashboard/state/capabilities-status.json</code>,
        then reload this page. Firebase is not required for this view.
      </div>
      <pre class="cap-empty-cmd">dontpanic capabilities status --format=json &gt; dashboard/state/capabilities-status.json</pre>
      <div class="cap-empty-hint">
        The Capability Center reads from a static JSON file on disk. No sign-in,
        no realtime sync, no Cloud Functions.
      </div>
    </div>
  `;
}

function renderPopulatedHTML(envelope) {
  return `
    <div class="cap-layout">
      <section class="panel cap-summary-panel">
        <h2>Capability Center</h2>
        <div class="cap-summary-scope">${renderScopeBadgeHTML('global')}</div>
        <div class="cap-summary-meta">${renderMetaHTML(envelope)}</div>
        <div class="cap-summary-grid" id="cap-summary-grid">${renderSummaryGridHTML(envelope)}</div>
        <div class="cap-advisory-list" id="cap-advisory-list">${renderAdvisoryListHTML(envelope.advisory_notes)}</div>
      </section>

      <section class="panel cap-cards-panel">
        <div class="cap-cards-header">
          <h2>Capabilities</h2>
          <div class="cap-cards-scope">${renderScopeBadgeHTML('global')}</div>
        </div>
        <div class="cap-cards" id="cap-cards">${renderCardsHTML(envelope.capabilities)}</div>
      </section>
    </div>
  `;
}

function renderMetaHTML(envelope) {
  return `
    <span class="cap-summary-meta-item">
      <span class="cap-summary-meta-label">schema</span>
      <span class="cap-summary-meta-value">${esc(envelope.schema_version || '—')}</span>
    </span>
    <span class="cap-summary-meta-item">
      <span class="cap-summary-meta-label">generated</span>
      <span class="cap-summary-meta-value">${esc(envelope.generated_at || '—')}</span>
    </span>
  `;
}

function renderSummaryGridHTML(envelope) {
  const s = summarizeByStatus(envelope.capabilities);
  return [
    summaryCardHTML('Total',         s.total,         'accent'),
    summaryCardHTML('Ready',         s.ready,         'green'),
    summaryCardHTML('Needs Setup',   s.needs_setup,   'yellow'),
    summaryCardHTML('Blocked',       s.blocked,       'red'),
    summaryCardHTML('Not Installed', s.not_installed, 'muted'),
    summaryCardHTML('Optional',      s.optional,      'accent'),
  ].join('');
}

function summaryCardHTML(label, value, color) {
  return `
    <div class="cap-summary-card">
      <div class="cap-summary-value cap-summary-value--${esc(color)}">${esc(String(value))}</div>
      <div class="cap-summary-label">${esc(label)}</div>
    </div>
  `;
}

function renderAdvisoryListHTML(notes) {
  if (!Array.isArray(notes) || notes.length === 0) return '';
  return notes.map(n => `<div class="cap-advisory">advisory: ${esc(n)}</div>`).join('');
}

function renderCardsHTML(capabilities) {
  const sorted = sortByAttention(capabilities);
  if (sorted.length === 0) {
    return `<div class="cap-empty-inline">The status envelope is present but lists no capabilities.</div>`;
  }
  return sorted.map(renderCapabilityCardHTML).join('');
}

function renderCapabilityCardHTML(cap) {
  const badge = getStatusBadge(cap.status);
  const chips = buildOwnerBoundaryChips(cap.owner_boundary);
  const { automatable, humanRequired } = partitionNextActions(cap);

  return `
    <article class="cap-card cap-card--${esc(badge.color)}" data-capability-id="${esc(cap.capability_id)}" data-status="${esc(cap.status)}">
      <header class="cap-card-header">
        <div class="cap-card-title">${esc(cap.capability_id)}</div>
        <span class="cap-status-badge cap-status-badge--${esc(badge.color)}">${esc(badge.label)}</span>
      </header>
      ${chips.length > 0 ? renderOwnerBoundaryHTML(chips) : ''}
      ${renderListBlockHTML('Configured', cap.configured, 'cap-list-configured')}
      ${renderListBlockHTML('Missing',    cap.missing,    'cap-list-missing')}
      ${renderPendingProbesHTML(cap.pending_probes)}
      ${renderNextActionsHTML(automatable, humanRequired)}
      ${renderAdvisoryListHTML(cap.advisory_notes)}
    </article>
  `;
}

function renderOwnerBoundaryHTML(chips) {
  return `
    <div class="cap-owner-boundary">
      <span class="cap-owner-label">owner_boundary</span>
      ${chips.map(chip => `
        <span class="cap-owner-chip cap-owner-chip--${esc(chip.role)}" title="${esc(chip.tokens.join(', '))}">
          ${esc(chip.label)}
          <span class="cap-owner-chip-count">${chip.tokens.length}</span>
        </span>
      `).join('')}
    </div>
  `;
}

function renderListBlockHTML(title, items, listClass) {
  if (!Array.isArray(items) || items.length === 0) return '';
  return `
    <div class="cap-list-block">
      <div class="cap-list-title">${esc(title)}</div>
      <ul class="cap-list ${esc(listClass)}">
        ${items.map(token => `<li>${esc(token)}</li>`).join('')}
      </ul>
    </div>
  `;
}

function renderPendingProbesHTML(probes) {
  if (!Array.isArray(probes) || probes.length === 0) return '';
  return `
    <div class="cap-list-block">
      <div class="cap-list-title">Pending probes</div>
      <ul class="cap-list cap-list-probes">
        ${probes.map(p => `
          <li>
            <span class="cap-probe-name">${esc(p && p.name ? p.name : '(unnamed)')}</span>
            <span class="cap-probe-reason">${esc(p && p.reason ? p.reason : '')}</span>
          </li>
        `).join('')}
      </ul>
    </div>
  `;
}

function renderNextActionsHTML(automatable, humanRequired) {
  if (automatable.length === 0 && humanRequired.length === 0) return '';
  return `
    <div class="cap-next-actions">
      <div class="cap-list-title">Next actions</div>
      ${renderActionGroupHTML('automatable', automatable)}
      ${renderActionGroupHTML('human_required', humanRequired)}
    </div>
  `;
}

function renderActionGroupHTML(kind, actions) {
  if (actions.length === 0) return '';
  const isHuman = kind === 'human_required';
  return `
    <div class="cap-action-group cap-action-group--${esc(isHuman ? 'human' : 'auto')}">
      <div class="cap-action-group-label">${esc(isHuman ? 'human-required' : 'automatable')}</div>
      <ul class="cap-action-list">
        ${actions.map(a => `
          <li class="cap-action-item">
            <div class="cap-action-what">${esc((a && (a.what || a.id)) || '(no description)')}</div>
            ${a && a.command_template ? `<pre class="cap-action-cmd">${esc(a.command_template)}</pre>` : ''}
            ${isHuman && a && a.human_required_reason ? `<div class="cap-action-reason">${esc(a.human_required_reason)}</div>` : ''}
          </li>
        `).join('')}
      </ul>
    </div>
  `;
}
