// F006 — operator console, default view (workbench left pane + top bar).
//
// Pure logic + render over the F001 triage MODEL (operator_triage.build_triage
// serialization). The console READS the model; it never re-derives buckets — one
// model, many renderers. The default view shows ALL unique live needs_auth +
// needs_decision items (with uncertain riding alongside, per D017), a one-line
// status, and collapses the non-human buckets to counts. No raw JSON; no cap.

import { esc } from './html-escape.js';
import { renderSectionHeaderHTML, renderCardHTML, renderCopyCommandHTML } from './components.js';

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
      actor: i.actor_label || null,
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

/** The run-state chip with actor (F010 parallel-ops). Empty when idle. The
 * conflicted state (>1 supervisor on the same plan) gets its own styling so two
 * agents racing the same plan is visible at a glance. */
export function renderRunChipHTML(runState, actor) {
  if (!runState || runState === 'idle') return '';
  const who = actor ? ` · ${esc(actor)}` : '';
  return `<span class="run-state run-state--${esc(runState)}">${esc(runState)}${who}</span>`;
}

function _needsYouItemHTML(item) {
  const chip = `<span class="scope-chip">${esc(item.scope)}</span>`;
  const conflicted = item.runState === 'conflicted' ? ' is-conflicted' : '';
  // data-item-id makes the row selectable (F007 inspect pane reads it).
  const body = `<div class="console-item-line console-item-select${conflicted}" data-item-id="${esc(item.id || '')}">` +
    `${chip} ${esc(item.bucket)} ${renderRunChipHTML(item.runState, item.actor)}` +
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
    actor: item.actor_label || null,
    duplicateCount: item.duplicate_count || 1,
  };
}

/** The decision drawer: what / why-now / evidence / the one move. In Operator
 * mode it carries the copy/handoff affordances (F008) + the mark-as-run control
 * (F009); in Observer mode it's pure-read. */
export function renderInspectHTML(detail, opts = {}) {
  if (!detail) {
    return `<div class="console-inspect console-inspect--empty">Select an item to see why it needs you and the evidence for the next move.</div>`;
  }
  const mode = opts.mode || OPERATOR;
  const markedRun = opts.markedRun || [];
  const rows = [];
  rows.push(`<div class="inspect-title">${esc(detail.title)}</div>`);
  const runChip = renderRunChipHTML(detail.runState, detail.actor);
  rows.push(`<div class="inspect-meta"><span class="scope-chip">${esc(detail.scope)}</span> ${esc(detail.bucket)}` +
    (runChip ? ` · ${runChip}` : '') +
    (detail.duplicateCount > 1 ? ` · ${esc(String(detail.duplicateCount))}× collapsed` : '') + `</div>`);
  if (detail.whyNow) rows.push(`<div class="inspect-why"><span class="inspect-label">Why now</span> ${esc(detail.whyNow)}</div>`);
  if (detail.evidence) rows.push(`<div class="inspect-evidence"><span class="inspect-label">Evidence</span> <code>${esc(detail.evidence)}</code></div>`);
  if (detail.move) rows.push(`<div class="inspect-move"><span class="inspect-label">The move</span> <code>${esc(detail.move)}</code></div>`);

  let tail = '';
  if (mode === OPERATOR) {
    tail += renderAffordancesHTML(deriveAffordances(detail));
    tail += markedRun.includes(detail.id)
      ? `<div class="mark-run mark-run--done">✓ Marked as run — clears on the next refresh if it resolved.</div>`
      : `<button type="button" class="btn mark-run-btn" data-mark-run="${esc(detail.id || '')}">Mark as run</button>`;
  } else {
    tail += `<div class="observer-note">Observer mode — switch to Operator to copy the command.</div>`;
  }
  return `<div class="console-inspect">${rows.join('')}${tail}</div>`;
}

// ── F008 — per-bucket handoff affordances ──
// COPY/OPEN/HANDOFF only — never execute (D018). The GUI hands the operator (or
// their agent) the exact command; running it stays in the human's terminal / the
// agent's loop. Built on the read-only renderCopyCommandHTML contract the Repair
// page already drives (.copy-cmd-btn → clipboard, no state mutation).

// Bucket-aware label for the primary copy action. The COMMAND is the model's
// exact_command verbatim — F008 labels, it does not re-derive the command.
const _PRIMARY_LABEL = {
  needs_auth: 'Copy setup command',
  needs_decision: 'Copy approve command',
  agent_runnable: 'Copy command for an agent',
  auto_safe: 'Copy safe-apply command',
  uncertain: 'Copy command',
};

/** The handoff affordance set for an inspect detail. Pure; no DOM. */
export function deriveAffordances(detail) {
  if (!detail) return { primary: null, evidence: null, handoff: null };
  const primary = detail.move
    ? { label: _PRIMARY_LABEL[detail.bucket] || 'Copy command', command: detail.move }
    : null;
  const evidence = detail.evidence
    ? { label: 'Copy evidence path', command: detail.evidence }
    : null;
  // A paste-into-agent block: full context so a Claude/Codex/Cursor session can act.
  const handoffLines = [detail.title || detail.id];
  if (detail.whyNow) handoffLines.push(`Why: ${detail.whyNow}`);
  if (detail.evidence) handoffLines.push(`Evidence: ${detail.evidence}`);
  if (detail.move) handoffLines.push(`Run: ${detail.move}`);
  const handoff = { label: 'Copy handoff for an agent', text: handoffLines.join('\n') };
  return { primary, evidence, handoff };
}

