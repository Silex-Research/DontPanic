// ── Project Selector Logic — Pure transformations + HTML builders ──
// Plan 2026-05-23-005 F003. Consumes the F001/F002 fleet-summary
// envelope as written to `dashboard/state/fleet-summary.json` by
// `dontpanic dashboard build --project all|<name>`.
//
// The selector is read-only against governed state: it never mutates
// the `~/.dontpanic/projects.json` registry. Add Project renders the
// exact `dontpanic projects add <name> <path>` command the operator
// runs themselves in a terminal.
//
// All exports are pure: same input → same string output. DOM access is
// confined to the shell wiring in `core.js`.
//
// Three scope labels are emitted as small chips so dashboard sections
// can declare their scope without each page reinventing the badge
// markup:
//   - `Scope: Global` — DontPanic install config + installed capabilities.
//   - `Scope: Project` — plans, gates, architecture, evidence for the
//     selected project.
//   - `Scope: Fleet`   — cross-project rollups (All Projects).

import { esc } from './html-escape.js';

/** Selector sentinel for "All Projects". Matches the CLI sentinel. */
export const ALL_PROJECTS_VALUE = 'all';

/** Closed set of scope labels declared on V0 dashboard sections. */
export const SCOPES = Object.freeze(['global', 'project', 'fleet']);

export const SCOPE_LABELS = Object.freeze({
  global:  'Global',
  project: 'Project',
  fleet:   'Fleet',
});

/** URL search-param name used for selection persistence. */
export const URL_PARAM = 'project';

/** localStorage key used as the fallback default. */
export const STORAGE_KEY = 'dontpanic.dashboard.selectedProject';

/**
 * `true` iff the fleet summary envelope is absent or unparseable.
 * @param {unknown} envelope
 */
export function isMissingFleetSummary(envelope) {
  if (envelope == null) return true;
  if (typeof envelope !== 'object') return true;
  if (!Array.isArray(envelope.projects)) return true;
  return false;
}

/**
 * Coerce a raw JSON value into a normalized fleet summary envelope.
 * Returns null when the value doesn't look like a fleet summary cache.
 * Drops any project entry without a stable `name` so the selector
 * cannot point at an unidentified row.
 * @param {unknown} raw
 */
export function normalizeFleetSummary(raw) {
  if (isMissingFleetSummary(raw)) return null;
  const projects = raw.projects
    .map(normalizeProject)
    .filter((p) => p != null);
  return {
    schema_version:    typeof raw.schema_version === 'string' ? raw.schema_version : '',
    captured_at:       typeof raw.captured_at === 'string' ? raw.captured_at : '',
    dontpanic_version: typeof raw.dontpanic_version === 'string' ? raw.dontpanic_version : '',
    project_count:     typeof raw.project_count === 'number' ? raw.project_count : projects.length,
    active_count:      typeof raw.active_count === 'number' ? raw.active_count : projects.filter((p) => p.active).length,
    worst_band:        typeof raw.worst_band === 'string' ? raw.worst_band : 'ready',
    projects,
  };
}

function normalizeProject(raw) {
  if (raw == null || typeof raw !== 'object') return null;
  if (typeof raw.name !== 'string' || raw.name.length === 0) return null;
  return {
    name:           raw.name,
    display_name:   typeof raw.display_name === 'string' && raw.display_name.length > 0 ? raw.display_name : raw.name,
    profile:        typeof raw.profile === 'string' ? raw.profile : null,
    active:         raw.active !== false,
    health_band:    typeof raw.health_band === 'string' ? raw.health_band : 'ready',
    warning_count:  typeof raw.warning_count === 'number' ? raw.warning_count : 0,
    skipped:        raw.skipped === true,
    skipped_reason: typeof raw.skipped_reason === 'string' ? raw.skipped_reason : null,
  };
}

/**
 * Build the option list (`{value, label}`) for the selector, with
 * `All Projects` first and registered projects in registry order.
 * @param {object|null} envelope normalized fleet summary
 */
export function getProjectOptions(envelope) {
  const options = [{ value: ALL_PROJECTS_VALUE, label: 'All Projects' }];
  if (envelope == null) return options;
  for (const p of envelope.projects) {
    const tag = p.active ? '' : ' (inactive)';
    options.push({ value: p.name, label: `${p.display_name}${tag}` });
  }
  return options;
}

/**
 * Resolve the active selection, in priority order:
 *   1. URL search-param (`?project=<name>`).
 *   2. localStorage fallback default.
 *   3. `all` when the fleet summary is present.
 *
 * The resolved value is always a member of `options` — if a stale
 * URL or storage value points at a name that's no longer registered,
 * fall through to the next layer rather than render a phantom row.
 *
 * @param {object} args
 * @param {string|null} args.urlValue param read from URLSearchParams
 * @param {string|null} args.storageValue value read from localStorage
 * @param {Array<{value:string,label:string}>} args.options getProjectOptions output
 * @returns {{ value: string, source: 'url'|'storage'|'default' }}
 */
export function resolveSelection({ urlValue, storageValue, options }) {
  const valid = new Set(options.map((o) => o.value));
  if (typeof urlValue === 'string' && valid.has(urlValue)) {
    return { value: urlValue, source: 'url' };
  }
  if (typeof storageValue === 'string' && valid.has(storageValue)) {
    return { value: storageValue, source: 'storage' };
  }
  return { value: ALL_PROJECTS_VALUE, source: 'default' };
}

