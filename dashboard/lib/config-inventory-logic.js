// ── Config Inventory Logic — Pure transformations + HTML builders ──
// Renders the F008 configuration inventory (plan 2026-05-30-001 F013) as
// dashboard Settings / Setup cards. Consumes the projection written by
// `dontpanic dashboard build` / `dontpanic dashboard serve` to
// `dashboard/state/config-inventory.json` — the SAME data the CLI
// `dontpanic config inventory` shows.
//
// The view is read-only. Edit affordances and run-actions are copyable
// command text the operator runs in their own terminal; the dashboard never
// mutates `~/.dontpanic/` config or secrets itself.
//
// All exports are pure: same input → same string output. DOM access lives
// in `pages/settings/settings.js`.

import { esc } from './html-escape.js';
import { renderProvenanceFooterHTML } from './provenance.js';
import { ALL_PROJECTS_VALUE } from './project-selector-logic.js';

const REFRESH_COMMAND = 'dontpanic dashboard build';
const SOURCE = 'dashboard/state/config-inventory.json';
const CLI_COMMAND = 'dontpanic config inventory';

// Human-readable status labels. Mirrors the Python `Status` enum values so a
// card's `status` string maps to a stable badge label + color modifier.
export const STATUS_LABELS = Object.freeze({
  ok: 'OK',
  needs_setup: 'NEEDS SETUP',
  missing: 'MISSING',
  optional_unconfigured: 'OPTIONAL',
  human_required: 'HUMAN REQUIRED',
  unknown: 'UNKNOWN',
});

export const STATUS_COLORS = Object.freeze({
  ok: 'green',
  needs_setup: 'yellow',
  missing: 'red',
  optional_unconfigured: 'muted',
  human_required: 'red',
  unknown: 'muted',
});

function statusLabel(status) {
  return STATUS_LABELS[status] || String(status || '').toUpperCase() || 'UNKNOWN';
}

function statusColor(status) {
  return STATUS_COLORS[status] || 'muted';
}

// ── per-project envelope resolution (project/fleet builds) ──
//
// Project + fleet builds mirror each project's inventory under
// `state/projects/<name>/config-inventory.json`; the loader keys those into
// `state.configInventoryByProject`. When a concrete project is selected we must
// render THAT project's inventory, not the top-level (machine-scope) blob —
// otherwise a served project dashboard shows the wrong scope (codex i1 finding).

/**
 * Resolve the effective config-inventory projection for the selected project.
 *
 *   - `all` (fleet) → the top-level single-repo / focused projection.
 *   - a concrete project with a per-project entry → that entry.
 *   - a concrete project whose per-project cache is present but lacks the
 *     entry → `null` (callers render the missing/empty state rather than
 *     silently showing another scope's inventory).
 *   - otherwise → the top-level projection (no per-project cache yet).
 *
 * @param {object} opts
 * @param {string} [opts.selectedProject]
 * @param {object|null} [opts.single]   the top-level `config-inventory.json`.
 * @param {object|null} [opts.byProject] map keyed by project name.
 * @returns {object|null}
 */
export function resolveConfigInventory(opts = {}) {
  const selected = typeof opts.selectedProject === 'string'
    ? opts.selectedProject
    : ALL_PROJECTS_VALUE;
  const byProject = opts.byProject && typeof opts.byProject === 'object'
    ? opts.byProject
    : null;
  const hasPerProjectCache = byProject != null && Object.keys(byProject).length > 0;
  if (selected !== ALL_PROJECTS_VALUE && hasPerProjectCache) {
    const scoped = byProject[selected];
    if (scoped != null) return scoped;
    // Per-project cache present but no entry for the selection: do NOT fall
    // back to opts.single — that would render machine-scope as if it were the
    // project's. Return null so the caller branches to the missing state.
    return null;
  }
  return opts.single != null ? opts.single : null;
}

/**
 * True when a concrete project is selected and the per-project cache is
 * present but has no entry for it — the caller renders the missing state
 * instead of another scope's inventory.
 */
export function isMissingSelectedProjectInventory(opts = {}) {
  const selected = typeof opts.selectedProject === 'string'
    ? opts.selectedProject
    : ALL_PROJECTS_VALUE;
  if (selected === ALL_PROJECTS_VALUE) return false;
  const byProject = opts.byProject && typeof opts.byProject === 'object'
    ? opts.byProject
    : null;
  if (byProject == null) return false;
  if (Object.keys(byProject).length === 0) return false;
  return byProject[selected] == null;
}

/** True when the projection is a usable config-inventory state blob. */
export function hasInventory(state) {
  if (!state || typeof state !== 'object') return false;
  if (state.kind !== 'config_inventory') return false;
  const settings = Array.isArray(state.settings_cards) ? state.settings_cards : [];
  const setup = Array.isArray(state.setup_cards) ? state.setup_cards : [];
  return settings.length + setup.length > 0;
}

// ── dashboard hint (AC2 + AC3): rendered exactly once at the top ──

function renderDashboardHintHTML(hint) {
  if (!hint || typeof hint !== 'object') return '';
  const running = hint.is_running === true;
  const detail = running
    ? `Open <a class="ci-hint-link" href="${esc(hint.active_url)}">${esc(hint.active_url)}</a>`
    : `Start it with <code class="ci-code">${esc(hint.start_command)}</code>`;
  return `
    <div class="ci-dashboard-hint ci-dashboard-hint--${running ? 'running' : 'stopped'}"
         id="ci-dashboard-hint"
         data-hint-id="${esc(hint.hint_id)}"
         data-running="${running ? '1' : '0'}">
      <span class="ci-hint-icon">${running ? '●' : '○'}</span>
      <span class="ci-hint-text">${esc(hint.text)}</span>
      <span class="ci-hint-detail">${detail}</span>
    </div>
  `;
}

