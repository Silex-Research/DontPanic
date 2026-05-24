// ── What Now Logic — Pure transformations + HTML builders ──
// Drives the "What Now" operator view (plan 2026-05-23-004 F004). Consumes
// the F001 ActionItem cache envelope (`operator_console.render_envelope`)
// as written to `dashboard/state/what-now.json` by
// `dontpanic dashboard build`.
//
// The view is read-only. It does NOT mutate gates, kick off commands, or
// surface drag/drop affordances — commands are copyable text the operator
// runs in their own terminal.
//
// All exports are pure: same input → same string output. DOM access lives
// in `pages/what-now/what-now.js`.

import { esc } from './html-escape.js';
import {
  ALL_PROJECTS_VALUE,
  renderScopeBadgeHTML,
} from './project-selector-logic.js';
import { renderProvenanceFooterHTML } from './provenance.js';

// F004: per-page provenance — what-now state is rewritten by
// `dontpanic dashboard build`. The fleet variant points at the
// fleet-what-now envelope written by the same command.
const WHAT_NOW_REFRESH = 'dontpanic dashboard build';
const WHAT_NOW_SOURCE = 'dashboard/state/what-now.json';
const FLEET_WHAT_NOW_SOURCE = 'dashboard/state/fleet-what-now.json';

function buildWhatNowProvenance(envelope, { fleet = false } = {}) {
  return renderProvenanceFooterHTML({
    source: fleet ? FLEET_WHAT_NOW_SOURCE : WHAT_NOW_SOURCE,
    lastUpdated: envelope && typeof envelope.captured_at === 'string' && envelope.captured_at.length > 0
      ? envelope.captured_at
      : null,
    refreshCommand: WHAT_NOW_REFRESH,
  });
}

/** Four-band taxonomy emitted by F001 providers — ordering reflects display priority. */
export const BANDS = Object.freeze(['needs_action', 'advisory', 'info', 'ready']);

/** Sources that surface ActionItems in V0. */
export const SOURCES = Object.freeze(['gate', 'capability', 'reconcile', 'supervisor', 'architecture']);

export const BAND_LABELS = Object.freeze({
  needs_action: 'NEEDS ACTION',
  advisory:     'ADVISORY',
  info:         'INFO',
  ready:        'READY',
});

/** Color tokens reuse the same vocabulary as the Capability Center. */
export const BAND_COLORS = Object.freeze({
  needs_action: 'red',
  advisory:     'yellow',
  info:         'accent',
  ready:        'green',
});

export const SOURCE_LABELS = Object.freeze({
  gate:         'Gate',
  capability:   'Capability',
  reconcile:    'Reconcile',
  supervisor:   'Supervisor',
  architecture: 'Architecture',
});

// F003: value-first "kind" labels. Primary Layer-1 text rendered before
// any technical noun. Pairs (source, band) → human-readable headline.
// The internal SOURCE_LABELS (gate / capability / supervisor / …) stay
// available as Layer-2 chips on each card.
const VALUE_KIND_LABELS = Object.freeze({
  'gate:needs_action':         'Approval needed',
  'gate:advisory':             'Approval pending',
  'gate:info':                 'Approval cleared',
  'gate:ready':                'Approval cleared',
  'capability:needs_action':   'Setup required',
  'capability:advisory':       'Setup advisory',
  'capability:info':           'Tool connected',
  'capability:ready':          'Tool connected',
  'reconcile:needs_action':    'Setup drift detected',
  'reconcile:advisory':        'Setup drift advisory',
  'reconcile:info':            'Setup change recorded',
  'reconcile:ready':           'Install matches baseline',
  'supervisor:needs_action':   'AI work needs help',
  'supervisor:advisory':       'AI work warning',
  'supervisor:info':           'Active AI work',
  'supervisor:ready':          'AI work clear',
  'architecture:needs_action': 'Architecture snapshot needs refresh',
  'architecture:advisory':     'Architecture snapshot is stale',
  'architecture:info':         'Architecture snapshot updated',
  'architecture:ready':        'Architecture snapshot fresh',
});

/**
 * Plain-language "kind" label derived from (source, band). Falls back
 * to the source's SOURCE_LABEL when the pair is unknown.
 * @param {string} source
 * @param {string} band
 * @returns {string}
 */
export function getValueKindLabel(source, band) {
  const key = `${source}:${band}`;
  if (VALUE_KIND_LABELS[key]) return VALUE_KIND_LABELS[key];
  return SOURCE_LABELS[source] || String(source || '');
}

const BAND_PRIORITY = Object.freeze({
  needs_action: 0, advisory: 1, info: 2, ready: 3,
});

