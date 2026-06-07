// Plan 2026-06-06-005 F003 — real-state → real-shell journey for the default Cockpit.
//
// The test the mount/state unit tests can't be: feed PRODUCER-GENERATED triage state into the
// REAL createJarvis() shell, boot it, and assert the operator lands on the Cockpit rendering the
// real queue — queue count, no raw JSON, honest freshness, resolution intents — plus the
// anti-synthetic negatives (missing / stale state render an honest surface, never fake-fresh).
//
// The operator-triage fixture is NOT hand-authored: it is write_triage_state() run over the SAME
// producer-generated fleet-what-now.json items the existing dashboard journey already guards, and a
// Python contract test (test_cockpit_fixture_contract_f003) re-derives it from the live producer so
// it cannot silently drift. By construction this fails if the producer stops emitting the F001 fields.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { setupDOM, setupChartMock, setupFetchMock } from '../helpers/setup.js';

import triage from '../fixtures/real-state/operator-triage.json' with { type: 'json' };
import fleetSummary from '../fixtures/real-state/fleet-summary.json' with { type: 'json' };

const NEED = new Set(['needs_auth', 'needs_decision', 'agent_runnable']);
const needCount = (m) => m.items.filter((i) => NEED.has(i.operator_bucket)).length;
const freshTriage = (overrides = {}) => ({ ...triage, generated_at: new Date().toISOString(), ...overrides });

async function bootShell(triageState) {
  setupDOM();
  setupChartMock();
  const fixtures = { 'fleet-summary': fleetSummary };
  if (triageState !== undefined) fixtures['operator-triage'] = triageState; // omit → 404 → missing
  setupFetchMock(fixtures);
  const { createJarvis } = await import('../../core.js');
  const J = createJarvis();
  globalThis.Jarvis = J; // the cockpit page IIFE registers into the real shell
  await import('../../pages/cockpit/cockpit-page.js' + `?j=${Math.random().toString(36).slice(2)}`);
  await J.init();
  return J;
}

describe('F003 cockpit journey: real producer state through the real shell', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-06-07T12:00:00Z')); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); delete globalThis.Jarvis; });

  it('boots → lands on the Cockpit rendering the real queue (count, no raw JSON, intents, honest freshness)', async () => {
    const J = await bootShell(freshTriage());
    expect(J.currentPage).toBe('cockpit'); // the landing surface

    const el = J.getPageEl('cockpit');
    const html = el.innerHTML;

    // (1) queue count correct — the hero "need you" count equals the producer's need-you items
    expect(el.querySelector('.dp-cockpit')).toBeTruthy();
    expect(el.querySelector('.dp-hero-count').textContent).toBe(String(needCount(triage)));
    // (2) no raw JSON leaked into the operator surface
    expect(html).not.toContain('"schema"');
    expect(html).not.toContain('operator-triage/v0');
    // (3) resolution intents reached the face (the human's buttons == the agent's options)
    expect(el.querySelector('[data-resolution]')).toBeTruthy();
    // (4) render-truth: with no item_probe basis in v0, NO freshness dot is shown as proven-live
    expect(el.querySelector('[data-filled="true"]')).toBeNull();
  });

  it('anti-synthetic — missing triage state renders an honest build prompt, not a fabricated queue', async () => {
    const J = await bootShell(undefined); // operator-triage 404s
    const el = J.getPageEl('cockpit');
    expect(el.querySelector('.dp-cockpit-empty')).toBeTruthy();
    expect(el.querySelector('.dp-cockpit')).toBeNull();
    expect(el.textContent).toContain('dontpanic dashboard build');
  });

  it('anti-synthetic — stale state is demoted under a banner, never rendered as fresh', async () => {
    const old = new Date(Date.now() - 30 * 3600 * 1000).toISOString();
    const J = await bootShell(freshTriage({ generated_at: old }));
    const el = J.getPageEl('cockpit');
    expect(el.querySelector('.dp-stale-banner')).toBeTruthy();
    expect(el.querySelector('.dp-cockpit')).toBeTruthy(); // queue still shown, just demoted
  });
});
