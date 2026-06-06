// F009 — lifecycle & refresh: Observer↔Operator mode, mark-as-run overlay,
// state_revision change detection. The GUI and a CLI/agent share one install;
// these keep the GUI honest about concurrent change without executing anything.

import { describe, it, expect } from 'vitest';
import {
  OBSERVER,
  OPERATOR,
  revisionChanged,
  reconcileMarkedRun,
  renderModeToggleHTML,
  renderRefreshHTML,
  deriveInspectView,
  renderInspectHTML,
} from '../../lib/operator-console-logic.js';

const detail = (over = {}) =>
  deriveInspectView({ items: [{ id: 'x', operator_bucket: 'needs_decision', title: 'X',
    why_now: 'w', evidence_uri: 'e', exact_command: 'dontpanic approve x', ...over }] }, 'x');

describe('revisionChanged', () => {
  it('is false on first load (no prior revision)', () => {
    expect(revisionChanged({ state_revision: 'abc' }, null)).toBe(false);
  });
  it('is false when the fingerprint is unchanged', () => {
    expect(revisionChanged({ state_revision: 'abc' }, 'abc')).toBe(false);
  });
  it('is true when the producer state moved underneath', () => {
    expect(revisionChanged({ state_revision: 'def' }, 'abc')).toBe(true);
  });
});

describe('reconcileMarkedRun', () => {
  it('drops marks whose items the producer cleared; keeps marks still present', () => {
    const model = { items: [{ id: 'a' }, { id: 'b' }] };
    const { stillPresent, resolved } = reconcileMarkedRun(['a', 'gone'], model);
    expect(stillPresent).toEqual(['a']);
    expect(resolved).toEqual(['gone']);
  });
  it('handles an empty overlay', () => {
    expect(reconcileMarkedRun([], { items: [{ id: 'a' }] })).toEqual({ stillPresent: [], resolved: [] });
  });
});

describe('renderModeToggleHTML', () => {
  it('offers both modes and marks the active one', () => {
    const html = renderModeToggleHTML(OBSERVER);
    expect(html).toContain('data-mode="observer"');
    expect(html).toContain('data-mode="operator"');
    expect(html).toContain('aria-pressed="true"'); // the active one
    expect(html).toMatch(/data-mode="observer"[^>]*is-active|is-active[^>]*data-mode="observer"/);
  });
});

describe('renderRefreshHTML', () => {
  it('always offers refresh; flags a changed state', () => {
    expect(renderRefreshHTML({ revisionChanged: false })).toContain('refresh-btn');
    const changed = renderRefreshHTML({ revisionChanged: true });
    expect(changed).toContain('State changed');
  });
});

describe('renderInspectHTML mode gating', () => {
  it('Operator mode carries the copy affordances + a Mark-as-run control', () => {
    const html = renderInspectHTML(detail(), { mode: OPERATOR, markedRun: [] });
    expect(html).toContain('copy-cmd-btn');
    expect(html).toContain('data-mark-run="x"');
  });
  it('a marked item shows the run state instead of the button', () => {
    const html = renderInspectHTML(detail(), { mode: OPERATOR, markedRun: ['x'] });
    expect(html).toContain('Marked as run');
    expect(html).not.toContain('data-mark-run="x"');
  });
  it('Observer mode is pure-read — no copy buttons', () => {
    const html = renderInspectHTML(detail(), { mode: OBSERVER });
    expect(html).not.toContain('copy-cmd-btn');
    expect(html).toContain('Observer mode');
    // it still shows the evidence/context (read is always allowed)
    expect(html).toContain('dontpanic approve x');
  });
  it('defaults to Operator when no mode is passed (back-compat with F007/F008)', () => {
    expect(renderInspectHTML(detail())).toContain('copy-cmd-btn');
  });
});