const SOURCE_PRIORITY = Object.freeze({
  gate: 0, reconcile: 1, capability: 2, supervisor: 3, architecture: 4,
});

/**
 * True iff the envelope is absent — either because the file was never
 * written (fresh operator before `dontpanic dashboard build`) or the
 * loaded value lacks an `items` array.
 * @param {unknown} envelope
 */
export function isMissingState(envelope) {
  if (envelope == null) return true;
  if (typeof envelope !== 'object') return true;
  if (!Array.isArray(envelope.items)) return true;
  return false;
}

/**
 * Coerce raw JSON into the normalized envelope shape. Returns `null`
 * when the input doesn't look like a what-now cache.
 * @param {unknown} raw
 * @returns {null | { schema_version: string, captured_at: string, items: Array<object> }}
 */
export function normalizeEnvelope(raw) {
  if (raw == null || typeof raw !== 'object') return null;
  if (!Array.isArray(raw.items)) return null;
  return {
    schema_version: typeof raw.schema_version === 'string' ? raw.schema_version : '',
    captured_at:    typeof raw.captured_at === 'string'    ? raw.captured_at    : '',
    items:          raw.items.map(normalizeActionItem).filter((it) => it != null),
  };
}

function normalizeActionItem(raw) {
  if (raw == null || typeof raw !== 'object') return null;
  const band = BANDS.includes(raw.band) ? raw.band : 'info';
  const source = SOURCES.includes(raw.source) ? raw.source : 'capability';
  const automatable = raw.automatable === true;
  return {
    id:                    typeof raw.id === 'string' ? raw.id : '',
    source,
    band,
    title:                 typeof raw.title === 'string' ? raw.title : '',
    detail:                typeof raw.detail === 'string' ? raw.detail : null,
    exact_command:         typeof raw.exact_command === 'string' ? raw.exact_command : null,
    automatable,
    human_required_reason: typeof raw.human_required_reason === 'string' ? raw.human_required_reason : null,
    evidence_uri:          typeof raw.evidence_uri === 'string' ? raw.evidence_uri : null,
    updated_at:            typeof raw.updated_at === 'string' ? raw.updated_at : '',
    // F004: optional project tag. Populated by per-project providers
    // (gates, architecture, supervisor, build warnings); null for
    // global items (capability/reconcile) so the relevance filter can
    // gate them against project declarations.
    project_name:          typeof raw.project_name === 'string' ? raw.project_name : null,
    display_name:          typeof raw.display_name === 'string' ? raw.display_name : null,
  };
}

// F004 — band priority for the worst-band rollup used to order
// All-Projects sections (worst band first, then project name).
const HEALTH_BAND_PRIORITY = Object.freeze({
  needs_action: 3, advisory: 2, ready: 1, quiet: 0,
});

/** Promote one of the four-band taxonomy values to a numeric rank for
 *  worst-band comparisons. Unknown values rank below ``quiet`` so a stale
 *  cache cannot accidentally jump to the front of the list.
 */
export function bandRank(band) {
  return HEALTH_BAND_PRIORITY[band] ?? -1;
}

/**
 * Stable sort: band priority → source priority → id (matches the server
 * `operator_console._sort` ordering so client and cache agree).
 * @param {Array<object>} items
 */
export function sortItems(items) {
  if (!Array.isArray(items)) return [];
  return [...items].sort((a, b) => {
    const ba = BAND_PRIORITY[a?.band] ?? 99;
    const bb = BAND_PRIORITY[b?.band] ?? 99;
    if (ba !== bb) return ba - bb;
    const sa = SOURCE_PRIORITY[a?.source] ?? 99;
    const sb = SOURCE_PRIORITY[b?.source] ?? 99;
    if (sa !== sb) return sa - sb;
    return String(a?.id ?? '').localeCompare(String(b?.id ?? ''));
  });
}

/**
 * Returns a tuple `{ band, items }` for each band that has at least one
 * item. Empty bands are omitted so the quiet state is visibly quiet
 * (acceptance #4).
 * @param {Array<object>} items
 */
export function groupByBand(items) {
  const buckets = new Map();
  for (const band of BANDS) buckets.set(band, []);
  for (const it of Array.isArray(items) ? items : []) {
    const band = BANDS.includes(it?.band) ? it.band : 'info';
    buckets.get(band).push(it);
  }
  const out = [];
  for (const band of BANDS) {
    const bucketItems = buckets.get(band);
    if (bucketItems.length > 0) {
      out.push({ band, items: sortItems(bucketItems) });
    }
  }
  return out;
}

