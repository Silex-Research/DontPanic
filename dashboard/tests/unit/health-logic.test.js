// Unit tests for health-logic.js — the pure HTML composition layer behind
// the F003 Health page. Per copy-map.md §2.5, every card must have a
// credible data source or a named missing-data state. These tests pin
// that invariant so regressions surface immediately.

import { describe, it, expect } from 'vitest';
import {
  renderHealthHTML,
  renderInstallHealthCardHTML,
  renderUpgradeStatusCardHTML,
  renderSetupDriftCardHTML,
  renderBuildWarningsCardHTML,
  renderSecurityCardHTML,
  renderBudgetGuardrailCardHTML,
  renderFleetWarningsCardHTML,
} from '../../lib/health-logic.js';

// ── renderHealthHTML — composition + scope ─────────────────────────────

describe('renderHealthHTML: composition', () => {
  it('renders the layout with the fleet scope marker by default', () => {
    const html = renderHealthHTML({});
    expect(html).toContain('class="hlth-layout"');
    expect(html).toContain('data-scope="fleet"');
  });

  it('switches to the project scope when a project is selected', () => {
    const html = renderHealthHTML({ selectedProject: 'styln' });
    expect(html).toContain('data-scope="project"');
    expect(html).toContain('Health for project styln');
  });

  it('includes every required card kind so no card silently disappears', () => {
    const html = renderHealthHTML({});
    for (const kind of ['upgrade', 'install', 'reconcile', 'build_warnings', 'security', 'budget', 'fleet']) {
      expect(html).toContain(`data-kind="${kind}"`);
    }
  });

  it('renders the upgrade status row even in the positive up-to-date case (D011)', () => {
    const upToDate = {
      status_line: 'DontPanic: up to date',
      update_state: 'up_to_date',
      upstream_status: 'current',
      behind_upstream: false,
      pending_required: 0,
      pending_advisory: 0,
      installed_commit: 'cur1234',
      last_acknowledged: 'Last acknowledged: r1 (commit ackc0de)',
    };
    const html = renderHealthHTML({ upgradeStatus: upToDate });
    expect(html).toContain('data-kind="upgrade"');
    expect(html).toContain('DontPanic: up to date');
  });

  it('escapes a malicious selectedProject value (no raw script tag)', () => {
    const evil = '<script>alert(1)</script>';
    const html = renderHealthHTML({ selectedProject: evil });
    expect(html).not.toContain('<script>alert(1)</script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('shows footer hint with refresh command', () => {
    const html = renderHealthHTML({});
    expect(html).toContain('dontpanic dashboard build');
  });
});

// ── Install health card ────────────────────────────────────────────────

describe('renderInstallHealthCardHTML', () => {
  it('renders the missing-data card when capabilities is null', () => {
    const html = renderInstallHealthCardHTML(null);
    expect(html).toContain('Install readiness — no data yet');
    expect(html).toContain('dashboard/state/capabilities-status.json');
    expect(html).toContain('hlth-card--muted');
  });

  it('reports blockers in red when any capability is blocked', () => {
    const env = {
      schema_version: '1.0.0',
      generated_at: '2026-05-24T10:00:00Z',
      capabilities: [
        { capability_id: 'a', status: 'blocked' },
        { capability_id: 'b', status: 'ready' },
      ],
    };
    const html = renderInstallHealthCardHTML(env);
    expect(html).toContain('Install has blockers');
    expect(html).toContain('hlth-card--red');
  });

  it('reports needs-setup in yellow when no blockers are present', () => {
    const env = {
      schema_version: '1.0.0',
      generated_at: '2026-05-24T10:00:00Z',
      capabilities: [
        { capability_id: 'a', status: 'needs_setup' },
        { capability_id: 'b', status: 'ready' },
      ],
    };
    const html = renderInstallHealthCardHTML(env);
    expect(html).toContain('Setup incomplete');
    expect(html).toContain('hlth-card--yellow');
  });

  it('reports healthy install in green when nothing is blocked or pending', () => {
    const env = {
      schema_version: '1.0.0',
      generated_at: '2026-05-24T10:00:00Z',
      capabilities: [
        { capability_id: 'a', status: 'ready' },
        { capability_id: 'b', status: 'ready' },
      ],
    };
    const html = renderInstallHealthCardHTML(env);
    expect(html).toContain('Install is healthy');
    expect(html).toContain('hlth-card--green');
  });
});

// ── Upgrade status card (Plan 2026-06-21-001 F008 — always-shown row) ──

describe('renderUpgradeStatusCardHTML', () => {
  it('renders the missing-data card when the projection is null', () => {
    const html = renderUpgradeStatusCardHTML(null);
    expect(html).toContain('Upgrade status — no data yet');
    expect(html).toContain('dashboard/state/upgrade-status.json');
    expect(html).toContain('hlth-card--muted');
  });

  it('renders a green up-to-date row that surfaces the status line + installed commit', () => {
    const html = renderUpgradeStatusCardHTML({
      status_line: 'DontPanic: up to date',
      update_state: 'up_to_date',
      upstream_status: 'current',
      behind_upstream: false,
      pending_required: 0,
      pending_advisory: 0,
      installed_commit: 'cur1234',
      last_acknowledged: 'Last acknowledged: r1 (commit ackc0de)',
    });
    expect(html).toContain('data-kind="upgrade"');
    expect(html).toContain('hlth-card--green');
    expect(html).toContain('DontPanic: up to date');
    expect(html).toContain('cur1234');
  });

  it('renders a red row with the count when required actions are pending', () => {
    const html = renderUpgradeStatusCardHTML({
      status_line: 'DontPanic: 2 upgrade actions pending',
      update_state: 'required_pending',
      upstream_status: 'current',
      behind_upstream: false,
      pending_required: 2,
      pending_advisory: 0,
      installed_commit: 'cur1234',
      last_acknowledged: 'never acknowledged',
    });
    expect(html).toContain('hlth-card--red');
    expect(html).toContain('DontPanic: 2 upgrade actions pending');
  });

  it('never reads up-to-date while upstream is behind (D031)', () => {
    const html = renderUpgradeStatusCardHTML({
      status_line: 'DontPanic: behind the newest DontPanic (run `git pull`)',
      update_state: 'up_to_date',
      upstream_status: 'behind',
      behind_upstream: true,
      pending_required: 0,
      pending_advisory: 0,
      installed_commit: 'cur1234',
      last_acknowledged: 'Last acknowledged: r1 (commit ackc0de)',
    });
    // A behind checkout is a red signal even with a clean update_state.
    expect(html).toContain('hlth-card--red');
    expect(html).toContain('behind the newest DontPanic');
    expect(html).not.toContain('up to date with the tracked');
    expect(html).toContain('git pull');
  });

  it('renders the last-acknowledged line from the projection (last_seen, not installed)', () => {
    const html = renderUpgradeStatusCardHTML({
      status_line: 'DontPanic: up to date',
      update_state: 'up_to_date',
      upstream_status: 'current',
      behind_upstream: false,
      pending_required: 0,
      pending_advisory: 0,
      installed_commit: 'cur1234',
      last_seen_commit: 'ackc0de',
      last_acknowledged: 'Last acknowledged: r1 (commit ackc0de)',
    });
    expect(html).toContain('Last acknowledged: r1 (commit ackc0de)');
    // installed_commit appears as its own row, never inside the ack line.
    expect(html).toContain('cur1234');
  });

  it('renders "never acknowledged" when the marker is absent (D042)', () => {
    const html = renderUpgradeStatusCardHTML({
      status_line: 'DontPanic: up to date',
      update_state: 'up_to_date',
      upstream_status: 'current',
      behind_upstream: false,
      pending_required: 0,
      pending_advisory: 0,
      installed_commit: 'cur1234',
      marker_state: 'absent',
      last_acknowledged: 'never acknowledged',
    });
    expect(html).toContain('never acknowledged');
  });

  it('escapes a malicious status line (no raw script tag)', () => {
    const html = renderUpgradeStatusCardHTML({
      status_line: '<script>alert(1)</script>',
      update_state: 'unknown',
      upstream_status: 'unknown',
      pending_required: 0,
      pending_advisory: 0,
    });
    expect(html).not.toContain('<script>alert(1)</script>');
    expect(html).toContain('&lt;script&gt;');
  });
});

// ── Setup drift card (reconcile items in what-now) ─────────────────────

describe('renderSetupDriftCardHTML', () => {
  it('renders missing-data card when whatNow is null', () => {
    const html = renderSetupDriftCardHTML(null, 'fleet');
    expect(html).toContain('Setup drift — no data yet');
    expect(html).toContain('dashboard/state/what-now.json');
  });

  it('renders green "matches baseline" when no reconcile items are present', () => {
    const env = {
      schema_version: '1.0.0',
      captured_at: '2026-05-24T10:00:00Z',
      items: [{ id: 'x', source: 'architecture', band: 'advisory' }],
    };
    const html = renderSetupDriftCardHTML(env, 'fleet');
    expect(html).toContain('Install matches baseline');
    expect(html).toContain('hlth-card--green');
  });

  it('flags drift in red when a reconcile item requires action', () => {
    const env = {
      schema_version: '1.0.0',
      captured_at: '2026-05-24T10:00:00Z',
      items: [
        { id: 'r1', source: 'reconcile', band: 'needs_action', title: 'Pip drift', exact_command: 'pip install -r req.txt' },
      ],
    };
    const html = renderSetupDriftCardHTML(env, 'fleet');
    expect(html).toContain('Setup drift detected');
    expect(html).toContain('hlth-card--red');
    expect(html).toContain('Pip drift');
    expect(html).toContain('pip install -r req.txt');
  });
});

// ── Build warnings card ────────────────────────────────────────────────

describe('renderBuildWarningsCardHTML', () => {
  it('renders missing-data card when whatNow is null', () => {
    const html = renderBuildWarningsCardHTML(null, 'project');
    expect(html).toContain('Recent build warnings — no data yet');
  });

  it('renders the green "no warnings" card when nothing is flagged', () => {
    const env = {
      schema_version: '1.0.0',
      captured_at: '2026-05-24T10:00:00Z',
      items: [
        { id: 'r', source: 'reconcile', band: 'advisory' },
      ],
    };
    const html = renderBuildWarningsCardHTML(env, 'fleet');
    expect(html).toContain('No recent build warnings');
    expect(html).toContain('hlth-card--green');
  });

  it('surfaces architecture warnings with their fix commands', () => {
    const env = {
      schema_version: '1.0.0',
      captured_at: '2026-05-24T10:00:00Z',
      items: [
        { id: 'a1', source: 'architecture', band: 'advisory', title: 'Unused import', detail: 'foo.py L10' },
      ],
    };
    const html = renderBuildWarningsCardHTML(env, 'fleet');
    expect(html).toContain('Recent build warnings');
    expect(html).toContain('Unused import');
    expect(html).toContain('foo.py L10');
  });
});

// ── Security card (finding 2 — credible security data) ─────────────────

describe('renderSecurityCardHTML', () => {
  it('renders the missing-data card when security is null', () => {
    const html = renderSecurityCardHTML(null);
    expect(html).toContain('Security hooks — no data yet');
    expect(html).toContain('dashboard/state/security.json');
    expect(html).toContain('hlth-card--muted');
  });

  it('renders the missing-data card when security is not an array', () => {
    const html = renderSecurityCardHTML({ not: 'an array' });
    expect(html).toContain('Security hooks — no data yet');
  });

  it('renders a quiet "no activity" card when security is an empty array', () => {
    // Present-but-empty is materially different from missing: the file
    // exists, the loader ran, no decisions have happened yet.
    const html = renderSecurityCardHTML([]);
    expect(html).toContain('No security hook activity yet');
    expect(html).toContain('hlth-card--muted');
    expect(html).not.toContain('no data yet');
  });

  it('reports blocks in red when any decision was a block', () => {
    const html = renderSecurityCardHTML([
      { action: 'block', category: 'file_write', agent: 'claude' },
      { action: 'log',   category: 'git_push',   agent: 'claude' },
    ]);
    expect(html).toContain('Security hooks blocked recent actions');
    expect(html).toContain('hlth-card--red');
    expect(html).toContain('1 block');
  });

  it('reports approvals in yellow when no blocks are present', () => {
    const html = renderSecurityCardHTML([
      { action: 'require_approval', category: 'api_call', agent: 'codex' },
      { action: 'log',              category: 'git_push', agent: 'claude' },
    ]);
    expect(html).toContain('Security hooks required approval');
    expect(html).toContain('hlth-card--yellow');
  });

  it('reports a watching/logging state when only logs are present', () => {
    const html = renderSecurityCardHTML([
      { action: 'log', category: 'git_push', agent: 'claude' },
      { action: 'log', category: 'git_push', agent: 'claude' },
    ]);
    expect(html).toContain('Security hooks logging');
    expect(html).toContain('hlth-card--accent');
  });

  it('reports green when every recorded decision was allowed', () => {
    const html = renderSecurityCardHTML([
      { action: 'allow', category: 'file_write', agent: 'claude' },
    ]);
    expect(html).toContain('Security hooks watching');
    expect(html).toContain('hlth-card--green');
  });

  it('names the source file even on a populated card', () => {
    const html = renderSecurityCardHTML([{ action: 'allow', category: 'x' }]);
    expect(html).toContain('dashboard/state/security.json');
  });
});

// ── Budget guardrail card ──────────────────────────────────────────────

describe('renderBudgetGuardrailCardHTML', () => {
  it('renders missing-data card when quota is empty', () => {
    const html = renderBudgetGuardrailCardHTML([]);
    expect(html).toContain('Budget guardrail — no data yet');
  });

  it('flags a tripped breaker in red', () => {
    const html = renderBudgetGuardrailCardHTML([
      { project: 'styln', breaker_name: 'weekly_token_ceiling', used: 100, ceiling: 100 },
    ]);
    expect(html).toContain('Budget guardrail engaged');
    expect(html).toContain('hlth-card--red');
    expect(html).toContain('weekly_token_ceiling');
  });

  it('renders the clear/green card when no breaker is tripped', () => {
    const html = renderBudgetGuardrailCardHTML([
      { project: 'styln', used: 10, ceiling: 100 },
    ]);
    expect(html).toContain('Budget guardrail clear');
    expect(html).toContain('hlth-card--green');
  });
});

// ── Fleet warnings card (fleet + per-project variants) ─────────────────

describe('renderFleetWarningsCardHTML', () => {
  it('renders missing-data card when fleetSummary lacks projects[] on fleet scope', () => {
    const html = renderFleetWarningsCardHTML(null, 'fleet', 'all');
    expect(html).toContain('Fleet warnings — no data yet');
    expect(html).toContain('dashboard/state/fleet-summary.json');
  });

  it('reports a clean fleet in green when no projects have warnings', () => {
    const html = renderFleetWarningsCardHTML({
      projects: [
        { name: 'styln', display_name: 'Styln', warning_count: 0, health_band: 'ready' },
      ],
    }, 'fleet', 'all');
    expect(html).toContain('Fleet clean');
    expect(html).toContain('hlth-card--green');
  });

  it('reports open warnings in the worst color across projects', () => {
    const html = renderFleetWarningsCardHTML({
      projects: [
        { name: 'a', warning_count: 3, health_band: 'needs_action' },
        { name: 'b', warning_count: 1, health_band: 'advisory' },
      ],
    }, 'fleet', 'all');
    expect(html).toContain('Fleet has open warnings');
    expect(html).toContain('hlth-card--red');
  });

  it('renders a missing-data card when project scope is selected but absent from fleet-summary', () => {
    const html = renderFleetWarningsCardHTML(
      { projects: [{ name: 'other', warning_count: 0 }] },
      'project',
      'missing-one',
    );
    expect(html).toContain('Fleet view for missing-one — no data yet');
  });

  it('renders the per-project card with warning count when project is in fleet-summary', () => {
    const html = renderFleetWarningsCardHTML(
      { projects: [{ name: 'styln', warning_count: 2, health_band: 'advisory' }] },
      'project',
      'styln',
    );
    expect(html).toContain('2 project warnings');
    expect(html).toContain('hlth-card--yellow');
  });
});
