// Unit tests for projection-adapter.js — the F002 thin adapter that
// maps the canonical F001 state-snapshot envelope into the dashboard's
// in-memory state object.
//
// Covers acceptance #1 (canonical input accepted), #4 (missing input
// produces empty / no-op, not bootstrap failure), and feeds into the
// integration tests for #2 (legacy fallback) and #3 (Capability Center
// reuse).

import { describe, it, expect } from 'vitest';
import {
  SUPPORTED_SCHEMA_VERSION,
  PER_STREAM_FILES,
  isCanonicalSnapshot,
  extractStreams,
  extractSnapshotMeta,
  adaptPlansToTasks,
  adaptSupervisorsToAgents,
  adaptInboxToActivity,
  adaptSnapshot,
  mergeSnapshotIntoState,
  mergePerStreamIntoState,
} from '../../lib/projection-adapter.js';

import snapshotFixture from '../fixtures/state-snapshot.json' with { type: 'json' };

// ── isCanonicalSnapshot ─────────────────────────────────────────────────

describe('isCanonicalSnapshot', () => {
  it('accepts the fixture envelope', () => {
    expect(isCanonicalSnapshot(snapshotFixture)).toBe(true);
  });

  it('pins to schema_version 1.0', () => {
    expect(SUPPORTED_SCHEMA_VERSION).toBe('1.0');
    expect(isCanonicalSnapshot({ ...snapshotFixture, schema_version: '2.0' })).toBe(false);
  });

  it('rejects null / undefined / non-objects', () => {
    expect(isCanonicalSnapshot(null)).toBe(false);
    expect(isCanonicalSnapshot(undefined)).toBe(false);
    expect(isCanonicalSnapshot('snap')).toBe(false);
    expect(isCanonicalSnapshot(42)).toBe(false);
  });

  it('rejects an envelope missing the streams object', () => {
    expect(isCanonicalSnapshot({ schema_version: '1.0' })).toBe(false);
  });

  it('rejects an envelope missing any required stream array', () => {
    const partial = JSON.parse(JSON.stringify(snapshotFixture));
    delete partial.streams.gates;
    expect(isCanonicalSnapshot(partial)).toBe(false);
  });

  it('rejects an envelope where a stream is the wrong type', () => {
    const broken = JSON.parse(JSON.stringify(snapshotFixture));
    broken.streams.inbox = 'oops';
    expect(isCanonicalSnapshot(broken)).toBe(false);
  });
});

// ── extractStreams / extractSnapshotMeta ────────────────────────────────

describe('extractStreams', () => {
  it('returns every canonical stream as an array', () => {
    const streams = extractStreams(snapshotFixture);
    expect(streams.plans).toHaveLength(2);
    expect(streams.gates).toHaveLength(1);
    expect(streams.inbox).toHaveLength(2);
    expect(streams.supervisors).toHaveLength(1);
    expect(streams.quota).toHaveLength(1);
    expect(streams.decisions).toHaveLength(1);
    expect(streams.evidenceRefs).toHaveLength(1);
  });

  it('renames evidence_refs to evidenceRefs (JS naming convention)', () => {
    const streams = extractStreams(snapshotFixture);
    expect(streams).toHaveProperty('evidenceRefs');
    expect(streams).not.toHaveProperty('evidence_refs');
  });
});

describe('extractSnapshotMeta', () => {
  it('returns the projection metadata block', () => {
    const meta = extractSnapshotMeta(snapshotFixture);
    expect(meta).toEqual({
      schema_version:   '1.0',
      captured_at:      '2026-05-23T03:15:00Z',
      redact_level:     'operator',
      dontpanic_version: '0.5.0',
    });
  });

  it('returns null when the snapshot is null', () => {
    expect(extractSnapshotMeta(null)).toBeNull();
  });
});

// ── adaptPlansToTasks ───────────────────────────────────────────────────