/**
 * Compact counts by band — surfaced in the header strip.
 * @param {Array<object>} items
 */
export function summarizeByBand(items) {
  const summary = { needs_action: 0, advisory: 0, info: 0, ready: 0, total: 0 };
  if (!Array.isArray(items)) return summary;
  for (const it of items) {
    summary.total++;
    if (BANDS.includes(it?.band)) summary[it.band]++;
  }
  return summary;
}

/**
 * `true` iff at least one item is in the `needs_action` band.
 * @param {Array<object>} items
 */
export function hasNeedsAction(items) {
  if (!Array.isArray(items)) return false;
  return items.some((it) => it && it.band === 'needs_action');
}

export function getBandBadge(band) {
  return {
    label: BAND_LABELS[band] ?? String(band ?? 'INFO').toUpperCase(),
    color: BAND_COLORS[band] ?? 'accent',
  };
}

export function getSourceLabel(source) {
  return SOURCE_LABELS[source] ?? String(source ?? '');
}

// ─────────────────────────────────────────────────────────────────────────
// HTML builders
// ─────────────────────────────────────────────────────────────────────────

/**
 * Top-level page renderer. Returns the innerHTML for the What Now page
 * given the raw `state.whatNow` value (already-parsed JSON or null).
 *
 * The optional `selectedProject` argument toggles the scope badge
 * between Project (any registered project name) and Fleet (the
 * ALL_PROJECTS_VALUE sentinel). The What Now surface itself is the
 * same query in either case — only the badge changes.
 *
 * @param {unknown} raw
 * @param {object} [opts]
 * @param {string} [opts.selectedProject]
 * @returns {string}
 */
export function renderWhatNowHTML(raw, opts = {}) {
  const envelope = normalizeEnvelope(raw);
  const selected = typeof opts.selectedProject === 'string'
    ? opts.selectedProject
    : ALL_PROJECTS_VALUE;
  const scope = selected === ALL_PROJECTS_VALUE ? 'fleet' : 'project';
  if (envelope == null) {
    return renderMissingStateHTML(scope);
  }
  // Quiet state only when there is literally nothing to surface. Advisory
  // and info items must render as cards so their exact commands stay
  // visible/copyable (F004 acceptance #3) — band colors handle restraint.
  if (envelope.items.length === 0) {
    return renderQuietStateHTML(envelope, scope);
  }
  return renderPopulatedHTML(envelope, scope);
}

/**
 * Missing-cache empty-state. Non-alarming wording: F004 acceptance (4)
 * says stale/missing optional data must not render as a blocker.
 * @param {'project'|'fleet'} [scope]
 */
export function renderMissingStateHTML(scope = 'project') {
  return `
    <div class="wn-empty-state" data-state="missing">
      <div class="wn-empty-scope">${renderScopeBadgeHTML(scope)}</div>
      <div class="wn-empty-title">No what-now cache yet</div>
      <div class="wn-empty-body">
        Run <code>dontpanic dashboard build</code> to populate
        <code>dashboard/state/what-now.json</code>. The dashboard reads the
        same local cache agents use to answer <q>what needs action now?</q>
      </div>
      <pre class="wn-empty-cmd">dontpanic dashboard build</pre>
      <div class="wn-empty-hint">
        Once the cache exists, this view will list gates, capabilities,
        reconcile drift, and active supervisors that need attention.
      </div>
      ${renderProvenanceFooterHTML({
        source: scope === 'fleet' ? FLEET_WHAT_NOW_SOURCE : WHAT_NOW_SOURCE,
        lastUpdated: null,
        refreshCommand: WHAT_NOW_REFRESH,
        note: 'Cache absent — dashboard treats this as a missing-data state, not a blocker.',
      })}
    </div>
  `;
}

/**
 * Quiet healthy state — rendered when the envelope is present but no
 * item is in the `needs_action` band. F004 acceptance (4): restrained
 * when no action is needed.
 * @param {object} envelope
 * @param {'project'|'fleet'} [scope]
 */
export function renderQuietStateHTML(envelope, scope = 'project', provenance = {}) {
  const summary = summarizeByBand(envelope.items);
  const advisoryLine = summary.advisory > 0
    ? `${summary.advisory} advisory item${summary.advisory === 1 ? '' : 's'} present.`
    : '';
  const infoLine = summary.info > 0
    ? `${summary.info} informational item${summary.info === 1 ? '' : 's'} present.`
    : '';
  const sublines = [advisoryLine, infoLine].filter(Boolean).join(' ');
  return `
    <div class="wn-quiet-state" data-state="quiet">
      <div class="wn-quiet-scope">${renderScopeBadgeHTML(scope)}</div>
      <div class="wn-quiet-title">No action needed</div>
      <div class="wn-quiet-body">
        Gates are clear, capabilities are ready or optional, reconcile is
        clean, and no supervisor is flagged.
        ${esc(sublines)}
      </div>
      <div class="wn-quiet-meta">
        ${renderMetaHTML(envelope)}
      </div>
      ${buildWhatNowProvenance(envelope, { fleet: provenance.fleetSource === true || scope === 'fleet' })}
    </div>
  `;
}

