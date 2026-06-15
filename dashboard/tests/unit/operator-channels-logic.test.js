// Plan 2026-06-14-001 F009 — operator-channels-logic locked rule matrix.
// Asserts the rule matrix CELL-BY-CELL for every bucket: the active/stale
// boundary, conflict precedence (same_plan > same_branch > same_repo) over active
// records only, remote_only / remote_cannot_mutate_local, unhealthy worktree
// binding, and operator_only_runtime_not_dispatchable. Conflict equality is on
// repo.path_key, never path_display.

import { describe, it, expect } from 'vitest';
import {
  ACTIVE_WITHIN_MS,
  BUCKET_IDS,
  deriveBuckets,
  isActive,
} from '../../lib/operator-channels-logic.js';

const NOW = Date.parse('2026-06-14T12:00:00Z');

function rec(overrides = {}) {
  return {
    operator_surface: 'terminal',
    agent_runtime: 'claude',
    role: 'implementer',
    locality: 'local_mac',
    execution_locality: 'local_mac',
    repo: { path_display: '<home>/r', path_key: 'repo-A' },
    worktree: null,
    branch: 'main',
    plan: null,
    last_seen: '2026-06-14T12:00:00Z',
    result: 'ok',
    ...overrides,
  };
}

function view({ records = [], worktree_bindings = [], runtimes = [], operator_roles = null } = {}) {
  return { records, worktree_bindings, runtimes, operator_roles };
}

describe('active/stale boundary', () => {
  it('a record exactly at the threshold is ACTIVE; just past it is STALE', () => {
    const onEdge = rec({ last_seen: new Date(NOW - ACTIVE_WITHIN_MS).toISOString() });
    const justOver = rec({ last_seen: new Date(NOW - ACTIVE_WITHIN_MS - 1000).toISOString() });
    expect(isActive(onEdge, NOW)).toBe(true);
    expect(isActive(justOver, NOW)).toBe(false);
    const b = deriveBuckets(view({ records: [onEdge, justOver] }), { now: NOW });
    expect(b.active).toContain(onEdge);
    expect(b.stale).toContain(justOver);
  });

  it('an unparseable last_seen is fail-closed to STALE', () => {
    const bad = rec({ last_seen: 'not-a-date' });
    const b = deriveBuckets(view({ records: [bad] }), { now: NOW });
    expect(b.stale).toContain(bad);
    expect(b.active).toHaveLength(0);
  });
});

describe('conflict precedence (most-specific wins, active only)', () => {
  it('same repo_key + same plan -> same_plan_conflict ONLY', () => {
    const a = rec({ plan: 'P', branch: 'b1' });
    const c = rec({ plan: 'P', branch: 'b2' });
    const b = deriveBuckets(view({ records: [a, c] }), { now: NOW });
    expect(b.same_plan_conflict).toEqual([a, c]);
    expect(b.same_branch).toHaveLength(0);
    expect(b.same_repo).toHaveLength(0);
  });

  it('same repo_key + same branch + different plan -> same_branch', () => {
    const a = rec({ plan: 'P1', branch: 'shared' });
    const c = rec({ plan: 'P2', branch: 'shared' });
    const b = deriveBuckets(view({ records: [a, c] }), { now: NOW });
    expect(b.same_branch).toEqual([a, c]);
    expect(b.same_plan_conflict).toHaveLength(0);
    expect(b.same_repo).toHaveLength(0);
  });

  it('same repo_key + different branch + different plan -> same_repo', () => {
    const a = rec({ plan: 'P1', branch: 'b1' });
    const c = rec({ plan: 'P2', branch: 'b2' });
    const b = deriveBuckets(view({ records: [a, c] }), { now: NOW });
    expect(b.same_repo).toEqual([a, c]);
    expect(b.same_plan_conflict).toHaveLength(0);
    expect(b.same_branch).toHaveLength(0);
  });

  it('conflicts consider ONLY active records (a stale partner does not conflict)', () => {
    const liveOne = rec({ plan: 'P' });
    const staleOne = rec({ plan: 'P', last_seen: '2020-01-01T00:00:00Z' });
    const b = deriveBuckets(view({ records: [liveOne, staleOne] }), { now: NOW });
    expect(b.same_plan_conflict).toHaveLength(0); // liveOne is alone among active
    expect(b.stale).toContain(staleOne);
  });

  it('equality is on path_key, NOT the scrubbed path_display', () => {
    const a = rec({ plan: 'P', repo: { path_display: '<home>/a', path_key: 'K' } });
    const c = rec({ plan: 'P', repo: { path_display: '<home>/DIFFERENT', path_key: 'K' } });
    const b = deriveBuckets(view({ records: [a, c] }), { now: NOW });
    expect(b.same_plan_conflict).toEqual([a, c]); // same path_key conflicts despite different display
  });
});