// ── one inventory card ──

function renderEditAffordanceHTML(card) {
  const edit = card.edit || {};
  // AC4: the exact, validated edit command. F008 guarantees this is never a
  // build/start/serve run-action, so it is always safe to render as an edit.
  if (edit.command) {
    return `
      <div class="ci-affordance ci-affordance--edit">
        <span class="ci-affordance-label">Edit</span>
        <code class="ci-edit-command">${esc(edit.command)}</code>
      </div>
    `;
  }
  // An arg-taking edit route surfaces as a fill-in template — info, not a
  // runnable command.
  if (edit.command_template) {
    return `
      <div class="ci-affordance ci-affordance--edit-template">
        <span class="ci-affordance-label">Edit (template)</span>
        <code class="ci-edit-template">${esc(edit.command_template)}</code>
      </div>
    `;
  }
  return '';
}

function renderRunActionHTML(card) {
  const run = card.run_action;
  if (!run || !run.command) return '';
  // AC4: build/start/serve surfaces render DISTINCTLY from edit affordances —
  // a separate, clearly-labelled run-action control, never an edit command.
  return `
    <div class="ci-affordance ci-affordance--run">
      <span class="ci-affordance-label">Run action</span>
      <code class="ci-run-action">${esc(run.command)}</code>
    </div>
  `;
}

function renderHintRefHTML(card) {
  // AC3: human-required cards reference the single response-level hint by id —
  // they never repeat its text.
  if (!card.human_required || !card.dashboard_hint_ref) return '';
  return `
    <div class="ci-hint-ref" data-hint-ref="${esc(card.dashboard_hint_ref)}">
      Human-required — see the dashboard pointer above.
    </div>
  `;
}

function renderCardHTML(card) {
  const status = card.status || 'unknown';
  return `
    <div class="ci-card ci-card--${statusColor(status)}"
         data-card-id="${esc(card.id)}"
         data-status="${esc(status)}">
      <div class="ci-card-head">
        <span class="ci-card-title">${esc(card.title)}</span>
        <span class="ci-status-badge ci-status-badge--${statusColor(status)}">${esc(statusLabel(status))}</span>
        ${card.optional ? '<span class="ci-optional-chip">optional</span>' : ''}
      </div>
      <div class="ci-card-scope">${esc(card.scope)}</div>
      <p class="ci-card-summary">${esc(card.summary)}</p>
      <div class="ci-card-owner">Owner: <code class="ci-code">${esc(card.owner)}</code></div>
      ${card.detail ? `<p class="ci-card-detail">${esc(card.detail)}</p>` : ''}
      ${renderEditAffordanceHTML(card)}
      ${renderRunActionHTML(card)}
      ${renderHintRefHTML(card)}
    </div>
  `;
}

function renderSectionHTML(titleText, descText, cards, extraClass) {
  if (!cards.length) return '';
  return `
    <section class="panel ci-section ${extraClass}">
      <h2>${esc(titleText)}</h2>
      <p class="ci-section-desc">${esc(descText)}</p>
      <div class="ci-cards">
        ${cards.map(renderCardHTML).join('')}
      </div>
    </section>
  `;
}

// ── empty state ──

function renderEmptyStateHTML() {
  return `
    <section class="panel ci-section ci-empty-state">
      <h2>Configuration inventory</h2>
      <p class="ci-section-desc">
        No configuration inventory has been generated yet. Run
        <code class="ci-code">${esc(REFRESH_COMMAND)}</code> to write
        <code class="ci-code">${esc(SOURCE)}</code>, or inspect it directly with
        <code class="ci-code">${esc(CLI_COMMAND)}</code>.
      </p>
    </section>
  `;
}

/**
 * Render the config inventory as Settings / Setup cards.
 *
 * @param {object|null} state — the `config-inventory.json` projection.
 * @returns {string} HTML.
 */
export function renderConfigInventoryHTML(state) {
  if (!hasInventory(state)) return renderEmptyStateHTML();

  const settings = Array.isArray(state.settings_cards) ? state.settings_cards : [];
  const setup = Array.isArray(state.setup_cards) ? state.setup_cards : [];
  const scopeLabel = state.project_name || state.project_path
    ? `project: ${state.project_name || state.project_path}`
    : 'scope: machine (no project)';

  return `
    <div class="ci-layout">
      <div class="ci-scope-label">${esc(scopeLabel)}</div>
      ${renderDashboardHintHTML(state.dashboard_hint)}
      ${renderSectionHTML(
        'Setup — needs attention',
        'Configuration surfaces that are incomplete, missing, or require a human. '
          + 'Each card carries the exact command (or fill-in template) that routes '
          + 'through a validated CLI surface.',
        setup,
        'ci-section--setup',
      )}
      ${renderSectionHTML(
        'Settings — configured surfaces',
        'Configured, editable surfaces. Edit affordances are validated commands; '
          + 'build/start/serve run-actions are shown separately.',
        settings,
        'ci-section--settings',
      )}
      ${renderProvenanceFooterHTML({
        source: SOURCE,
        lastUpdated: null,
        refreshCommand: REFRESH_COMMAND,
        note: 'Same data as `dontpanic config inventory`. Edits run through the '
          + 'dontpanic CLI; the dashboard never mutates ~/.dontpanic/ directly.',
      })}
    </div>
  `;
}