function renderPopulatedHTML(envelope, scope = 'project', provenance = {}) {
  const groups = groupByBand(envelope.items);
  return `
    <div class="wn-layout">
      <section class="panel wn-header-panel">
        <div class="wn-header-row">
          <h2>Needs Attention</h2>
          <div class="wn-header-scope">${renderScopeBadgeHTML(scope)}</div>
          <div class="wn-header-meta">${renderMetaHTML(envelope)}</div>
        </div>
        <div class="wn-summary-strip">${renderSummaryStripHTML(envelope.items)}</div>
      </section>
      ${groups.map((g) => renderBandSectionHTML(g, scope)).join('')}
      ${buildWhatNowProvenance(envelope, { fleet: provenance.fleetSource === true || scope === 'fleet' })}
    </div>
  `;
}

function renderMetaHTML(envelope) {
  return `
    <span class="wn-meta-item"><span class="wn-meta-label">schema</span><span class="wn-meta-value">${esc(envelope.schema_version || '—')}</span></span>
    <span class="wn-meta-item"><span class="wn-meta-label">captured</span><span class="wn-meta-value">${esc(envelope.captured_at || '—')}</span></span>
  `;
}

function renderSummaryStripHTML(items) {
  const s = summarizeByBand(items);
  return [
    summaryChipHTML('Needs action', s.needs_action, 'red'),
    summaryChipHTML('Advisory',     s.advisory,     'yellow'),
    summaryChipHTML('Info',         s.info,         'accent'),
    summaryChipHTML('Ready',        s.ready,        'green'),
  ].join('');
}

function summaryChipHTML(label, value, color) {
  return `
    <span class="wn-summary-chip wn-summary-chip--${esc(color)}">
      <span class="wn-summary-chip-value">${esc(String(value))}</span>
      <span class="wn-summary-chip-label">${esc(label)}</span>
    </span>
  `;
}

function renderBandSectionHTML(group, scope = 'project') {
  const badge = getBandBadge(group.band);
  return `
    <section class="panel wn-band-panel wn-band-panel--${esc(badge.color)}" data-band="${esc(group.band)}">
      <div class="wn-band-header">
        <span class="wn-band-badge wn-band-badge--${esc(badge.color)}">${esc(badge.label)}</span>
        <span class="wn-band-count">${esc(String(group.items.length))} item${group.items.length === 1 ? '' : 's'}</span>
        <span class="wn-band-scope">${renderScopeBadgeHTML(scope)}</span>
      </div>
      <div class="wn-cards">${group.items.map(renderActionCardHTML).join('')}</div>
    </section>
  `;
}

function renderActionCardHTML(item) {
  const badge = getBandBadge(item.band);
  const sourceLabel = getSourceLabel(item.source);
  const kindLabel = getValueKindLabel(item.source, item.band);
  const projectChip = item.display_name || item.project_name
    ? `<span class="wn-project-chip" title="project">${esc(item.display_name || item.project_name)}</span>`
    : '';
  // Layer 1 ("what does this mean for me?") leads with the kind label.
  // Layer 2 (the upstream provider title and ids) lives below in the
  // technical-detail block so the non-technical reviewer reads value
  // language first.
  return `
    <article class="wn-card wn-card--${esc(badge.color)}"
             data-action-id="${esc(item.id)}"
             data-source="${esc(item.source)}"
             data-band="${esc(item.band)}">
      <header class="wn-card-header">
        <span class="wn-card-kind">${esc(kindLabel)}</span>
        ${projectChip}
        ${renderRoleChipHTML(item)}
      </header>
      <div class="wn-card-impact">${esc(item.title || '')}</div>
      ${item.detail ? `<div class="wn-card-detail">${esc(item.detail)}</div>` : ''}
      ${renderCommandHTML(item.exact_command)}
      ${renderEvidenceHTML(item.evidence_uri)}
      <footer class="wn-card-footer">
        <span class="wn-source-chip wn-source-chip--${esc(item.source)}" title="provider">${esc(sourceLabel)}</span>
        <span class="wn-card-id" title="${esc(item.id)}">${esc(item.id)}</span>
        ${item.updated_at ? `<span class="wn-card-updated">updated ${esc(item.updated_at)}</span>` : ''}
      </footer>
    </article>
  `;
}

