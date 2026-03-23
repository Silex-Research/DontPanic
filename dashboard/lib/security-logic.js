// ── Security Logic — Pure, DOM-free business logic ──
// Extracted from pages/security/security.js for testability.

export const ACTION_COLORS = {
  block:            'red',
  require_approval: 'yellow',
  log:              'accent',
  allow:            'green',
};

export const ACTION_LABELS = {
  block:            'BLOCK',
  require_approval: 'APPROVAL',
  log:              'LOG',
  allow:            'ALLOW',
};

export const SEVERITY_COLORS = {
  high:   'red',
  medium: 'yellow',
  low:    'accent',
};

// Known Claude hooks that appear in state entries as agent/category fields
export const HOOK_DEFS = [
  {
    id:          'security-gate',
    label:       'security-gate.sh',
    description: 'Pre-tool call gate — blocks destructive operations',
    categories:  ['file_write', 'file_delete', 'shell_exec'],
  },
  {
    id:          'git-safety',
    label:       'git-safety.sh',
    description: 'Git operation guard — prevents force-push, branch deletion',
    categories:  ['git_push', 'git_branch', 'git_rebase'],
  },
  {
    id:          'api-audit',
    label:       'api-audit.sh',
    description: 'Outbound API call auditor — logs external requests',
    categories:  ['api_call', 'network_request'],
  },
];

/**
 * Aggregates top-level stats across all security decisions.
 * @param {Array<{ action: string }>} decisions
 * @returns {{ total: number, blocks: number, approvals: number, logged: number }}
 */
export function aggregateStats(decisions) {
  const total     = decisions.length;
  const blocks    = decisions.filter(d => d.action === 'block').length;
  const approvals = decisions.filter(d => d.action === 'require_approval').length;
  const logged    = decisions.filter(d => d.action === 'log').length;
  return { total, blocks, approvals, logged };
}

/**
 * Aggregates security decisions grouped by agent name.
 * @param {Array<{ agent?: string, action: string, timestamp?: string }>} decisions
 * @returns {Record<string, { total: number, blocks: number, approvals: number, logged: number, allowed: number, last: string|null }>}
 */
export function aggregatePerAgent(decisions) {
  const agents = {};

  for (const d of decisions) {
    const name = d.agent || 'unknown';
    if (!agents[name]) {
      agents[name] = { total: 0, blocks: 0, approvals: 0, logged: 0, allowed: 0, last: null };
    }
    agents[name].total++;
    if (d.action === 'block')                 agents[name].blocks++;
    else if (d.action === 'require_approval') agents[name].approvals++;
    else if (d.action === 'log')              agents[name].logged++;
    else if (d.action === 'allow')            agents[name].allowed++;
    if (d.timestamp && (!agents[name].last || d.timestamp > agents[name].last)) {
      agents[name].last = d.timestamp;
    }
  }

  return agents;
}

/**
 * Finds all decisions that match a hook's categories, and returns aggregated
 * counts and the most recent timestamp.
 * @param {{ categories: string[] }} hook
 * @param {Array<{ category?: string, action: string, timestamp?: string }>} decisions
 * @returns {{ count: number, blocks: number, lastFired: string|null }}
 */
export function matchHookDecisions(hook, decisions) {
  const fired = decisions.filter(d => hook.categories.includes(d.category));
  const count = fired.length;
  const blocks = fired.filter(d => d.action === 'block').length;
  const lastFired = fired.reduce((latest, d) => {
    if (!d.timestamp) return latest;
    return (!latest || d.timestamp > latest) ? d.timestamp : latest;
  }, null);
  return { count, blocks, lastFired };
}
