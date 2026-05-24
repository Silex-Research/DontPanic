// F005 evidence snapshot generator.
//
// Renders the architecture explorer's HTML and JSON evidence into the
// plan's evidence directory by importing the same `architecture-logic.js`
// helpers the page uses at runtime. No DOM is required — `renderArchitectureHTML`
// returns a fully-formed HTML string.
//
// Output: docs/plans/2026-05-24-002-feat-dashboard-architecture-explorer-v1/evidence/
// Run:    node tests/scripts/generate-architecture-snapshots.mjs

import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import url from 'node:url';

import {
  renderArchitectureHTML,
  renderNodeDetailHTML,
  renderStepInspectorHTML,
  normalizeEnvelope,
} from '../../lib/architecture-logic.js';
import { ALL_PROJECTS_VALUE } from '../../lib/project-selector-logic.js';

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const DASHBOARD_ROOT = path.resolve(__dirname, '../..');
const PLAN_EVIDENCE_DIR = path.resolve(
  DASHBOARD_ROOT,
  '../docs/plans/2026-05-24-002-feat-dashboard-architecture-explorer-v1/evidence',
);

const FIXTURE_PRIMARY = path.join(DASHBOARD_ROOT, 'tests/fixtures/architecture-view-state.json');
const FIXTURE_F004    = path.join(DASHBOARD_ROOT, 'tests/fixtures/architecture-view-state-f004.json');

async function readJSON(p) {
  return JSON.parse(await readFile(p, 'utf8'));
}

