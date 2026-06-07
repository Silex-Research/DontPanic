/*
 * Gate resolution flow (plan 2026-06-06-004 F005, spec §5.3). A gate is a needs_decision item
 * whose run_state is running (a volley paused mid-flight). The operator never hunts for which
 * run — the item carries it. Pure: resolveGate produces the confirm model; applyResolution
 * produces the post-state. The governed action layer (not the UI) owns execution.
 */

const PLAN_RE = /\b(\d{4}-\d{2}-\d{2}-\d{3}-[a-z0-9-]+)\b/;

export const APPROVAL_INTENTS = Object.freeze(['approve', 'request_changes', 'reject']);

const INTENT_LABELS = Object.freeze({
  approve: 'Approve',
  request_changes: 'Request changes',
  reject: 'Reject',
  run: 'Run',
  apply_fix: 'Apply fix',
  guided_setup: 'Guided setup',
  inspect: 'Inspect',
});

/** A human-readable reference to the run an approval unblocks (names it, never guesses a number). */
export function runRef(item) {
  const m = PLAN_RE.exec(String(item?.id || '')) || PLAN_RE.exec(String(item?.title || ''));
  const plan = m ? m[1] : null;
  const where = item?.project_name ? ` on ${item.project_name}` : '';
  return plan ? `${plan}${where}` : (item?.project_name ? `the run on ${item.project_name}` : 'the paused run');
}

/**
 * The confirm model for choosing `intent` on `item`. Throws if the intent isn't one this item
 * actually offers (the buttons == resolution[], §3.3) — no inventing actions.
 */
export function resolveGate(item, intent) {
  const offered = Array.isArray(item?.resolution) ? item.resolution : [];
  if (!offered.includes(intent)) throw new Error(`intent "${intent}" not offered by item ${item?.id}`);
  const isApproval = APPROVAL_INTENTS.includes(intent);
  const isLiveGate = isApproval && item.run_state === 'running';
  let confirm;
  if (intent === 'approve') confirm = `This will resume ${runRef(item)}.`;
  else if (intent === 'request_changes') confirm = `This will send ${runRef(item)} back for changes.`;
  else if (intent === 'reject') confirm = `This will reject and stop ${runRef(item)}.`;
  else confirm = `Run ${runRef(item)}?`;
  return { intent, label: INTENT_LABELS[intent] || intent, primary: isApproval, isLiveGate, confirm, runRef: runRef(item) };
}

/**
 * The transition produced by applying `intent`. Returns an ACTION RESULT — `{ item, removed,
 * intent }` — not a mutated item: `removed` and `intent` are action-layer signals, never
 * operator-triage fields, so the item carries only real fields (agent parity). The caller's
 * model decides queue membership from `removed`; `item` reflects only the real run_state change.
 */
export function applyResolution(item, intent) {
  const offered = Array.isArray(item?.resolution) ? item.resolution : [];
  if (!offered.includes(intent)) throw new Error(`intent "${intent}" not offered by item ${item?.id}`);
  const next = { ...item };
  if (intent === 'approve') next.run_state = 'running';   // resume the volley
  else if (intent === 'reject') next.run_state = 'idle';  // stop it
  return { item: next, removed: true, intent };
}
