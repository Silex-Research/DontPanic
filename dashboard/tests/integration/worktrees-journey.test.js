// Worktree Isolation v0 F007 — REAL-SHELL journey for the active-worktrees
// block. Boots the real createJarvis() shell with an active-worktrees.json
// payload fixture, switches to the Operator console, and asserts the rendered
// DOM shows branch, drift, dirty state, untracked count, actor, health
// reasons, the corrupt-registry warning, and an honest empty state.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { setupDOM, setupChartMock, setupFetchMock } from '../helpers/setup.js';
import triageModel from '../fixtures/operator-triage-model.json' with { type: 'json' };

const binding = (over = {}) => ({
  plan_id: '2026-06-10-002-feat-worktree-isolation-v0',
  branch: 'plan/2026-06-10-002-feat-worktree-isolation-v0',
  current_branch: 'plan/2026-06-10-002-feat-worktree-isolation-v0',
  worktree_path: '/home/op/.dontpanic/worktrees/DontPanic-abc12345/2026-06-10-002-feat-worktree-isolation-v0',
  owner_actor: 'op@workstation',
  base_ref: 'main',
  base_sha: 'a'.repeat(40),
  healthy: true,
  health_reason: null,
  dirty: true,
  untracked_count: 2,
  ...over,
});

const wtModel = (bindings, corrupt = false) => ({
  registry_corrupt: corrupt,
  registry_path: '/home/op/.dontpanic/worktrees.json',
  bindings,
});

async function boot(activeWorktrees) {
  setupDOM();
  setupChartMock();
  setupFetchMock({
    'operator-triage': triageModel,
    'active-worktrees': activeWorktrees,
  });
  const { createJarvis } = await import('../../core.js');
  const J = createJarvis();
  globalThis.Jarvis = J;
  await import(
    '../../pages/operator-console/operator-console.js' +
    `?wt=${Math.random().toString(36).slice(2)}`
  );
  await J.init();
  J.switchTo('operator-console');
  return J.getPageEl('operator-console');
}

describe('F007 active worktrees through the real shell', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); delete globalThis.Jarvis; });

  it('renders branch, dirty, untracked count, and actor for a live binding', async () => {
    const el = await boot(wtModel([binding()]));
    const section = el.querySelector('[data-testid="active-worktrees"]');
    expect(section).toBeTruthy();
    const text = section.textContent;
    expect(text).toContain('plan/2026-06-10-002-feat-worktree-isolation-v0');
    expect(text).toContain('dirty=true');
    expect(text).toContain('untracked=2');
    expect(text).toContain('op@workstation');
  });

  it('drifted binding shows BOTH recorded and current branch with its health reason', async () => {
    const el = await boot(wtModel([binding({
      healthy: false,
      health_reason: "current branch 'hotfix' differs from recorded branch",
      current_branch: 'hotfix', dirty: null, untracked_count: null,
    })]));
    const section = el.querySelector('[data-testid="active-worktrees"]');
    expect(section.querySelector('[data-testid="aw-drift"]')).toBeTruthy();
    expect(section.textContent).toContain('on hotfix');
    expect(section.textContent).toContain('differs from recorded branch');
    // explicit nulls render as unknown, never fabricated false/zero
    expect(section.textContent).toContain('dirty=unknown');
  });

  it('corrupt registry shows a visible warning — never a silent empty state', async () => {
    const el = await boot(wtModel([], true));
    const section = el.querySelector('[data-testid="active-worktrees"]');
    expect(section.querySelector('[data-testid="aw-registry-corrupt"]')).toBeTruthy();
    expect(section.querySelector('[data-testid="aw-empty"]')).toBeFalsy();
  });

  it('honest empty state when no bindings exist (nothing fabricated)', async () => {
    const el = await boot(wtModel([]));
    const section = el.querySelector('[data-testid="active-worktrees"]');
    expect(section.querySelector('[data-testid="aw-empty"]')).toBeTruthy();
    expect(section.querySelectorAll('[data-testid="aw-row"]').length).toBe(0);
  });

  it('missing producer state renders the honest no-state line', async () => {
    const el = await boot(undefined); // fetch 404s → state.activeWorktrees = null
    const section = el.querySelector('[data-testid="active-worktrees"]');
    expect(section.querySelector('[data-testid="aw-missing"]')).toBeTruthy();
  });
});
