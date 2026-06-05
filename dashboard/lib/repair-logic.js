// ── DontPanic Dashboard — Repair surfaces logic (plan 2026-06-04-006 F006) ──
//
// Pure layer behind the two dashboard repair controls:
//   • "Repair automatically" — surfaces (and copies the command for) the
//     --safe-derived-state batch ONLY; the stronger --safe --confirm tier is
//     never offered without the operator explicitly choosing it.
//   • "Copy agent repair plan" — emits the F003 agent-handoff bundle, byte-parity
//     with `dontpanic repair plan --format=json`.
//
// This mirrors the Python repair_safety / repair_planner / repair_bundle so the
// browser and the CLI classify and order identically. The dashboard is read-only
// (D002): these helpers compute and the page copies a command — they never
// execute a mutation. Safety is PRODUCER-ASSERTED; an item whose producer
// declared no safety fails closed to human_required, exactly like the CLI.
//
// All exports are pure: same input → same output. DOM access lives in the page
// module (pages/repair/repair.js).

import { esc } from './html-escape.js';

// ── safety classes ──────────────────────────────────────────────────────────
export const AUTO_SAFE = 'auto_safe';
export const HUMAN_REQUIRED = 'human_required';
export const BLOCKED_EXTERNAL = 'blocked_external';
export const INFO = 'info';
export const SAFETY_CLASSES = new Set([AUTO_SAFE, HUMAN_REQUIRED, BLOCKED_EXTERNAL, INFO]);

// ── apply tiers (auto_safe only) ──────────────────────────────────────────────
export const TIER_DERIVED_STATE = 'derived_state';
export const TIER_CONFIRMED_LOCAL = 'confirmed_local';

// ── run tiers granted by the `repair apply` flags ─────────────────────────────
export const RUN_TIER_DERIVED = 'safe-derived-state';
export const RUN_TIER_CONFIRM = 'safe-confirm';

// Kinds that may NEVER auto-run at any tier (always human_required).
export const FORBIDDEN_KINDS = new Set([
  'deploy',
  'credential_setup',
  'paid_dispatch',
  'role_change',
  'plan_state_mutation',
  'registry_change',
  'destructive_cleanup',
  'baseline_write',
]);

// Kinds that regenerate derived/cached projection state ONLY (no source write).
export const DERIVED_STATE_KINDS = new Set([
  'rebuild_dashboard_state',
  'recompute_what_now',
  'refresh_capabilities',
  'refresh_reconcile_check',
  'regen_architecture',
  'clear_replaceable_cache',
  're_export_state',
  'suppress_resolved',
]);

// Explicit allowlist of local safe MUTATIONS eligible for confirmed_local.
export const CONFIRMED_LOCAL_KINDS = new Set([
  'clear_stale_generated_cache',
  'rewrite_local_derived_config',
]);

/** Validate an action's asserted safety against the policy, fail-closed.
 *  Returns the effective `{ safetyClass, applyTier }`. */
export function resolveSafety(action) {
  const kind = action.kind ?? null;
  const asserted = action.safetyClass ?? null;
  const tier = action.applyTier ?? null;
  if (FORBIDDEN_KINDS.has(kind)) return { safetyClass: HUMAN_REQUIRED, applyTier: null };
  if (!SAFETY_CLASSES.has(asserted)) return { safetyClass: HUMAN_REQUIRED, applyTier: null };
  if (asserted === AUTO_SAFE) {
    if (tier === TIER_DERIVED_STATE && DERIVED_STATE_KINDS.has(kind)) {
      return { safetyClass: AUTO_SAFE, applyTier: TIER_DERIVED_STATE };
    }
    if (tier === TIER_CONFIRMED_LOCAL && CONFIRMED_LOCAL_KINDS.has(kind)) {
      return { safetyClass: AUTO_SAFE, applyTier: TIER_CONFIRMED_LOCAL };
    }
    return { safetyClass: HUMAN_REQUIRED, applyTier: null };
  }
  return { safetyClass: asserted, applyTier: null };
}

