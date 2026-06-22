// ── Health Logic — Pure HTML builders + data composition ──
// Drives the Health page. Per copy-map.md §2.5, Health is the honesty
// surface: every card has a credible data source or a named missing-data
// state. We never render an empty card as "OK".
//
// Sources composed:
//   - dashboard/state/capabilities-status.json (install readiness)
//   - dashboard/state/what-now.json (build warnings, reconcile drift)
//   - dashboard/state/security.json (hook decision audit log)
//   - dashboard/state/fleet-summary.json (fleet-level warning counts)
//   - dashboard/state/quota.json or .quota stream (budget guardrails)
//
// All exports are pure: same input → same string output, no DOM access.
// The page module (`pages/health/health.js`) is responsible for wiring
// this into `Jarvis.getPageEl('health').innerHTML`.

import { esc } from './html-escape.js';
import {
  ALL_PROJECTS_VALUE,
  renderScopeBadgeHTML,
} from './project-selector-logic.js';
import { normalizeEnvelope as normalizeWhatNow } from './what-now-logic.js';
import { normalizeEnvelope as normalizeCapabilities } from './capabilities-logic.js';
import { aggregateStats } from './security-logic.js';
import { renderProvenanceFooterHTML } from './provenance.js';

/**
 * Build all Health page sections from the dashboard state.
 *
 * @param {object} state
 * @param {object|null} state.capabilities
 * @param {object|null} state.upgradeStatus
 * @param {object|null} state.whatNow
 * @param {Array<object>|null} state.security
 * @param {object|null} state.fleetSummary
 * @param {Array<object>|object|null} state.quota
 * @param {string|null} state.selectedProject
 * @returns {string} innerHTML for the Health page
 */
export function renderHealthHTML(state) {
  state = state || {};
  const selected = typeof state.selectedProject === 'string'
    ? state.selectedProject
    : ALL_PROJECTS_VALUE;
  const scope = selected === ALL_PROJECTS_VALUE ? 'fleet' : 'project';
  const sections = [
    renderHeaderHTML(scope, selected, state.fleetSummary),
    renderUpgradeStatusCardHTML(state.upgradeStatus),
    renderInstallHealthCardHTML(state.capabilities),
    renderSetupDriftCardHTML(state.whatNow, scope),
    renderBuildWarningsCardHTML(state.whatNow, scope),
    renderSecurityCardHTML(state.security),
    renderBudgetGuardrailCardHTML(state.quota),
    renderFleetWarningsCardHTML(state.fleetSummary, scope, selected),
  ];
  return `
    <div class="hlth-layout" data-scope="${esc(scope)}">
      ${sections.join('')}
      <section class="panel hlth-footer-panel">
        <div class="hlth-footer-line">
          Health composes the install/setup/build-warning data already on disk.
          Run <code>dontpanic dashboard build</code> after capability or
          plan changes to refresh every card here.
        </div>
        ${renderProvenanceFooterHTML({
          source: 'dashboard/state/*.json (composed: capabilities-status, what-now, security, fleet-summary, quota)',
          lastUpdated: deriveLatestCaptured(state),
          refreshCommand: 'dontpanic dashboard build',
          note: 'Each card declares its own per-source provenance above. This footer summarizes the page-level inputs.',
        })}
      </section>
    </div>
  `;
}

function deriveLatestCaptured(state) {
  // Health composes several sources; surface the freshest envelope timestamp
  // so the operator can tell "when did anything on this page last refresh?"
  const candidates = [];
  const caps = normalizeCapabilities(state.capabilities);
  if (caps && typeof caps.generated_at === 'string' && caps.generated_at.length > 0) {
    candidates.push(caps.generated_at);
  }
  const wn = normalizeWhatNow(state.whatNow);
  if (wn && typeof wn.captured_at === 'string' && wn.captured_at.length > 0) {
    candidates.push(wn.captured_at);
  }
  if (candidates.length === 0) return null;
  // Lexicographic max works for ISO-8601 timestamps.
  return candidates.reduce((best, ts) => (ts > best ? ts : best));
}

