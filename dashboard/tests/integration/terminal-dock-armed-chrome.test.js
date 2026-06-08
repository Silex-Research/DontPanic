// Audit 2026-06-08 remediation (B2#1/B2#3): test the REAL terminal dock that
// production loads (terminal-dock.js, the IIFE wired in index.html) — NOT the
// unused armed-terminal.js component. The prior "journey" asserted a standalone
// component the shell never mounts; this boots the real dock with a mocked
// /terminal/session and asserts the armed hazard chrome on the real surface.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const DOCK_SRC = readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), '../../terminal-dock.js'),
  'utf-8'
);

async function bootRealDock(session) {
  document.body.innerHTML = '';
  // xterm globals the dock references lazily; not needed for the chrome path.
  globalThis.fetch = vi.fn(async (url) => {
    if (String(url).includes('/terminal/session')) {
      return { ok: true, json: async () => session };
    }
    return { ok: false, json: async () => ({}) };
  });
  // Run the real IIFE; it calls init() immediately (readyState !== 'loading').
  // eslint-disable-next-line no-new-func
  new Function(DOCK_SRC)();
  // Let the fetch().then(r=>r.json()).then(applySessionChrome) microtask chain settle.
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

describe('real terminal dock chrome (production terminal-dock.js)', () => {
  beforeEach(() => { vi.useRealTimers(); });
  afterEach(() => { vi.restoreAllMocks(); delete globalThis.fetch; });

  it('armed session → the warn element announces via role=alert + assertive aria-live', async () => {
    await bootRealDock({ enabled: true, cwd_label: 'repo root' });
    const warn = document.querySelector('.term-dock-warn');
    expect(warn).not.toBeNull();
    expect(warn.classList.contains('is-armed')).toBe(true);
    expect(warn.getAttribute('role')).toBe('alert');
    expect(warn.getAttribute('aria-live')).toBe('assertive');
    expect(warn.textContent).toMatch(/unrestricted/i);
  });

  it('disabled session → no hazard chrome, no alert semantics (never fake-armed)', async () => {
    await bootRealDock({ enabled: false });
    const warn = document.querySelector('.term-dock-warn');
    expect(warn).not.toBeNull();
    expect(warn.classList.contains('is-armed')).toBe(false);
    expect(warn.getAttribute('role')).toBeNull();
    expect(warn.getAttribute('aria-live')).toBeNull();
    expect(warn.textContent).toBe('');
  });
});
