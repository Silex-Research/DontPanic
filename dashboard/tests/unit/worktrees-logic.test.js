// Worktree Isolation v0 F007 — pure render logic for the worktree-status
// model (one model, three renderers: list / brief / dashboard). Six states:
// clean, dirty, broken-binding, branch-drifted, unhealthy-with-reason
// (explicit null dirty/untracked rendered as unknown), corrupt-registry.

import { describe, it, expect } from 'vitest';
import { deriveWorktreesView, renderWorktreesHTML } from '../../lib/worktrees-logic.js';

const binding = (over = {}) => ({
  plan_id: 'plan-a',
  branch: 'plan/plan-a',
  current_branch: 'plan/plan-a',
  worktree_path: '/home/op/.dontpanic/worktrees/repo-abc12345/plan-a',
  owner_actor: 'op@host',
  base_ref: 'main',
  base_sha: 'f'.repeat(40),
  healthy: true,
  health_reason: null,
  dirty: false,
  untracked_count: 0,
  ...over,
});

const model = (bindings, corrupt = false) => ({
  registry_corrupt: corrupt,
  registry_path: '/home/op/.dontpanic/worktrees.json',
  bindings,
});

describe('renderWorktreesHTML — six fixture states', () => {
  it('clean: branch, dirty=false, untracked=0, owner, path all visible', () => {
    const html = renderWorktreesHTML(model([binding()]));
    expect(html).toContain('plan/plan-a');
    expect(html).toContain('dirty=false');
    expect(html).toContain('untracked=0');
    expect(html).toContain('op@host');
    expect(html).toContain('worktrees/repo-abc12345/plan-a');
    expect(html).not.toContain('aw-unhealthy');
  });

  it('dirty: true dirty state and untracked count render honestly', () => {
    const html = renderWorktreesHTML(model([binding({ dirty: true, untracked_count: 3 })]));
    expect(html).toContain('dirty=true');
    expect(html).toContain('untracked=3');
  });

  it('broken binding: rendered with its reason, never dropped', () => {
    const html = renderWorktreesHTML(model([binding({
      healthy: false, health_reason: 'worktree path does not exist',
      current_branch: null, dirty: null, untracked_count: null,
    })]));
    expect(html).toContain('data-testid="aw-row"');
    expect(html).toContain('UNHEALTHY: worktree path does not exist');
  });

  it('branch drift: shows BOTH the recorded branch and the current branch', () => {
    const html = renderWorktreesHTML(model([binding({
      healthy: false,
      health_reason: "current branch 'elsewhere' differs from recorded branch 'plan/plan-a'",
      current_branch: 'elsewhere', dirty: null, untracked_count: null,
    })]));
    expect(html).toContain('plan/plan-a');
    expect(html).toContain('data-testid="aw-drift"');
    expect(html).toContain('on elsewhere');
  });

  it('unhealthy: explicit null dirty/untracked render as unknown, never false/0', () => {
    const html = renderWorktreesHTML(model([binding({
      healthy: false, health_reason: 'path is not a git worktree',
      dirty: null, untracked_count: null,
    })]));
    expect(html).toContain('dirty=unknown');
    expect(html).toContain('untracked=unknown');
    expect(html).not.toContain('dirty=false');
    expect(html).not.toContain('untracked=0');
  });

  it('corrupt registry: visible warning, never a silent empty state', () => {
    const html = renderWorktreesHTML(model([], true));
    expect(html).toContain('data-testid="aw-registry-corrupt"');
    expect(html).toContain('CORRUPT');
    expect(html).not.toContain('data-testid="aw-empty"');
  });

  it('honest empty state when no bindings exist (nothing fabricated)', () => {
    const html = renderWorktreesHTML(model([]));
    expect(html).toContain('data-testid="aw-empty"');
    expect(html).toContain('No active worktrees');
    expect(html).not.toContain('data-testid="aw-row"');
  });

  it('missing model (producer never ran): honest no-state line', () => {
    const html = renderWorktreesHTML(null);
    expect(html).toContain('data-testid="aw-missing"');
    expect(html).toContain('dontpanic dashboard build');
  });

  it('escapes HTML in model values', () => {
    const html = renderWorktreesHTML(model([binding({ owner_actor: '<img src=x>' })]));
    expect(html).not.toContain('<img src=x>');
    expect(html).toContain('&lt;img src=x&gt;');
  });
});

describe('deriveWorktreesView', () => {
  it('flags drift only when current differs from recorded', () => {
    expect(deriveWorktreesView(model([binding()])).rows[0].drifted).toBe(false);
    expect(
      deriveWorktreesView(model([binding({ current_branch: 'other' })])).rows[0].drifted
    ).toBe(true);
    // an unprobeable current branch (null) is not "drift" — it is unhealthy
    expect(
      deriveWorktreesView(model([binding({ current_branch: null })])).rows[0].drifted
    ).toBe(false);
  });
});
