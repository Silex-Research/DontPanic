// Unit tests for the shared provenance footer helper used by every V0
// page (plan 2026-05-24-001 F004). Provenance lives in Layer 2 — these
// tests pin the visible labels, the missing-data fallback, and the
// optional refresh / note rows.

import { describe, it, expect } from 'vitest';

import {
  renderProvenanceFooterHTML,
  hasProvenanceFooter,
} from '../../lib/provenance.js';

describe('renderProvenanceFooterHTML', () => {
  it('emits the canonical Source / Updated / Refresh rows when all inputs are present', () => {
    const html = renderProvenanceFooterHTML({
      source: 'dashboard/state/what-now.json',
      lastUpdated: '2026-05-23T03:50:00Z',
      refreshCommand: 'dontpanic dashboard build',
    });
    expect(html).toContain('data-provenance="1"');
    expect(html).toContain('>Source<');
    expect(html).toContain('>Updated<');
    expect(html).toContain('>Refresh<');
    expect(html).toContain('dashboard/state/what-now.json');
    expect(html).toContain('2026-05-23T03:50:00Z');
    expect(html).toContain('dontpanic dashboard build');
  });

  it('omits the Refresh row when no refreshCommand is supplied', () => {
    const html = renderProvenanceFooterHTML({
      source: 'localStorage',
      lastUpdated: null,
    });
    expect(html).toContain('localStorage');
    expect(html).not.toContain('>Refresh<');
  });

  it('renders the Updated row as "—" when lastUpdated is absent', () => {
    const html = renderProvenanceFooterHTML({
      source: 'dashboard/state/what-now.json',
      lastUpdated: null,
      refreshCommand: 'dontpanic dashboard build',
    });
    expect(html).toMatch(/Updated[\s\S]*—/);
  });

  it('appends the note line when provided', () => {
    const html = renderProvenanceFooterHTML({
      source: 'localStorage',
      lastUpdated: null,
      note: 'Browser-local only.',
    });
    expect(html).toContain('Browser-local only.');
  });

  it('escapes HTML in source, lastUpdated, refreshCommand, and note', () => {
    const html = renderProvenanceFooterHTML({
      source: '<script>x</script>',
      lastUpdated: '"now"',
      refreshCommand: 'dontpanic <eval>',
      note: 'cat <file> | wc',
    });
    expect(html).not.toContain('<script>x</script>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('&quot;now&quot;');
    expect(html).toContain('&lt;eval&gt;');
    expect(html).toContain('&lt;file&gt;');
  });

  it('falls back to "—" when source is empty or non-string', () => {
    const empty = renderProvenanceFooterHTML({ source: '' });
    expect(empty).toMatch(/Source[\s\S]*—/);
    const noArg = renderProvenanceFooterHTML();
    expect(noArg).toMatch(/Source[\s\S]*—/);
    expect(noArg).toMatch(/Updated[\s\S]*—/);
  });
});

describe('hasProvenanceFooter', () => {
  it('returns true for HTML containing the provenance marker', () => {
    const html = renderProvenanceFooterHTML({ source: 'x' });
    expect(hasProvenanceFooter(html)).toBe(true);
  });

  it('returns false for HTML without the marker', () => {
    expect(hasProvenanceFooter('<div>no footer here</div>')).toBe(false);
  });

  it('returns false for non-string input', () => {
    expect(hasProvenanceFooter(null)).toBe(false);
    expect(hasProvenanceFooter(undefined)).toBe(false);
    expect(hasProvenanceFooter(42)).toBe(false);
  });
});