function renderHeaderHTML(scope, selected, fleetSummary) {
  const scopeBadge = renderScopeBadgeHTML(scope);
  const subtitle = scope === 'fleet'
    ? 'Is this DontPanic install safe and current enough to keep using?'
    : `Health for project ${esc(selected)}. Global rows still apply to every project.`;
  let fleetLine = '';
  if (scope === 'fleet' && fleetSummary && Array.isArray(fleetSummary.projects)) {
    const total = fleetSummary.projects.length;
    fleetLine = `<div class="hlth-header-meta">${esc(String(total))} project${total === 1 ? '' : 's'} tracked.</div>`;
  }
  return `
    <section class="panel hlth-header-panel">
      <div class="hlth-header-row">
        <h2>Health</h2>
        <div class="hlth-header-scope">${scopeBadge}</div>
      </div>
      <div class="hlth-header-subtitle">${subtitle}</div>
      ${fleetLine}
    </section>
  `;
}

// ─────────────────────────────────────────────────────────────────────────
// Card helpers
// ─────────────────────────────────────────────────────────────────────────

function cardHTML({ scopeLabel, kind, headline, impact, color, body, source, fixCommand }) {
  const sourceLine = source
    ? `<div class="hlth-card-source">Source: <code>${esc(source)}</code></div>`
    : '';
  const fixLine = fixCommand
    ? `<pre class="hlth-card-fix">${esc(fixCommand)}</pre>`
    : '';
  const scopeChip = scopeLabel
    ? `<span class="hlth-card-scope-chip">${esc(scopeLabel)}</span>`
    : '';
  return `
    <section class="panel hlth-card hlth-card--${esc(color || 'accent')}" data-kind="${esc(kind)}">
      <header class="hlth-card-header">
        <span class="hlth-card-kind">${esc(headline)}</span>
        ${scopeChip}
      </header>
      ${impact ? `<div class="hlth-card-impact">${esc(impact)}</div>` : ''}
      ${body || ''}
      ${fixLine}
      ${sourceLine}
    </section>
  `;
}

function missingDataCardHTML({ kind, headline, sourceFile, fixCommand, scopeLabel }) {
  // Honesty surface: never render an empty card as healthy. Each missing
  // card names the absent file and the exact command that would create it.
  return cardHTML({
    scopeLabel,
    kind,
    headline,
    impact: `No data yet. The dashboard expects ${sourceFile} on disk.`,
    color: 'muted',
    body: '',
    source: sourceFile,
    fixCommand,
  });
}

// ─────────────────────────────────────────────────────────────────────────
// Upgrade status (Plan 2026-06-21-001 F008 — ALWAYS-shown standing signal)
// ─────────────────────────────────────────────────────────────────────────

/**
 * Render the ALWAYS-shown upgrade-readiness status row (D011).
 *
 * Consumes the `upgrade_status_projection` written to
 * `dashboard/state/upgrade-status.json` by the dashboard build. The row is
 * rendered in EVERY state — including the positive up-to-date case — so the
 * Health page never silently omits the "is this install current?" signal.
 *
 * `update_state` (manifest-action readiness) and `upstream_status` (code-level
 * freshness) are DISTINCT and both shown (D031); the row never reads green
 * while the checkout is behind the newest DontPanic. The last-acknowledged line
 * renders `last_acknowledged` (driven by `last_seen_commit`, D037), and
 * `installed_commit` is shown separately as the current checkout. An absent
 * marker renders "never acknowledged" rather than a synthetic acknowledgement
 * (D042) — the projection already encodes that in `last_acknowledged`.
 *
 * @param {object|null} proj the upgrade_status_projection, or null when absent.
 * @returns {string} innerHTML for the upgrade status card.
 */