describe('adaptPlansToTasks', () => {
  it('maps plan_summary entries into mission-control task shape', () => {
    const tasks = adaptPlansToTasks(snapshotFixture.streams.plans);
    expect(tasks).toHaveLength(2);
    expect(tasks[0]).toEqual({
      id:       '2026-05-23-004-feat-operator-console-v0',
      title:    'Operator console v0',
      project:  'feat',
      status:   'in_progress',
      priority: 'medium',
      agent:    'claude',
      created:  '2026-05-23T00:00:00Z',
    });
  });

  it('maps every plan status to a known mission-control column', () => {
    const matrix = [
      { status: 'draft',           expected: 'backlog' },
      { status: 'active',          expected: 'in_progress' },
      { status: 'ready_for_audit', expected: 'review' },
      { status: 'in_audit',        expected: 'review' },
      { status: 'completed',       expected: 'done' },
      { status: 'abandoned',       expected: 'done' },
      { status: 'blocked',         expected: 'todo' },
    ];
    for (const { status, expected } of matrix) {
      const [task] = adaptPlansToTasks([{ plan_id: 'p', title: 't', type: 'feat', status, date: '2026-01-01' }]);
      expect(task.status).toBe(expected);
    }
  });

  it('uses a default column for unknown statuses without crashing', () => {
    const [task] = adaptPlansToTasks([{ plan_id: 'p', title: 't', status: 'made-up', type: 'feat' }]);
    expect(task.status).toBe('backlog');
  });

  it('falls back to plan_id when title is missing', () => {
    const [task] = adaptPlansToTasks([{ plan_id: 'p123', status: 'draft' }]);
    expect(task.title).toBe('p123');
  });

  it('omits agent when agents_required is empty', () => {
    const [task] = adaptPlansToTasks([{ plan_id: 'p', status: 'completed', agents_required: [] }]);
    expect(task.agent).toBeNull();
  });

  it('lowercases the first agent', () => {
    const [task] = adaptPlansToTasks([{ plan_id: 'p', status: 'active', agents_required: ['Codex'] }]);
    expect(task.agent).toBe('codex');
  });

  it('returns [] for an undefined input (quiet empty state)', () => {
    expect(adaptPlansToTasks(undefined)).toEqual([]);
    expect(adaptPlansToTasks(null)).toEqual([]);
  });
});

// ── adaptSupervisorsToAgents ────────────────────────────────────────────

describe('adaptSupervisorsToAgents', () => {
  it('maps each supervisor to an online agent row', () => {
    const agents = adaptSupervisorsToAgents(snapshotFixture.streams.supervisors);
    expect(agents).toHaveLength(1);
    expect(agents[0]).toEqual({
      id:           'claude',
      name:         'claude',
      role:         'Supervised',
      status:       'busy',
      currentTask:  '2026-05-23-004-feat-operator-console-v0',
      lastSeen:     '2026-05-23T02:52:18Z',
      tokensUsed:   0,
      tokenBudget:  0,
    });
  });

  it('falls back to supervisor_id when implementer_agent is missing', () => {
    const [agent] = adaptSupervisorsToAgents([
      { supervisor_id: 'sup-1', plan_id: 'p1', started_at: '2026-01-01T00:00:00Z' },
    ]);
    expect(agent.id).toBe('sup-1');
  });

  it('returns [] when supervisors is missing (quiet)', () => {
    expect(adaptSupervisorsToAgents(undefined)).toEqual([]);
  });
});

// ── adaptInboxToActivity ────────────────────────────────────────────────

describe('adaptInboxToActivity', () => {
  it('routes breaker_* and gate_* events to the alert bucket', () => {
    const activity = adaptInboxToActivity(snapshotFixture.streams.inbox);
    const breaker = activity.find(a => a.text.includes('breaker_tripped'));
    expect(breaker.type).toBe('alert');
  });

  it('routes volley_* to sync', () => {
    const [act] = adaptInboxToActivity([
      { plan_id: 'p', event: 'volley_start', captured_at: '2026-01-01T00:00:00Z' },
    ]);
    expect(act.type).toBe('sync');
  });

  it('routes signoff to task', () => {
    const [act] = adaptInboxToActivity([
      { plan_id: 'p', event: 'signoff', captured_at: '2026-01-01T00:00:00Z' },
    ]);
    expect(act.type).toBe('task');
  });

  it('returns [] for empty / missing input', () => {
    expect(adaptInboxToActivity(undefined)).toEqual([]);
    expect(adaptInboxToActivity([])).toEqual([]);
  });
});

// ── adaptSnapshot (top-level) ───────────────────────────────────────────

describe('adaptSnapshot', () => {
  it('returns null for a non-canonical input — loader treats this as legacy fallback', () => {
    expect(adaptSnapshot(null)).toBeNull();
    expect(adaptSnapshot({ schema_version: '0.9' })).toBeNull();
    expect(adaptSnapshot('not-an-envelope')).toBeNull();
  });

  it('produces both canonical and legacy-shaped fields', () => {
    const adapted = adaptSnapshot(snapshotFixture);
    expect(adapted).not.toBeNull();
    // Canonical projection keys
    expect(adapted.plans).toHaveLength(2);
    expect(adapted.gates).toHaveLength(1);
    expect(adapted.inbox).toHaveLength(2);
    expect(adapted.supervisors).toHaveLength(1);
    expect(adapted.quota).toHaveLength(1);
    expect(adapted.decisions).toHaveLength(1);
    expect(adapted.evidenceRefs).toHaveLength(1);
    expect(adapted.snapshotMeta).toMatchObject({ schema_version: '1.0', captured_at: '2026-05-23T03:15:00Z' });
    // Legacy-shaped projection
    expect(adapted.tasks).toHaveLength(2);
    expect(adapted.agents).toHaveLength(1);
    expect(adapted.activity).toHaveLength(2);
  });
});

