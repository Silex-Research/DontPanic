/*
 * The ActionItem atom — comfort card + dense row + the "you're clear" empty state
 * (plan 2026-06-06-004 F003, spec §2.4/§3). One model, two densities: the card and the
 * row render the SAME operator-triage/v0 fields; only spacing/wrapping differ (driven by
 * data-density). Agent parity: every visual element maps to a real field — no UI-only state.
 * Resolution affordances replace copy-command-as-primary: the face shows resolution[] as
 * intents; the literal exact_command is revealed only on inspect (§3.3), never the face.
 */

export const BUCKET_LABELS = Object.freeze({
  needs_auth: 'Needs Auth',
  needs_decision: 'Needs Decision',
  agent_runnable: 'Agent-Runnable',
  auto_safe: 'Auto-Safe',
  uncertain: 'Uncertain',
  quiet: 'Quiet',
});

// resolution INTENT → human label. The renderer maps intents to affordances; it does NOT
// infer executability from the strings (the governed action layer owns that — see F005).
export const RESOLUTION_LABELS = Object.freeze({
  approve: 'Approve',
  request_changes: 'Request changes',
  reject: 'Reject',
  run: 'Run',
  apply_fix: 'Apply fix',
  guided_setup: 'Guided setup',
  inspect: 'Inspect',
});

export const SCOPE_LABELS = Object.freeze({ project: 'Project', global: 'Install-level' });

function bucketClass(bucket) {
  return `dp-bucket-${String(bucket).replace(/_/g, '-')}`;
}

/* Render-truth dot (§2.2): FILLED only when item-level freshness is proven
   (freshness_basis === "item_probe"); otherwise a hollow ring. F007 extends the grammar
   (aging/stale desaturation); F003 keeps the honest filled-vs-hollow distinction. */
export function freshnessState(item) {
  return item && item.freshness_basis === 'item_probe' ? 'proven' : 'unproven';
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function freshnessDot(item) {
  const state = freshnessState(item);
  const dot = el('span', `dp-freshness dp-freshness--${state}`);
  dot.dataset.freshness = state;
  // honest label: a proven item shows its age; an unproven one says so outright
  dot.title = state === 'proven'
    ? `proven live · ${item.asserted_at || 'recently'}`
    : 'unverified — asserted, not proven live';
  dot.setAttribute('aria-label', dot.title);
  return dot;
}

function resolutionBar(item) {
  const bar = el('div', 'dp-resolutions');
  const intents = Array.isArray(item.resolution) ? item.resolution : [];
  for (const intent of intents) {
    const btn = el('button', 'dp-affordance', RESOLUTION_LABELS[intent] || intent);
    btn.type = 'button';
    btn.dataset.resolution = intent;          // parity: button ⟵ a resolution[] entry
    btn.dataset.itemId = item.id ?? '';
    bar.appendChild(btn);
  }
  return bar;
}

function scopeChip(item) {
  // In single-project frames the chip is suppressed (§4); the caller passes showScope=false.
  // Parity (§4/§7): a project chip names the real project_name so fleet items are distinguishable;
  // global carries the install-level label.
  const label = item.scope === 'global' ? SCOPE_LABELS.global : (item.project_name || SCOPE_LABELS.project);
  const chip = el('span', `dp-scope-chip dp-scope-chip--${item.scope || 'global'}`, label);
  return chip;
}

function metaLine(item, { showScope }) {
  const meta = el('div', 'dp-item-meta');
  meta.appendChild(freshnessDot(item));
  if (item.actor_label) meta.appendChild(el('span', 'dp-actor', item.actor_label));
  if (showScope && (item.project_name || item.scope === 'global')) meta.appendChild(scopeChip(item));
  if (item.duplicate_count > 1) meta.appendChild(el('span', 'dp-dupes', `asserted by ${item.duplicate_count}`));
  return meta;
}

function baseItem(item, { density, showScope }) {
  const root = el('article', `dp-item dp-item--${density} ${bucketClass(item.operator_bucket)}`);
  root.dataset.bucket = item.operator_bucket ?? '';
  root.dataset.scope = item.scope ?? '';
  root.dataset.runState = item.run_state ?? '';
  if (item.id != null) root.dataset.itemId = item.id;
  root.appendChild(el('span', 'dp-scope-accent'));   // 3px left bar, colour from --scope-*
  return root;
}

/** Comfort card (§2.4 left) — title, why-now, meta, resolution affordances. */
export function renderCard(item, opts = {}) {
  const showScope = opts.showScope !== false;
  const root = baseItem(item, { density: 'card', showScope });
  const body = el('div', 'dp-item-body');
  body.appendChild(el('h3', 'dp-item-title', item.title || '(untitled)'));
  if (item.why_now) body.appendChild(el('p', 'dp-item-why', item.why_now));
  // Plan 2026-08-09-002 F008 — dashboard is the unabridged brief surface.
  if (item.what_changes) {
    body.appendChild(el('p', 'dp-item-what', item.what_changes));
  }
  if (item.user_impact) {
    body.appendChild(el('p', 'dp-item-impact', item.user_impact));
  }
  if (item.plain_consequence) {
    body.appendChild(el('p', 'dp-item-consequence', item.plain_consequence));
  }
  body.appendChild(metaLine(item, { showScope }));
  body.appendChild(resolutionBar(item));
  root.appendChild(body);
  return root;
}

/** Dense row (§2.4 right) — same fields, one compact line + inline actions. */
export function renderRow(item, opts = {}) {
  const showScope = opts.showScope !== false;
  const root = baseItem(item, { density: 'row', showScope });
  const body = el('div', 'dp-item-body');
  const head = el('div', 'dp-item-head');
  head.appendChild(freshnessDot(item));
  head.appendChild(el('span', 'dp-item-title', item.title || '(untitled)'));
  body.appendChild(head);
  body.appendChild(metaLine(item, { showScope }));
  body.appendChild(resolutionBar(item));
  root.appendChild(body);
  return root;
}

/** Density-aware single entry point (§8 toggle): comfort → card, dense → row. */
export function renderItem(item, opts = {}) {
  return (opts.density || 'comfort') === 'dense' ? renderRow(item, opts) : renderCard(item, opts);
}

/**
 * The "you're clear" payoff (§2.5) — not "No items" (which reads as broken). One calm line
 * of reassurance plus the proof (monitored signal count + freshness).
 */
export function renderEmptyState({ signals = 0, projects = 0, lastRefresh = null } = {}) {
  const root = el('div', 'dp-clear');
  root.appendChild(el('div', 'dp-clear-mark', '◔'));
  root.appendChild(el('div', 'dp-clear-head', "You're clear."));
  root.appendChild(el('div', 'dp-clear-sub', 'No decisions. No approvals. No blocked runs.'));
  root.appendChild(el('div', 'dp-clear-proof',
    `${signals} monitored signals across ${projects} projects — all healthy.`));
  const fresh = el('div', 'dp-clear-fresh');
  fresh.appendChild(el('span', null, `Last full refresh · ${lastRefresh || 'just now'} `));
  fresh.appendChild(freshnessDot({ freshness_basis: 'item_probe', asserted_at: lastRefresh }));
  root.appendChild(fresh);
  return root;
}
