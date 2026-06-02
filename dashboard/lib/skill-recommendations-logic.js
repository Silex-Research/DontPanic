// ── Skill Recommendations Logic — Pure transformations + HTML builders ──
// Renders the F016 skill recommendation report (plan 2026-05-30-001) as
// dashboard Settings cards. Consumes the projection written by
// `dontpanic dashboard build` / `dontpanic dashboard serve` to
// `dashboard/state/skill-recommendations.json` — the SAME
// RecommendationReport the CLI `dontpanic skills recommend` prints (AC9), so
// the two surfaces can never drift.
//
// The view is read-only. Exact commands and evidence targets are copyable
// text the operator runs in their own terminal; the dashboard never executes
// a skill or mutates state.
//
// All exports are pure: same input → same string output. DOM access lives in
// `pages/settings/settings.js`.

import { esc } from './html-escape.js';

const REFRESH_COMMAND = 'dontpanic dashboard build';
const SOURCE = 'dashboard/state/skill-recommendations.json';
const CLI_COMMAND = 'dontpanic skills recommend';

// Coarse risk-band → color modifier (mirrors the Python `Risk` enum values).
const RISK_COLORS = Object.freeze({
  low: 'green',
  medium: 'yellow',
  high: 'red',
});

function riskColor(risk) {
  return RISK_COLORS[risk] || 'muted';
}

/** True when the report carries at least one surfaced skill action. */
export function hasRecommendations(report) {
  if (!report || typeof report !== 'object') return false;
  return Array.isArray(report.actions) && report.actions.length > 0;
}

// ── one SkillAction card ──
//
// Renders the SAME per-skill fields the CLI prints (AC9): skill name,
// recommendation, reason, risk, exact_command (when present),
// approval_required, evidence_target. Missing inputs are listed when present.

function renderActionHTML(action) {
  if (!action || typeof action !== 'object') return '';
  const risk = action.risk || 'low';
  const approval = action.approval_required === true
    ? '<span class="sr-approval">approval required</span>'
    : '';
  const command = action.exact_command
    ? `<div class="sr-field sr-command"><span class="sr-field-label">command</span><code class="sr-code">${esc(action.exact_command)}</code></div>`
    : '';
  const evidence = action.evidence_target
    ? `<div class="sr-field sr-evidence"><span class="sr-field-label">evidence</span><code class="sr-code">${esc(action.evidence_target)}</code></div>`
    : '';
  const missing = Array.isArray(action.missing_inputs) && action.missing_inputs.length > 0
    ? `<div class="sr-field sr-missing"><span class="sr-field-label">missing</span><span class="sr-missing-list">${esc(action.missing_inputs.join(', '))}</span></div>`
    : '';
  return `
    <div class="sr-card sr-card--${riskColor(risk)}"
         data-skill="${esc(action.skill_name)}"
         data-recommendation="${esc(action.recommendation || '')}">
      <div class="sr-card-head">
        <span class="sr-skill-name">${esc(action.skill_name)}</span>
        <span class="sr-recommendation">${esc(action.recommendation || '')}</span>
        <span class="sr-risk-badge sr-risk-badge--${riskColor(risk)}">risk: ${esc(risk)}</span>
        ${approval}
      </div>
      <div class="sr-field sr-reason"><span class="sr-field-label">reason</span><span>${esc(action.reason || '')}</span></div>
      ${command}
      ${evidence}
      ${missing}
    </div>
  `;
}

function renderBlockerHTML(blocker) {
  if (!blocker || typeof blocker !== 'object') return '';
  const rows = Array.isArray(blocker.unavailable_resources)
    ? blocker.unavailable_resources
      .map((r) => `<li class="sr-blocker-resource">${esc(r.id)} [${esc(r.status)}]${r.safe_command ? ` — fix: <code class="sr-code">${esc(r.safe_command)}</code>` : ''}</li>`)
      .join('')
    : '';
  return `
    <div class="sr-blocker" data-skill="${esc(blocker.skill_name)}">
      <span class="sr-blocker-text">${esc(blocker.explanation || '')}</span>
      ${rows ? `<ul class="sr-blocker-resources">${rows}</ul>` : ''}
    </div>
  `;
}

function renderMissingInputActionHTML(action) {
  if (!action || typeof action !== 'object') return '';
  return `
    <div class="sr-missing-input-action" data-action-id="${esc(action.id || '')}">
      <span class="sr-mia-title">→ ${esc(action.title || '')}</span>
      <span class="sr-mia-rationale">${esc(action.rationale || '')}</span>
    </div>
  `;
}

function renderMigrationHTML(report) {
  const names = Array.isArray(report.migration_candidates) ? report.migration_candidates : [];
  if (names.length === 0) return '';
  const items = names
    .map((n) => `<li class="sr-migration-item">${esc(n)} — <code class="sr-code">dontpanic skills rubric --suggest ${esc(n)}</code></li>`)
    .join('');
  return `
    <div class="sr-migration">
      <div class="sr-migration-head">Migration (advisory — core use is not blocked): these high-value skills lack an invocation rubric.</div>
      <ul class="sr-migration-list">${items}</ul>
    </div>
  `;
}

/**
 * Render the full skill-recommendation report as a Settings section. Returns
 * the empty-state shell when the report is absent or carries no actions so the
 * operator sees an honest "run build" pointer (AC9 parity with the CLI).
 *
 * @param {object|null} report  the parsed `skill-recommendations.json`.
 * @returns {string} HTML.
 */
export function renderSkillRecommendationsHTML(report) {
  if (!hasRecommendations(report)) {
    return `
      <section class="sr-section sr-section--empty" data-source="${esc(SOURCE)}">
        <h3 class="sr-title">Skill Recommendations</h3>
        <p class="sr-empty">No skill recommendations yet. Run <code class="sr-code">${esc(REFRESH_COMMAND)}</code> against a plan, then refresh.</p>
        <p class="sr-cli-note">Same data as <code class="sr-code">${esc(CLI_COMMAND)}</code>.</p>
      </section>
    `;
  }
  const head = `${esc(report.plan_id || '(unknown plan)')}${report.stage ? ` / stage=${esc(report.stage)}` : ''}`;
  const actions = report.actions.map(renderActionHTML).join('');
  const blockers = Array.isArray(report.blockers)
    ? report.blockers.map(renderBlockerHTML).join('')
    : '';
  const missingInput = renderMissingInputActionHTML(report.missing_input_action);
  const migration = renderMigrationHTML(report);
  return `
    <section class="sr-section" data-source="${esc(SOURCE)}">
      <h3 class="sr-title">Skill Recommendations <span class="sr-plan">${head}</span></h3>
      <p class="sr-cli-note">Same data as <code class="sr-code">${esc(CLI_COMMAND)}</code>.</p>
      <div class="sr-cards">${actions}</div>
      ${blockers ? `<div class="sr-blockers">${blockers}</div>` : ''}
      ${missingInput}
      ${migration}
    </section>
  `;
}