function wrapDocument(title, bodyHTML, opts = {}) {
  const viewport = opts.mobile
    ? 'width=390, initial-scale=1.0'
    : 'width=1440, initial-scale=1.0';
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="${viewport}">
  <title>${title}</title>
  <link rel="stylesheet" href="../../../../dashboard/core.css">
  <link rel="stylesheet" href="../../../../dashboard/pages/architecture/architecture.css">
  <style>body{background:#050912;color:#e2e8f0;font-family:-apple-system,system-ui,sans-serif;margin:0;padding:16px;}</style>
</head>
<body>
  <main class="page-view active" id="page-architecture" data-snapshot-of="${title}">
    ${bodyHTML}
  </main>
</body>
</html>`;
}

async function main() {
  await mkdir(PLAN_EVIDENCE_DIR, { recursive: true });

  const fixture = await readJSON(FIXTURE_PRIMARY);
  const f004    = await readJSON(FIXTURE_F004);
  const envelope = normalizeEnvelope(fixture);

  // 1. Architecture graph snapshot (neutral, no flow selected) — desktop.
  await writeFile(
    path.join(PLAN_EVIDENCE_DIR, 'architecture-graph-snapshot.html'),
    wrapDocument(
      'architecture-graph-snapshot',
      renderArchitectureHTML(fixture, { selectedProject: 'spindineswift' }),
    ),
  );

  // 2. Selected flow / path-highlighted snapshot.
  const flowId = (envelope.flows[0] && envelope.flows[0].id) || null;
  let selectedFlowHTML = renderArchitectureHTML(fixture, {
    selectedProject: 'spindineswift',
    selectedFlowId: flowId,
  });
  if (flowId) {
    const inspector = renderStepInspectorHTML(envelope, flowId);
    selectedFlowHTML += `
      <section class="panel arch-snapshot-inspector">
        <h2>Step inspector — ${flowId}</h2>
        <ol class="arch-step-list" data-step-inspector="1">${inspector}</ol>
      </section>`;
  }
  await writeFile(
    path.join(PLAN_EVIDENCE_DIR, 'architecture-flow-selected-snapshot.html'),
    wrapDocument('architecture-flow-selected-snapshot', selectedFlowHTML),
  );

  // 3. Clear-selection snapshot (same as neutral — selection cleared).
  await writeFile(
    path.join(PLAN_EVIDENCE_DIR, 'architecture-clear-selection-snapshot.html'),
    wrapDocument(
      'architecture-clear-selection-snapshot',
      renderArchitectureHTML(fixture, { selectedProject: 'spindineswift' }),
    ),
  );

  // 4. Node detail snapshot — pick a node that participates in a flow.
  const node = envelope.nodes.find((n) => /command:dontpanic-architecture-regen/.test(n.id))
    || envelope.nodes[0];
  const nodeDetailHTML = `
    <section class="panel arch-detail-panel" data-detail-panel data-node-id="${node.id}">
      <header><h2>Node detail — ${node.title || node.id}</h2></header>
      <div class="arch-detail-body">
        ${renderNodeDetailHTML(envelope, node.id)}
      </div>
    </section>
    <section class="panel arch-snapshot-context">
      <h3>Context map</h3>
      ${renderArchitectureHTML(fixture, { selectedProject: 'spindineswift' })}
    </section>`;
  await writeFile(
    path.join(PLAN_EVIDENCE_DIR, 'architecture-node-detail-snapshot.html'),
    wrapDocument('architecture-node-detail-snapshot', nodeDetailHTML),
  );

  // 5. Filter snapshot — render with a search term highlighted in markup.
  const filteredHTML = renderArchitectureHTML(fixture, {
    selectedProject: 'spindineswift',
    searchQuery: 'supervisor',
    filters: { categories: ['module'], lanes: null, edges: null },
  });
  await writeFile(
    path.join(PLAN_EVIDENCE_DIR, 'architecture-filter-snapshot.html'),
    wrapDocument(
      'architecture-filter-snapshot',
      `<p class="arch-snapshot-note">Snapshot rendered with <code>searchQuery=&quot;supervisor&quot;</code> and the <code>module</code> category filter applied. Search/filter UI is interactive at runtime; the static snapshot captures the layer-1 markup the JS handlers narrow on.</p>${filteredHTML}`,
    ),
  );

  // 6. Missing-state snapshot — fixture with absent freshness.
  const absentFixture = {
    ...fixture,
    nodes: [], edges: [], lanes: [], flows: [], steps: [],
    freshness: {
      ...fixture.freshness,
      state: 'absent',
      message: 'architecture.json was not found. Run the regen command to generate it.',
    },
  };
  await writeFile(
    path.join(PLAN_EVIDENCE_DIR, 'architecture-missing-state-snapshot.html'),
    wrapDocument(
      'architecture-missing-state-snapshot',
      renderArchitectureHTML(absentFixture, { selectedProject: 'spindineswift' }),
    ),
  );

  // 7. Fleet-state snapshot — render fleet (All Projects) card view.
  const projectA = { ...fixture, project: { name: 'projecta', display_name: 'Project A' } };
  const projectB = {
    ...fixture,
    project: { name: 'projectb', display_name: 'Project B' },
    freshness: { ...fixture.freshness, state: 'fresh', message: 'Snapshot matches working tree.' },
  };
  const fleetHTML = renderArchitectureHTML(null, {
    selectedProject: ALL_PROJECTS_VALUE,
    byProject: { projecta: projectA, projectb: projectB },
    fleetSummary: {
      projects: [
        { name: 'projecta', display_name: 'Project A', active: true },
        { name: 'projectb', display_name: 'Project B', active: true },
        { name: 'unbuilt',  display_name: 'Unbuilt repo', active: true },
      ],
    },
  });
  await writeFile(
    path.join(PLAN_EVIDENCE_DIR, 'architecture-fleet-state-snapshot.html'),
    wrapDocument('architecture-fleet-state-snapshot', fleetHTML),
  );

  // 8. Mobile snapshot — same content, viewport=390.
  await writeFile(
    path.join(PLAN_EVIDENCE_DIR, 'architecture-mobile-snapshot.html'),
    wrapDocument(
      'architecture-mobile-snapshot',
      renderArchitectureHTML(fixture, { selectedProject: 'spindineswift' }),
      { mobile: true },
    ),
  );

  // 9. View-state JSON snapshot (copy fixture as the canonical agent-facing shape).
  await writeFile(
    path.join(PLAN_EVIDENCE_DIR, 'architecture-view-state-snapshot.json'),
    JSON.stringify(fixture, null, 2) + '\n',
  );

  // 10. Flows JSON snapshot — flows + steps only.
  const flowsOnly = {
    schema_version: fixture.schema_version,
    project: fixture.project,
    generated_at: fixture.generated_at,
    flows: fixture.flows || [],
    steps: fixture.steps || [],
    validation_warnings: fixture.validation_warnings || [],
  };
  await writeFile(
    path.join(PLAN_EVIDENCE_DIR, 'architecture-flows-snapshot.json'),
    JSON.stringify(flowsOnly, null, 2) + '\n',
  );

  console.log(`Wrote ${PLAN_EVIDENCE_DIR}`);
}

await main();