export function renderUpgradeStatusCardHTML(proj) {
  if (proj == null || typeof proj !== 'object') {
    return missingDataCardHTML({
      kind: 'upgrade',
      headline: 'Upgrade status — no data yet',
      sourceFile: 'dashboard/state/upgrade-status.json',
      fixCommand: 'dontpanic dashboard build',
      scopeLabel: 'global',
    });
  }
  const statusLine = typeof proj.status_line === 'string' && proj.status_line.length > 0
    ? proj.status_line
    : 'DontPanic: upgrade status unknown';
  const updateState = typeof proj.update_state === 'string' ? proj.update_state : 'unknown';
  const upstreamStatus = typeof proj.upstream_status === 'string' ? proj.upstream_status : 'unknown';
  const behind = proj.behind_upstream === true || upstreamStatus === 'behind';
  const pendingRequired = typeof proj.pending_required === 'number' ? proj.pending_required : 0;
  const pendingAdvisory = typeof proj.pending_advisory === 'number' ? proj.pending_advisory : 0;
  // Colour: behind-upstream or a required-pending action is a red signal; pending
  // advisories are yellow; an unknown state is muted; otherwise up-to-date green.
  let color = 'green';
  if (behind || updateState === 'required_pending') {
    color = 'red';
  } else if (updateState === 'advisories_pending') {
    color = 'yellow';
  } else if (updateState === 'unknown') {
    color = 'muted';
  }
  const impact = behind
    ? 'This checkout is behind the newest DontPanic. Pull the latest code, then re-check.'
    : (pendingRequired > 0
      ? 'Required upgrade actions are pending before this install is current.'
      : (pendingAdvisory > 0
        ? 'Optional upgrade advisories are available.'
        : (updateState === 'unknown'
          ? 'Upgrade status could not be determined from the release manifest.'
          : 'This install is up to date with the tracked DontPanic release.')));
  const installedCommit = typeof proj.installed_commit === 'string' && proj.installed_commit.length > 0
    ? proj.installed_commit
    : '—';
  const lastAcknowledged = typeof proj.last_acknowledged === 'string' && proj.last_acknowledged.length > 0
    ? proj.last_acknowledged
    : 'never acknowledged';
  const body = `
    <div class="hlth-upgrade-status-line">${esc(statusLine)}</div>
    <ul class="hlth-card-rows">
      <li><span class="hlth-row-label">Update state</span> <span class="hlth-row-value">${esc(updateState)}</span></li>
      <li><span class="hlth-row-label">Upstream</span> <span class="hlth-row-value">${esc(upstreamStatus)}</span></li>
      <li><span class="hlth-row-label">Required pending</span> <span class="hlth-row-value">${esc(String(pendingRequired))}</span></li>
      <li><span class="hlth-row-label">Advisory pending</span> <span class="hlth-row-value">${esc(String(pendingAdvisory))}</span></li>
      <li><span class="hlth-row-label">Installed commit</span> <span class="hlth-row-value">${esc(installedCommit)}</span></li>
      <li><span class="hlth-row-label">Last acknowledged</span> <span class="hlth-row-value">${esc(lastAcknowledged)}</span></li>
    </ul>
  `;
  return cardHTML({
    scopeLabel: 'global',
    kind: 'upgrade',
    headline: statusLine,
    impact,
    color,
    body,
    source: 'dashboard/state/upgrade-status.json',
    fixCommand: behind ? 'git pull' : undefined,
  });
}

// ─────────────────────────────────────────────────────────────────────────
// Install health (capabilities)
// ─────────────────────────────────────────────────────────────────────────

