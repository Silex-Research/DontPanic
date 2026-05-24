// F004 / F005 snapshot generator (plan 2026-05-24-001).
//
// Produces the static HTML snapshots required by objective_contract.json:
//   - dashboard-core-nav-snapshot.html
//   - dashboard-needs-attention-snapshot.html
//   - dashboard-tools-setup-snapshot.html
//   - dashboard-health-empty-state-snapshot.html
//   - dashboard-preferences-snapshot.html
//   - dashboard-fleet-home-snapshot.html       (F005 — Needs Attention, All Projects)
//   - dashboard-fleet-health-snapshot.html     (F005 — Health, All Projects)
//
// The snapshots are intentionally fragment-level: each one is the inner
// HTML emitted by the corresponding pure renderer (or the Preferences
// page-module IIFE) wrapped in a minimal <html> shell so they remain
// readable in a browser without the runtime shell. Provenance footers
// are preserved verbatim so the F004 evidence test can rescan them.
//
// Run: `node dashboard/tests/scripts/generate-f004-snapshots.mjs`

import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  renderWhatNowHTML,
  renderFleetWhatNowHTML,
} from '../../lib/what-now-logic.js';
import { renderCapabilityCenterHTML } from '../../lib/capabilities-logic.js';
import { renderHealthHTML } from '../../lib/health-logic.js';
import { renderWorkProvenanceHTML } from '../../lib/mission-control-logic.js';
import { renderProvenanceFooterHTML } from '../../lib/provenance.js';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, '..', '..', '..');
const outDir = resolve(
  repoRoot,
  'docs',
  'plans',
  '2026-05-24-001-feat-dashboard-value-language-ia-v0',
  'evidence',
  'snapshots',
);
mkdirSync(outDir, { recursive: true });

const fixturesDir = resolve(here, '..', 'fixtures');
const whatNow = JSON.parse(readFileSync(resolve(fixturesDir, 'what-now.json'), 'utf8'));
const capabilities = JSON.parse(readFileSync(resolve(fixturesDir, 'capabilities-status.json'), 'utf8'));
const fleetSummary = JSON.parse(readFileSync(resolve(fixturesDir, 'fleet-summary.json'), 'utf8'));

// Synthesize a fleet what-now envelope by tagging the single-project
// fixture items across the fleet-summary projects. The fleet renderer
// groups by `project_name`; a single global item is left untagged so
// reviewers see the `__global__` band the renderer pins at the top.
const fleetWhatNow = (() => {
  const items = Array.isArray(whatNow.items) ? whatNow.items : [];
  const activeProjects = (fleetSummary.projects || []).filter((p) => p && p.active);
  const tagged = [];
  items.forEach((item, idx) => {
    if (item.id === 'reconcile:new_capabilities') {
      // Global / fleet-wide reconcile blocker — no project_name.
      tagged.push({ ...item });
      return;
    }
    const project = activeProjects[idx % Math.max(1, activeProjects.length)];
    if (!project) {
      tagged.push({ ...item });
      return;
    }
    tagged.push({
      ...item,
      project_name: project.name,
      display_name: project.display_name,
    });
  });
  return {
    ...whatNow,
    items: tagged,
  };
})();

function wrap(title, body) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>${title} — F004 snapshot</title>
  <!--
    Static F004 evidence snapshot. Pure-renderer output captured by
    dashboard/tests/scripts/generate-f004-snapshots.mjs. Do not edit by
    hand — regenerate by re-running the script. The snapshot intentionally
    omits the dashboard's runtime CSS so it remains text-readable.
  -->
