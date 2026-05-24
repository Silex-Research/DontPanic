// Static-check tests for the value-language contract documented in
// docs/design/dashboard-value-language-ia-v0/copy-map.md.
//
// Plan: 2026-05-24-001-feat-dashboard-value-language-ia-v0 (F001).
//
// This suite establishes the contract for F002/F003:
//   - the scanner correctly identifies forbidden first-read tokens
//   - the scanner correctly identifies Jarvis-era shell branding
//   - the canonical token list in copy-map.md §5 matches the code
//   - the live shell HTML currently carries the Jarvis-era branding
//     that F002 must remove (audit trail; F002 will invert this)
//
// F002 will add complementary tests asserting the rebrand removed the
// Jarvis-era phrases from the live shell.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import {
  FORBIDDEN_FIRST_READ_TOKENS,
  FORBIDDEN_SHELL_BRAND_PHRASES,
  FORBIDDEN_STALE_NAV_LABELS,
  scanForFirstReadViolations,
  scanShellTextForViolations,
  scanForStaleNavLabels,
  extractShellTextRegions,
  extractRegisteredPageLabel,
} from '../../lib/value-language-static-checks.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '../../..');

const COPY_MAP_PATH = resolve(
  REPO_ROOT,
  'docs/design/dashboard-value-language-ia-v0/copy-map.md',
);
const SHELL_PATH = resolve(REPO_ROOT, 'dashboard/index.html');
const FIREBASE_SHELL_PATH = resolve(REPO_ROOT, 'dashboard/index-firebase.html');

// Page modules that participate in V0 core nav. After F002 the live
// `registerPage({ label: ... })` of each module must NOT match a
// FORBIDDEN_STALE_NAV_LABELS entry. Modules that were removed from V0
// core nav (command-center, cloud-costs, financial) remain on disk but
// are no longer imported by `dashboard/core.js`'s `pageModules` array —
// see CORE_NAV_PAGE_MODULES below.
const CORE_NAV_PAGE_MODULES = [
  'dashboard/pages/what-now/what-now.js',
  'dashboard/pages/mission-control/mission-control.js',
  'dashboard/pages/capabilities/capabilities.js',
  'dashboard/pages/health/health.js',
  'dashboard/pages/settings/settings.js',
];

const CORE_JS_PATH = resolve(REPO_ROOT, 'dashboard/core.js');

// Page modules that F002 explicitly de-registered from V0 core nav.
// Their files remain on disk for path stability, but `core.js` must not
// import them — otherwise the runtime `<nav>` would re-surface them.
const DEFERRED_PAGE_IMPORTS = [
  'pages/command-center/command-center.js',
  'pages/cloud-costs/cloud-costs.js',
  'pages/financial/financial.js',
  'pages/security/security.js',
];

// ── First-read token scanner ─────────────────────────────────────────────────

describe('scanForFirstReadViolations', () => {
  it('flags each forbidden token in a synthetic Layer 1 sample', () => {
    const sample = [
      'gate needs approval',
      'supervisor is running',
      'volley closed',
      'manifest applied',
      'quota tripped',
      'pre_impl gate',
      'pre_merge gate',
    ].join(' ');
    const found = scanForFirstReadViolations(sample);
    const tokens = new Set(found.map((v) => v.token));
    for (const tok of FORBIDDEN_FIRST_READ_TOKENS) {
      expect(tokens.has(tok)).toBe(true);
    }
  });

  it('returns an empty array for a clean Layer 1 sample', () => {
    const sample =
      'Approval needed. Setup required. Budget guardrail engaged. ' +
      'Active AI work. Connected tool. All clear.';
    expect(scanForFirstReadViolations(sample)).toEqual([]);
  });

  it('matches whole-word only — does not flag substrings inside other words', () => {
    // `gateway`, `quotation`, `manifesto`, `supervisors-meta` etc. share a
    // prefix but are not the forbidden token. The scanner is whole-word.
    const sample =
      'API gateway is healthy. The quotation deck. A manifesto. Tag: supervisors-meta.';
    const found = scanForFirstReadViolations(sample);
    expect(found.map((v) => v.token)).not.toContain('gate');
    expect(found.map((v) => v.token)).not.toContain('quota');
    expect(found.map((v) => v.token)).not.toContain('manifest');
    // `supervisors` (plural) is a different token; we deliberately keep the
    // scanner whole-word against the canonical singular `supervisor`.
    expect(found.map((v) => v.token)).not.toContain('supervisor');
  });

  it('is case-insensitive on the token side', () => {
    const sample = 'Gate cleared. SUPERVISOR running. Pre_Impl approval.';
    const found = scanForFirstReadViolations(sample);
    const tokens = new Set(found.map((v) => v.token));
    expect(tokens.has('gate')).toBe(true);
    expect(tokens.has('supervisor')).toBe(true);
    expect(tokens.has('pre_impl')).toBe(true);
  });

  it('returns an empty array on non-string input', () => {
    expect(scanForFirstReadViolations(null)).toEqual([]);
    expect(scanForFirstReadViolations(undefined)).toEqual([]);
    expect(scanForFirstReadViolations(42)).toEqual([]);
  });
});