function renderRoleChipHTML(item) {
  if (item.automatable) {
    return `<span class="wn-role-chip wn-role-chip--auto" title="An agent or script can run this without human judgement">automatable</span>`;
  }
  const reason = item.human_required_reason ? ` — ${item.human_required_reason}` : '';
  return `<span class="wn-role-chip wn-role-chip--human" title="${esc('human-required' + reason)}">human-required</span>`;
}

function renderCommandHTML(command) {
  if (!command) return '';
  // Render the command as a pre/code block plus a non-mutating copy
  // affordance. The dashboard is read-only: the copy button writes the
  // raw command string to the clipboard so the operator runs it in their
  // own terminal. No dispatch, no kanban.
  return `
    <div class="wn-card-command">
      <pre class="wn-cmd"><code>${esc(command)}</code></pre>
      <button type="button" class="wn-copy-btn" data-command="${esc(command)}" aria-label="Copy command to clipboard">copy</button>
    </div>
  `;
}

function renderEvidenceHTML(evidenceUri) {
  if (!evidenceUri) return '';
  // Evidence URIs are local paths or file:/// references. Render as
  // plain text inside a <code> block so the operator can copy them; do
  // NOT link them — `file://` links break in many browsers and `<a>`
  // would invite drift toward navigation we don't yet support.
  return `
    <div class="wn-card-evidence">
      <span class="wn-evidence-label">evidence</span>
      <code class="wn-evidence-uri">${esc(evidenceUri)}</code>
    </div>
  `;
}

// ─────────────────────────────────────────────────────────────────────────
// F004 — Fleet what-now: grouping + filtering + status header
// ─────────────────────────────────────────────────────────────────────────

/**
 * Group ActionItems by ``project_name`` (the F004 fleet view).
 *
 * Output is sorted by worst band (needs_action → advisory → ready →
 * quiet), then by project ``name`` string-ascending. Items without a
 * ``project_name`` land in a synthetic ``__global__`` bucket that the
 * renderer treats as a separate top section so global capability /
 * reconcile blockers stay visible.
 *
 * @param {Array<object>} items normalized ActionItems
 * @param {Array<object>} projects fleet-summary projects entries
 *                                  (``{name, display_name, health_band, ...}``)
 * @returns {Array<{name: string, display_name: string, health_band: string, items: Array<object>}>}
 */
export function groupByProject(items, projects) {
  if (!Array.isArray(items)) items = [];
  const projectIndex = new Map();
  if (Array.isArray(projects)) {
    for (const p of projects) {
      if (p && typeof p.name === 'string') {
        projectIndex.set(p.name, p);
      }
    }
  }
  const buckets = new Map();
  for (const it of items) {
    const key = typeof it?.project_name === 'string' && it.project_name.length > 0
      ? it.project_name
      : '__global__';
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(it);
  }

  /** @type {Array<{name: string, display_name: string, health_band: string, items: Array<object>}>} */
  const groups = [];
  for (const [name, bucketItems] of buckets.entries()) {
    const projectEntry = projectIndex.get(name);
    let health_band = projectEntry?.health_band || 'ready';
    // Refine the band from the items present in case the fleet summary
    // is older than the per-project what-now cache.
    for (const it of bucketItems) {
      if (it.band === 'needs_action') { health_band = 'needs_action'; break; }
      if (it.band === 'advisory' && health_band === 'ready') health_band = 'advisory';
    }
    let display_name = projectEntry?.display_name || name;
    if (name === '__global__') {
      health_band = bucketItems.some((it) => it.band === 'needs_action')
        ? 'needs_action'
        : bucketItems.some((it) => it.band === 'advisory') ? 'advisory' : 'ready';
      display_name = 'Global';
    }
    groups.push({
      name,
      display_name,
      health_band,
      items: sortItems(bucketItems),
    });
  }
  // Stable sort: __global__ pinned to the top so doctor/install
  // blockers stay at eye level; the rest sort by worst band, then by
  // name (string-ascending).
  groups.sort((a, b) => {
    if (a.name === '__global__' && b.name !== '__global__') return -1;
    if (b.name === '__global__' && a.name !== '__global__') return 1;
    const rankDiff = bandRank(b.health_band) - bandRank(a.health_band);
    if (rankDiff !== 0) return rankDiff;
    return a.name.localeCompare(b.name);
  });
  return groups;
}

