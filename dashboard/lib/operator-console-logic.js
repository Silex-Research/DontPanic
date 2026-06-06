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
  const body = `<div class="console-item-line">${chip} ${esc(item.bucket)} ${running}` +
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