/**
 * Build a fresh URL for the same page with `?project=<value>` set
 * (or removed when `value === ALL_PROJECTS_VALUE`). Returns the
 * absolute URL string — the shell pushes it via history.replaceState.
 * The hash (which carries the active page id) is preserved verbatim.
 * @param {string|URL} baseHref
 * @param {string} value
 */
export function buildSelectionURL(baseHref, value) {
  const url = new URL(String(baseHref));
  if (value === ALL_PROJECTS_VALUE) {
    url.searchParams.delete(URL_PARAM);
  } else {
    url.searchParams.set(URL_PARAM, value);
  }
  return url.toString();
}

/**
 * Compute the exact registration command shape Add Project surfaces.
 * Defaults to placeholder values; callers can override either side
 * when prefilling from cwd / registry state.
 */
export function formatAddProjectCommand(name = '<name>', path = '<path>') {
  return `dontpanic projects add ${name} ${path}`;
}

/**
 * Exact command shape surfaced when the fleet summary is missing.
 */
export function formatBuildFleetCommand() {
  return 'dontpanic dashboard build --project all';
}

// ─────────────────────────────────────────────────────────────────────────
// HTML builders
// ─────────────────────────────────────────────────────────────────────────

/**
 * Inline selector chip rendered in the dashboard header. Includes:
 *   - a labeled `<select>` with All Projects + every registered project
 *   - a scope chip declaring the current selection (Project vs Fleet)
 *   - an Add Project command-emission row
 *
 * The select uses `data-project-selector` so the shell can wire its
 * change handler without re-rendering the surrounding markup.
 *
 * @param {object|null} envelope normalized fleet summary
 * @param {string} selected the currently-resolved selection value
 */
export function renderSelectorHTML(envelope, selected) {
  const options = getProjectOptions(envelope);
  const scope = selected === ALL_PROJECTS_VALUE ? 'fleet' : 'project';
  const optionsHTML = options.map((opt) => {
    const isSelected = opt.value === selected ? ' selected' : '';
    return `<option value="${esc(opt.value)}"${isSelected}>${esc(opt.label)}</option>`;
  }).join('');
  return `
    <div class="project-selector" data-state="${esc(envelope == null ? 'missing' : 'ready')}">
      <label class="project-selector-label" for="project-selector-input">Project</label>
      <select class="project-selector-input"
              id="project-selector-input"
              data-project-selector="1"
              aria-label="Selected project">
        ${optionsHTML}
      </select>
      ${renderScopeBadgeHTML(scope)}
      ${renderAddProjectHTML()}
    </div>
  `;
}

/**
 * Renders the missing-fleet-summary banner. Wired into the selector
 * container when `state.fleetSummary` is null so the operator gets a
 * single actionable command rather than a silent empty selector. The
 * Add Project command-emission row is included here too: with no fleet
 * summary, registering a project is the most likely next step, and the
 * acceptance contract requires Add Project to be present whenever the
 * selector surface renders.
 */
export function renderMissingSummaryHTML() {
  const cmd = formatBuildFleetCommand();
  return `
    <div class="project-selector-missing" data-state="missing">
      <div class="project-selector-missing-title">No fleet summary yet</div>
      <div class="project-selector-missing-body">
        Build the All-Projects rollup so the selector can list every
        registered project:
      </div>
      <pre class="project-selector-missing-cmd"><code>${esc(cmd)}</code></pre>
      ${renderAddProjectHTML()}
    </div>
  `;
}

/**
 * Renders the Add Project command-emission row. The dashboard does
 * NOT mutate the registry — Add Project surfaces the exact command
 * the operator runs themselves, never an inline form.
 */
export function renderAddProjectHTML() {
  const cmd = formatAddProjectCommand();
  return `
    <div class="project-selector-add" data-add-project="1">
      <span class="project-selector-add-label">Add project</span>
      <code class="project-selector-add-cmd">${esc(cmd)}</code>
    </div>
  `;
}

/**
 * Build a `Scope: <Label>` chip for a dashboard section. Pages call
 * this to declare which governance domain they belong to without
 * duplicating the badge markup.
 * @param {'global'|'project'|'fleet'} scope
 */
export function renderScopeBadgeHTML(scope) {
  const key = SCOPES.includes(scope) ? scope : 'project';
  const label = SCOPE_LABELS[key];
  return `
    <span class="scope-badge scope-badge--${esc(key)}" data-scope="${esc(key)}">
      <span class="scope-badge-label">Scope:</span>
      <span class="scope-badge-value">${esc(label)}</span>
    </span>
  `;
}

/**
 * Convenience: structured payload the shell uses to render the whole
 * header strip (selector + missing-state). Pure — DOM wiring lives
 * in `core.js`.
 * @param {object} args
 * @param {object|null} args.envelope normalized fleet summary
 * @param {string} args.selected resolved selection value
 */
export function renderHeaderStripHTML({ envelope, selected }) {
  if (envelope == null) {
    return renderMissingSummaryHTML();
  }
  return renderSelectorHTML(envelope, selected);
}