// Closed set of capability ids whose blockers are universally relevant
// (mirrors :data:`dashboard_relevance.GLOBAL_DOCTOR_CAPABILITIES`). The
// JS keeps its own copy so the project filter can render without an
// extra Python round-trip; tests check the two stay in sync.
export const GLOBAL_DOCTOR_CAPABILITIES = Object.freeze(new Set([
  'python', 'schema-support', 'dontpanic-install', 'git',
]));

/**
 * True iff this item is a doctor / install / install-drift blocker that
 * applies to every project (relevance table rows 2-3 + reconcile).
 */
export function isGlobalDoctorBlocker(item) {
  if (item == null) return false;
  if (item.source === 'reconcile') return true;
  if (item.source === 'capability' && typeof item.id === 'string') {
    const prefix = 'capability:';
    const capId = item.id.startsWith(prefix) ? item.id.slice(prefix.length) : null;
    if (capId && GLOBAL_DOCTOR_CAPABILITIES.has(capId)) return true;
  }
  return false;
}

/**
 * Filter ActionItems down to the ones relevant to a selected project.
 *
 * Mirrors :func:`dashboard_relevance.is_item_relevant_to_project` on
 * the Python side. The full F004 design-table relevance rule:
 *
 *   1. ``item.project_name`` set + equals selected → True
 *   2. ``item.project_name`` set + differs → False
 *   3. Global doctor / install / drift blocker → True (universally relevant)
 *   4. Capability item:
 *        - declared in ``required_capability_ids`` → True
 *        - ``capability_categories[cap_id]`` ∈ ``referenced_adapter_categories``
 *          → True (adapter-not-configured rule via category)
 *        - otherwise → False
 *   5. Architecture without ``project_name`` → True (legacy single-repo)
 *   6. Other unscoped sources → True
 *
 * @param {Array<object>} items
 * @param {string} selectedProject the registered project ``name``
 * @param {object} [opts]
 * @param {Set<string>|Array<string>} [opts.requiredCapabilityIds]
 *        Capability ids the selected project's plans declare.
 * @param {Set<string>|Array<string>} [opts.referencedAdapterCategories]
 *        Adapter categories the selected project's plans reference.
 * @param {Record<string,string>} [opts.capabilityCategories]
 *        Capability id → category map (typically the fleet what-now
 *        envelope's ``capability_categories`` field).
 */
export function filterItemsForProject(items, selectedProject, opts = {}) {
  if (!Array.isArray(items)) return [];
  const required = new Set(opts.requiredCapabilityIds || []);
  const referencedCategories = new Set(opts.referencedAdapterCategories || []);
  const capCategories = opts.capabilityCategories && typeof opts.capabilityCategories === 'object'
    ? opts.capabilityCategories
    : {};
  return items.filter((it) => {
    if (!it) return false;
    if (typeof it.project_name === 'string' && it.project_name.length > 0) {
      return it.project_name === selectedProject;
    }
    if (isGlobalDoctorBlocker(it)) return true;
    if (it.source === 'capability') {
      const prefix = 'capability:';
      const capId = typeof it.id === 'string' && it.id.startsWith(prefix)
        ? it.id.slice(prefix.length)
        : null;
      if (capId == null) return false;
      if (required.has(capId)) return true;
      const category = capCategories[capId];
      if (typeof category === 'string' && referencedCategories.has(category)) {
        return true;
      }
      return false;
    }
    // Unscoped non-capability items (legacy single-repo) — keep them
    // visible so the V0 fallback view doesn't lose architecture
    // / supervisor data.
    return true;
  });
}

// ─────────────────────────────────────────────────────────────────────────
// Status header (acceptance 5)
// ─────────────────────────────────────────────────────────────────────────

/**
 * Compute the status-header payload — scope, selected health band,
 * warning count, and data age — given the fleet-what-now envelope, the
 * fleet summary, and the operator's selection.
 *
 * @param {object} args
 * @param {object|null} args.envelope normalized fleet-what-now envelope
 * @param {object|null} args.fleetSummary normalized fleet summary
 * @param {string} args.selected selected project ``name`` or
 *                               ``"all"`` for fleet
 * @param {Date|number} [args.now] for deterministic tests
 */
