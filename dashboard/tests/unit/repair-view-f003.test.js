// Plan 2026-06-05-003 F003 — Repair render states, driven purely by fixture inputs.

import { describe, it, expect } from 'vitest';
import {
  deriveRepairView,
  renderRepairPageHTML,
  REPAIR_VIEW_POPULATED,
  REPAIR_VIEW_ZERO,
  REPAIR_VIEW_NEVER_RAN,
  REPAIR_VIEW_CORRUPT,
} from '../../lib/repair-logic.js';

// One auto-safe (derived-state) item + one human-required item.
const ITEMS = [
  { id: 'reexport-state', repair_kind: 're_export_state', safety_class: 'auto_safe',
    apply_tier: 'derived_state',
    exact_command: 'dontpanic repair apply --safe-derived-state --scope fleet',
    plain_consequence: 'Re-derives the render cache from source.' },
  { id: 'rotate-token', repair_kind: 'rotate_secret', safety_class: 'human_required',
    exact_command: 'dontpanic capabilities setup agent-claude-cli',
    plain_consequence: 'Needs a human to paste credentials.' },
];

describe('deriveRepairView (state classification from fixtures)', () => {
  it('populated when the cache ran and has items', () => {
    expect(deriveRepairView({ items: ITEMS, envPresent: true, scope: 'fleet' }).kind).toBe(REPAIR_VIEW_POPULATED);
  });
  it('zero when the cache ran but has nothing to repair', () => {
    expect(deriveRepairView({ items: [], envPresent: true, scope: 'fleet' }).kind).toBe(REPAIR_VIEW_ZERO);
  });
  it('never_ran when no cache is present', () => {
    expect(deriveRepairView({ items: [], envPresent: false, scope: 'fleet' }).kind).toBe(REPAIR_VIEW_NEVER_RAN);
  });
  it('corrupt (distinct from never_ran) when a load/parse error is preserved', () => {
    const v = deriveRepairView({ items: [], envPresent: true, errored: true, scope: 'fleet' });
    expect(v.kind).toBe(REPAIR_VIEW_CORRUPT);
    expect(v.kind).not.toBe(REPAIR_VIEW_NEVER_RAN);
  });
});

describe('renderRepairPageHTML — populated lists items, not just counts', () => {
  const html = renderRepairPageHTML(deriveRepairView({ items: ITEMS, envPresent: true, scope: 'fleet' }));

  it('leads with the actionable count in a stat strip', () => {
    expect(html).toContain('class="stat-strip"');
    expect(html).toContain('Auto-safe now');
  });
  it('LISTS each repair item (the bug: 173 shown as a count with none listed)', () => {
    expect(html).toContain('reexport-state');
    expect(html).toContain('rotate-token');
    expect(html).toContain('Re-derives the render cache from source.');
  });
  it('groups items by safety class with section headers', () => {
    expect(html).toContain('Auto-safe (derived state)');
    expect(html).toContain('Human required');
  });
  it('every per-item action is an honest "Copy …" command with feedback', () => {
    expect(html).toContain('>Copy command</button>');
    expect(html).toContain('copy-cmd-feedback');
    expect(html).toContain('data-copy="dontpanic capabilities setup agent-claude-cli"');
  });
  it('relabels the global action honestly (no execute-implying "Repair automatically")', () => {
    expect(html).toContain('Copy safe-repair command');
    expect(html).not.toContain('Repair automatically');
  });
});

describe('renderRepairPageHTML — the three non-populated states distinguish themselves', () => {
  it('corrupt names a read failure (not the empty/never-ran message)', () => {
    const html = renderRepairPageHTML(deriveRepairView({ envPresent: true, errored: true, scope: 'fleet' }));
    expect(html).toMatch(/could not be read/i);
    expect(html).toContain('banner--error');
  });
  it('never_ran tells the operator to run a scan', () => {
    const html = renderRepairPageHTML(deriveRepairView({ envPresent: false, scope: 'fleet' }));
    expect(html).toMatch(/No repair scan yet/i);
    expect(html).not.toMatch(/could not be read/i);
  });
  it('zero says the scope is clean', () => {
    const html = renderRepairPageHTML(deriveRepairView({ items: [], envPresent: true, scope: 'fleet' }));
    expect(html).toMatch(/Nothing to repair/i);
  });
});
