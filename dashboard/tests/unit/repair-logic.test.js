// Unit tests for repair-logic.js — the pure layer behind the F006 dashboard
// repair surfaces (plan 2026-06-04-006). Mirrors the Python repair_safety /
// repair_planner / repair_bundle so the "Copy agent repair plan" bundle is
// byte-parity with `dontpanic repair plan --format=json`, and the "Repair
// automatically" control runs ONLY the derived-state batch unless the operator
// explicitly confirms the stronger tier.

import { describe, it, expect } from 'vitest';
import {
  buildBundle,
  buildBundleFromItems,
  buildRepairAutoPreview,
  buildAgentRepairPlanText,
  buildRepairSummary,
  repairApplyCommand,
  repairPlanCommand,
  renderRepairControlsHTML,
  AUTO_SAFE,
  HUMAN_REQUIRED,
  TIER_DERIVED_STATE,
  TIER_CONFIRMED_LOCAL,
  RUN_TIER_DERIVED,
  RUN_TIER_CONFIRM,
} from '../../lib/repair-logic.js';

function action(id, over = {}) {
  return {
    id,
    kind: 'recompute_what_now',
    safetyClass: AUTO_SAFE,
    applyTier: TIER_DERIVED_STATE,
    resolutionClass: 'command_resolvable',
    clearsWhen: { predicate: 'gate_no_longer_actionable', params: { plan_id: id, gate: 'g' } },
    dependsOn: [],
    command: 'dontpanic state build',
    plainConsequence: 'Rebuilds the dashboard projection.',
    scope: 'project:glam',
    ...over,
  };
}

// ── bundle parity with the Python CLI (F003) ────────────────────────────────────
describe('buildBundle / buildBundleFromItems', () => {
  it('emits the six contract fields per action (parity with the CLI bundle)', () => {
    const item = {
      id: 'A',
      repair_kind: 'recompute_what_now',
      safety_class: AUTO_SAFE,
      apply_tier: TIER_DERIVED_STATE,
      resolution_class: 'command_resolvable',
      clears_when: { predicate: 'gate_no_longer_actionable', params: { plan_id: 'A', gate: 'g' } },
      exact_command: 'dontpanic state build',
      plain_consequence: 'Rebuilds the dashboard projection.',
      scope: 'project:glam',
    };
    const bundle = buildBundleFromItems([item], 'project:glam');
    expect(bundle.scope).toBe('project:glam');
    expect(bundle.actions).toEqual([
      {
        id: 'A',
        command: 'dontpanic state build',
        safety_class: 'auto_safe',
        apply_tier: 'derived_state',
        resolution_class: 'command_resolvable',
        clears_when: { predicate: 'gate_no_longer_actionable', params: { plan_id: 'A', gate: 'g' } },
        plain_consequence: 'Rebuilds the dashboard projection.',
        scope: 'project:glam',
        depends_on: [],
      },
    ]);
    expect(bundle.deferred).toEqual([]);
  });

  it('orders actions by dependency (prerequisite first)', () => {
    const a = action('A');
    const b = action('B', { dependsOn: ['A'] });
    const bundle = buildBundle([b, a], 'fleet');
    expect(bundle.actions.map((x) => x.id)).toEqual(['A', 'B']);
  });

  it('surfaces a dependency cycle as deferred, not in actions', () => {
    const a = action('A', { dependsOn: ['B'] });
    const b = action('B', { dependsOn: ['A'] });
    const bundle = buildBundle([a, b], 'fleet');
    expect(bundle.actions).toEqual([]);
    expect(bundle.deferred).toEqual([
      { id: 'A', reason: 'cycle' },
      { id: 'B', reason: 'cycle' },
    ]);
  });

  it('fails closed: an unclassified item emits human_required', () => {
    const bundle = buildBundleFromItems([{ id: 'X', exact_command: null }], 'fleet');
    expect(bundle.actions[0].safety_class).toBe(HUMAN_REQUIRED);
    expect(bundle.actions[0].apply_tier).toBe(null);
  });

  it('fails closed: a forbidden kind asserted auto_safe emits human_required', () => {
    const item = { id: 'D', repair_kind: 'deploy', safety_class: AUTO_SAFE, apply_tier: TIER_DERIVED_STATE };
    const bundle = buildBundleFromItems([item], 'fleet');
    expect(bundle.actions[0].safety_class).toBe(HUMAN_REQUIRED);
  });
});