export function renderAffordancesHTML(aff) {
  if (!aff || (!aff.primary && !aff.handoff)) return '';
  const parts = [];
  if (aff.primary) parts.push(renderCopyCommandHTML(aff.primary.command, { label: aff.primary.label }));
  if (aff.evidence) parts.push(renderCopyCommandHTML(aff.evidence.command, { label: aff.evidence.label }));
  if (aff.handoff) parts.push(renderCopyCommandHTML(aff.handoff.text, { label: aff.handoff.label, ariaLabel: 'Copy the full handoff context for an agent' }));
  parts.push(`<div class="affordances-note">Copying never runs anything — DontPanic hands you (or your agent) the command.</div>`);
  return `<div class="console-affordances">${parts.join('')}</div>`;
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

// ── F009 — lifecycle & refresh (Observer↔Operator, mark-run, state_revision) ──
// The console + a CLI/terminal/agent operate the same install concurrently. F009
// keeps the GUI honest about that: a mode toggle (Observer is pure-read), a local
// mark-as-run overlay (the GUI doesn't execute — the human runs the copied
// command elsewhere and marks it), and a refresh that uses the model's
// state_revision fingerprint to detect when the producer state moved underneath.

export const OBSERVER = 'observer';
export const OPERATOR = 'operator';

/** True when the model's fingerprint differs from the last one shown — i.e. the
 * producer state changed under us (another process rebuilt it). False on first
 * load (no prior revision to compare). */
export function revisionChanged(model, lastRevision) {
  if (!lastRevision) return false;
  return !!(model && model.state_revision) && model.state_revision !== lastRevision;
}

/** Reconcile the local mark-as-run overlay against a freshly-loaded model: ids
 * still present in the model are stillPresent (action not yet reflected); ids
 * gone are resolved (the producer cleared them — drop the mark). */
export function reconcileMarkedRun(markedRunIds, model) {
  const present = new Set((model && Array.isArray(model.items) ? model.items : []).map((i) => i.id));
  const stillPresent = [];
  const resolved = [];
  for (const id of markedRunIds || []) (present.has(id) ? stillPresent : resolved).push(id);
  return { stillPresent, resolved };
}

export function renderModeToggleHTML(mode) {
  const active = mode === OBSERVER ? OBSERVER : OPERATOR;
  const btn = (m, label) =>
    `<button type="button" class="mode-toggle-btn${active === m ? ' is-active' : ''}" ` +
    `data-mode="${m}" aria-pressed="${active === m}">${esc(label)}</button>`;
  return `<div class="mode-toggle" role="group" aria-label="Console mode">${btn(OBSERVER, 'Observe')}${btn(OPERATOR, 'Operate')}</div>`;
}

export function renderRefreshHTML(view) {
  const changed = view && view.revisionChanged;
  const note = changed
    ? `<span class="refresh-note refresh-note--changed">State changed — refresh to resync</span>`
    : '';
  return `<div class="console-refresh">${note}<button type="button" class="btn refresh-btn">Refresh</button></div>`;
}

// ── F010 — parallel-ops awareness ──
// The console, a CLI, and one or more agents operate the same install at once.
// The model already derives run_state (idle/running/conflicted, by joining each
// item's plan to the live active-supervisors registry) + actor_label. F010 makes
// concurrency visible: who's working what, and where two actors race one plan
// (conflicted). Derived read-only; no claim/lease is written (D023).

/** Project the model into the running / conflicted sets with their actors. */
export function deriveParallelOps(model) {
  const items = (model && Array.isArray(model.items) ? model.items : []);
  const pick = (i) => ({ id: i.id, actor: i.actor_label || null, scope: _SCOPE_LABEL(i), bucket: i.operator_bucket });
  const running = items.filter((i) => i.run_state === 'running').map(pick);
  const conflicted = items.filter((i) => i.run_state === 'conflicted').map(pick);
  return { running, conflicted, counts: { running: running.length, conflicted: conflicted.length } };
}

/** Ambient banner: "N running · M conflicted" with actors. Empty when the install
 * is quiet (nothing running) — concurrency cues only appear when they're real. */
export function renderParallelOpsBannerHTML(ops) {
  if (!ops || (ops.counts.running === 0 && ops.counts.conflicted === 0)) return '';
  const cls = ops.counts.conflicted > 0 ? 'parallel-ops parallel-ops--conflicted' : 'parallel-ops';
  const parts = [
    `<span class="parallel-ops-summary">${esc(String(ops.counts.running))} running` +
    (ops.counts.conflicted > 0 ? ` · ${esc(String(ops.counts.conflicted))} conflicted` : '') + `</span>`,
  ];
  if (ops.counts.conflicted > 0) {
    const who = ops.conflicted.map((c) => esc(c.actor || c.id)).join(', ');
    parts.push(`<span class="parallel-ops-warn">⚠ two actors on one plan: ${who}</span>`);
  }
  const actors = ops.running.filter((r) => r.actor).map((r) => esc(r.actor));
  if (actors.length) parts.push(`<span class="parallel-ops-actors">${actors.join(' · ')}</span>`);
  return `<div class="${cls}" role="status">${parts.join('')}</div>`;
}
