// ── Provenance Footer — Shared per-page source/timestamp treatment ──
// F004 of plan 2026-05-24-001-feat-dashboard-value-language-ia-v0.
//
// Every V0 page must declare where its data came from and when. The footer
// is intentionally Layer-2: it lives below the page's value-first content
// and never dominates the first read. The contract is:
//
//   Source: <state file path>
//   Updated: <captured/generated timestamp, or "—" when absent>
//   Refresh: <exact CLI command that rewrites the file>
//
// All exports are pure; the renderer returns an HTML string suitable for
// concatenation into a page innerHTML. The footer uses a single `pv-*`
// class namespace so it can be styled or scoped from CSS without colliding
// with the page-specific prefixes (`wn-*`, `cap-*`, `hlth-*`, `stg-*`).

import { esc } from './html-escape.js';

/**
 * Build the canonical provenance footer HTML for a V0 page region.
 *
 * @param {object} args
 * @param {string} args.source        State file path or descriptive source label
 *                                    (e.g. `dashboard/state/what-now.json`,
 *                                    `localStorage`).
 * @param {string|null|undefined} [args.lastUpdated]
 *                                    ISO timestamp or pre-formatted string.
 *                                    When absent we render "—" so the row
 *                                    keeps its shape rather than collapsing.
 * @param {string|null|undefined} [args.refreshCommand]
 *                                    Exact CLI command that regenerates the
 *                                    source. Optional — omit when the source
 *                                    is operator-edited (e.g. localStorage).
 * @param {string|null|undefined} [args.note]
 *                                    Optional short clarifier rendered as a
 *                                    plain sentence under the rows. Use for
 *                                    "this preference is browser-local" or
 *                                    similar honesty disclosures.
 * @returns {string} HTML string
 */
export function renderProvenanceFooterHTML({
  source,
  lastUpdated,
  refreshCommand,
  note,
} = {}) {
  const sourceText = typeof source === 'string' && source.length > 0
    ? source
    : '—';
  const updatedText = typeof lastUpdated === 'string' && lastUpdated.length > 0
    ? lastUpdated
    : '—';
  const refreshLine = typeof refreshCommand === 'string' && refreshCommand.length > 0
    ? `<div class="pv-row pv-row--refresh"><span class="pv-label">Refresh</span><code class="pv-cmd">${esc(refreshCommand)}</code></div>`
    : '';
  const noteLine = typeof note === 'string' && note.length > 0
    ? `<div class="pv-note">${esc(note)}</div>`
    : '';
  return `
    <div class="pv-footer" data-provenance="1">
      <div class="pv-row pv-row--source"><span class="pv-label">Source</span><code class="pv-value">${esc(sourceText)}</code></div>
      <div class="pv-row pv-row--updated"><span class="pv-label">Updated</span><span class="pv-value">${esc(updatedText)}</span></div>
      ${refreshLine}
      ${noteLine}
    </div>
  `;
}

/**
 * True iff the rendered fragment looks like a provenance footer (used by
 * snapshot tests asserting that every V0 page region has one).
 *
 * @param {string} html
 * @returns {boolean}
 */
export function hasProvenanceFooter(html) {
  if (typeof html !== 'string') return false;
  return /data-provenance="1"/.test(html);
}
