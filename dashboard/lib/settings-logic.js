// ── Settings Logic — Pure, DOM-free business logic ──
// Extracted from pages/settings/settings.js for testability.

export const HARNESSES = [
  {
    id:    'claude',
    label: 'Claude',
    badge: 'Anthropic',
    path:  '~/.claude/',
    desc:  'Primary reasoning agent — Claude Code + Hooks',
  },
  {
    id:    'codex',
    label: 'Codex',
    badge: 'OpenAI',
    path:  '~/.codex/',
    desc:  'Code generation and refactoring assistant',
  },
  {
    id:    'gemini',
    label: 'Gemini',
    badge: 'Google',
    path:  '~/.gemini/',
    desc:  'Multi-modal analysis and vision tasks',
  },
  {
    id:    'cursor',
    label: 'Cursor',
    badge: 'Anysphere',
    path:  '~/.cursor/rules/',
    desc:  'IDE-embedded agent for inline edits',
  },
];

/** Threshold above which a lastSeen timestamp is considered stale: 1 hour. */
export const STALE_THRESHOLD_MS = 3600 * 1000;

/**
 * Derives the sync status of a harness by looking it up in the agents list.
 *
 * Returns:
 *   'in-sync'  — agent present in state.agents and lastSeen is recent (< 1hr)
 *   'stale'    — agent present but lastSeen is older than STALE_THRESHOLD_MS or null
 *   'missing'  — agent not found in state.agents
 *
 * @param {string} harnessId
 * @param {Array<{ id: string, lastSeen?: string|null }>|null|undefined} agents
 * @returns {'in-sync' | 'stale' | 'missing'}
 */
export function deriveSyncStatus(harnessId, agents) {
  if (!agents) return 'missing';

  const agent = agents.find(a => (a.id || '').toLowerCase() === harnessId.toLowerCase());

  if (!agent) return 'missing';

  const isStale = agent.lastSeen
    ? (Date.now() - new Date(agent.lastSeen).getTime()) > STALE_THRESHOLD_MS
    : true;

  return isStale ? 'stale' : 'in-sync';
}
