// Unit tests for the F004 "Global tools" grouping (plan 2026-06-05-001).
// Consumes the F003 producer label (item.group === 'global_tool_setup') and
// renders install-level tools under a "Global tools" heading, distinct from the
// project-scoped items / tracked-projects list.

import { describe, it, expect } from 'vitest';
import { renderGlobalToolsHTML } from '../../lib/what-now-logic.js';

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
