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
  };
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
 * @param {unknown} raw
 * @returns {string}
 */
export function renderWhatNowHTML(raw) {
  const envelope = normalizeEnvelope(raw);
  if (envelope == null) {
    return renderMissingStateHTML();
  }
  // Quiet state only when there is literally nothing to surface. Advisory
  // and info items must render as cards so their exact commands stay
  // visible/copyable (F004 acceptance #3) — band colors handle restraint.
  if (envelope.items.length === 0) {
    return renderQuietStateHTML(envelope);
  }
  return renderPopulatedHTML(envelope);
}

/**
 * Missing-cache empty-state. Non-alarming wording: F004 acceptance (4)
 * says stale/missing optional data must not render as a blocker.
 */
export function renderMissingStateHTML() {
  return `
    <div class="wn-empty-state" data-state="missing">
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
    </div>
  `;
}

/**
 * Quiet healthy state — rendered when the envelope is present but no
 * item is in the `needs_action` band. F004 acceptance (4): restrained
 * when no action is needed.
 */
export function renderQuietStateHTML(envelope) {
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
      <div class="wn-quiet-title">No action needed</div>
      <div class="wn-quiet-body">
        Gates are clear, capabilities are ready or optional, reconcile is
        clean, and no supervisor is flagged.
        ${esc(sublines)}
      </div>
      <div class="wn-quiet-meta">
        ${renderMetaHTML(envelope)}
      </div>
    </div>
  `;
}

function renderPopulatedHTML(envelope) {
  const groups = groupByBand(envelope.items);
  return `
    <div class="wn-layout">
      <section class="panel wn-header-panel">
        <div class="wn-header-row">
          <h2>What Now</h2>
          <div class="wn-header-meta">${renderMetaHTML(envelope)}</div>
        </div>
        <div class="wn-summary-strip">${renderSummaryStripHTML(envelope.items)}</div>
      </section>
      ${groups.map(renderBandSectionHTML).join('')}
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

function renderBandSectionHTML(group) {
  const badge = getBandBadge(group.band);
  return `
    <section class="panel wn-band-panel wn-band-panel--${esc(badge.color)}" data-band="${esc(group.band)}">
      <div class="wn-band-header">
        <span class="wn-band-badge wn-band-badge--${esc(badge.color)}">${esc(badge.label)}</span>
        <span class="wn-band-count">${esc(String(group.items.length))} item${group.items.length === 1 ? '' : 's'}</span>
      </div>
      <div class="wn-cards">${group.items.map(renderActionCardHTML).join('')}</div>
    </section>
  `;
}

function renderActionCardHTML(item) {
  const badge = getBandBadge(item.band);
  const sourceLabel = getSourceLabel(item.source);
  return `
    <article class="wn-card wn-card--${esc(badge.color)}"
             data-action-id="${esc(item.id)}"
             data-source="${esc(item.source)}"
             data-band="${esc(item.band)}">
      <header class="wn-card-header">
        <span class="wn-source-chip wn-source-chip--${esc(item.source)}">${esc(sourceLabel)}</span>
        <span class="wn-card-title">${esc(item.title)}</span>
        ${renderRoleChipHTML(item)}
      </header>
      ${item.detail ? `<div class="wn-card-detail">${esc(item.detail)}</div>` : ''}
      ${renderCommandHTML(item.exact_command)}
      ${renderEvidenceHTML(item.evidence_uri)}
      <footer class="wn-card-footer">
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