// ── Shell brand phrase scanner ───────────────────────────────────────────────

describe('scanShellTextForViolations', () => {
  it('flags each forbidden brand phrase in a synthetic shell sample', () => {
    const sample =
      'JARVIS — Personal Control Dashboard. JARVIS v1.0 — Silex Research.';
    const found = scanShellTextForViolations(sample);
    const phrases = new Set(found.map((v) => v.phrase));
    for (const phrase of FORBIDDEN_SHELL_BRAND_PHRASES) {
      expect(phrases.has(phrase)).toBe(true);
    }
  });

  it('returns an empty array for a clean shell sample', () => {
    const sample = 'DontPanic — Local Operating Console. DontPanic v0.';
    expect(scanShellTextForViolations(sample)).toEqual([]);
  });

  it('matches case-insensitively on the phrase side', () => {
    const sample = 'jarvis — personal control dashboard';
    const found = scanShellTextForViolations(sample);
    const phrases = new Set(found.map((v) => v.phrase));
    expect(phrases.has('JARVIS')).toBe(true);
    expect(phrases.has('Personal Control Dashboard')).toBe(true);
  });
});

// ── Stale nav-label scanner ──────────────────────────────────────────────────

describe('scanForStaleNavLabels', () => {
  it('flags each forbidden stale nav label in a synthetic sample', () => {
    const sample = FORBIDDEN_STALE_NAV_LABELS.join(' · ');
    const found = scanForStaleNavLabels(sample);
    const labels = new Set(found.map((v) => v.label));
    for (const label of FORBIDDEN_STALE_NAV_LABELS) {
      expect(labels.has(label)).toBe(true);
    }
  });

  it('returns an empty array for the V0 nav-label set', () => {
    const sample = [
      'Needs Attention',
      'Work',
      'Tools & Setup',
      'Health',
      'Preferences',
    ].join(' · ');
    expect(scanForStaleNavLabels(sample)).toEqual([]);
  });

  it('is case-insensitive on the label side', () => {
    const sample = 'WHAT NOW · mission control · cloud costs';
    const found = scanForStaleNavLabels(sample);
    const labels = new Set(found.map((v) => v.label));
    expect(labels.has('What Now')).toBe(true);
    expect(labels.has('Mission Control')).toBe(true);
    expect(labels.has('Cloud Costs')).toBe(true);
  });

  it('returns an empty array on non-string input', () => {
    expect(scanForStaleNavLabels(null)).toEqual([]);
    expect(scanForStaleNavLabels(undefined)).toEqual([]);
    expect(scanForStaleNavLabels(42)).toEqual([]);
  });
});

// ── extractRegisteredPageLabel ───────────────────────────────────────────────