export function renderInstallHealthCardHTML(rawCapabilities) {
  const env = normalizeCapabilities(rawCapabilities);
  if (env == null) {
    return missingDataCardHTML({
      kind: 'install',
      headline: 'Install readiness — no data yet',
      sourceFile: 'dashboard/state/capabilities-status.json',
      fixCommand: 'dontpanic capabilities status --format=json > dashboard/state/capabilities-status.json',
      scopeLabel: 'global',
    });
  }
  let blocked = 0; let needsSetup = 0; let ready = 0; let notInstalled = 0;
  for (const c of env.capabilities) {
    if (c.status === 'blocked') blocked++;
    else if (c.status === 'needs_setup') needsSetup++;
    else if (c.status === 'ready') ready++;
    else if (c.status === 'not_installed') notInstalled++;
  }
  let color = 'green';
  let headline = 'Install is healthy';
  let impact = `${ready} tools connected. No blockers or unfinished setup.`;
  if (blocked > 0) {
    color = 'red';
    headline = 'Install has blockers';
    impact = `${blocked} tool${blocked === 1 ? '' : 's'} blocked. Resolve them before relying on this install.`;
  } else if (needsSetup > 0) {
    color = 'yellow';
    headline = 'Setup incomplete';
    impact = `${needsSetup} tool${needsSetup === 1 ? '' : 's'} still need setup before they're available.`;
  } else if (notInstalled > 0 && ready === 0) {
    color = 'muted';
    headline = 'Install minimal';
    impact = `${notInstalled} tool${notInstalled === 1 ? '' : 's'} not installed yet; nothing currently connected.`;
  }
  // F006 (plan 2026-06-05-001) — name install readiness "Global tools" so a human
  // reading "Setup incomplete" understands these are install-level tools (set up
  // once for this install), distinct from the tracked-projects count in the header.
  const body = `
    <div class="hlth-global-tools">
      <span class="hlth-global-tools-label">Global tools</span>
      <span class="hlth-global-tools-note">Install-level — set up once for this install, not tied to any project.</span>
    </div>
    <ul class="hlth-card-rows">
      <li><span class="hlth-row-label">Connected</span> <span class="hlth-row-value">${ready}</span></li>
      <li><span class="hlth-row-label">Setup required</span> <span class="hlth-row-value">${needsSetup}</span></li>
      <li><span class="hlth-row-label">Blocked</span> <span class="hlth-row-value">${blocked}</span></li>
      <li><span class="hlth-row-label">Not installed</span> <span class="hlth-row-value">${notInstalled}</span></li>
    </ul>
  `;
  return cardHTML({
    scopeLabel: 'global',
    kind: 'install',
    headline,
    impact,
    color,
    body,
    source: `dashboard/state/capabilities-status.json · captured ${esc(env.generated_at || '—')}`,
    fixCommand: 'dontpanic capabilities status --format=json > dashboard/state/capabilities-status.json',
  });
}

// ─────────────────────────────────────────────────────────────────────────
// Setup drift (reconcile items in what-now)
// ─────────────────────────────────────────────────────────────────────────

export function renderSetupDriftCardHTML(rawWhatNow, scope) {
  const env = normalizeWhatNow(rawWhatNow);
  if (env == null) {
    return missingDataCardHTML({
      kind: 'reconcile',
      headline: 'Setup drift — no data yet',
      sourceFile: 'dashboard/state/what-now.json',
      fixCommand: 'dontpanic dashboard build',
      scopeLabel: 'global',
    });
  }
  const reconcileItems = env.items.filter(it => it.source === 'reconcile');
  if (reconcileItems.length === 0) {
    return cardHTML({
      scopeLabel: 'global',
      kind: 'reconcile',
      headline: 'Install matches baseline',
      impact: 'No setup drift since the last reconcile snapshot.',
      color: 'green',
      body: '',
      source: 'dashboard/state/what-now.json',
    });
  }
  const worst = reconcileItems.some(it => it.band === 'needs_action')
    ? 'needs_action'
    : reconcileItems.some(it => it.band === 'advisory') ? 'advisory' : 'info';
  const color = worst === 'needs_action' ? 'red' : (worst === 'advisory' ? 'yellow' : 'accent');
  const headline = worst === 'needs_action' ? 'Setup drift detected' : 'Setup drift advisory';
  const impact = `${reconcileItems.length} reconcile finding${reconcileItems.length === 1 ? '' : 's'}. Run reconcile to bring the install back in sync.`;
  const body = `
    <ul class="hlth-finding-list">
      ${reconcileItems.slice(0, 5).map(it => `
        <li class="hlth-finding">
          <div class="hlth-finding-title">${esc(it.title || it.id)}</div>
          ${it.detail ? `<div class="hlth-finding-detail">${esc(it.detail)}</div>` : ''}
          ${it.exact_command ? `<pre class="hlth-finding-cmd">${esc(it.exact_command)}</pre>` : ''}
        </li>
      `).join('')}
    </ul>
  `;
  return cardHTML({
    scopeLabel: 'global',
    kind: 'reconcile',
    headline,
    impact,
    color,
    body,
    source: `dashboard/state/what-now.json · captured ${esc(env.captured_at || '—')}`,
  });
}

