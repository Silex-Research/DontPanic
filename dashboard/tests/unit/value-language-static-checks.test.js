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

// Page modules whose `registerPage({ label: ... })` field will be touched
// by F002 to remove stale Jarvis-era nav labels. The list intentionally
// covers the four labels the auditor named (What Now, Mission Control,
// Command Center, Financial) plus the rest of the stale set in
// copy-map.md §4.5 that currently ship a stale `label:` string. F002
// will either rename each label to the V0 surface name or de-register
// the page from V0 core nav.
const STALE_LABEL_PAGE_MODULES = [
  'dashboard/pages/what-now/what-now.js',
  'dashboard/pages/mission-control/mission-control.js',
  'dashboard/pages/command-center/command-center.js',
  'dashboard/pages/capabilities/capabilities.js',
  'dashboard/pages/cloud-costs/cloud-costs.js',
  'dashboard/pages/financial/financial.js',
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

// ── Audit trail: identify the Jarvis-era substrate F002 must clean ───────────
//
// These tests document the CURRENT state of the live shell HTML so the
// rebrand work in F002 has a clear before/after. F002 should invert each
// `toContain` to a `not.toContain` (or replace with a forbidden-token scan
// that returns an empty array) once the shell carries DontPanic branding.

describe('audit trail: pre-F002 shell branding', () => {
  it('dashboard/index.html currently carries Jarvis-era shell branding', () => {
    const html = readFileSync(SHELL_PATH, 'utf8');
    const shellText = extractShellTextRegions(html);
    const violations = scanShellTextForViolations(shellText);
    // Pre-F002: the live shell carries these brand phrases. This assertion
    // proves they are present so F002 has an explicit before-state to
    // remove. F002 must update or replace this test to assert
    // `violations.length === 0` once the rebrand lands.
    expect(violations.length).toBeGreaterThan(0);
    const phrases = new Set(violations.map((v) => v.phrase));
    expect(phrases.has('JARVIS')).toBe(true);
  });

  it('dashboard/index-firebase.html currently carries Jarvis-era shell branding', () => {
    const html = readFileSync(FIREBASE_SHELL_PATH, 'utf8');
    const shellText = extractShellTextRegions(html);
    const violations = scanShellTextForViolations(shellText);
    expect(violations.length).toBeGreaterThan(0);
  });

  it('each stale-label page module still registers a forbidden nav label', () => {
    // For every page in STALE_LABEL_PAGE_MODULES, read the source,
    // extract the live `Jarvis.registerPage({ label: ... })` value,
    // and assert it appears in FORBIDDEN_STALE_NAV_LABELS. This proves
    // the scanner would catch a regression *today* and gives F002 the
    // explicit before-state to flip: after the rebrand, the same
    // assertion must invert to `scanForStaleNavLabels(label).length === 0`
    // (or the page must be de-registered from V0 core nav entirely).
    const liveLabels = [];
    for (const rel of STALE_LABEL_PAGE_MODULES) {
      const src = readFileSync(resolve(REPO_ROOT, rel), 'utf8');
      const label = extractRegisteredPageLabel(src);
      expect(label, `${rel} must register a label`).not.toBeNull();
      liveLabels.push(label);
      const violations = scanForStaleNavLabels(label);
      expect(
        violations.length,
        `${rel} registers '${label}' which must match FORBIDDEN_STALE_NAV_LABELS`,
      ).toBeGreaterThan(0);
    }
    // Sanity: the audit-trail snapshot covers all four labels the
    // auditor named explicitly (What Now, Mission Control, Command
    // Center, Financial — the last matched via 'Financial Analysis').
    const joined = liveLabels.join(' · ');
    expect(joined).toContain('What Now');
    expect(joined).toContain('Mission Control');
    expect(joined).toContain('Command Center');
    expect(joined).toMatch(/Financial/);
  });
});