describe('extractRegisteredPageLabel', () => {
  it('extracts the label from a single-quoted registerPage block', () => {
    const src = `
      Jarvis.registerPage({
        id: 'demo',
        label: 'Demo Surface',
        init() {}
      });
    `;
    expect(extractRegisteredPageLabel(src)).toBe('Demo Surface');
  });

  it('extracts the label from a double-quoted registerPage block', () => {
    const src = `Jarvis.registerPage({ id: "x", label: "X Page" });`;
    expect(extractRegisteredPageLabel(src)).toBe('X Page');
  });

  it('ignores chart/table `label:` fields that come after registerPage', () => {
    // A deep nested `label: 'Score'` inside the page body must not
    // shadow the registerPage label — the helper limits its scan to
    // the first 400 chars of each registerPage block.
    const src = `
      Jarvis.registerPage({
        id: 'demo',
        label: 'Demo Surface',
        init() {
          const chartCfg = { datasets: [{ label: 'Score' }] };
        }
      });
    `;
    expect(extractRegisteredPageLabel(src)).toBe('Demo Surface');
  });

  it('returns null when no registerPage block is present', () => {
    expect(extractRegisteredPageLabel('export function noop(){}')).toBe(null);
  });

  it('returns null on non-string input', () => {
    expect(extractRegisteredPageLabel(null)).toBe(null);
    expect(extractRegisteredPageLabel(undefined)).toBe(null);
    expect(extractRegisteredPageLabel(42)).toBe(null);
  });
});

// ── extractShellTextRegions ──────────────────────────────────────────────────

describe('extractShellTextRegions', () => {
  it('returns title / header / nav / footer text concatenated', () => {
    const html = `
      <!DOCTYPE html>
      <html><head><title>Test Page</title></head>
      <body>
        <header><h1>Hello</h1><span class="subtitle">World</span></header>
        <nav><a>Tab A</a><a>Tab B</a></nav>
        <main>Body content should not appear.</main>
        <footer>Footer line</footer>
      </body></html>
    `;
    const regions = extractShellTextRegions(html);
    expect(regions).toContain('Test Page');
    expect(regions).toContain('Hello');
    expect(regions).toContain('World');
    expect(regions).toContain('Tab A');
    expect(regions).toContain('Tab B');
    expect(regions).toContain('Footer line');
    expect(regions).not.toContain('Body content should not appear');
  });

  it('returns the empty string for non-HTML input', () => {
    expect(extractShellTextRegions(null)).toBe('');
    expect(extractShellTextRegions(undefined)).toBe('');
    expect(extractShellTextRegions(42)).toBe('');
  });
});

// ── Copy-map contract sync ───────────────────────────────────────────────────

describe('copy-map.md ↔ code contract', () => {
  const copyMap = readFileSync(COPY_MAP_PATH, 'utf8');

  it('copy-map.md §5 lists every forbidden first-read token', () => {
    for (const tok of FORBIDDEN_FIRST_READ_TOKENS) {
      expect(copyMap).toContain(tok);
    }
  });

  it('copy-map.md §5 lists every forbidden shell brand phrase', () => {
    for (const phrase of FORBIDDEN_SHELL_BRAND_PHRASES) {
      expect(copyMap).toContain(phrase);
    }
  });

  it('copy-map.md §4.5 lists every stale nav label', () => {
    for (const label of FORBIDDEN_STALE_NAV_LABELS) {
      expect(copyMap).toContain(label);
    }
  });

  it('copy-map.md preserves the four-band status taxonomy', () => {
    for (const band of ['needs_action', 'advisory', 'info', 'ready']) {
      expect(copyMap).toContain(band);
    }
  });

  it('copy-map.md documents optional as a relevance chip, not a status', () => {
    expect(copyMap).toMatch(/optional[\s\S]*relevance chip/i);
  });

  it('copy-map.md identifies the V0 nav surfaces', () => {
    for (const label of [
      'Needs Attention',
      'Work',
      'Tools & Setup',
      'Health',
      'Preferences',
    ]) {
      expect(copyMap).toContain(label);
    }
  });

  it('copy-map.md documents the drag-to-command decision', () => {
    expect(copyMap).toMatch(/drag-to-command/i);
    expect(copyMap).toMatch(/command-preview/i);
  });

  it('copy-map.md documents the JSX-to-vanilla translation strategy', () => {
    expect(copyMap).toMatch(/JSX/);
    expect(copyMap).toMatch(/vanilla/i);
  });

  it('copy-map.md documents fleet-mode expectations for Home, Work, and Health', () => {
    expect(copyMap).toMatch(/fleet/i);
    expect(copyMap).toMatch(/All Projects/);
  });

  it('copy-map.md documents the non-technical reviewer audience expansion', () => {
    expect(copyMap).toMatch(/non-technical reviewer/i);
  });
});

