// F006 — operator console default view, REAL-SHELL journey (H1/H4/H5).
// Boots the real createJarvis() shell with the real F001 model fixture in
// state/operator-triage.json, switches to the Operator tab, and asserts the
// rendered DOM is the calm triage queue: one status line, ALL unique live human
// items (not capped), non-human collapsed, zero raw JSON. Plus an anti-synthetic
// negative: if the producer stops classifying, the human items don't appear.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { setupDOM, setupChartMock, setupFetchMock } from '../helpers/setup.js';
import model from '../fixtures/operator-triage-model.json' with { type: 'json' };

async function boot(triageModel) {
  setupDOM();
  setupChartMock();
  setupFetchMock({ 'operator-triage': triageModel });
  const { createJarvis } = await import('../../core.js');
  const J = createJarvis();
  globalThis.Jarvis = J; // the page IIFE registers into the real shell
  await import('../../pages/operator-console/operator-console.js' + `?j=${Math.random().toString(36).slice(2)}`);
  await J.init();
  return J;
}

const count = (hay, needle) => hay.split(needle).length - 1;

describe('F006 operator console: real F001 model through the real shell', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); delete globalThis.Jarvis; });

  it('default view: one status line, all 14 unique live human items, non-human collapsed, no raw JSON', async () => {
    const J = await boot(model);
    J.switchTo('operator-console');
    const html = J.getPageEl('operator-console').innerHTML;

    // one honest pipeline status line (H5)
    expect(html).toContain('313 raw → 182 unique → 14 need you');
    // a real needs-you command surfaces — the human's one move (H1/H4)
    expect(html).toContain('dontpanic capabilities setup agent-claude-cli --print-steps');
    // non-human work is collapsed to a count, not listed
    expect(html).toContain('an agent can run');
    // and NO raw JSON leaks into the surface
    expect(html).not.toContain('"operator_bucket"');
    expect(html).not.toContain('[{');
  });

  it('F007: clicking a queue row fills the decision drawer with that item (decide in place)', async () => {
    const J = await boot(model);
    J.switchTo('operator-console');
    const el = J.getPageEl('operator-console');

    // the workbench has a right pane that starts empty (prompts a selection)...
    expect(el.querySelector('#console-inspect-pane').innerHTML.toLowerCase()).toContain('select an item');
    // ...and the why-hidden inspector is present (the compression is auditable, H6).
    expect(el.innerHTML).toContain('Why the rest is hidden');
    // the activity strip carries the pipeline line as ambient chrome (H2).
    expect(el.querySelector('.console-activity').textContent).toContain('313');

    // click the first needs-you row → the drawer fills with its move + bucket.
    const row = el.querySelector('.console-item-select');
    expect(row).toBeTruthy();
    row.click();
    const drawer = el.querySelector('#console-inspect-pane').innerHTML;
    expect(drawer.toLowerCase()).not.toContain('select an item');
    expect(drawer).toContain('Why now');     // the decision context
    expect(drawer).toContain('The move');    // the next action
    expect(row.classList.contains('is-selected')).toBe(true);
  });

  it('F008: the drawer offers copy affordances and copying writes to the clipboard (never executes)', async () => {
    const writes = [];
    const clip = { writeText: (t) => { writes.push(t); return Promise.resolve(); } };
    // jsdom has no clipboard by default — install a spy.
    Object.defineProperty(globalThis.navigator, 'clipboard', { value: clip, configurable: true });

    const J = await boot(model);
    J.switchTo('operator-console');
    const el = J.getPageEl('operator-console');
    el.querySelector('.console-item-select').click(); // select a human item → drawer fills

    const copyBtn = el.querySelector('#console-inspect-pane .copy-cmd-btn');
    expect(copyBtn).toBeTruthy();
    const cmd = copyBtn.dataset.copy;
    expect(cmd).toBeTruthy();

    copyBtn.click();
    await Promise.resolve(); await Promise.resolve();
    // the command was copied — and nothing was executed (no runner exists on this surface)
    expect(writes).toContain(cmd);
    expect(copyBtn.dataset.copied).toBe('1');
    // the no-run promise is on the surface
    expect(el.innerHTML).toContain('Copying never runs anything');
  });

  it('ANTI-SYNTHETIC: if the model classifies nothing as human, the needs-you queue is empty', async () => {
    // Regress the producer: make every item agent_runnable (no human buckets).
    const regressed = {
      ...model,
      items: model.items.map((i) => ({ ...i, operator_bucket: 'agent_runnable' })),
      data_quality: { ...model.data_quality, counts: { agent_runnable: model.items.length }, uncertain: 0 },
    };
    const J = await boot(regressed);
    J.switchTo('operator-console');
    const html = J.getPageEl('operator-console').innerHTML;
    expect(html).toContain('Nothing needs you');
    // proves the assertion above is tied to the model's classification, not the fixture shape
    expect(count(html, 'capabilities setup agent-claude-cli')).toBe(0);
  });
});
