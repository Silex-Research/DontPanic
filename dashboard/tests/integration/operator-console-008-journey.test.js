// Plan 2026-06-07-003 (operator-console 008) F004 — real-shell journey.
//
// Boots the REAL createJarvis() shell and exercises the three 008 usability
// seams against the booted document rather than a synthetic mount:
//   F002 — a theme/density swap toggles the root attributes the --dp-* tokens +
//          legacy bridge cascade from (so legacy pages re-colour).
//   F001 — the armed-terminal dock shows hazard chrome only when armed, mounted
//          into the live shell DOM.
//   F003 — the shared surface-state renderer produces the right honest chrome
//          for every one of the five states inside the shell document.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { setupDOM, setupChartMock, setupFetchMock } from '../helpers/setup.js';
import { SURFACE_STATES, renderSurfaceChrome } from '../../lib/surface-state.js';
import { renderTerminalDock } from '../../components/armed-terminal.js';

async function bootShell() {
  setupDOM();
  setupChartMock();
  setupFetchMock({});
  const tokens = await import('../../lib/tokens.js');
  const { createJarvis } = await import('../../core.js');
  const J = createJarvis();
  globalThis.Jarvis = J;
  await J.init();
  return { J, tokens };
}

describe('operator-console 008 journey: chrome + theming + state matrix through the real shell', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-08T12:00:00Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    delete globalThis.Jarvis;
  });

  it('boots the real shell, then a theme + density swap survives on the root', async () => {
    const { tokens } = await bootShell();
    const root = document.documentElement;

    tokens.setTheme('light', document);
    expect(root.getAttribute('data-theme')).toBe('light');
    tokens.setTheme('dark', document);
    expect(root.getAttribute('data-theme')).toBe('dark');

    tokens.setDensity('dense', document);
    expect(root.getAttribute('data-density')).toBe('dense');
    tokens.setDensity('comfort', document);
    expect(root.getAttribute('data-density')).toBe('comfort');

    // toggleTheme flips it (the header chip's affordance) — survives a round trip.
    const before = tokens.getTheme(document);
    tokens.toggleTheme(document);
    expect(tokens.getTheme(document)).not.toBe(before);
  });

  it('armed-terminal chrome mounts into the live shell DOM (disarmed → no hazard; armed → hazard alert)', async () => {
    await bootShell();
    const host = document.createElement('div');
    document.body.appendChild(host);

    host.appendChild(renderTerminalDock({}));
    expect(host.querySelector('.dp-hazard-frame')).toBeNull();
    expect(host.querySelector('[data-action="arm"]')).not.toBeNull();

    host.replaceChildren(renderTerminalDock({ armed: true, scope: 'repo root' }));
    const frame = host.querySelector('.dp-hazard-frame');
    expect(frame).not.toBeNull();
    expect(frame.getAttribute('role')).toBe('alert');
    expect(frame.getAttribute('aria-live')).toBe('assertive');
    expect(host.querySelector('[data-action="disarm"]')).not.toBeNull();
    expect(host.querySelector('[data-action="arm"]')).toBeNull();
  });

  it('surface-state matrix renders honest chrome for all five states inside the shell', async () => {
    await bootShell();
    const host = document.createElement('div');
    document.body.appendChild(host);
    const NOW = Date.parse('2026-06-08T12:00:00Z');
    const old = NOW - 48 * 60 * 60 * 1000;

    const seen = new Set();
    for (const state of SURFACE_STATES) {
      const chrome = renderSurfaceChrome(state, { label: 'health', generatedAt: old, now: NOW });
      if (state === 'ready') {
        expect(chrome).toBeNull(); // ready yields to the surface's own content
        continue;
      }
      host.replaceChildren(chrome);
      const node = host.querySelector('[data-surface-state]');
      expect(node.dataset.surfaceState).toBe(state);
      seen.add(state);
    }
    expect(seen).toEqual(new Set(['loading', 'error', 'missing', 'stale']));

    // render-truth: stale admits its age, error offers retry — never a blank or a fake-fresh face.
    host.replaceChildren(renderSurfaceChrome('stale', { label: 'health', generatedAt: old, now: NOW }));
    expect(host.textContent.toLowerCase()).toMatch(/out of date/);
    host.replaceChildren(renderSurfaceChrome('error', { label: 'health' }));
    expect(host.querySelector('[data-action="retry"]')).not.toBeNull();
  });
});
