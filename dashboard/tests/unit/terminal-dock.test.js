// Embedded terminal dock — frontend smoke test (plan 2026-06-06-002).
// Asserts the always-visible dock renders, surfaces the governance warning +
// scope when the terminal is armed, and shows an honest off-hint when it isn't.
// (xterm itself isn't exercised here — only the dock chrome + session branch.)

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { setupDOM } from '../helpers/setup.js';

async function bootDock(session) {
  setupDOM();
  globalThis.fetch = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(session) }));
  await import('../../terminal-dock.js?j=' + Math.random().toString(36).slice(2));
  // let the session fetch + applySessionChrome resolve
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
}

describe('terminal dock', () => {
  beforeEach(() => { vi.restoreAllMocks(); });
  afterEach(() => { delete globalThis.fetch; });

  it('always renders the dock bar (collapsed) regardless of state', async () => {
    await bootDock({ enabled: false });
    const dock = document.querySelector('.term-dock');
    expect(dock).toBeTruthy();
    expect(dock.classList.contains('term-dock--collapsed')).toBe(true);
    expect(document.querySelector('.term-dock-title').textContent).toContain('Terminal');
  });

  it('when ENABLED, surfaces the governance warning + scope (the visible contract)', async () => {
    await bootDock({ enabled: true, token: 't', cwd: '/x/DontPanic', cwd_label: 'DontPanic', unrestricted: true });
    const warn = document.querySelector('.term-dock-warn');
    expect(warn.textContent).toContain('Terminal enabled');
    expect(warn.textContent).toContain('local shell');
    expect(warn.textContent).toContain('DontPanic');
    expect(warn.textContent).toContain('unrestricted commands');
    expect(warn.classList.contains('is-armed')).toBe(true);
    expect(document.querySelector('.term-dock-scope').textContent).toContain('Shell: DontPanic');
  });

  it('when DISABLED, shows an honest off-hint and NO warning', async () => {
    await bootDock({ enabled: false });
    expect(document.querySelector('.term-dock-warn').textContent).toBe('');
    expect(document.querySelector('.term-dock-status').textContent.toLowerCase()).toContain('--enable-terminal');
  });
});
