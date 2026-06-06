// Plan 2026-06-05-003 F001 — shared component render helpers.
//
// The ONE way to build a button / copy-command / card / stat / banner / etc. Pages
// compose these instead of hand-rolling markup (docs/dashboard-design-system.md §4).
// Pure: every helper returns an escaped HTML string. The copy-command emits the real
// read-only-console affordance — a "Copy …" button (data-copy) + an aria-live feedback
// element the shared copy handler toggles to "Copied ✓" / a failure hint.

import { esc } from './html-escape.js';

/** A real button. variant ∈ {primary, secondary, ghost}. */
export function renderButtonHTML(label, { variant = 'secondary', attrs = '' } = {}) {
  const cls = variant === 'secondary' ? 'btn' : `btn btn--${esc(variant)}`;
  return `<button type="button" class="${cls}" ${attrs}>${esc(label)}</button>`;
}

/**
 * The canonical read-only action: copies `command` to the clipboard. The visible label
 * MUST start with "Copy" (honesty); success/failure feedback is a live region.
 */
export function renderCopyCommandHTML(command, { label = 'Copy command', ariaLabel = '' } = {}) {
  const aria = ariaLabel || `Copy the command: ${command}`;
  return (
    `<div class="copy-cmd">` +
    `<code class="copy-cmd-code">${esc(command)}</code>` +
    `<button type="button" class="btn copy-cmd-btn" data-copy="${esc(command)}" ` +
    `aria-label="${esc(aria)}">${esc(label)}</button>` +
    `<span class="copy-cmd-feedback" role="status" aria-live="polite"></span>` +
    `</div>`
  );
}

/** A status-accented card. status ∈ {ok, attention, blocked, info, muted}. */
export function renderCardHTML({ title, impact = '', status = 'muted', body = '' } = {}) {
  const cls = status && status !== 'muted' ? `card card--${esc(status)}` : 'card';
  const impactHTML = impact ? `<div class="card-impact">${esc(impact)}</div>` : '';
  return `<div class="${cls}"><div class="card-title">${esc(title)}</div>${impactHTML}${body}</div>`;
}

/** One metric tile. status tints the number. */
export function renderStatTileHTML(value, label, { status = '' } = {}) {
  const cls = status ? `stat stat--${esc(status)}` : 'stat';
  return `<div class="${cls}"><div class="stat-value">${esc(String(value))}</div><div class="stat-label">${esc(label)}</div></div>`;
}

/** A row of stat tiles. `tiles` = [{value,label,status?}]. */
export function renderStatStripHTML(tiles) {
  const inner = (tiles || []).map((t) => renderStatTileHTML(t.value, t.label, { status: t.status })).join('');
  return `<div class="stat-strip">${inner}</div>`;
}

export function renderSectionHeaderHTML(title, { count = '' } = {}) {
  const countHTML = count !== '' && count != null ? `<span class="section-header-count">${esc(String(count))}</span>` : '';
  return `<div class="section-header"><span class="section-header-title">${esc(title)}</span>${countHTML}</div>`;
}

/** A page-level notice. kind ∈ {info, warn, error}. */
export function renderBannerHTML(message, { kind = 'info' } = {}) {
  return `<div class="banner banner--${esc(kind)}">${esc(message)}</div>`;
}

/** A loading placeholder (one bar per `rows`). */
export function renderSkeletonHTML(rows = 3) {
  return Array.from({ length: Math.max(1, rows) }, () => `<div class="skeleton"></div>`).join('');
}
