// Plan 2026-06-05-002 F001 — core.js exports the real page-module list so tests
// reference the single source of truth instead of copying/re-declaring it.
// This is the drift guard: adding/removing a registered page WITHOUT updating
// test awareness fails here, not silently in a hand-maintained list.

import { describe, it, expect } from 'vitest';
import { pageModules } from '../../core.js';

describe('core.js: real page-module surface (2026-06-05-002 F001)', () => {
  it('exports pageModules as an array', () => {
    expect(Array.isArray(pageModules)).toBe(true);
  });

  it('matches the registered V0 nav pages exactly (drift guard)', () => {
    expect(pageModules).toEqual([
      'pages/what-now/what-now.js',
      'pages/repair/repair.js',
      'pages/mission-control/mission-control.js',
      'pages/architecture/architecture.js',
      'pages/capabilities/capabilities.js',
      'pages/health/health.js',
      'pages/settings/settings.js',
    ]);
  });

  it('includes repair + architecture + mission-control (pages older nav tests omitted)', () => {
    expect(pageModules).toContain('pages/repair/repair.js');
    expect(pageModules).toContain('pages/architecture/architecture.js');
    expect(pageModules).toContain('pages/mission-control/mission-control.js');
  });
});