// ── Post-F002 invariants: shell rebrand and V0 nav cleanup ──────────────────
//
// F002 has landed. The live shell HTML must no longer carry Jarvis-era
// brand phrases, every V0 core-nav page module must register a label
// that does NOT match FORBIDDEN_STALE_NAV_LABELS, and `core.js` must not
// import the deferred page modules.

describe('F002: shell rebrand and V0 nav cleanup', () => {
  it('dashboard/index.html user-visible shell text carries no Jarvis-era brand phrases', () => {
    const html = readFileSync(SHELL_PATH, 'utf8');
    const shellText = extractShellTextRegions(html);
    const violations = scanShellTextForViolations(shellText);
    expect(
      violations,
      `index.html shell text still contains: ${violations.map((v) => v.phrase).join(', ')}`,
    ).toEqual([]);
  });

  it('dashboard/index.html shell text contains the DontPanic brand', () => {
    const html = readFileSync(SHELL_PATH, 'utf8');
    const shellText = extractShellTextRegions(html);
    // The shell text must mention DontPanic — the rebrand replaces, it
    // doesn't just delete.
    expect(shellText).toMatch(/DontPanic/);
  });

  it('dashboard/index-firebase.html user-visible shell text carries no Jarvis-era brand phrases', () => {
    const html = readFileSync(FIREBASE_SHELL_PATH, 'utf8');
    const shellText = extractShellTextRegions(html);
    const violations = scanShellTextForViolations(shellText);
    expect(
      violations,
      `index-firebase.html shell text still contains: ${violations.map((v) => v.phrase).join(', ')}`,
    ).toEqual([]);
  });

  it('every V0 core-nav page module registers a non-stale nav label', () => {
    // After F002, each core-nav module's `Jarvis.registerPage({ label: ... })`
    // must be a value-language label that does NOT appear in
    // FORBIDDEN_STALE_NAV_LABELS. Modules deferred from V0 nav are
    // covered by the separate `core.js does not import deferred pages`
    // assertion below.
    const liveLabels = [];
    for (const rel of CORE_NAV_PAGE_MODULES) {
      const src = readFileSync(resolve(REPO_ROOT, rel), 'utf8');
      const label = extractRegisteredPageLabel(src);
      expect(label, `${rel} must register a label`).not.toBeNull();
      liveLabels.push(label);
      const violations = scanForStaleNavLabels(label);
      expect(
        violations,
        `${rel} registers stale label '${label}'`,
      ).toEqual([]);
    }
    // Spot-check the V0 surface labels we expect to see.
    // F002 acceptance #2: Home/Needs Attention, Work, Tools & Setup or
    // Connections, Health, and Preferences must all appear in V0 nav.
    const joined = liveLabels.join(' · ');
    expect(joined).toContain('Needs Attention');
    expect(joined).toContain('Work');
    expect(joined).toMatch(/Tools & Setup|Connections/);
    expect(joined).toContain('Health');
    expect(joined).toContain('Preferences');
  });

  it('dashboard/core.js does not import deferred page modules into V0 core nav', () => {
    // The deferred modules (command-center, cloud-costs, financial,
    // security) remain on disk for path stability and may be brought
    // back behind a capability gate in a future plan, but they must
    // not be re-registered into V0 core nav by `core.js`.
    const coreSrc = readFileSync(CORE_JS_PATH, 'utf8');
    // We scan for the page-module path string with surrounding quotes
    // and a slash to avoid matching the CSS link, comment, or doc
    // references. The exact import-list entry in core.js is e.g.
    //   'pages/command-center/command-center.js'
    for (const rel of DEFERRED_PAGE_IMPORTS) {
      const quoted = `'${rel}'`;
      expect(
        coreSrc.includes(quoted),
        `core.js still imports deferred page module ${rel}`,
      ).toBe(false);
    }
  });
});