export function buildStatusHeader({ envelope, fleetSummary, selected, now }) {
  const scope = selected === 'all' ? 'fleet' : 'project';
  const items = Array.isArray(envelope?.items) ? envelope.items : [];
  const summary = summarizeByBand(items);
  let warningCount = 0;
  if (Array.isArray(fleetSummary?.projects)) {
    for (const p of fleetSummary.projects) {
      if (typeof p?.warning_count === 'number') warningCount += p.warning_count;
    }
  }
  let healthBand = 'ready';
  if (selected === 'all') {
    if (typeof fleetSummary?.worst_band === 'string') {
      healthBand = fleetSummary.worst_band;
    } else if (summary.needs_action > 0) {
      healthBand = 'needs_action';
    } else if (summary.advisory > 0) {
      healthBand = 'advisory';
    }
  } else {
    const entry = Array.isArray(fleetSummary?.projects)
      ? fleetSummary.projects.find((p) => p?.name === selected)
      : null;
    if (entry?.health_band) {
      healthBand = entry.health_band;
    } else if (summary.needs_action > 0) {
      healthBand = 'needs_action';
    } else if (summary.advisory > 0) {
      healthBand = 'advisory';
    }
    // Per-project warning_count only.
    warningCount = typeof entry?.warning_count === 'number'
      ? entry.warning_count
      : 0;
  }
  let dataAgeSeconds = null;
  if (typeof envelope?.captured_at === 'string' && envelope.captured_at.length > 0) {
    const captured = Date.parse(envelope.captured_at);
    const reference = now instanceof Date
      ? now.getTime()
      : typeof now === 'number' ? now : Date.now();
    if (!Number.isNaN(captured) && !Number.isNaN(reference)) {
      dataAgeSeconds = Math.max(0, Math.round((reference - captured) / 1000));
    }
  }
  return {
    scope,
    selected,
    health_band: healthBand,
    warning_count: warningCount,
    data_age_seconds: dataAgeSeconds,
    captured_at: typeof envelope?.captured_at === 'string' ? envelope.captured_at : '',
  };
}

/**
 * Render the status header strip as HTML. The strip is the only
 * surface that declares the active scope chip + health-band badge
 * outside the selector itself.
 */
export function renderStatusHeaderHTML(header) {
  if (header == null) return '';
  const scopeLabel = header.scope === 'fleet' ? 'fleet' : 'project';
  const bandBadge = getBandBadge(header.health_band);
  const ageDisplay = header.data_age_seconds == null
    ? '—'
    : `${header.data_age_seconds}s`;
  return `
    <div class="wn-status-header" data-status-header="1" data-scope="${esc(scopeLabel)}">
      <span class="wn-status-chip wn-status-chip--scope">
        ${renderScopeBadgeHTML(scopeLabel)}
      </span>
      <span class="wn-status-chip wn-status-chip--band wn-status-chip--${esc(bandBadge.color)}">
        <span class="wn-status-chip-label">${esc(bandBadge.label)}</span>
      </span>
      <span class="wn-status-chip wn-status-chip--warnings">
        <span class="wn-status-chip-label">warnings</span>
        <span class="wn-status-chip-value">${esc(String(header.warning_count))}</span>
      </span>
      <span class="wn-status-chip wn-status-chip--age">
        <span class="wn-status-chip-label">data age</span>
        <span class="wn-status-chip-value">${esc(ageDisplay)}</span>
      </span>
    </div>
  `;
}

/**
 * Render the fleet view (All Projects) — section headers per project,
 * ordered by worst band, then project name.
 *
 * @param {object} envelope normalized fleet-what-now envelope
 * @param {object} fleetSummary normalized fleet summary
 * @param {object} [opts]
 * @param {Date|number} [opts.now] reference clock for status header age
 */
export function renderFleetWhatNowHTML(envelope, fleetSummary, opts = {}) {
  if (envelope == null) return renderMissingStateHTML('fleet');
  const items = Array.isArray(envelope.items) ? envelope.items : [];
  const header = buildStatusHeader({
    envelope,
    fleetSummary,
    selected: 'all',
    now: opts.now,
  });
  const headerHTML = renderStatusHeaderHTML(header);
  if (items.length === 0) {
    return `
      <div class="wn-layout wn-layout--fleet">
        ${headerHTML}
        ${renderQuietStateHTML(envelope, 'fleet')}
      </div>
    `;
  }
  const projects = Array.isArray(fleetSummary?.projects)
    ? fleetSummary.projects
    : [];
  const groups = groupByProject(items, projects);
  const sections = groups.map((g) => renderProjectSectionHTML(g)).join('');
  return `
    <div class="wn-layout wn-layout--fleet">
      ${headerHTML}
      <section class="panel wn-header-panel">
        <div class="wn-header-row">
          <h2>Needs Attention — All Projects</h2>
          <div class="wn-header-scope">${renderScopeBadgeHTML('fleet')}</div>
          <div class="wn-header-meta">${renderMetaHTML(envelope)}</div>
        </div>
        <div class="wn-summary-strip">${renderSummaryStripHTML(items)}</div>
      </section>
      ${sections}
      ${buildWhatNowProvenance(envelope, { fleet: true })}
    </div>
  `;
}