// ─────────────────────────────────────────────────────────────────────────
// Build warnings (architecture + advisory items)
// ─────────────────────────────────────────────────────────────────────────

export function renderBuildWarningsCardHTML(rawWhatNow, scope) {
  const env = normalizeWhatNow(rawWhatNow);
  if (env == null) {
    return missingDataCardHTML({
      kind: 'build_warnings',
      headline: 'Recent build warnings — no data yet',
      sourceFile: 'dashboard/state/what-now.json',
      fixCommand: 'dontpanic dashboard build',
      scopeLabel: scope === 'fleet' ? 'fleet' : 'project',
    });
  }
  const warnings = env.items.filter(it => it.source === 'architecture' || (it.band === 'advisory' && it.source !== 'reconcile'));
  if (warnings.length === 0) {
    return cardHTML({
      scopeLabel: scope === 'fleet' ? 'fleet' : 'project',
      kind: 'build_warnings',
      headline: 'No recent build warnings',
      impact: 'Nothing flagged by architecture, supervisor, or capability advisories.',
      color: 'green',
      body: '',
      source: 'dashboard/state/what-now.json',
    });
  }
  const color = warnings.some(it => it.band === 'needs_action') ? 'red' : 'yellow';
  const body = `
    <ul class="hlth-finding-list">
      ${warnings.slice(0, 5).map(it => `
        <li class="hlth-finding">
          <div class="hlth-finding-title">${esc(it.title || it.id)}</div>
          ${it.detail ? `<div class="hlth-finding-detail">${esc(it.detail)}</div>` : ''}
          ${it.exact_command ? `<pre class="hlth-finding-cmd">${esc(it.exact_command)}</pre>` : ''}
        </li>
      `).join('')}
    </ul>
  `;
  return cardHTML({
    scopeLabel: scope === 'fleet' ? 'fleet' : 'project',
    kind: 'build_warnings',
    headline: 'Recent build warnings',
    impact: `${warnings.length} warning${warnings.length === 1 ? '' : 's'} on architecture / supervisor / advisory checks.`,
    color,
    body,
    source: `dashboard/state/what-now.json · captured ${esc(env.captured_at || '—')}`,
  });
}

// ─────────────────────────────────────────────────────────────────────────
// Security hook activity (security decisions stream)
// ─────────────────────────────────────────────────────────────────────────