/** True iff `action` may execute under `runTier`. derived_state runs under both
 *  flags; confirmed_local only under --safe --confirm. */
export function isRunnableAt(action, runTier) {
  const { safetyClass, applyTier } = resolveSafety(action);
  if (safetyClass !== AUTO_SAFE) return false;
  if (runTier === RUN_TIER_DERIVED) return applyTier === TIER_DERIVED_STATE;
  if (runTier === RUN_TIER_CONFIRM) {
    return applyTier === TIER_DERIVED_STATE || applyTier === TIER_CONFIRMED_LOCAL;
  }
  return false;
}

/** Topologically order actions (Kahn); dependencies outside the set are treated
 *  as satisfied. Returns `{ ordered, cyclic }`. Deterministic (sorted by id). */
export function orderActions(actions) {
  const byId = new Map(actions.map((a) => [a.id, a]));
  const ids = new Set(byId.keys());
  const depsIn = new Map();
  const indeg = new Map();
  const dependents = new Map();
  for (const id of ids) dependents.set(id, []);
  for (const a of actions) {
    const ds = (a.dependsOn || []).filter((d) => ids.has(d));
    depsIn.set(a.id, ds);
    indeg.set(a.id, ds.length);
  }
  for (const a of actions) for (const d of depsIn.get(a.id)) dependents.get(d).push(a.id);

  let ready = [...ids].filter((id) => indeg.get(id) === 0).sort();
  const ordered = [];
  while (ready.length) {
    const n = ready.shift();
    ordered.push(byId.get(n));
    for (const m of [...dependents.get(n)].sort()) {
      indeg.set(m, indeg.get(m) - 1);
      if (indeg.get(m) === 0) {
        ready.push(m);
        ready.sort();
      }
    }
  }
  const orderedIds = new Set(ordered.map((a) => a.id));
  const cyclic = new Set([...ids].filter((id) => !orderedIds.has(id)));
  return { ordered, cyclic };
}

/** Adapt a live what-now ActionItem into a normalized repair action, reading
 *  PRODUCER-ASSERTED safety (never inferring it). */
export function actionFromItem(item) {
  const it = item || {};
  return {
    id: it.id,
    kind: it.repair_kind ?? it.kind ?? null,
    safetyClass: it.safety_class ?? null,
    applyTier: it.apply_tier ?? null,
    resolutionClass: it.resolution_class ?? 'command_resolvable',
    clearsWhen: it.clears_when ?? null,
    dependsOn: Array.isArray(it.depends_on) ? it.depends_on : [],
    command: it.exact_command ?? null,
    plainConsequence: it.plain_consequence ?? null,
    scope: it.scope ?? (it.project_name ? `project:${it.project_name}` : null),
  };
}

function emitAction(action) {
  const { safetyClass, applyTier } = resolveSafety(action);
  return {
    id: action.id,
    command: action.command ?? null,
    safety_class: safetyClass,
    apply_tier: applyTier,
    resolution_class: action.resolutionClass ?? 'command_resolvable',
    clears_when: action.clearsWhen ?? null,
    plain_consequence: action.plainConsequence ?? null,
    scope: action.scope ?? null,
    depends_on: [...(action.dependsOn || [])],
  };
}

/** Build the dependency-ordered, safety-classified emit bundle (F003 parity).
 *  The emitted safety_class is the EFFECTIVE value, so an unclassified / forbidden
 *  action reads human_required — the bundle never overstates what may auto-run. */
export function buildBundle(actions, scope) {
  const { ordered, cyclic } = orderActions(actions);
  return {
    scope,
    actions: ordered.map(emitAction),
    deferred: [...cyclic].sort().map((id) => ({ id, reason: 'cycle' })),
  };
}

/** Convenience: build the bundle straight from live what-now items. */
export function buildBundleFromItems(items, scope) {
  return buildBundle((items || []).map(actionFromItem), scope);
}

/** Partition the bundle into what the "Repair automatically" control WILL run vs
 *  WILL leave. Default = derived-state tier only; confirmed_local is included only
 *  when the operator explicitly confirms the stronger tier. */
