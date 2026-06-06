// Plan 2026-06-05-003 F003 — Repair real-state → real-shell journey.
//
// Boots the REAL shell, feeds VERBATIM producer what-now items into Repair, and
// asserts the operator can see + act on the per-item repair set — the thing the
// old Repair tab could not do (it showed a count with nothing listed).

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { setupDOM, setupChartMock, setupFetchMock } from '../helpers/setup.js';
import { ALL_PROJECTS_VALUE } from '../../lib/project-selector-logic.js';
import fleetWhatNow from '../fixtures/real-state/fleet-what-now.json' with { type: 'json' };

async function bootRepair(stateOverrides = {}) {
  setupDOM();
  setupChartMock();
  setupFetchMock({ 'fleet-what-now': fleetWhatNow });
  const { createJarvis } = await import('../../core.js');
  const J = createJarvis();
  globalThis.Jarvis = J;
  const suffix = `?j=${Math.random().toString(36).slice(2)}`;
  // what-now first so the default active page is NOT repair — that lets a later
  // switchTo('repair') re-activate and render against the state we set below.
  await import('../../pages/what-now/what-now.js' + suffix);
  await import('../../pages/repair/repair.js' + suffix);
  await J.init();
  J.state.selectedProject = ALL_PROJECTS_VALUE;
  // Verbatim producer fleet what-now items drive the repair surface.
  J.state.fleetWhatNow = { items: fleetWhatNow.items, ...stateOverrides };
  return J;
}

describe('F003 Repair journey: producer state through the real shell', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); delete globalThis.Jarvis; });

  it('renders the per-item repair set on the design-system primitives (not just a count)', async () => {
    const J = await bootRepair();
    J.switchTo('repair');
    const html = J.getPageEl('repair').innerHTML;

    expect(html).toContain('class="page"');         // page skeleton (F002)
    expect(html).toContain('class="stat-strip"');   // leads with counts (F001)
    expect(html).toContain('class="card');          // items are LISTED as cards
    // every producer item id is actually rendered, not summarized away
    for (const it of fleetWhatNow.items) {
      expect(html).toContain(it.id);
    }
  });

  it('exposes honest copy-commands with feedback for the per-item actions', async () => {
    const J = await bootRepair();
    J.switchTo('repair');
    const html = J.getPageEl('repair').innerHTML;
    expect(html).toContain('>Copy command</button>');
    expect(html).toContain('copy-cmd-feedback');
    expect(html).not.toContain('Repair automatically'); // no execute-implying label
  });

  it('a copy click writes feedback into the aria-live region (read-only, no execution)', async () => {
    const writeText = vi.fn().mockResolvedValue();
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    const J = await bootRepair();
    J.switchTo('repair');
    const el = J.getPageEl('repair');
    const btn = el.querySelector('.copy-cmd-btn');
    expect(btn).not.toBeNull();
    btn.click();
    await Promise.resolve();
    expect(writeText).toHaveBeenCalledOnce();
    expect(btn.dataset.copied).toBe('1');
    const feedback = btn.parentElement.querySelector('.copy-cmd-feedback');
    expect(feedback.textContent).toMatch(/Copied/);
  });

  it('distinguishes the corrupt-cache state from never-ran (from the error envelope)', async () => {
    const J = await bootRepair();
    J.switchTo('repair'); // render populated first
    J.switchTo('what-now'); // leave repair so the next switch re-activates it
    J.state.fleetWhatNow = { error: 'parse failure', items: [] };
    J.switchTo('repair');
    const html = J.getPageEl('repair').innerHTML;
    expect(html).toMatch(/could not be read/i);
    expect(html).toContain('banner--error');
  });
});