// ── mergeSnapshotIntoState ──────────────────────────────────────────────

describe('mergeSnapshotIntoState', () => {
  function freshState() {
    return {
      agents: [], tasks: [], activity: [], costs: null, security: [],
      capabilities: null,
      plans: [], gates: [], inbox: [], supervisors: [], quota: [],
      decisions: [], evidenceRefs: [], snapshotMeta: null,
    };
  }

  it('populates canonical + legacy fields when a snapshot is present', () => {
    const state = freshState();
    mergeSnapshotIntoState(state, snapshotFixture);
    expect(state.plans).toHaveLength(2);
    expect(state.tasks).toHaveLength(2);
    expect(state.agents).toHaveLength(1);
    expect(state.activity).toHaveLength(2);
    expect(state.snapshotMeta).not.toBeNull();
  });

  it('overwrites legacy tasks/agents/activity when a snapshot is present (projection preferred)', () => {
    const state = freshState();
    state.tasks    = [{ id: 'legacy-only', title: 'demo' }];
    state.agents   = [{ id: 'legacy-only', name: 'demo' }];
    state.activity = [{ type: 'info', text: 'demo' }];
    mergeSnapshotIntoState(state, snapshotFixture);
    expect(state.tasks.find(t => t.id === 'legacy-only')).toBeUndefined();
    expect(state.agents.find(a => a.id === 'legacy-only')).toBeUndefined();
    expect(state.activity.find(a => a.text === 'demo')).toBeUndefined();
  });

  it('leaves capabilities alone — Capability Center keeps its existing path', () => {
    const capEnvelope = { schema_version: 'v0b', generated_at: '2026-05-23T03:00:00Z', capabilities: [] };
    const state = freshState();
    state.capabilities = capEnvelope;
    mergeSnapshotIntoState(state, snapshotFixture);
    expect(state.capabilities).toBe(capEnvelope);
  });

  it('is a no-op for malformed / missing snapshots — legacy data survives', () => {
    const state = freshState();
    state.tasks = [{ id: 'legacy', title: 'legacy demo' }];
    mergeSnapshotIntoState(state, null);
    mergeSnapshotIntoState(state, { schema_version: 'broken' });
    expect(state.tasks).toEqual([{ id: 'legacy', title: 'legacy demo' }]);
    expect(state.snapshotMeta).toBeNull();
  });

  it('returns true when applied, false when input is not canonical', () => {
    // Loader uses this signal to skip the per-stream fallback when the
    // envelope was successfully consumed.
    const state = freshState();
    expect(mergeSnapshotIntoState(state, snapshotFixture)).toBe(true);
    expect(mergeSnapshotIntoState(state, null)).toBe(false);
    expect(mergeSnapshotIntoState(state, { schema_version: 'broken' })).toBe(false);
  });
});

// ── PER_STREAM_FILES ────────────────────────────────────────────────────

describe('PER_STREAM_FILES', () => {
  it('matches state_projection.ALL_STREAMS so the loader picks up new streams', () => {
    // Mirror of state_projection.ALL_STREAMS — see state_cli.py
    // _export_dashboard_main; if the F001 projection contract grows a
    // stream, this list grows with it.
    expect(PER_STREAM_FILES).toEqual([
      'plans',
      'gates',
      'inbox',
      'supervisors',
      'quota',
      'decisions',
      'evidence_refs',
    ]);
  });

  it('is frozen — callers must not mutate the canonical list', () => {
    expect(Object.isFrozen(PER_STREAM_FILES)).toBe(true);
  });
});

// ── mergePerStreamIntoState ─────────────────────────────────────────────