describe('remote buckets', () => {
  it('remote record with no co-active local record + no binding -> remote_only only', () => {
    const r = rec({ locality: 'remote_vm', execution_locality: 'remote_vm', repo: { path_display: '<home>/x', path_key: 'R1' } });
    const b = deriveBuckets(view({ records: [r] }), { now: NOW });
    expect(b.remote_only).toEqual([r]);
    expect(b.remote_cannot_mutate_local).toHaveLength(0);
  });

  it('remote record whose repo_key matches a worktree binding -> remote_cannot_mutate_local', () => {
    const r = rec({ locality: 'github_vm', execution_locality: 'github_vm', repo: { path_display: '<home>/x', path_key: 'R2' } });
    const b = deriveBuckets(
      view({ records: [r], worktree_bindings: [{ path_key: 'R2', path_display: '<home>/wt', healthy: true }] }),
      { now: NOW },
    );
    expect(b.remote_cannot_mutate_local).toEqual([r]);
  });

  it('remote record with a co-active LOCAL record on the same repo is NOT remote_only', () => {
    const remote = rec({ locality: 'remote_vm', execution_locality: 'remote_vm', repo: { path_display: '<home>/x', path_key: 'R3' } });
    const local = rec({ locality: 'local_mac', repo: { path_display: '<home>/x', path_key: 'R3' }, plan: 'L', branch: 'lb' });
    const b = deriveBuckets(view({ records: [remote, local] }), { now: NOW });
    expect(b.remote_only).toHaveLength(0);
    expect(b.remote_cannot_mutate_local).toEqual([remote]); // local record IS a local target
  });
});

describe('worktree + runtime buckets', () => {
  it('unhealthy_worktree_binding contains only bindings with healthy === false', () => {
    const bindings = [
      { path_key: 'wt1', path_display: '<home>/wt1', healthy: true },
      { path_key: 'wt2', path_display: '<home>/wt2', healthy: false },
    ];
    const b = deriveBuckets(view({ worktree_bindings: bindings }), { now: NOW });
    expect(b.unhealthy_worktree_binding).toEqual([bindings[1]]);
  });

  it('operator_only_runtime_not_dispatchable: op-role value runtime that is not dispatchable', () => {
    const channelView = view({
      runtimes: [
        { id: 'gemini', supports_dispatch: false, has_capability_manifest: false },
        { id: 'claude', supports_dispatch: true, has_capability_manifest: true },
        { id: 'aider', supports_dispatch: false, has_capability_manifest: false },
      ],
      operator_roles: {
        operator_roles: { intent_only: true, dispatch_authority: false, entries: [
          { role: 'researcher', value: 'gemini', scope: 'global' },
          { role: 'primary_operator', value: 'claude', scope: 'global' },
        ] },
        worker_roles: { dispatch_authority: true, entries: [] },
      },
    });
    const b = deriveBuckets(channelView, { now: NOW });
    const ids = b.operator_only_runtime_not_dispatchable.map((r) => r.id);
    expect(ids).toEqual(['gemini']); // gemini: op-value + not dispatchable; claude dispatchable; aider not an op-value
  });
});

describe('shape', () => {
  it('always returns every bucket id (empty arrays when none)', () => {
    const b = deriveBuckets(view({}), { now: NOW });
    for (const id of BUCKET_IDS) expect(Array.isArray(b[id])).toBe(true);
  });
});