export function buildRepairAutoPreview(bundle, opts = {}) {
  const confirmed = opts.confirmed === true;
  const runTier = confirmed ? RUN_TIER_CONFIRM : RUN_TIER_DERIVED;
  const willRun = [];
  const willLeave = [];
  for (const a of bundle.actions) {
    const runnable =
      a.safety_class === AUTO_SAFE &&
      (a.apply_tier === TIER_DERIVED_STATE ||
        (confirmed && a.apply_tier === TIER_CONFIRMED_LOCAL));
    (runnable ? willRun : willLeave).push(a);
  }
  return { runTier, willRun, willLeave };
}

/** Count the current (re-evaluated) bundle by safety class — the truthful
 *  post-run cleared/remaining summary. As cards clear, the re-gathered bundle
 *  shrinks and these counts fall. */
export function buildRepairSummary(bundle) {
  const s = {
    auto_safe: 0,
    derived_state: 0,
    confirmed_local: 0,
    human_required: 0,
    blocked_external: 0,
    info: 0,
    total: bundle.actions.length,
  };
  for (const a of bundle.actions) {
    if (a.safety_class === AUTO_SAFE) {
      s.auto_safe += 1;
      if (a.apply_tier === TIER_DERIVED_STATE) s.derived_state += 1;
      else if (a.apply_tier === TIER_CONFIRMED_LOCAL) s.confirmed_local += 1;
    } else if (a.safety_class === HUMAN_REQUIRED) s.human_required += 1;
    else if (a.safety_class === BLOCKED_EXTERNAL) s.blocked_external += 1;
    else if (a.safety_class === INFO) s.info += 1;
  }
  return s;
}

/** The agent-handoff bundle as the copyable JSON text (CLI render_json parity). */
export function buildAgentRepairPlanText(bundle) {
  return JSON.stringify(bundle, null, 2);
}

/** The emit-only plan command for a scope. */
export function repairPlanCommand(scope) {
  return `dontpanic repair plan --scope ${scope} --format=json`;
}

/** The apply command. Default = derived-state batch; the "Repair automatically"
 *  control always uses this form and NEVER the confirmed tier. */
export function repairApplyCommand(scope, opts = {}) {
  return opts.confirmed === true
    ? `dontpanic repair apply --safe --confirm --scope ${scope}`
    : `dontpanic repair apply --safe-derived-state --scope ${scope}`;
}

/** Render the two read-only repair controls. Buttons carry the command / bundle
 *  text in a data-copy attribute; the page's copy handler writes it to the
 *  clipboard (the dashboard never executes — D002). */
export function renderRepairControlsHTML(bundle, scope) {
  const preview = buildRepairAutoPreview(bundle);
  const summary = buildRepairSummary(bundle);
  const applyCmd = repairApplyCommand(scope); // derived-state only, never --confirm
  const bundleText = buildAgentRepairPlanText(bundle);
  return `
    <section class="repair-controls" data-scope="${esc(scope)}">
      <h2 class="repair-title">Repair</h2>
      <p class="repair-summary">
        Auto-safe (derived state): ${summary.derived_state} ·
        Human required: ${summary.human_required} ·
        Blocked external: ${summary.blocked_external} ·
        Info: ${summary.info}
      </p>
      <div class="repair-control repair-auto">
        <button type="button" class="repair-copy-btn repair-auto-btn"
          data-copy="${esc(applyCmd)}"
          aria-label="Copy the safe derived-state repair command">Repair automatically</button>
        <p class="repair-control-note">
          Runs ${preview.willRun.length} safe derived-state repair(s);
          leaves ${preview.willLeave.length} for a human / external / info.
          The stronger confirmed tier is never run without your explicit --confirm.
        </p>
      </div>
      <div class="repair-control repair-plan">
        <button type="button" class="repair-copy-btn repair-plan-btn"
          data-copy="${esc(bundleText)}"
          aria-label="Copy the agent repair plan bundle">Copy agent repair plan</button>
        <p class="repair-control-note">Hand the ordered, safety-classified bundle to an agent (Codex / Claude / Grok).</p>
      </div>
    </section>`;
}
