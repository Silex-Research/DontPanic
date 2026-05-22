// Unit tests for capabilities-logic.js — the pure transformation layer
// behind the Capability Center page.

import { describe, it, expect } from 'vitest';
import {
  CAPABILITY_STATUSES,
  STATUS_LABELS,
  STATUS_COLORS,
  OWNER_BOUNDARY_LABELS,
  buildOwnerBoundaryChips,
  getStatusBadge,
  isMissingState,
  normalizeEnvelope,
  partitionNextActions,
  sortByAttention,
  summarizeByStatus,
} from '../../lib/capabilities-logic.js';

import fixture from '../fixtures/capabilities-status.json' with { type: 'json' };

// ── Constants ──

describe('capabilities: constants', () => {
  it('exposes all five V0b status values', () => {
    expect(CAPABILITY_STATUSES).toEqual([
      'ready',
      'needs_setup',
      'blocked',
      'not_installed',
      'optional',
    ]);
  });

  it('has a human label for every status', () => {
    for (const s of CAPABILITY_STATUSES) {
      expect(STATUS_LABELS[s]).toBeTruthy();
    }
  });

  it('has a color token for every status', () => {
    for (const s of CAPABILITY_STATUSES) {
      expect(STATUS_COLORS[s]).toBeTruthy();
    }
  });

  it('labels every owner_boundary role', () => {
    for (const role of ['dontpanic_core', 'adapter', 'operator']) {
      expect(OWNER_BOUNDARY_LABELS[role]).toBeTruthy();
    }
  });
});

// ── isMissingState ──

describe('capabilities: isMissingState', () => {
  it('treats null as missing', () => {
    expect(isMissingState(null)).toBe(true);
  });

  it('treats undefined as missing', () => {
    expect(isMissingState(undefined)).toBe(true);
  });

  it('treats non-objects as missing', () => {
    expect(isMissingState('not-an-object')).toBe(true);
    expect(isMissingState(42)).toBe(true);
  });

  it('treats an object without capabilities array as missing', () => {
    expect(isMissingState({})).toBe(true);
    expect(isMissingState({ capabilities: 'nope' })).toBe(true);
  });

  it('treats a valid envelope as present', () => {
    expect(isMissingState({ capabilities: [] })).toBe(false);
    expect(isMissingState(fixture)).toBe(false);
  });
});

// ── normalizeEnvelope ──

describe('capabilities: normalizeEnvelope', () => {
  it('returns null for non-envelope inputs', () => {
    expect(normalizeEnvelope(null)).toBeNull();
    expect(normalizeEnvelope(undefined)).toBeNull();
    expect(normalizeEnvelope('string')).toBeNull();
    expect(normalizeEnvelope({})).toBeNull();
  });

  it('preserves all envelope-level fields from a real status JSON', () => {
    const env = normalizeEnvelope(fixture);
    expect(env.schema_version).toBe('1.0.0');
    expect(env.generated_at).toMatch(/2026-/);
    expect(env.advisory_notes.length).toBe(1);
    expect(env.capabilities.length).toBe(4);
  });

  it('fills missing optional fields with safe defaults', () => {
    const env = normalizeEnvelope({
      capabilities: [
        { capability_id: 'x', status: 'ready' },
      ],
    });
    const cap = env.capabilities[0];
    expect(cap.configured).toEqual([]);
    expect(cap.missing).toEqual([]);
    expect(cap.automatable).toEqual([]);
    expect(cap.human_required).toEqual([]);
    expect(cap.pending_probes).toEqual([]);
    expect(cap.next_actions).toEqual([]);
    expect(cap.advisory_notes).toEqual([]);
    expect(cap.owner_boundary).toEqual({ dontpanic_core: [], adapter: [], operator: [] });
  });

  it('coerces unknown status values to "optional"', () => {
    const env = normalizeEnvelope({
      capabilities: [{ capability_id: 'x', status: 'mystery' }],
    });
    expect(env.capabilities[0].status).toBe('optional');
  });

  it('drops non-string entries from string-typed arrays', () => {
    const env = normalizeEnvelope({
      capabilities: [{
        capability_id: 'x',
        status: 'ready',
        configured: ['a', 1, null, 'b'],
        missing:    ['m', false, 'n'],
        owner_boundary: { dontpanic_core: ['real', 99], adapter: 'not-array', operator: ['op'] },
      }],
    });
    const cap = env.capabilities[0];
    expect(cap.configured).toEqual(['a', 'b']);
    expect(cap.missing).toEqual(['m', 'n']);
    expect(cap.owner_boundary.dontpanic_core).toEqual(['real']);
    expect(cap.owner_boundary.adapter).toEqual([]);
    expect(cap.owner_boundary.operator).toEqual(['op']);
  });
});

