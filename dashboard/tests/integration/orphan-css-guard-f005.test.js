// Plan 2026-06-05-003 F005 — guard: index.html loads page CSS ONLY for pages in
// pageModules. Stops a retired/orphan page's stylesheet from silently restyling the
// live pages via last-wins cascade.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { pageModules } from '../../core.js';

const __dir = dirname(fileURLToPath(import.meta.url));
const indexHtml = readFileSync(resolve(__dir, '../../index.html'), 'utf8');

// page names registered in the loader (pages/<name>/<name>.js → <name>)
const registeredPages = new Set(
  pageModules.map((m) => m.replace(/^pages\//, '').split('/')[0]),
);

// page CSS hrefs actually loaded by index.html
const loadedPageCss = [...indexHtml.matchAll(/href="pages\/([^/]+)\/[^"]+\.css"/g)].map((m) => m[1]);

const RETIRED = ['command-center', 'financial', 'cloud-costs', 'security'];

describe('F005 orphan-CSS guard', () => {
  it('index.html loads a page stylesheet only for pages registered in pageModules', () => {
    const orphans = loadedPageCss.filter((p) => !registeredPages.has(p));
    expect(orphans, `orphan CSS still loaded: ${orphans.join(', ')}`).toEqual([]);
  });

  it('the 4 retired orphan stylesheets are no longer referenced', () => {
    for (const name of RETIRED) {
      expect(indexHtml).not.toContain(`pages/${name}/${name}.css`);
    }
  });

  it('still loads the base + component layer', () => {
    expect(indexHtml).toContain('href="core.css"');
    expect(indexHtml).toContain('href="components.css"');
  });
});
