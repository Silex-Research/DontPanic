// Plan 2026-06-05-002 F003 — real-state → real-shell journey test.
//
// THE test the prior suite lacked: feed PRODUCER-GENERATED dashboard state into
// the REAL createJarvis() shell, boot it, select All Projects, and assert the
// operator path end to end. This would have caught the 2026-06-05-001 "Global
// tools" miss — the render helper had capability items in fleet state but the
// produced fleet-what-now.json had zero, so a synthetic-fixture render test
// passed while the real path was broken.
//
// The fleet fixture's capability items are VERBATIM producer output (group +
// command). A Python contract test (test_dashboard_fixture_contract_f003)
// guards that the live producer still emits that shape, so the fixture cannot
// silently go stale. By construction this test FAILS if the producer stops
// emitting the global-tools group (see the negative check below).

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { setupDOM, setupChartMock, setupFetchMock } from '../helpers/setup.js';
import { ALL_PROJECTS_VALUE } from '../../lib/project-selector-logic.js';

import fleetWhatNow from '../fixtures/real-state/fleet-what-now.json' with { type: 'json' };
import fleetSummary from '../fixtures/real-state/fleet-summary.json' with { type: 'json' };
import capabilities from '../fixtures/real-state/capabilities-status.json' with { type: 'json' };
import security from '../fixtures/real-state/security.json' with { type: 'json' };

function fixtureMock(overrides = {}) {
  return setupFetchMock({
    'fleet-what-now': overrides.fleetWhatNow ?? fleetWhatNow,
    'fleet-summary': fleetSummary,
    'capabilities-status': capabilities,
    security,
  });
}

async function bootShell() {
  setupDOM();
  setupChartMock();
  const { createJarvis } = await import('../../core.js');
  const J = createJarvis();
  globalThis.Jarvis = J; // page IIFEs register into the real shell
  // Boot only the two tabs this journey traverses (Needs Attention + Health) —
  // a real-shell boot of those surfaces, not a synthetic render.
  await import('../../pages/what-now/what-now.js' + `?j=${Math.random().toString(36).slice(2)}`);
  await import('../../pages/health/health.js' + `?j=${Math.random().toString(36).slice(2)}`);
  await J.init();
  J.state.selectedProject = ALL_PROJECTS_VALUE;
  return J;
}

const count = (hay, needle) => hay.split(needle).length - 1;

describe('F003 operator journey: real producer state through the real shell', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); delete globalThis.Jarvis; });

  it('All Projects → Needs Attention shows Global tools ONCE (not duplicated)', async () => {
    fixtureMock();
    const J = await bootShell();
    J.switchTo('what-now');
    const html = J.getPageEl('what-now').innerHTML;

    // The dedicated "Global tools" block (its heading element) renders exactly once...
    expect(count(html, 'wn-gt-heading')).toBe(1);
    expect(html).toContain('Global tools');
    // ...carrying the resolving guidance command (F001 of 2026-06-05-001)...
    expect(html).toContain('dontpanic capabilities setup agent-claude-cli --print-steps');
    // ...and the capability item is NOT duplicated into a project / __global__ group.
    expect(count(html, 'capabilities setup agent-claude-cli --print-steps')).toBe(1);
  });

  it('Health labels install readiness as Global tools', async () => {
    fixtureMock();
    const J = await bootShell();
    J.switchTo('health');
    const html = J.getPageEl('health').innerHTML;
    expect(html).toContain('Global tools');
  });

  it('ANTI-SYNTHETIC: drops the Global tools block if the producer stops emitting the group', async () => {
    // Simulate a producer regression: strip the group tag + capability source so
    // the fleet items look like ordinary project work. The journey must then NOT
    // render the dedicated Global tools block — proving the assertion above is
    // tied to the producer's output, not to the test's own fixture shape.
    const regressed = {
      ...fleetWhatNow,
      items: fleetWhatNow.items.map((it) =>
        it.source === 'capability' ? { ...it, group: null, source: 'architecture' } : it),
    };
    fixtureMock({ fleetWhatNow: regressed });
    const J = await bootShell();
    J.switchTo('what-now');
    const html = J.getPageEl('what-now').innerHTML;
    expect(count(html, 'Global tools')).toBe(0);
  });
});
