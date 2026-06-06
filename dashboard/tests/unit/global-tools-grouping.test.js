// Unit tests for the F004 "Global tools" grouping (plan 2026-06-05-001).
// Consumes the F003 producer label (item.group === 'global_tool_setup') and
// renders install-level tools under a "Global tools" heading, distinct from the
// project-scoped items / tracked-projects list.

import { describe, it, expect } from 'vitest';
import { renderGlobalToolsHTML, groupByProject } from '../../lib/what-now-logic.js';
import { renderInstallHealthCardHTML } from '../../lib/health-logic.js';

const globalItem = {
  id: 'capability:linear',
  group: 'global_tool_setup',
  title: 'Capability linear is not installed',
  exact_command: 'dontpanic capabilities setup linear --print-steps',
  detail: 'Setup: Install the Linear adapter',
};
const projectItem = {
  id: 'gate:glam:F001',
  group: null,
  title: 'Gate not cleared for glam',
  project_name: 'glam',
};

describe('renderGlobalToolsHTML', () => {
  it('renders a "Global tools" heading with install-level clarifying copy', () => {
    const html = renderGlobalToolsHTML([globalItem, projectItem]);
    expect(html).toContain('Global tools');
    expect(html.toLowerCase()).toContain('install-level');
  });

  it('includes the global-tool item and excludes project-scoped items', () => {
    const html = renderGlobalToolsHTML([globalItem, projectItem]);
    expect(html).toContain('Capability linear is not installed');
    expect(html).toContain('dontpanic capabilities setup linear --print-steps');
    expect(html).not.toContain('Gate not cleared for glam'); // project item not in this section
  });

  it('returns empty string when there are no global tools', () => {
    expect(renderGlobalToolsHTML([projectItem])).toBe('');
    expect(renderGlobalToolsHTML([])).toBe('');
    expect(renderGlobalToolsHTML(null)).toBe('');
  });

  it('escapes item text (no raw HTML injection)', () => {
    const html = renderGlobalToolsHTML([
      { id: 'x', group: 'global_tool_setup', title: '<script>bad</script>', exact_command: '' },
    ]);
    expect(html).not.toContain('<script>bad</script>');
    expect(html).toContain('&lt;script&gt;');
  });
});

// ── F005: re-derive identity + dedup guard (groupByProject) ───────────────────
describe('renderGlobalToolsHTML — re-derive from source', () => {
  it('renders a capability item whose group tag is absent (source===capability)', () => {
    const html = renderGlobalToolsHTML([
      { id: 'capability:x', source: 'capability', title: 'Cap x',
        exact_command: 'dontpanic capabilities setup x --print-steps' },
    ]);
    expect(html).toContain('Global tools');
    expect(html).toContain('Cap x');
  });
});

describe('groupByProject — global-tools dedup guard', () => {
  const cap = { id: 'capability:x', group: 'global_tool_setup', source: 'capability', band: 'needs_action', title: 'Cap x' };
  const reconcile = { id: 'reconcile:snap', source: 'reconcile', band: 'needs_action', title: 'Install snapshot missing' };
  const gate = { id: 'gate:glam:F1', source: 'gate', project_name: 'glam', band: 'needs_action', title: 'gate' };

  it('excludes global-tool items from every group (rendered by the dedicated block)', () => {
    const groups = groupByProject([cap, reconcile, gate], [{ name: 'glam' }]);
    const allIds = groups.flatMap((g) => g.items.map((i) => i.id));
    expect(allIds).not.toContain('capability:x');
  });

  it('keeps non-capability reconcile globals in __global__', () => {
    const groups = groupByProject([cap, reconcile, gate], [{ name: 'glam' }]);
    const globalGroup = groups.find((g) => g.name === '__global__');
    const globalIds = (globalGroup ? globalGroup.items : []).map((i) => i.id);
    expect(globalIds).toContain('reconcile:snap');
    expect(globalIds).not.toContain('capability:x');
  });

  it('also excludes capability-source items lacking the group tag', () => {
    const untagged = { id: 'capability:y', source: 'capability', band: 'advisory', title: 'Cap y' };
    const groups = groupByProject([untagged, gate], [{ name: 'glam' }]);
    const allIds = groups.flatMap((g) => g.items.map((i) => i.id));
    expect(allIds).not.toContain('capability:y');
  });
});

// ── F006: Health install card labelled "Global tools" ─────────────────────────
describe('renderInstallHealthCardHTML — Global tools label', () => {
  const env = {
    schema_version: '1.0.0',
    generated_at: '2026-06-05T22:00:00Z',
    capabilities: [
      { capability_id: 'linear', status: 'not_installed' },
      { capability_id: 'discord', status: 'needs_setup' },
    ],
  };
  it('labels install readiness as "Global tools" with install-level copy', () => {
    const html = renderInstallHealthCardHTML(env);
    expect(html).toContain('Global tools');
    expect(html.toLowerCase()).toContain('install-level');
  });
});
