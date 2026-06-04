// ── Skill Recommendations Logic — Unit Tests (plan 2026-05-30-001 F016) ──
//
// Proves the dashboard actually LOADS + RENDERS the F016 skill-recommendation
// report as per-skill SkillAction cards (not merely a state blob), covering
// F016 AC9: the dashboard surface renders the SAME per-skill fields the CLI
// `dontpanic skills recommend` prints — skill name, recommendation, reason,
// risk, exact_command (when present), approval_required, evidence_target — plus
// blockers, the single missing-input action, and migration candidates.

import { describe, it, expect } from 'vitest';
import {
  renderSkillRecommendationsHTML,
  hasRecommendations,
} from '../../lib/skill-recommendations-logic.js';

// A RecommendationReport.to_dict() shape — the EXACT JSON the Python CLI
// `dontpanic skills recommend --format json` prints and `dashboard build`
// writes to `state/skill-recommendations.json` (AC9 parity).
const report = {
  schema_version: '1.0',
  plan_id: '2026-05-30-001-demo',
  stage: null,
  actions: [
    {
      skill_name: 'needy',
      recommendation: 'blocked_missing_inputs',
      reason: 'missing required inputs: [\'token\']',
      risk: 'low',
      exact_command: null,
      approval_required: false,
      evidence_target: null,
      missing_inputs: ['token'],
    },
    {
      skill_name: 'deployer',
      recommendation: 'approval_required',
      reason: 'declared approval_required',
      risk: 'high',
      exact_command: 'dontpanic skills run deployer',
      approval_required: true,
      evidence_target: 'evidence/deploy.json',
      missing_inputs: [],
    },
  ],
  blockers: [
    {
      skill_name: 'deployer',
      missing_inputs: [],
      unavailable_resources: [
        { id: 'secret_anthropic_auth', title: 'Anthropic auth', scope: 'secret', status: 'needs_setup', ok: false, summary: '', safe_command: 'dontpanic config set ...' },
      ],
      explanation: 'deployer is blocked: unavailable config: Anthropic auth (needs_setup)',
    },
  ],
  missing_input_action: {
    id: 'skills-missing-inputs',
    kind: 'skill_missing_input',
    title: 'Provide missing skill inputs',
    rationale: 'Missing skill input(s): token.',
  },
  dashboard_affordance: null,
  migration_candidates: ['legacy-skill'],
};

describe('hasRecommendations', () => {
  it('is false for null / empty report', () => {
    expect(hasRecommendations(null)).toBe(false);
    expect(hasRecommendations({})).toBe(false);
    expect(hasRecommendations({ actions: [] })).toBe(false);
  });

  it('is true when the report carries at least one action', () => {
    expect(hasRecommendations(report)).toBe(true);
  });
});

describe('renderSkillRecommendationsHTML', () => {
  it('renders the empty state with a build pointer when no report is present', () => {
    const html = renderSkillRecommendationsHTML(null);
    expect(html).toContain('No skill recommendations yet');
    expect(html).toContain('dontpanic dashboard build');
  });

  it('renders every per-skill SkillAction field the CLI prints (AC9 parity)', () => {
    const html = renderSkillRecommendationsHTML(report);
    // skill name + recommendation + risk for each surfaced skill
    expect(html).toContain('needy');
    expect(html).toContain('blocked_missing_inputs');
    expect(html).toContain('deployer');
    expect(html).toContain('approval_required');
    expect(html).toContain('risk: high');
    // reason
    expect(html).toContain('declared approval_required');
    // exact_command (only when present)
    expect(html).toContain('dontpanic skills run deployer');
    // approval_required badge
    expect(html).toContain('approval required');
    // evidence_target
    expect(html).toContain('evidence/deploy.json');
    // missing_inputs
    expect(html).toContain('token');
  });

  it('renders the F008 blocker explanation + remediation', () => {
    const html = renderSkillRecommendationsHTML(report);
    expect(html).toContain('deployer is blocked');
    expect(html).toContain('secret_anthropic_auth');
    expect(html).toContain('dontpanic config set');
  });

  it('renders the single missing-input action', () => {
    const html = renderSkillRecommendationsHTML(report);
    expect(html).toContain('Provide missing skill inputs');
    expect(html).toContain('Missing skill input(s): token.');
  });

  it('renders migration candidates with exact suggest commands', () => {
    const html = renderSkillRecommendationsHTML(report);
    expect(html).toContain('legacy-skill');
    expect(html).toContain('dontpanic skills rubric --suggest legacy-skill');
  });

  it('escapes user-supplied skill text (no raw HTML injection)', () => {
    const evil = {
      plan_id: 'p',
      actions: [{
        skill_name: '<img src=x onerror=alert(1)>',
        recommendation: 'suggest',
        reason: 'r',
        risk: 'low',
        exact_command: null,
        approval_required: false,
        evidence_target: null,
        missing_inputs: [],
      }],
      blockers: [],
      missing_input_action: null,
      migration_candidates: [],
    };
    const html = renderSkillRecommendationsHTML(evil);
    expect(html).not.toContain('<img src=x');
    expect(html).toContain('&lt;img');
  });
});