describe('mergePerStreamIntoState', () => {
  function freshState() {
    return {
      agents: [], tasks: [], activity: [], costs: null, security: [],
      capabilities: null,
      plans: [], gates: [], inbox: [], supervisors: [], quota: [],
      decisions: [], evidenceRefs: [], snapshotMeta: null,
    };
  }

  // The seven canonical per-stream arrays state_cli.py writes when
  // exporting the dashboard projection (envelope absent).
  function perStreamFromFixture() {
    const s = snapshotFixture.streams;
    return {
      plans:         s.plans,
      gates:         s.gates,
      inbox:         s.inbox,
      supervisors:   s.supervisors,
      quota:         s.quota,
      decisions:     s.decisions,
      evidence_refs: s.evidence_refs,
    };
  }

  it('populates canonical projection keys from per-stream input', () => {
    const state = freshState();
    expect(mergePerStreamIntoState(state, perStreamFromFixture())).toBe(true);
    expect(state.plans).toHaveLength(2);
    expect(state.gates).toHaveLength(1);
    expect(state.inbox).toHaveLength(2);
    expect(state.supervisors).toHaveLength(1);
    expect(state.quota).toHaveLength(1);
    expect(state.decisions).toHaveLength(1);
    // evidence_refs (on-disk) → evidenceRefs (state key).
    expect(state.evidenceRefs).toHaveLength(1);
  });

  it('populates legacy tasks/agents/activity from per-stream plans/supervisors/inbox', () => {
    // Auditor recommendation: per-stream files must populate the adapted
    // legacy keys (tasks/agents/activity) so mission-control and
    // command-center render without a per-page rewrite.
    const state = freshState();
    mergePerStreamIntoState(state, perStreamFromFixture());
    expect(state.tasks).toHaveLength(2);
    expect(state.tasks[0]).toMatchObject({
      id:     '2026-05-23-004-feat-operator-console-v0',
      status: 'in_progress',
      agent:  'claude',
    });
    expect(state.agents).toHaveLength(1);
    expect(state.agents[0]).toMatchObject({ id: 'claude', status: 'busy' });
    expect(state.activity).toHaveLength(2);
  });

  it('leaves snapshotMeta null — per-stream mode has no envelope metadata', () => {
    const state = freshState();
    mergePerStreamIntoState(state, perStreamFromFixture());
    expect(state.snapshotMeta).toBeNull();
  });

  it('handles partial per-stream input (only plans.json present)', () => {
    const state = freshState();
    expect(mergePerStreamIntoState(state, { plans: snapshotFixture.streams.plans })).toBe(true);
    expect(state.plans).toHaveLength(2);
    expect(state.tasks).toHaveLength(2);
    // Streams not provided stay at empty defaults.
    expect(state.gates).toEqual([]);
    expect(state.supervisors).toEqual([]);
    expect(state.agents).toEqual([]);
  });

  it('is a no-op when every stream is empty — legacy demo data survives', () => {
    // Acceptance #2: a state directory containing only zero-length
    // per-stream files (or no per-stream files at all) must not stomp
    // the legacy demo state already loaded.
    const state = freshState();
    state.tasks = [{ id: 'legacy', title: 'legacy demo' }];
    expect(mergePerStreamIntoState(state, {})).toBe(false);
    expect(mergePerStreamIntoState(state, { plans: [], gates: [], inbox: [] })).toBe(false);
    expect(state.tasks).toEqual([{ id: 'legacy', title: 'legacy demo' }]);
  });

  it('returns false and is a no-op for null / non-object input (acceptance #4)', () => {
    const state = freshState();
    expect(mergePerStreamIntoState(state, null)).toBe(false);
    expect(mergePerStreamIntoState(state, undefined)).toBe(false);
    expect(mergePerStreamIntoState(state, 'oops')).toBe(false);
    expect(state.plans).toEqual([]);
  });

  it('ignores non-array stream values — quietly, without bootstrap failure', () => {
    const state = freshState();
    mergePerStreamIntoState(state, {
      plans:         snapshotFixture.streams.plans, // valid
      gates:         'not-an-array',                // junk — ignored
      inbox:         null,                          // junk — ignored
      supervisors:   { wrong: 'shape' },            // junk — ignored
      evidence_refs: snapshotFixture.streams.evidence_refs,
    });
    expect(state.plans).toHaveLength(2);
    expect(state.gates).toEqual([]);
    expect(state.inbox).toEqual([]);
    expect(state.supervisors).toEqual([]);
    expect(state.evidenceRefs).toHaveLength(1);
  });

  it('does not touch the capabilities envelope (Capability Center reuse)', () => {
    const capEnvelope = { schema_version: 'v0b', capabilities: [] };
    const state = freshState();
    state.capabilities = capEnvelope;
    mergePerStreamIntoState(state, perStreamFromFixture());
    expect(state.capabilities).toBe(capEnvelope);
  });
});
