/*
 * Cockpit default mount — plan 2026-06-06-005 F002.
 * Pins the MOUNT (not just the components, which cockpit-gate.test.js already covers):
 * the cockpit page registers via Jarvis.registerPage, renders renderQueue from the live
 * operator-triage model into its container, opens the inspect-why panel on card click,
 * shows an honest empty state when the model is absent, leads pageModules as the landing
 * surface, and leaves the old Operator console + other tabs registered.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { pageModules } from '../../core.js';

const MODEL = {
  schema: 'operator-triage/v0',
  state_revision: 'rev-1',
  items: [
    { id: 'd1', title: 'Approve the auditor verdict', operator_bucket: 'needs_decision', scope: 'project',
      project_name: 'mercury', run_state: 'running', why_now: 'auditor returned needs_changes',
      resolution: ['approve', 'request_changes', 'reject'], freshness_basis: null,
      provenance_source: 'claude-auditor', actor_label: 'Claude Auditor', asserted_at: '2026-06-07T00:00:00Z' },
    { id: 'q1', title: 'quiet thing', operator_bucket: 'quiet', scope: 'project', project_name: 'mercury',
      run_state: 'idle', resolution: [], freshness_basis: null },
  ],
};

async function mountCockpit() {
  const container = document.createElement('div');
  let registered = null;
  globalThis.Jarvis = {
    registerPage: (cfg) => { registered = cfg; },
    getPageEl: () => container,
  };
  vi.resetModules();
  await import('../../pages/cockpit/cockpit-page.js');
  return { container, page: registered };
}

describe('F002 — cockpit registers as a page', () => {
  it('registers id "cockpit" with a label + lifecycle hooks', async () => {
    const { page } = await mountCockpit();
    expect(page.id).toBe('cockpit');
    expect(page.label).toBe('Cockpit');
    expect(typeof page.init).toBe('function');
    expect(typeof page.onActivate).toBe('function');
  });
});

describe('F002 — renders the live triage model via the redesign components', () => {
  let container; let page;
  beforeEach(async () => { ({ container, page } = await mountCockpit()); });

  it('mounts renderQueue (hero count + grouped feed) from state.operatorTriage', () => {
    page.init({ operatorTriage: MODEL });
    expect(container.querySelector('.dp-cockpit')).toBeTruthy();
    expect(container.querySelector('.dp-hero-count').textContent).toBe('1'); // one needs_decision
    expect(container.querySelector('.dp-group--needs_decision')).toBeTruthy();
    // render-truth: no raw JSON dump in the mounted surface
    expect(container.textContent).not.toContain('"schema"');
    expect(container.textContent).not.toContain('operator-triage/v0');
  });

  it('clicking a card opens the inspect-why panel for that item', () => {
    page.init({ operatorTriage: MODEL });
    const card = container.querySelector('[data-item-id="d1"]');
    expect(card).toBeTruthy();
    card.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    const panel = container.querySelector('.dp-cockpit-inspect .dp-inspect');
    expect(panel).toBeTruthy();
    expect(panel.querySelector('.dp-inspect-title').textContent).toContain('Approve the auditor verdict');
    // render-truth carried through the mount: hollow freshness basis is stated plainly
    expect(panel.querySelector('.dp-inspect-basis').textContent).toContain('no basis');
  });

  it('absent model renders an honest empty state, never a fabricated queue', () => {
    page.init({ operatorTriage: null }); // init sets the container, then renders the missing state
    expect(container.querySelector('.dp-cockpit-empty')).toBeTruthy();
    expect(container.querySelector('.dp-cockpit')).toBeNull();
    expect(container.textContent).toContain('dontpanic dashboard build');
  });
});

describe('F002 — landing surface, old tabs preserved', () => {
  it('cockpit leads pageModules (the landing surface)', () => {
    expect(pageModules[0]).toBe('pages/cockpit/cockpit-page.js');
  });

  it('the old Operator console + other tabs stay registered', () => {
    expect(pageModules).toContain('pages/operator-console/operator-console.js');
    expect(pageModules).toContain('pages/what-now/what-now.js');
    expect(pageModules.length).toBeGreaterThanOrEqual(9);
  });
});

describe('F004 — honest state matrix on the Cockpit', () => {
  it('loading: no resolved model yet → a skeleton, never a blank', async () => {
    const { container, page } = await mountCockpit();
    page.init({}); // no operatorTriage key → the load has not resolved
    expect(container.querySelector('.dp-cockpit-skeleton')).toBeTruthy();
    expect(container.querySelector('.dp-cockpit')).toBeNull();
  });

  it('stale: an old model renders UNDER a stale banner — demoted, not hidden', async () => {
    const { container, page } = await mountCockpit();
    const old = { ...MODEL, generated_at: new Date(Date.now() - 30 * 3600 * 1000).toISOString() };
    page.init({ operatorTriage: old });
    expect(container.querySelector('.dp-stale-banner')).toBeTruthy();
    expect(container.querySelector('.dp-cockpit')).toBeTruthy();      // the queue is still shown
    expect(container.querySelector('.dp-hero-count').textContent).toBe('1');
  });

  it('error: a failed refresh shows last-good under an error banner + retry, never fake-fresh', async () => {
    const { container, page } = await mountCockpit();
    page.init({ operatorTriage: MODEL });                              // good first load → last-good captured
    globalThis.fetch = vi.fn(() => Promise.reject(new Error('network')));
    await page.refresh();
    expect(container.querySelector('.dp-error-banner')).toBeTruthy();
    expect(container.querySelector('.dp-cockpit-retry')).toBeTruthy();
    expect(container.querySelector('.dp-cockpit')).toBeTruthy();       // last-good queue retained
  });

  it('error→recover: clicking retry re-fetches and returns to the live queue', async () => {
    const { container, page } = await mountCockpit();
    page.init({ operatorTriage: MODEL });
    globalThis.fetch = vi.fn(() => Promise.reject(new Error('network')));
    await page.refresh();
    expect(container.querySelector('.dp-error-banner')).toBeTruthy();
    globalThis.fetch = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(MODEL) }));
    container.querySelector('.dp-cockpit-retry').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    await new Promise((r) => setTimeout(r, 0));                        // flush the fetch chain
    expect(container.querySelector('.dp-error-banner')).toBeNull();
    expect(container.querySelector('.dp-cockpit')).toBeTruthy();
  });
});
