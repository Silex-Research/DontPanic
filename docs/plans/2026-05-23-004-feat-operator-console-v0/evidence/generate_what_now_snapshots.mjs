#!/usr/bin/env node
// Regenerate F004 What Now HTML evidence snapshots.
//
// Usage (from repo root):
//   node docs/plans/2026-05-23-004-feat-operator-console-v0/evidence/generate_what_now_snapshots.mjs
//
// Writes:
//   what-now-needs-action-snapshot.html
//   what-now-quiet-state-snapshot.html
//   what-now-advisory-only-snapshot.html
//
// All files embed the dashboard's core.css + what-now.css so the snapshot
// renders standalone for the auditor / operator without booting the page
// module. Inputs match the fixtures used in the vitest suite — keep them
// in sync if the F001 envelope shape changes.

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(__dirname, '..', '..', '..', '..');
const libUrl = pathToFileURL(join(repoRoot, 'dashboard', 'lib', 'what-now-logic.js'));
const { renderWhatNowHTML } = await import(libUrl.href);

const fixturePath = join(repoRoot, 'dashboard', 'tests', 'fixtures', 'what-now.json');
const fixture = JSON.parse(readFileSync(fixturePath, 'utf8'));

const coreCss = readFileSync(join(repoRoot, 'dashboard', 'core.css'), 'utf8');
const pageCss = readFileSync(join(repoRoot, 'dashboard', 'pages', 'what-now', 'what-now.css'), 'utf8');

function wrap(title, bodyHtml) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>${title}</title>
  <style>
${coreCss}
${pageCss}
  </style>
</head>
<body>
  <header>
    <div class="header-left"><h1>JARVIS</h1><span class="subtitle">What Now — F004 evidence</span></div>
    <div class="header-right"><span id="clock">snapshot</span></div>
  </header>
  <nav class="view-nav">
    <button class="view-tab active">What Now</button>
  </nav>
  <div id="page-container">
    <div class="page-view active">
      ${bodyHtml}
    </div>
  </div>
</body>
</html>
`;
}

// Advisory/info-only envelope — exercises the F004 acceptance #3 + #4
// path where no needs_action items exist but stale/missing optional state
// must still surface exact commands as copyable cards (band coloring
// provides restraint, not a quiet collapse).
const advisoryOnlyEnvelope = {
  schema_version: '1.0.0',
  captured_at: '2026-05-23T03:50:00Z',
  items: [
    {
      id: 'reconcile:missing_snapshot',
      source: 'reconcile',
      band: 'advisory',
      title: 'Install snapshot is missing',
      detail: 'no baseline to compare current capability set against',
      exact_command: 'dontpanic reconcile baseline --yes',
      automatable: false,
      human_required_reason: 'no baseline to compare against',
      evidence_uri: '/home/op/.dontpanic/install-snapshot.json',
      updated_at: '2026-05-23T03:49:55Z',
    },
    {
      id: 'architecture:stale',
      source: 'architecture',
      band: 'advisory',
      title: 'Architecture snapshot is stale',
      detail: null,
      exact_command: 'dontpanic architecture regen',
      automatable: true,
      human_required_reason: null,
      evidence_uri: 'docs/architecture/CURRENT.md',
      updated_at: '2026-05-23T03:49:55Z',
    },
    {
      id: 'supervisor:48211:2026-05-23-004-feat-operator-console-v0',
      source: 'supervisor',
      band: 'info',
      title: 'Supervisor active on 2026-05-23-004-feat-operator-console-v0',
      detail: 'started_at=2026-05-23T03:50:00Z, env=dev',
      exact_command: 'dontpanic ps',
      automatable: true,
      human_required_reason: null,
      evidence_uri: null,
      updated_at: '2026-05-23T03:49:55Z',
    },
  ],
};

const needsActionHtml = wrap('What Now — Needs Action snapshot', renderWhatNowHTML(fixture));
const quietHtml = wrap('What Now — Quiet state snapshot', renderWhatNowHTML({
  schema_version: '1.0.0',
  captured_at: '2026-05-23T03:50:00Z',
  items: [],
}));
const advisoryHtml = wrap('What Now — Advisory/info-only snapshot', renderWhatNowHTML(advisoryOnlyEnvelope));

writeFileSync(join(__dirname, 'what-now-needs-action-snapshot.html'), needsActionHtml);
writeFileSync(join(__dirname, 'what-now-quiet-state-snapshot.html'), quietHtml);
writeFileSync(join(__dirname, 'what-now-advisory-only-snapshot.html'), advisoryHtml);
writeFileSync(join(__dirname, 'agent-cache-shape-snapshot.json'), JSON.stringify(fixture, null, 2) + '\n');

console.log('wrote what-now-needs-action-snapshot.html');
console.log('wrote what-now-quiet-state-snapshot.html');
console.log('wrote what-now-advisory-only-snapshot.html');
console.log('wrote agent-cache-shape-snapshot.json');
