// Plan 2026-06-05-003 F001 — shared component render helpers.

import { describe, it, expect } from 'vitest';
import {
  renderButtonHTML,
  renderCopyCommandHTML,
  renderCardHTML,
  renderStatTileHTML,
  renderStatStripHTML,
  renderSectionHeaderHTML,
  renderBannerHTML,
  renderSkeletonHTML,
} from '../../lib/components.js';

describe('renderButtonHTML', () => {
  it('emits a real <button> with the primary variant class', () => {
    const html = renderButtonHTML('Go', { variant: 'primary' });
    expect(html).toContain('<button type="button"');
    expect(html).toContain('btn btn--primary');
    expect(html).toContain('>Go</button>');
  });
  it('escapes the label', () => {
    expect(renderButtonHTML('<x>')).toContain('&lt;x&gt;');
  });
});

describe('renderCopyCommandHTML (the read-only action affordance)', () => {
  const html = renderCopyCommandHTML('dontpanic dashboard build --project all', {
    label: 'Copy build command',
  });
  it('renders the command in a code block + a copy button carrying data-copy', () => {
    expect(html).toContain('copy-cmd-code');
    expect(html).toContain('data-copy="dontpanic dashboard build --project all"');
  });
  it('has an honest "Copy …" label and an aria-live feedback element', () => {
    expect(html).toContain('>Copy build command</button>');
    expect(html).toMatch(/class="copy-cmd-feedback"[^>]*aria-live="polite"/);
  });
  it('carries an aria-label describing the copy behavior', () => {
    expect(html).toContain('aria-label="Copy the command');
  });
});

describe('renderCardHTML', () => {
  it('applies the status accent + title + impact', () => {
    const html = renderCardHTML({ title: 'Install has blockers', impact: '1 blocked', status: 'blocked' });
    expect(html).toContain('card card--blocked');
    expect(html).toContain('Install has blockers');
    expect(html).toContain('1 blocked');
  });
});

describe('stat tiles', () => {
  it('renders a big value + label with optional status tint', () => {
    expect(renderStatTileHTML(173, 'Human required', { status: 'attention' })).toContain('stat stat--attention');
    expect(renderStatTileHTML(173, 'Human required')).toContain('>173</div>');
  });
  it('renders a strip of tiles', () => {
    const html = renderStatStripHTML([
      { value: 0, label: 'Auto-safe' },
      { value: 173, label: 'Human required', status: 'attention' },
    ]);
    expect(html).toContain('class="stat-strip"');
    expect((html.match(/class="stat-value"/g) || []).length).toBe(2); // one value per tile
    expect(html).toContain('stat--attention'); // status tile tinted
  });
});

describe('section header / banner / skeleton', () => {
  it('section header shows title + count', () => {
    expect(renderSectionHeaderHTML('Auto-safe', { count: 41 })).toContain('section-header-count');
  });
  it('banner applies the kind modifier', () => {
    expect(renderBannerHTML('cache corrupt', { kind: 'error' })).toContain('banner banner--error');
  });
  it('skeleton renders one bar per row', () => {
    expect((renderSkeletonHTML(4).match(/class="skeleton"/g) || []).length).toBe(4);
  });
});
