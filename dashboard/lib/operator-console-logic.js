// F006 — operator console, default view (workbench left pane + top bar).
//
// Pure logic + render over the F001 triage MODEL (operator_triage.build_triage
// serialization). The console READS the model; it never re-derives buckets — one
// model, many renderers. The default view shows ALL unique live needs_auth +
// needs_decision items (with uncertain riding alongside, per D017), a one-line
// status, and collapses the non-human buckets to counts. No raw JSON; no cap.

import { esc } from './html-escape.js';
import { renderSectionHeaderHTML, renderCardHTML } from './components.js';

// Buckets the human must see. uncertain rides WITH needs-you (the honesty bucket,
// never buried — D017).
export const NEEDS_YOU_BUCKETS = ['needs_auth', 'needs_decision', 'uncertain'];

const _SCOPE_LABEL = (item) =>
  item.scope === 'project' && item.project_name ? item.project_name : 'global';

/** Project the F001 model into the default-view shape. Pure; no DOM. */
export function deriveConsoleView(model) {
  const items = (model && Array.isArray(model.items) ? model.items : []);
  const dq = (model && model.data_quality) || {};
  const counts = dq.counts || {};

  const needsYou = items
    .filter((i) => NEEDS_YOU_BUCKETS.includes(i.operator_bucket))
    .map((i) => ({
      id: i.id,
      bucket: i.operator_bucket,
      scope: _SCOPE_LABEL(i),
      command: i.exact_command || '',
      runState: i.run_state || 'idle',
    }));

  const raw = dq.input_count != null ? dq.input_count : (dq.total != null ? dq.total : items.length);
  const unique = dq.total != null ? dq.total : items.length;

  return {
    statusLine: { raw, unique, needsYou: needsYou.length },
    healthy: needsYou.length === 0,
    needsYou, // ALL of them — never capped
    handled: {
      agent_runnable: counts.agent_runnable || 0,
      auto_safe: counts.auto_safe || 0,
      quiet: counts.quiet || 0,
    },
    stateRevision: (model && model.state_revision) || null,
  };
}

function _statusBarHTML(view) {
  const s = view.statusLine;
  const verdict = view.healthy ? 'Install healthy' : `${s.needsYou} need you`;
  return (
    `<div class="console-statusbar">` +
    `<span class="console-verdict">${esc(verdict)}</span>` +
    `<span class="console-pipeline">${esc(String(s.raw))} raw → ${esc(String(s.unique))} unique → ${esc(String(s.needsYou))} need you</span>` +
    `</div>`
  );
}

function _needsYouItemHTML(item) {
  const chip = `<span class="scope-chip">${esc(item.scope)}</span>`;
  const running = item.runState && item.runState !== 'idle'
    ? `<span class="run-state run-state--${esc(item.runState)}">${esc(item.runState)}</span>`
    : '';
  // data-item-id makes the row selectable (F007 inspect pane reads it).
  const body = `<div class="console-item-line console-item-select" data-item-id="${esc(item.id || '')}">` +
    `${chip} ${esc(item.bucket)} ${running}` +
    (item.command ? `<div class="console-item-move">${esc(item.command)}</div>` : '') +
    `</div>`;
  return renderCardHTML({ title: '', status: 'attention', body });
}

/** The default-view HTML: top status bar + the needs-you queue + a collapsed
 * 'handled' line. No raw JSON. */
export function renderConsoleDefaultHTML(view) {
  const parts = [_statusBarHTML(view)];

  parts.push(renderSectionHeaderHTML('Needs you', { count: view.needsYou.length }));
  if (view.needsYou.length === 0) {
    parts.push(`<div class="console-empty">✓ Nothing needs you — everything is handled.</div>`);
  } else {
    parts.push(`<div class="console-needs-you">${view.needsYou.map(_needsYouItemHTML).join('')}</div>`);
  }

  const h = view.handled;
  parts.push(
    `<div class="console-handled">` +
    `${esc(String(h.agent_runnable))} an agent can run · ` +
    `${esc(String(h.auto_safe))} auto-safe · ` +
    `${esc(String(h.quiet))} quiet — handled, not shown` +
    `</div>`
  );
  return `<div class="operator-console">${parts.join('')}</div>`;
}

// ── F007 — inspect surfaces (workbench right pane + activity strip) ──
// The decision drawer (decide from evidence in place), the why-hidden inspector
// (audit the compression), and the activity strip (one evidence source). All
// read the F001 model; render evidence, execute nothing.

// Human-readable reason an item is NOT in the needs-you queue (why-hidden, H6).
const _HIDDEN_REASON = {
  agent_runnable: 'an agent can run it — a command resolves it, no human judgment',
  auto_safe: 'DontPanic can apply it — reversible derived-state',
  quiet: 'info / advisory — not an action',
};

