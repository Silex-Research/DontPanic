// Plan 2026-06-07-003 (operator-console 008) F001 — armed-terminal hazard chrome.
// Pins the trust-boundary contract: OFF by default, a persistent hazard frame
// only when armed (role=alert + assertive live region + scope), disarm-only, and
// token-only colours with no new backend/exec channel.
import { describe, it, expect } from 'vitest';
import { renderTerminalDock, isArmed } from '../../components/armed-terminal.js';

describe('armed-terminal chrome (008 F001)', () => {
  it('is OFF by default — quiet bar, an Arm control, no hazard frame', () => {
    const dock = renderTerminalDock({});
    expect(isArmed({})).toBe(false);
    expect(dock.dataset.armed).toBe('false');
    expect(dock.querySelector('.dp-hazard-frame')).toBeNull();
    expect(dock.querySelector('[role="alert"]')).toBeNull();
    const arm = dock.querySelector('[data-action="arm"]');
    expect(arm).not.toBeNull();
    expect(dock.querySelector('[data-action="disarm"]')).toBeNull();
  });

  it('armed → persistent hazard frame, role=alert + assertive live region, scope shown', () => {
    const dock = renderTerminalDock({ armed: true, scope: 'packages/gateway' });
    expect(dock.dataset.armed).toBe('true');
    const frame = dock.querySelector('.dp-hazard-frame');
    expect(frame).not.toBeNull();
    expect(frame.getAttribute('role')).toBe('alert');
    expect(frame.getAttribute('aria-live')).toBe('assertive');
    expect(frame.getAttribute('aria-atomic')).toBe('true');
    expect(dock.querySelector('.dp-hazard-scope').textContent).toContain('packages/gateway');
  });

  it('armed is disarm-only — a Disarm control and no arm/close/dismiss control', () => {
    const dock = renderTerminalDock({ armed: true });
    expect(dock.querySelector('[data-action="disarm"]')).not.toBeNull();
    expect(dock.querySelector('[data-action="arm"]')).toBeNull();
    expect(dock.querySelector('[data-action="close"]')).toBeNull();
    expect(dock.querySelector('[data-action="dismiss"]')).toBeNull();
  });

  it('colours are token-only — the component emits no raw hex and no inline colour', () => {
    const armed = renderTerminalDock({ armed: true, scope: 'repo root' });
    const off = renderTerminalDock({});
    for (const dock of [armed, off]) {
      expect(dock.outerHTML).not.toMatch(/#[0-9a-fA-F]{3,6}\b/);
      expect(dock.outerHTML).not.toMatch(/style="[^"]*color/i);
    }
  });

  it('introduces no new backend/exec channel — buttons carry only arm/disarm intents', () => {
    const dock = renderTerminalDock({ armed: true });
    const actions = [...dock.querySelectorAll('[data-action]')].map((n) => n.dataset.action);
    expect(new Set(actions).size).toBeGreaterThan(0);
    for (const a of actions) expect(['arm', 'disarm']).toContain(a);
  });
});
