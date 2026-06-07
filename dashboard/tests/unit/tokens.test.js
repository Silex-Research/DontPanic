/*
 * F002 — semantic token layer (plan 2026-06-06-004, spec §2/§8).
 * Pins: the token vocabulary is complete; every meaning-bearing token is themed in BOTH
 * light + dark; density overrides exist; the redesign palette lives ONLY in tokens.css
 * (components reference tokens, never raw hex); and the data-theme/data-density controller
 * swaps :root correctly.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  THEMES, DENSITIES, DEFAULT_THEME, DEFAULT_DENSITY,
  BUCKETS, FRESHNESS, SCOPES, RUN_STATES, bucketToken,
  setTheme, setDensity, getTheme, getDensity, toggleTheme, toggleDensity, initThemeDefaults,
} from '../../lib/tokens.js';

const here = dirname(fileURLToPath(import.meta.url));
const dashRoot = join(here, '..', '..');
const tokensCss = readFileSync(join(dashRoot, 'tokens.css'), 'utf8');

function block(css, selector) {
  // return the body of the first `selector { … }` rule (no nested braces in this file)
  const start = css.indexOf(selector);
  if (start < 0) return '';
  const open = css.indexOf('{', start);
  const close = css.indexOf('}', open);
  return css.slice(open + 1, close);
}

const rootBlock = block(tokensCss, ':root {');
const lightBlock = block(tokensCss, ':root[data-theme="light"]');
const denseBlock = block(tokensCss, ':root[data-density="dense"]');

const bucketVars = BUCKETS.map((b) => `--bucket-${b.replace(/_/g, '-')}`);
const freshVars = FRESHNESS.map((f) => `--freshness-${f}`);
const scopeVars = SCOPES.map((s) => `--scope-${s}`);
const runVars = RUN_STATES.map((r) => `--run-${r}`);
const neutralVars = ['--dp-bg', '--dp-surface-1', '--dp-surface-2', '--dp-border',
  '--dp-text-1', '--dp-text-2', '--dp-text-3'];

describe('tokens.css — vocabulary completeness', () => {
  it.each([...bucketVars, ...freshVars, ...scopeVars, ...runVars, ...neutralVars])(
    'defines %s in :root', (name) => {
      expect(rootBlock).toContain(`${name}:`);
    });

  it('defines the font roles (Inter sans, JetBrains mono) and the type scale', () => {
    expect(rootBlock).toMatch(/--dp-font-sans:\s*'Inter'/);
    expect(rootBlock).toMatch(/--dp-font-mono:\s*'JetBrains Mono'/);
    for (const role of ['hero', 'section', 'count', 'title', 'body', 'meta', 'mono', 'prov']) {
      expect(rootBlock).toContain(`--dp-type-${role}-size:`);
      expect(rootBlock).toContain(`--dp-type-${role}-weight:`);
    }
  });

  it('defines the density spacing tokens that the card/row consume', () => {
    for (const t of ['--dp-card-pad', '--dp-row-py', '--dp-stack-gap', '--dp-group-gap']) {
      expect(rootBlock).toContain(`${t}:`);
    }
  });
});

describe('tokens.css — render-truth + theming invariants', () => {
  it('themes every meaning-bearing token in BOTH light and dark', () => {
    // each bucket/freshness/scope token must be re-stated in the light block (dark = :root default)
    for (const name of [...bucketVars, ...freshVars, ...scopeVars]) {
      expect(rootBlock, `${name} missing dark default`).toContain(`${name}:`);
      expect(lightBlock, `${name} missing light value`).toContain(`${name}:`);
    }
  });

  it('themes the neutrals in light too (light is a first-class peer, not derived)', () => {
    for (const name of neutralVars) expect(lightBlock).toContain(`${name}:`);
  });

  it('provides a dense density override', () => {
    expect(denseBlock).toContain('--dp-card-pad:');
    expect(denseBlock).toContain('--dp-row-py:');
  });

  it('keeps saturated hazard red reserved for the armed terminal (§5.5), not a bucket', () => {
    expect(rootBlock).toContain('--hazard:');
    // no bucket may reuse the hazard hex — danger means exactly one thing
    expect(rootBlock).not.toMatch(/--bucket-[a-z-]+:\s*#EF4444/i);
  });
});

describe('no raw hex in components — the palette lives only in tokens.css (§2.2)', () => {
  // Every hex the redesign palette introduces. Components must consume the tokens, not these.
  const palette = [
    // buckets (dark + light)
    '#F87171', '#FBBF24', '#60A5FA', '#4ADE80', '#A78BFA',
    '#DC2626', '#D97706', '#2563EB', '#16A34A', '#7C3AED',
    // scope
    '#818CF8', '#2DD4BF', '#4F46E5', '#0D9488', '#475569',
    // neutrals
    '#0B0F17', '#121826', '#1A2233', '#283142', '#E8EDF4', '#9FB0C3',
    '#FBFCFD', '#F1F5F9', '#E2E8F0', '#0F172A',
    // hazard
    '#EF4444',
  ];

  function walkCss(dir, acc = []) {
    let entries;
    try { entries = readdirSync(dir); } catch { return acc; }
    for (const name of entries) {
      if (name === 'node_modules' || name === 'vendor') continue;
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walkCss(p, acc);
      else if (name.endsWith('.css')) acc.push(p);
    }
    return acc;
  }

  it('tokens.css is the single source of the palette (every hex defined there)', () => {
    const css = tokensCss.toUpperCase();
    for (const hex of palette) expect(css, `${hex} missing from tokens.css`).toContain(hex.toUpperCase());
  });

  it('the redesign component layer (components/) contains no raw hex — tokens only', () => {
    // Legacy stylesheets (core.css, pages/*) keep their own palette until F006 migrates them;
    // the NEW redesign components must be token-only. This bites as soon as F003 adds CSS here.
    const offenders = [];
    for (const file of walkCss(join(dashRoot, 'components'))) {
      const lines = readFileSync(file, 'utf8').split('\n');
      lines.forEach((line, i) => {
        if (/#[0-9a-fA-F]{3,8}\b/.test(line)) offenders.push(`${file}:${i + 1}: ${line.trim()}`);
      });
    }
    expect(offenders, `raw hex in redesign component layer:\n${offenders.join('\n')}`).toEqual([]);
  });
});

describe('tokens.js — the data-theme / data-density controller', () => {
  const fakeDoc = () => ({ documentElement: { dataset: {} } });

  it('exposes closed vocabularies and a bucket→token mapping', () => {
    expect(THEMES).toEqual(['dark', 'light']);
    expect(DENSITIES).toEqual(['comfort', 'dense']);
    expect(BUCKETS).toContain('needs_auth');
    expect(bucketToken('agent_runnable')).toBe('--bucket-agent-runnable');
  });

  it('setTheme / setDensity write the dataset; getters read it', () => {
    const doc = fakeDoc();
    setTheme('light', doc);
    setDensity('dense', doc);
    expect(doc.documentElement.dataset.theme).toBe('light');
    expect(doc.documentElement.dataset.density).toBe('dense');
    expect(getTheme(doc)).toBe('light');
    expect(getDensity(doc)).toBe('dense');
  });

  it('rejects unknown theme/density (closed enum)', () => {
    expect(() => setTheme('neon', fakeDoc())).toThrow();
    expect(() => setDensity('roomy', fakeDoc())).toThrow();
  });

  it('falls back to the documented defaults when unset', () => {
    const doc = fakeDoc();
    expect(getTheme(doc)).toBe(DEFAULT_THEME);
    expect(getDensity(doc)).toBe(DEFAULT_DENSITY);
    expect(DEFAULT_THEME).toBe('dark');
    expect(DEFAULT_DENSITY).toBe('comfort');
  });

  it('initThemeDefaults seeds a known state; toggles flip it', () => {
    const doc = fakeDoc();
    initThemeDefaults(doc);
    expect(doc.documentElement.dataset.theme).toBe('dark');
    expect(doc.documentElement.dataset.density).toBe('comfort');
    expect(toggleTheme(doc)).toBe('light');
    expect(toggleDensity(doc)).toBe('dense');
  });
});