function _whyNowFor(item) {
  if (item.why_now) return item.why_now;
  if (item.bucket === 'needs_decision') return 'A human must judge this before it clears.';
  if (item.bucket === 'needs_auth') return 'Requires your credentials — only you can complete it.';
  if (item.bucket === 'uncertain') return 'Could not be classified confidently — review before acting.';
  return '';
}

/** The right-pane detail for the selected item. null when nothing is selected. */
export function deriveInspectView(model, selectedId) {
  const items = (model && Array.isArray(model.items) ? model.items : []);
  const item = items.find((i) => i.id === selectedId);
  if (!item) return null;
  return {
    id: item.id,
    title: item.title || item.id,
    bucket: item.operator_bucket,
    scope: item.scope === 'project' && item.project_name ? item.project_name : 'global',
    whyNow: _whyNowFor({ bucket: item.operator_bucket, why_now: item.why_now }),
    move: item.exact_command || '',
    evidence: item.evidence_uri || null,
    runState: item.run_state || 'idle',
    duplicateCount: item.duplicate_count || 1,
  };
}

/** The decision drawer: what / why-now / evidence / the one move. Read-only —
 * F008 adds the copy/open affordances; F007 only surfaces the context (H3). */
export function renderInspectHTML(detail) {
  if (!detail) {
    return `<div class="console-inspect console-inspect--empty">Select an item to see why it needs you and the evidence for the next move.</div>`;
  }
  const rows = [];
  rows.push(`<div class="inspect-title">${esc(detail.title)}</div>`);
  rows.push(`<div class="inspect-meta"><span class="scope-chip">${esc(detail.scope)}</span> ${esc(detail.bucket)}` +
    (detail.runState !== 'idle' ? ` · <span class="run-state run-state--${esc(detail.runState)}">${esc(detail.runState)}</span>` : '') +
    (detail.duplicateCount > 1 ? ` · ${esc(String(detail.duplicateCount))}× collapsed` : '') + `</div>`);
  if (detail.whyNow) rows.push(`<div class="inspect-why"><span class="inspect-label">Why now</span> ${esc(detail.whyNow)}</div>`);
  if (detail.evidence) rows.push(`<div class="inspect-evidence"><span class="inspect-label">Evidence</span> <code>${esc(detail.evidence)}</code></div>`);
  if (detail.move) rows.push(`<div class="inspect-move"><span class="inspect-label">The move</span> <code>${esc(detail.move)}</code></div>`);
  return `<div class="console-inspect">${rows.join('')}</div>`;
}

/** Group every NON-human item by bucket with the reason it's hidden (H6). The
 * compression is auditable: nothing silently dropped. */
export function deriveWhyHidden(model) {
  const items = (model && Array.isArray(model.items) ? model.items : []);
  const groups = {};
  for (const i of items) {
    const b = i.operator_bucket;
    if (b === 'needs_auth' || b === 'needs_decision' || b === 'uncertain') continue; // shown in the queue
    if (!groups[b]) groups[b] = { bucket: b, reason: _HIDDEN_REASON[b] || 'handled', items: [] };
    groups[b].items.push({ id: i.id, title: i.title || i.id, command: i.exact_command || '' });
  }
  return Object.values(groups);
}

export function renderWhyHiddenHTML(groups) {
  if (!groups || groups.length === 0) return `<div class="why-hidden why-hidden--empty">Nothing hidden.</div>`;
  const blocks = groups.map((g) =>
    `<div class="why-hidden-group">` +
    renderSectionHeaderHTML(g.bucket, { count: g.items.length }) +
    `<div class="why-hidden-reason">${esc(g.reason)}</div></div>`);
  return `<div class="why-hidden">${blocks.join('')}</div>`;
}

/** The activity strip: ONE evidence source rendered as ambient chrome — the
 * raw→unique→need-you pipeline line plus recent agent/auto actions (H2). */
export function renderActivityStripHTML(model, events) {
  const dq = (model && model.data_quality) || {};
  const raw = dq.input_count != null ? dq.input_count : (dq.total || 0);
  const unique = dq.total != null ? dq.total : 0;
  const counts = dq.counts || {};
  const needs = (counts.needs_auth || 0) + (counts.needs_decision || 0);
  const lines = [`<div class="activity-pipeline">${esc(String(raw))} → ${esc(String(unique))} unique → ${esc(String(needs))} need you</div>`];
  for (const ev of (Array.isArray(events) ? events : []).slice(0, 6)) {
    const when = ev && ev.when ? `${esc(String(ev.when))} ` : '';
    const what = ev && ev.summary ? esc(String(ev.summary)) : '';
    lines.push(`<div class="activity-row">${when}${what}</div>`);
  }
  return `<div class="console-activity">${lines.join('')}</div>`;
}
