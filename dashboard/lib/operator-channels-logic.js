// ── Operator Channels Logic — pure bucket derivation (plan 2026-06-14-001 F009) ──
// Derives the Operator Channels panel buckets + operator-role matrix from the
// channel-view object emitted by the Python producer (operator_channels.py,
// written to dashboard/state/operator-channels.json by `dontpanic dashboard build`).
//
// Every bucket is governed by a LOCKED RULE MATRIX (D013): a deterministic
// criterion + precedence is pinned for EACH bucket so the producer and renderer
// can never diverge. All exports are pure: same input → same output. DOM access
// lives in pages/operator-channels/. Conflict equality uses repo.path_key (F003),
// NEVER the scrubbed path_display.

import { esc } from './html-escape.js';

// ── LOCKED rule-matrix constants ──────────────────────────────────────────────

/** Active-vs-stale threshold (from last_seen). A record is ACTIVE when
 *  now - last_seen <= ACTIVE_WITHIN_MS, else STALE. Pinned at 15 minutes. */
export const ACTIVE_WITHIN_MS = 15 * 60 * 1000;

/** execution_locality ids treated as remote / local (F001 canonical ids). */
export const REMOTE_LOCALITIES = Object.freeze(['remote_vm', 'github_vm']);
export const LOCAL_LOCALITIES = Object.freeze([
  'local_mac', 'plan_worktree', 'dashboard_terminal', 'code_task',
]);

/** Conflict precedence, most-specific → least-specific. A record is assigned to
 *  AT MOST ONE conflict bucket: the most specific overlap it participates in. */
export const CONFLICT_PRECEDENCE = Object.freeze(['same_plan_conflict', 'same_branch', 'same_repo']);

/** Every panel bucket, in display order. */
export const BUCKET_IDS = Object.freeze([
  'active',
  'stale',
  'remote_only',
  'same_plan_conflict',
  'same_branch',
  'same_repo',
  'unhealthy_worktree_binding',
  'remote_cannot_mutate_local',
  'operator_only_runtime_not_dispatchable',
]);

// ── helpers (pure) ────────────────────────────────────────────────────────────

function repoKey(record) {
  return record && record.repo && typeof record.repo.path_key === 'string' ? record.repo.path_key : '';
}

function isRemote(record) {
  return REMOTE_LOCALITIES.includes(record && record.locality);
}

function isLocal(record) {
  return LOCAL_LOCALITIES.includes(record && record.locality);
}

/** ACTIVE iff last_seen parses AND is within the threshold of `now`. A missing or
 *  unparseable last_seen is fail-closed to STALE (never silently "active"). */
export function isActive(record, now, activeWithinMs = ACTIVE_WITHIN_MS) {
  const t = Date.parse(record && record.last_seen);
  if (Number.isNaN(t)) return false;
  return now - t <= activeWithinMs;
}

/** The set of runtime ids that appear as an operator-role VALUE (F004). */
export function operatorRoleValues(channelView) {
  const matrix = channelView && channelView.operator_roles;
  const section = matrix && matrix.operator_roles;
  const entries = (section && section.entries) || [];
  return new Set(entries.map((e) => e.value).filter(Boolean));
}

// ── the locked derivation ──────────────────────────────────────────────────────

/**
 * Derive every panel bucket from the channel-view under the locked rule matrix.
 * @param {object} channelView - producer output (records, worktree_bindings, runtimes, operator_roles).
 * @param {{now:number, activeWithinMs?:number}} opts - `now` epoch-ms (required for determinism).
 * @returns {Object<string, Array>} bucket id → members.
 */
export function deriveBuckets(channelView, { now, activeWithinMs = ACTIVE_WITHIN_MS } = {}) {
  const records = (channelView && channelView.records) || [];
  const bindings = (channelView && channelView.worktree_bindings) || [];
  const runtimes = (channelView && channelView.runtimes) || [];
  const buckets = Object.fromEntries(BUCKET_IDS.map((b) => [b, []]));

  // 1. active / stale — every record is EXACTLY one (the active/stale boundary).
  const active = [];
  for (const r of records) {
    if (isActive(r, now, activeWithinMs)) {
      buckets.active.push(r);
      active.push(r);
    } else {
      buckets.stale.push(r);
    }
  }

  // 2. conflicts — consider ONLY active records; each record → the MOST SPECIFIC
  //    overlap it participates in (precedence: same_plan > same_branch > same_repo).
  //    Equality on repo.path_key, never path_display.
  for (const r of active) {
    const key = repoKey(r);
    const others = active.filter((o) => o !== r && repoKey(o) === key);
    if (others.length === 0) continue; // alone in its repo → no conflict
    if (r.plan && others.some((o) => o.plan === r.plan)) {
      buckets.same_plan_conflict.push(r);
    } else if (r.branch && others.some((o) => o.branch === r.branch)) {
      buckets.same_branch.push(r);
    } else {
      buckets.same_repo.push(r);
    }
  }

  // 3. remote buckets — over active remote records.
  const activeLocalRepoKeys = new Set(active.filter(isLocal).map(repoKey));
  const localTargetKeys = new Set([...activeLocalRepoKeys, ...bindings.map((b) => b.path_key)]);
  for (const r of active.filter(isRemote)) {
    const key = repoKey(r);
    // remote_only: a remote record with NO co-active local RECORD on the same repo.
    if (!activeLocalRepoKeys.has(key)) buckets.remote_only.push(r);
    // remote_cannot_mutate_local: a remote record whose target is local-only state
    // (a local record OR a worktree binding it cannot mutate from remote).
    if (localTargetKeys.has(key)) buckets.remote_cannot_mutate_local.push(r);
  }

  // 4. unhealthy_worktree_binding — a binding failing its health check (F004 health).
  buckets.unhealthy_worktree_binding = bindings.filter((b) => b.healthy === false);

  // 5. operator_only_runtime_not_dispatchable — a runtime that is an operator-role
  //    value but is NOT dispatchable (absent from AGENT_REGISTRY; D009/F006).
  const opValues = operatorRoleValues(channelView);
  for (const rt of runtimes) {
    if (rt.supports_dispatch === false && opValues.has(rt.id)) {
      buckets.operator_only_runtime_not_dispatchable.push(rt);
    }
  }

  return buckets;
}

/** The operator-role matrix, passed through from the producer (F005 projection).
 *  Surfaced as intent only — never a dispatchability claim. */
export function deriveOperatorRoleMatrix(channelView) {
  return (channelView && channelView.operator_roles) || null;
}

export const CHANNELS_SOURCE = 'dashboard/state/operator-channels.json';
export const CHANNELS_REFRESH = 'dontpanic dashboard build';

/** Bucket id → human label (display aliases; canonical ids stay machine-side). */
export const BUCKET_LABELS = Object.freeze({
  active: 'Active',
  stale: 'Stale',
  remote_only: 'Remote only',
  same_plan_conflict: 'Same-plan conflict',
  same_branch: 'Same branch',
  same_repo: 'Same repo',
  unhealthy_worktree_binding: 'Unhealthy worktree binding',
  remote_cannot_mutate_local: 'Remote cannot mutate local',
  operator_only_runtime_not_dispatchable: 'Operator-only runtime (not dispatchable)',
});

/** Render one bucket's count badge — escaped, no secrets (path_display only). */
export function renderBucketBadgeHTML(bucketId, members) {
  const label = BUCKET_LABELS[bucketId] || bucketId;
  return `<span class="channel-bucket" data-bucket="${esc(bucketId)}">${esc(label)}: ${members.length}</span>`;
}