export function renderSecurityCardHTML(rawSecurity) {
  // Honest missing-data state: the file must exist on disk before we make
  // any claim about security posture. An absent file is different from a
  // present-but-empty file, which is a real "no activity" signal.
  if (rawSecurity == null || !Array.isArray(rawSecurity)) {
    return missingDataCardHTML({
      kind: 'security',
      headline: 'Security hooks — no data yet',
      sourceFile: 'dashboard/state/security.json',
      fixCommand: 'dontpanic dashboard build',
      scopeLabel: 'global',
    });
  }
  if (rawSecurity.length === 0) {
    return cardHTML({
      scopeLabel: 'global',
      kind: 'security',
      headline: 'No security hook activity yet',
      impact: 'No agent actions have been logged, blocked, or required approval.',
      color: 'muted',
      body: '',
      source: 'dashboard/state/security.json',
    });
  }
  const { total, blocks, approvals, logged } = aggregateStats(rawSecurity);
  let color = 'green';
  let headline = 'Security hooks watching';
  let impact = `${total} decision${total === 1 ? '' : 's'} recorded. Nothing required approval or was blocked.`;
  if (blocks > 0) {
    color = 'red';
    headline = 'Security hooks blocked recent actions';
    impact = `${blocks} block${blocks === 1 ? '' : 's'} of ${total} decision${total === 1 ? '' : 's'}. Review the Security page before resuming risky operations.`;
  } else if (approvals > 0) {
    color = 'yellow';
    headline = 'Security hooks required approval';
    impact = `${approvals} approval${approvals === 1 ? '' : 's'} of ${total} decision${total === 1 ? '' : 's'}. Confirm each was intentional.`;
  } else if (logged > 0) {
    color = 'accent';
    headline = 'Security hooks logging';
    impact = `${logged} of ${total} decision${total === 1 ? '' : 's'} logged for review.`;
  }
  const body = `
    <ul class="hlth-card-rows">
      <li><span class="hlth-row-label">Total</span> <span class="hlth-row-value">${total}</span></li>
      <li><span class="hlth-row-label">Blocked</span> <span class="hlth-row-value">${blocks}</span></li>
      <li><span class="hlth-row-label">Approvals</span> <span class="hlth-row-value">${approvals}</span></li>
      <li><span class="hlth-row-label">Logged</span> <span class="hlth-row-value">${logged}</span></li>
    </ul>
  `;
  return cardHTML({
    scopeLabel: 'global',
    kind: 'security',
    headline,
    impact,
    color,
    body,
    source: 'dashboard/state/security.json',
  });
}

// ─────────────────────────────────────────────────────────────────────────
// Budget guardrail (quota state)
// ─────────────────────────────────────────────────────────────────────────

export function renderBudgetGuardrailCardHTML(rawQuota) {
  // The projection adapter exposes quota as an array (per-project rows)
  // and the legacy demo state may surface it under different shapes —
  // we accept either an array of {project, used, ceiling, ...} rows or
  // a single object snapshot.
  const rows = Array.isArray(rawQuota)
    ? rawQuota
    : (rawQuota && typeof rawQuota === 'object' ? [rawQuota] : []);
  if (rows.length === 0) {
    return missingDataCardHTML({
      kind: 'budget',
      headline: 'Budget guardrail — no data yet',
      sourceFile: 'dashboard/state/quota.json',
      fixCommand: 'dontpanic dashboard build',
      scopeLabel: 'global',
    });
  }
  // Look for any tripped breaker (breaker_name present + non-empty), or
  // an explicit `tripped: true` flag. Otherwise summarize ceiling usage.
  const tripped = rows.find(r => (r && (r.tripped === true || (typeof r.breaker_name === 'string' && r.breaker_name.length > 0))));
  if (tripped) {
    return cardHTML({
      scopeLabel: 'global',
      kind: 'budget',
      headline: 'Budget guardrail engaged',
      impact: `Breaker ${esc(tripped.breaker_name || '(unnamed)')} stopped new work. Review the quota state before resuming.`,
      color: 'red',
      body: `
        <ul class="hlth-card-rows">
          ${rows.map(r => `
            <li><span class="hlth-row-label">${esc(r.project || r.scope || 'global')}</span>
                <span class="hlth-row-value">${esc(String(r.used ?? '—'))} / ${esc(String(r.ceiling ?? '—'))}</span></li>
          `).join('')}
        </ul>
      `,
      source: 'dashboard/state/quota.json',
    });
  }
  return cardHTML({
    scopeLabel: 'global',
    kind: 'budget',
    headline: 'Budget guardrail clear',
    impact: 'No quota breaker tripped. Spend is within configured ceilings.',
    color: 'green',
    body: `
      <ul class="hlth-card-rows">
        ${rows.slice(0, 5).map(r => `
          <li><span class="hlth-row-label">${esc(r.project || r.scope || 'global')}</span>
              <span class="hlth-row-value">${esc(String(r.used ?? '—'))} / ${esc(String(r.ceiling ?? '—'))}</span></li>
        `).join('')}
      </ul>
    `,
    source: 'dashboard/state/quota.json',
  });
}