</head>
<body>
${body}
</body>
</html>
`;
}

// 1. Needs Attention — populated state (the missing-cache state is
//    also covered by the F004 evidence test; here we want to show the
//    operator the value-first headlines + provenance row).
writeFileSync(
  resolve(outDir, 'dashboard-needs-attention-snapshot.html'),
  wrap('Needs Attention', renderWhatNowHTML(whatNow)),
);

// 2. Tools & Setup — populated state.
writeFileSync(
  resolve(outDir, 'dashboard-tools-setup-snapshot.html'),
  wrap('Tools & Setup', renderCapabilityCenterHTML(capabilities)),
);

// 3. Health — the honest empty/missing-data state (matches the contract).
writeFileSync(
  resolve(outDir, 'dashboard-health-empty-state-snapshot.html'),
  wrap('Health (empty state)', renderHealthHTML({
    capabilities: null, whatNow: null, security: null, quota: null,
    fleetSummary: null, selectedProject: 'all',
  })),
);

// 4. Preferences — the settings page is an IIFE; we mirror its rendered
//    template here using the same helper so the snapshot reflects what an
//    operator actually sees. Kept in lockstep with pages/settings/settings.js.
writeFileSync(
  resolve(outDir, 'dashboard-preferences-snapshot.html'),
  wrap('Preferences', `
    <div class="stg-layout">
      <section class="panel stg-section stg-config-section">
        <h2>Preferences</h2>
        <p class="stg-section-desc">
          How this dashboard behaves for you. These preferences live in
          your browser's localStorage only — they do not edit DontPanic
          configuration, secrets, or capability state. Anything under
          <code>~/.dontpanic/</code> is managed through
          <code>dontpanic</code> CLI commands surfaced in Tools &amp; Setup.
        </p>
        <div class="stg-config-form">
          <div class="stg-field">
            <label class="stg-label">Appearance</label>
            <div class="stg-field-right">
              <select class="stg-select"><option>Dark</option><option>Light</option></select>
              <span class="stg-field-hint">Stored in localStorage</span>
            </div>
          </div>
          <div class="stg-field">
            <label class="stg-label">Auto-refresh</label>
            <div class="stg-field-right">
              <select class="stg-select"><option>30 seconds</option></select>
              <span class="stg-field-hint">Takes effect on next page load</span>
            </div>
          </div>
          <div class="stg-field">
            <label class="stg-label">State files</label>
            <div class="stg-field-right">
              <code class="stg-code">dashboard/state/*.json</code>
              <span class="stg-field-hint">Written by <code>dontpanic dashboard build</code>; read-only in dashboard</span>
            </div>
          </div>
        </div>
        <div class="stg-source-footer">
          Source: <code>localStorage</code> (this browser only) ·
          DontPanic config edits use the <code>dontpanic</code> CLI surfaced under Tools &amp; Setup.
        </div>
        ${renderProvenanceFooterHTML({
          source: 'localStorage (this browser only)',
          lastUpdated: null,
          note: 'Preferences are browser-local. DontPanic config edits live under ~/.dontpanic/ and are managed via the dontpanic CLI from Tools & Setup.',
        })}
      </section>
    </div>
  `),
);

// 5. Core nav shell — V0 surface table from plan 2026-05-24-001 F002.
//    Includes the Work provenance footer so reviewers can see Work's
//    standardized treatment alongside the other tabs.
writeFileSync(
  resolve(outDir, 'dashboard-core-nav-snapshot.html'),
  wrap('Core nav shell', `
    <header>
      <div class="header-left"><h1>DontPanic</h1></div>
      <div class="header-right">
        <span class="status-badge online">Ready</span>
        <span id="project-selector-container"></span>
      </div>
    </header>
    <nav class="view-nav" id="view-nav">
      <button class="view-tab active" data-page="what-now">Needs Attention</button>
      <button class="view-tab" data-page="mission-control">Work</button>
      <button class="view-tab" data-page="capabilities">Tools &amp; Setup</button>
      <button class="view-tab" data-page="health">Health</button>
      <button class="view-tab" data-page="settings">Preferences</button>
    </nav>
    <div id="page-container">
      <div id="page-work-preview" class="page-view">
        <h2>Work</h2>
        <p>Read-only kanban of plan / feature lifecycle. The full surface
        is captured in the per-tab snapshots; this shell preview shows
        the standardized provenance treatment Work now carries.</p>
        ${renderWorkProvenanceHTML({
          tasks: [{ id: 'demo', created: '2026-05-23T03:50:00Z' }],
          agents: [{ id: 'claude', lastSeen: '2026-05-23T04:00:00Z' }],
          activity: [{ type: 'task', text: 'demo', timestamp: '2026-05-23T04:05:00Z' }],
        })}
      </div>
    </div>
    <footer>
      <span>DontPanic dashboard (V0 nav)</span>
      <span id="last-sync">Last sync: 2026-05-23 04:05Z</span>
    </footer>
  `),
);

// 6. Fleet Home — Needs Attention in All Projects mode. Drives
//    objective-contract evidence `dashboard-fleet-home-snapshot.html`.
//    The renderer groups items per project and pins a `__global__`
//    section for reconcile/doctor blockers; a fleet provenance footer
//    points at `dashboard/state/fleet-what-now.json` (D013).
writeFileSync(
  resolve(outDir, 'dashboard-fleet-home-snapshot.html'),
  wrap('Needs Attention — All Projects (fleet)', renderFleetWhatNowHTML(
    fleetWhatNow,
    fleetSummary,
    { now: new Date('2026-05-23T03:50:30Z') },
  )),
);

// 7. Fleet Health — Health page in All Projects mode. Drives
//    objective-contract evidence `dashboard-fleet-health-snapshot.html`.
//    Captures the fleet warnings card, the honest empty/missing-data
//    states for capability / security / quota inputs, and the
//    page-level provenance footer (D013).
writeFileSync(
  resolve(outDir, 'dashboard-fleet-health-snapshot.html'),
  wrap('Health — All Projects (fleet)', renderHealthHTML({
    capabilities: null,
    whatNow: null,
    security: null,
    quota: null,
    fleetSummary,
    selectedProject: 'all',
  })),
);

// stdout receipt for the operator running the script.
console.log(`Wrote 7 dashboard snapshots to ${outDir}`);