// ── summarizeByStatus ──

describe('capabilities: summarizeByStatus', () => {
  it('returns zeros for missing input', () => {
    expect(summarizeByStatus(undefined)).toEqual({
      total: 0, ready: 0, needs_setup: 0, blocked: 0, not_installed: 0, optional: 0,
    });
  });

  it('counts each status correctly against the fixture', () => {
    const env = normalizeEnvelope(fixture);
    const s = summarizeByStatus(env.capabilities);
    expect(s.total).toBe(4);
    expect(s.ready).toBe(1);
    expect(s.needs_setup).toBe(1);
    expect(s.blocked).toBe(1);
    expect(s.not_installed).toBe(1);
    expect(s.optional).toBe(0);
  });
});

// ── buildOwnerBoundaryChips ──

describe('capabilities: buildOwnerBoundaryChips', () => {
  it('emits one chip per non-empty bucket in fixed order', () => {
    const chips = buildOwnerBoundaryChips({
      dontpanic_core: ['a'],
      adapter:        ['b', 'c'],
      operator:       ['d'],
    });
    expect(chips.map(c => c.role)).toEqual(['dontpanic_core', 'adapter', 'operator']);
    expect(chips[1].tokens.length).toBe(2);
  });

  it('skips empty buckets', () => {
    const chips = buildOwnerBoundaryChips({
      dontpanic_core: [],
      adapter:        ['b'],
      operator:       [],
    });
    expect(chips.length).toBe(1);
    expect(chips[0].role).toBe('adapter');
  });

  it('returns empty array for null/non-object inputs', () => {
    expect(buildOwnerBoundaryChips(null)).toEqual([]);
    expect(buildOwnerBoundaryChips('nope')).toEqual([]);
  });
});

// ── sortByAttention ──

describe('capabilities: sortByAttention', () => {
  it('orders blocked > needs_setup > not_installed > optional > ready', () => {
    const env = normalizeEnvelope(fixture);
    const sorted = sortByAttention(env.capabilities);
    const order = sorted.map(c => c.status);
    expect(order[0]).toBe('blocked');
    expect(order[1]).toBe('needs_setup');
    expect(order[2]).toBe('not_installed');
    expect(order[order.length - 1]).toBe('ready');
  });

  it('breaks ties by capability_id ascending', () => {
    const sorted = sortByAttention([
      { capability_id: 'z', status: 'ready' },
      { capability_id: 'a', status: 'ready' },
      { capability_id: 'm', status: 'ready' },
    ]);
    expect(sorted.map(c => c.capability_id)).toEqual(['a', 'm', 'z']);
  });

  it('does not mutate the input array', () => {
    const input = [
      { capability_id: 'x', status: 'ready' },
      { capability_id: 'y', status: 'blocked' },
    ];
    const snapshot = JSON.stringify(input);
    sortByAttention(input);
    expect(JSON.stringify(input)).toBe(snapshot);
  });
});

// ── partitionNextActions ──

describe('capabilities: partitionNextActions', () => {
  it('returns the writer-provided arrays as-is', () => {
    const cap = {
      automatable:    [{ id: 'a', what: 'run script' }],
      human_required: [{ id: 'h', what: 'sign in', human_required_reason: 'browser' }],
    };
    const { automatable, humanRequired } = partitionNextActions(cap);
    expect(automatable.length).toBe(1);
    expect(humanRequired.length).toBe(1);
    expect(humanRequired[0].human_required_reason).toBe('browser');
  });

  it('returns empty arrays when neither side is populated', () => {
    const { automatable, humanRequired } = partitionNextActions({});
    expect(automatable).toEqual([]);
    expect(humanRequired).toEqual([]);
  });
});

// ── getStatusBadge ──

describe('capabilities: getStatusBadge', () => {
  it('returns a label and color for every known status', () => {
    for (const s of CAPABILITY_STATUSES) {
      const badge = getStatusBadge(s);
      expect(badge.label).toBe(STATUS_LABELS[s]);
      expect(badge.color).toBe(STATUS_COLORS[s]);
    }
  });

  it('falls back to an UPPERCASE label for unknown statuses', () => {
    const badge = getStatusBadge('mystery');
    expect(badge.label).toBe('MYSTERY');
    expect(badge.color).toBe('accent');
  });
});