// ─────────────────────────────────────────────────────────────────────────
// Fleet warnings (fleet-summary aggregation)
// ─────────────────────────────────────────────────────────────────────────

export function renderFleetWarningsCardHTML(fleetSummary, scope, selected) {
  // Only show this card on fleet view (or always — but the per-project
  // view already gets project-specific build warnings above, so the
  // fleet card is mostly useful in All Projects mode).
  if (scope !== 'fleet') {
    const projects = Array.isArray(fleetSummary?.projects) ? fleetSummary.projects : [];
    const entry = projects.find(p => p && p.name === selected);
    if (!entry) {
      return missingDataCardHTML({
        kind: 'fleet',
        headline: `Fleet view for ${esc(selected)} — no data yet`,
        sourceFile: 'dashboard/state/fleet-summary.json',
        fixCommand: 'dontpanic dashboard build --project all',
        scopeLabel: 'project',
      });
    }
    const warningCount = typeof entry.warning_count === 'number' ? entry.warning_count : 0;
    const band = entry.health_band || 'ready';
    const color = band === 'needs_action' ? 'red' : (band === 'advisory' ? 'yellow' : 'green');
    return cardHTML({
      scopeLabel: 'project',
      kind: 'fleet',
      headline: warningCount > 0 ? `${warningCount} project warning${warningCount === 1 ? '' : 's'}` : 'Project clean',
      impact: warningCount > 0
        ? 'Open Needs Attention or Work for the specific items.'
        : 'No fleet-summary warnings for this project.',
      color,
      body: '',
      source: 'dashboard/state/fleet-summary.json',
    });
  }
  if (!fleetSummary || !Array.isArray(fleetSummary.projects)) {
    return missingDataCardHTML({
      kind: 'fleet',
      headline: 'Fleet warnings — no data yet',
      sourceFile: 'dashboard/state/fleet-summary.json',
      fixCommand: 'dontpanic dashboard build --project all',
      scopeLabel: 'fleet',
    });
  }
  const projects = fleetSummary.projects;
  const total = projects.reduce((sum, p) => sum + (typeof p?.warning_count === 'number' ? p.warning_count : 0), 0);
  const worstBand = projects.some(p => p?.health_band === 'needs_action')
    ? 'needs_action'
    : projects.some(p => p?.health_band === 'advisory') ? 'advisory' : 'ready';
  const color = worstBand === 'needs_action' ? 'red' : (worstBand === 'advisory' ? 'yellow' : 'green');
  const body = `
    <ul class="hlth-card-rows">
      ${projects.slice(0, 8).map(p => `
        <li>
          <span class="hlth-row-label">${esc(p.display_name || p.name || '(unnamed)')}</span>
          <span class="hlth-row-value hlth-row-value--${esc(p.health_band || 'ready')}">${esc(String(p.warning_count ?? 0))} warning${(p.warning_count ?? 0) === 1 ? '' : 's'}</span>
        </li>
      `).join('')}
    </ul>
  `;
  return cardHTML({
    scopeLabel: 'fleet',
    kind: 'fleet',
    headline: total > 0 ? 'Fleet has open warnings' : 'Fleet clean',
    impact: total > 0
      ? `${total} warning${total === 1 ? '' : 's'} across ${projects.length} project${projects.length === 1 ? '' : 's'}. Switch the project selector to investigate.`
      : `No warnings across ${projects.length} project${projects.length === 1 ? '' : 's'}.`,
    color,
    body,
    source: 'dashboard/state/fleet-summary.json',
  });
}