function renderProjectSectionHTML(group) {
  const bandBadge = getBandBadge(group.health_band);
  const scope = group.name === '__global__' ? 'global' : 'project';
  return `
    <section class="panel wn-project-panel wn-project-panel--${esc(bandBadge.color)}"
             data-project="${esc(group.name)}">
      <div class="wn-project-header">
        <h3 class="wn-project-title">${esc(group.display_name)}</h3>
        <span class="wn-project-band wn-project-band--${esc(bandBadge.color)}">${esc(bandBadge.label)}</span>
        <span class="wn-project-scope">${renderScopeBadgeHTML(scope)}</span>
        <span class="wn-project-count">${esc(String(group.items.length))} item${group.items.length === 1 ? '' : 's'}</span>
      </div>
      <div class="wn-cards">${group.items.map(renderActionCardHTML).join('')}</div>
    </section>
  `;
}

/**
 * Render the project view — filtered ActionItems for the selected
 * project, plus globally-relevant blockers (doctor/install/reconcile,
 * declared capabilities, adapter-category matches).
 *
 * The fleet summary entry for ``selectedProject`` carries the project's
 * typed capability/adapter declarations; the fleet what-now envelope
 * carries a ``capability_categories`` map. When both are present this
 * call mirrors :func:`dashboard_relevance.is_item_relevant_to_project`
 * exactly.
 *
 * @param {object} envelope normalized fleet-what-now envelope
 * @param {object} fleetSummary normalized fleet summary
 * @param {string} selectedProject project ``name``
 * @param {object} [opts]
 * @param {Set<string>|Array<string>} [opts.requiredCapabilityIds]
 * @param {Set<string>|Array<string>} [opts.referencedAdapterCategories]
 * @param {Record<string,string>} [opts.capabilityCategories]
 * @param {Date|number} [opts.now]
 */
export function renderProjectWhatNowHTML(envelope, fleetSummary, selectedProject, opts = {}) {
  if (envelope == null) return renderMissingStateHTML('project');
  // If the caller didn't supply declarations, pull them out of the fleet
  // summary entry for the selected project. This is how the dashboard
  // shell normally calls us — the Python build persists declarations on
  // every fleet-summary project entry plus the fleet what-now envelope.
  const fleetEntry = Array.isArray(fleetSummary?.projects)
    ? fleetSummary.projects.find((p) => p?.name === selectedProject)
    : null;
  const requiredCapabilityIds = opts.requiredCapabilityIds
    || (Array.isArray(fleetEntry?.required_capability_ids)
      ? fleetEntry.required_capability_ids
      : []);
  const referencedAdapterCategories = opts.referencedAdapterCategories
    || (Array.isArray(fleetEntry?.referenced_adapter_categories)
      ? fleetEntry.referenced_adapter_categories
      : []);
  const capabilityCategories = opts.capabilityCategories
    || (envelope.capability_categories && typeof envelope.capability_categories === 'object'
      ? envelope.capability_categories
      : {});
  const filterOpts = {
    requiredCapabilityIds,
    referencedAdapterCategories,
    capabilityCategories,
  };
  const items = Array.isArray(envelope.items) ? envelope.items : [];
  const filtered = filterItemsForProject(items, selectedProject, filterOpts);
  const header = buildStatusHeader({
    envelope: { ...envelope, items: filtered },
    fleetSummary,
    selected: selectedProject,
    now: opts.now,
  });
  const headerHTML = renderStatusHeaderHTML(header);
  if (filtered.length === 0) {
    return `
      <div class="wn-layout wn-layout--project">
        ${headerHTML}
        ${renderQuietStateHTML(envelope, 'project', { fleetSource: true })}
      </div>
    `;
  }
  // Reuse the existing populated renderer with a fabricated single-band
  // payload — keep the per-card markup identical to legacy what-now. The
  // populated renderer attaches its own pv-footer using the single-repo
  // source path; the fleet-scoped header chip already carries fleet
  // context, so we don't double up here.
  const fabricatedEnvelope = {
    schema_version: envelope.schema_version,
    captured_at: envelope.captured_at,
    items: filtered,
  };
  return `
    <div class="wn-layout wn-layout--project">
      ${headerHTML}
      ${renderPopulatedHTML(fabricatedEnvelope, 'project', { fleetSource: true })}
    </div>
  `;
}