// ── Repair automatically: derived-state only unless confirmed ───────────────────
describe('buildRepairAutoPreview', () => {
  it('runs ONLY derived_state actions by default; confirmed_local is left, not run', () => {
    const derived = action('D');
    const confirmed = action('C', { kind: 'clear_stale_generated_cache', applyTier: TIER_CONFIRMED_LOCAL });
    const human = action('H', { kind: 'deploy', safetyClass: AUTO_SAFE });
    const bundle = buildBundle([derived, confirmed, human], 'fleet');

    const preview = buildRepairAutoPreview(bundle);
    expect(preview.runTier).toBe(RUN_TIER_DERIVED);
    expect(preview.willRun.map((a) => a.id)).toEqual(['D']);
    expect(preview.willLeave.map((a) => a.id).sort()).toEqual(['C', 'H']);
  });

  it('includes confirmed_local only when the operator confirms the stronger tier', () => {
    const derived = action('D');
    const confirmed = action('C', { kind: 'clear_stale_generated_cache', applyTier: TIER_CONFIRMED_LOCAL });
    const bundle = buildBundle([derived, confirmed], 'fleet');

    const preview = buildRepairAutoPreview(bundle, { confirmed: true });
    expect(preview.runTier).toBe(RUN_TIER_CONFIRM);
    expect(preview.willRun.map((a) => a.id).sort()).toEqual(['C', 'D']);
    expect(preview.willLeave).toEqual([]);
  });

  it('the auto command is the derived-state tier and never carries --confirm', () => {
    const cmd = repairApplyCommand('project:glam');
    expect(cmd).toContain('--safe-derived-state');
    expect(cmd).not.toContain('--confirm');
    expect(repairApplyCommand('project:glam', { confirmed: true })).toContain('--safe --confirm');
  });
});

// ── post-run summary reflects the re-evaluated render set ────────────────────────
describe('buildRepairSummary', () => {
  it('counts the current (re-evaluated) bundle by safety class', () => {
    const bundle = buildBundle(
      [
        action('D'),
        action('C', { kind: 'clear_stale_generated_cache', applyTier: TIER_CONFIRMED_LOCAL }),
        action('H', { kind: 'deploy' }),
        action('U', { safetyClass: null, applyTier: null }),
      ],
      'fleet',
    );
    const s = buildRepairSummary(bundle);
    expect(s.derived_state).toBe(1);
    expect(s.confirmed_local).toBe(1);
    expect(s.human_required).toBe(2); // deploy + unclassified both fail closed
    expect(s.total).toBe(4);
  });

  it('shrinks after a card clears (re-evaluated set is smaller)', () => {
    const before = buildRepairSummary(buildBundle([action('D'), action('E')], 'fleet'));
    // 'D' cleared on the rebuild → only 'E' remains in the re-gathered set.
    const after = buildRepairSummary(buildBundle([action('E')], 'fleet'));
    expect(after.total).toBe(before.total - 1);
  });
});

// ── controls render (read-only: copy commands, never execute) ────────────────────
describe('renderRepairControlsHTML', () => {
  it('renders both controls, scope-aware, copying the derived-state command + bundle', () => {
    const bundle = buildBundle([action('D')], 'project:glam');
    const html = renderRepairControlsHTML(bundle, 'project:glam');
    expect(html).toContain('Repair automatically');
    expect(html).toContain('Copy agent repair plan');
    expect(html).toContain('repair apply --safe-derived-state --scope project:glam');
    expect(html).not.toContain('--safe --confirm'); // auto control never escalates
  });

  it('buildAgentRepairPlanText is valid JSON round-tripping the bundle', () => {
    const bundle = buildBundle([action('D')], 'fleet');
    expect(JSON.parse(buildAgentRepairPlanText(bundle))).toEqual(bundle);
  });

  it('repairPlanCommand targets the emit-only plan subcommand', () => {
    expect(repairPlanCommand('fleet')).toBe('dontpanic repair plan --scope fleet --format=json');
  });
});
