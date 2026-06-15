// Plan 2026-06-14-001 F010 — real-state → real-shell Operator Channels journey.
//
// Boots the REAL createJarvis() shell against a PRODUCER-EMITTED channel-view
// fixture (dashboard/tests/fixtures/real-state/operator-channels.json — verbatim
// output of operator_channels.build_channel_view, guarded by the Python contract
// test test_operator_channels_fixture_contract). Asserts the Operator Channels
// panel renders the F009 buckets + operator-role matrix, consuming the locked
// rule matrix (deriveBuckets) rather than re-deriving thresholds/precedence.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { setupDOM, setupChartMock, setupFetchMock } from '../helpers/setup.js';
import {
  deriveBuckets,
  BUCKET_IDS,
} from '../../lib/operator-channels-logic.js';

import operatorChannels from '../fixtures/real-state/operator-channels.json' with { type: 'json' };
import capabilities from '../fixtures/real-state/capabilities-status.json' with { type: 'json' };
import security from '../fixtures/real-state/security.json' with { type: 'json' };

// `now` matches the fixture's active-window anchor (12:05 is within 15 min of the
// 12:00–12:02 active records; the 2020 record is stale).
const NOW = Date.parse('2026-06-14T12:05:00Z');

const count = (hay, needle) => hay.split(needle).length - 1;

async function bootShell() {
  setupDOM();
  setupChartMock();
  setupFetchMock({
    'operator-channels': operatorChannels,
    'capabilities-status': capabilities,
    security,
  });
  const { createJarvis } = await import('../../core.js');
  const J = createJarvis();
  globalThis.Jarvis = J; // the page IIFE registers into the real shell
  await import('../../pages/operator-channels/operator-channels.js' + `?j=${Math.random().toString(36).slice(2)}`);
  await J.init();
  return J;
}

describe('Operator Channels real-state journey', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW); // page render uses Date.now() for the active/stale boundary
  });
  afterEach(() => {
    vi.useRealTimers();
    delete globalThis.Jarvis;
  });

  it('boots the shell against the real producer fixture and renders every bucket', async () => {
    const J = await bootShell();
    const el = J.getPageEl('operator-channels');
    expect(el).toBeTruthy();
    const html = el.innerHTML;

    // it IS the real producer output (schema is the producer's, not synthetic)
    expect(operatorChannels.schema).toBe('operator-channels/v0');

    // the panel rendered, with a section for EVERY bucket id (locked matrix)
    for (const id of BUCKET_IDS) {
      expect(html).toContain(`data-bucket="${id}"`);
    }

    // counts match the LOCKED logic exactly — the panel consumes deriveBuckets,
    // it does not re-derive thresholds/precedence.
    const buckets = deriveBuckets(operatorChannels, { now: NOW });
    expect(buckets.same_plan_conflict).toHaveLength(2); // the two active same-plan records
    expect(buckets.stale).toHaveLength(1);
    expect(buckets.unhealthy_worktree_binding).toHaveLength(1);
    // cursor + gemini: both are operator-role values AND non-dispatchable runtimes
    // (cursor is in F001 AGENT_RUNTIMES too), so both legitimately qualify.
    expect(buckets.operator_only_runtime_not_dispatchable.map((r) => r.id)).toEqual(['cursor', 'gemini']);

    // UNCAPPED: same_plan_conflict renders exactly its 2 member rows (no top-N).
    const conflictSection = html.slice(html.indexOf('data-bucket="same_plan_conflict"'));
    const conflictBlock = conflictSection.slice(0, conflictSection.indexOf('</section>'));
    expect(count(conflictBlock, '<li')).toBe(2);

    // the operator-role matrix renders, intent-only (no dispatch claim)
    expect(html).toContain('data-section="operator-role-matrix"');
    expect(html).toContain('intent only');
  });

  it('renders an honest empty surface when no channel-view state is present', async () => {
    setupDOM();
    setupChartMock();
    setupFetchMock({ 'capabilities-status': capabilities, security });
    const { createJarvis } = await import('../../core.js' + `?n=${Math.random()}`);
    const J = createJarvis();
    globalThis.Jarvis = J;
    await import('../../pages/operator-channels/operator-channels.js' + `?j=${Math.random().toString(36).slice(2)}`);
    await J.init();
    const html = J.getPageEl('operator-channels').innerHTML;
    expect(html).toContain('dontpanic dashboard build'); // no fabricated empty buckets
  });
});
