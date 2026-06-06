// Plan 2026-06-05-003 F002 — page skeleton + shell hardening, proven on the real shell.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { setupDOM, setupChartMock, setupFetchMock } from '../helpers/setup.js';
import { pageModules } from '../../core.js';

const __dir = dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(resolve(__dir, '../../', rel), 'utf8');

describe('F002 shell hardening (real shell boot)', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); delete globalThis.Jarvis; });

  async function boot() {
    setupDOM();
    setupChartMock();
    setupFetchMock({});
    const { createJarvis } = await import('../../core.js');
    const J = createJarvis();
    globalThis.Jarvis = J;
    const suffix = `?j=${Math.random().toString(36).slice(2)}`;
    for (const mod of pageModules) {
      await import(`../../${mod}${suffix}`);
    }
    await J.init();
    return J;
  }

  it('exposes a <main> landmark + a skip-to-content link', async () => {
    await boot();
    const main = document.querySelector('main#main');
    expect(main).not.toBeNull();
    expect(main.querySelector('#page-container')).not.toBeNull();
    const skip = document.querySelector('a.skip-link[href="#main"]');
    expect(skip).not.toBeNull();
  });

  it('builds the nav from pageModules and the tabs are real, focusable buttons', async () => {
    await boot();
    const tabs = document.querySelectorAll('#view-nav button');
    expect(tabs.length).toBe(pageModules.length); // at least registered ones present
    // real <button>s are keyboard-focusable by default (no tabindex=-1)
    tabs.forEach((t) => expect(t.getAttribute('tabindex')).not.toBe('-1'));
  });

  it('nav order leads with the triage→fix→work→status priority', () => {
    // Plan 2026-06-06-001 F006 — the operator-console workbench is the primary
    // triage surface and now leads, ahead of the legacy What Now page.
    expect(pageModules.slice(0, 5)).toEqual([
      'pages/operator-console/operator-console.js',
      'pages/what-now/what-now.js',
      'pages/repair/repair.js',
      'pages/mission-control/mission-control.js',
      'pages/health/health.js',
    ]);
  });

  it('defines the focus-ring token + a global :focus-visible rule in CSS', () => {
    expect(read('core.css')).toContain('--focus-ring');
    const components = read('components.css');
    expect(components).toMatch(/:focus-visible\s*{[^}]*--focus-ring/);
    expect(components).toContain('.skip-link');
  });

  it('exports renderPageHTML with the title→summary→content→footer skeleton', async () => {
    const { renderPageHTML } = await import('../../lib/components.js');
    const html = renderPageHTML({ title: 'Repair', summary: '<x>', content: '<y>', footer: '<z>' });
    expect(html).toContain('class="page-header"');
    expect(html).toContain('class="page-title">Repair');
    expect(html).toContain('class="page-summary"');
    expect(html).toContain('class="page-content"');
    expect(html).toContain('class="page-footer"');
  });
});
