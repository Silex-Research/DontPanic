// Plan 2026-06-07-003 (operator-console 008) F002 — legacy theme bridge.
// The bridge maps the legacy core.css colour variables onto the --dp-* design
// tokens so a theme/density swap survives onto legacy pages, with no per-page
// edits and no raw hex. Verified as a CSS contract (jsdom can't resolve var()
// cascades); the real-shell theme swap is exercised by the F004 journey.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const DASH = resolve(HERE, '../..');
const bridge = readFileSync(resolve(DASH, 'legacy-theme-bridge.css'), 'utf8');
const indexHtml = readFileSync(resolve(DASH, 'index.html'), 'utf8');

const LEGACY_TO_DP = {
  '--bg-primary': '--dp-bg',
  '--bg-secondary': '--dp-surface-1',
  '--bg-card': '--dp-surface-1',
  '--bg-card-hover': '--dp-surface-2',
  '--border': '--dp-border',
  '--text-primary': '--dp-text-1',
  '--text-secondary': '--dp-text-2',
  '--text-muted': '--dp-text-3',
};

describe('legacy theme bridge (008 F002)', () => {
  it('maps every legacy colour var onto a --dp-* token', () => {
    for (const [legacy, dp] of Object.entries(LEGACY_TO_DP)) {
      const re = new RegExp(`${legacy}\\s*:\\s*var\\(\\s*${dp}\\s*\\)`);
      expect(bridge).toMatch(re);
    }
  });

  it('carries no raw hex (it must defer entirely to the tokens)', () => {
    expect(bridge).not.toMatch(/#[0-9a-fA-F]{3,6}\b/);
  });

  it('is loaded AFTER core.css so the bridge wins', () => {
    const core = indexHtml.indexOf('core.css');
    const br = indexHtml.indexOf('legacy-theme-bridge.css');
    expect(core).toBeGreaterThan(-1);
    expect(br).toBeGreaterThan(core);
  });

  it('only redefines colour vars — it does not introduce new component rules', () => {
    // The bridge is variable-only: no selectors beyond :root, so it can never
    // accidentally restyle a legacy component, only re-point its colours.
    const noComments = bridge.replace(/\/\*[\s\S]*?\*\//g, '');
    const selectors = (noComments.match(/([^{}]+)\{/g) || []).map((s) =>
      s.replace(/\{$/, '').trim()
    );
    expect(selectors.length).toBeGreaterThan(0);
    for (const sel of selectors) expect(sel).toBe(':root');
  });
});
