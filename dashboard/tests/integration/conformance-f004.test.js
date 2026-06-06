// Plan 2026-06-05-003 F004 — tiered conformance checks.
//   BLOCKING: shared primitives (components.css) + the migrated Repair page.
//   ADVISORY: an explicit offender ledger for the unmigrated live tabs.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { setupDOM, setupChartMock, setupFetchMock } from '../helpers/setup.js';
import { ALL_PROJECTS_VALUE } from '../../lib/project-selector-logic.js';
import {
  definedClasses,
  emittedClasses,
  unresolvedClasses,
  rawValueOffenders,
  isTokenOnly,
} from '../../lib/conformance.js';
import fleetWhatNow from '../fixtures/real-state/fleet-what-now.json' with { type: 'json' };
import ledger from '../fixtures/conformance-offender-ledger.json' with { type: 'json' };

const __dir = dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(resolve(__dir, '../../', rel), 'utf8');
const pageCss = (name) => read(`pages/${name}/${name}.css`);

describe('F004 detector self-verification (synthetic fixtures)', () => {
  it('rawValueOffenders flags raw color/font/spacing but allows :root + tokens', () => {
    expect(rawValueOffenders('.x { color: #abc123; }')).toHaveLength(1);
    expect(rawValueOffenders('.x { padding: 12px; }')).toHaveLength(1);
    expect(rawValueOffenders('.x { font-size: 14px; }')).toHaveLength(1);
    expect(rawValueOffenders(':root { --c: #abc123; --s: 12px; }')).toHaveLength(0); // sanctioned
    expect(rawValueOffenders('.x { padding: var(--space-3); color: var(--accent); }')).toHaveLength(0);
    // borders / times / transforms are intentionally not flagged
    expect(rawValueOffenders('.x { border: 1px solid var(--border); transition: 0.12s; }')).toHaveLength(0);
  });
  it('unresolvedClasses catches an emitted class with no CSS rule', () => {
    const defined = definedClasses('.known { color: red; }');
    expect(unresolvedClasses(new Set(['known']), defined)).toHaveLength(0);
    expect(unresolvedClasses(new Set(['known', 'ghost-xyz']), defined)).toEqual(['ghost-xyz']);
  });
});

describe('F004 BLOCKING — shared primitives are token-only', () => {
  it('components.css uses only tokens (no raw hex/rgba/font-px/spacing-px)', () => {
    const offenders = rawValueOffenders(read('components.css'));
    expect(offenders, JSON.stringify(offenders)).toEqual([]);
    expect(isTokenOnly(read('components.css'))).toBe(true);
  });
});

describe('F004 BLOCKING — migrated Repair emits no unstyled classes', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); delete globalThis.Jarvis; });

  it('every class Repair renders resolves to a rule in core.css + components.css', async () => {
    setupDOM();
    setupChartMock();
    setupFetchMock({ 'fleet-what-now': fleetWhatNow });
    const { createJarvis } = await import('../../core.js');
    const J = createJarvis();
    globalThis.Jarvis = J;
    const suffix = `?j=${Math.random().toString(36).slice(2)}`;
    await import('../../pages/what-now/what-now.js' + suffix);
    await import('../../pages/repair/repair.js' + suffix);
    await J.init();
    J.state.selectedProject = ALL_PROJECTS_VALUE;
    J.state.fleetWhatNow = { items: fleetWhatNow.items };
    J.switchTo('repair');

    const defined = new Set([
      ...definedClasses(read('core.css')),
      ...definedClasses(read('components.css')),
    ]);
    const emitted = emittedClasses(J.getPageEl('repair'));
    const unresolved = unresolvedClasses(emitted, defined);
    expect(unresolved, `unstyled classes: ${unresolved.join(', ')}`).toEqual([]);
  });
});

describe('F004 ADVISORY — offender ledger reports exactly the current backlog (never fails the suite)', () => {
  it('every ledgered unmigrated tab still carries raw-value debt', () => {
    for (const tab of ledger.unmigrated_live_tabs) {
      expect(rawValueOffenders(pageCss(tab)).length, `${tab} should still have debt`).toBeGreaterThan(0);
    }
  });

  it('the detector finds debt in EXACTLY the ledgered set (shrinks as tabs migrate)', () => {
    // The live tabs that own a page CSS file (Repair has none — it migrated).
    const liveTabsWithCss = [
      'architecture', 'capabilities', 'health', 'mission-control', 'settings', 'what-now',
    ];
    const offenders = liveTabsWithCss.filter((t) => rawValueOffenders(pageCss(t)).length > 0);
    expect(offenders.sort()).toEqual([...ledger.unmigrated_live_tabs].sort());
  });

  it('the migrated Repair tab is NOT in the advisory backlog (it is blocking)', () => {
    expect(ledger.migrated_blocking).toContain('repair');
    expect(ledger.unmigrated_live_tabs).not.toContain('repair');
  });
});
