// ── command-center-logic.js ──
// Pure logic extracted from the command-center page IIFE.
// No DOM access — all functions are side-effect free and testable.

// ── Agent metadata ──────────────────────────────────────────────────────────

const AGENT_META = {
  claude:  { initials: 'CC', color: '#3b82f6', badge: 'LEAD' },
  codex:   { initials: 'CX', color: '#22c55e', badge: 'OAI'  },
  gemini:  { initials: 'GM', color: '#f97316', badge: 'GGL'  },
  grok:    { initials: 'GK', color: '#a855f7', badge: 'XAI'  },
  kimi:    { initials: 'KM', color: '#eab308', badge: 'MSH'  },
  qwen:    { initials: 'QW', color: '#ef4444', badge: 'ALI'  },
};

// Returns metadata for a known agent id, or a computed fallback for unknown ids.
export function getAgentMeta(id) {
  return AGENT_META[id] || {
    initials: (id || '??').slice(0, 2).toUpperCase(),
    color: '#64748b',
    badge: 'AGT',
  };
}

// ── normalizeStatus ──────────────────────────────────────────────────────────
// Maps legacy 'todo' to 'pending'; defaults null/undefined to 'pending'.

export function normalizeStatus(status) {
  if (status === 'todo') return 'pending';
  return status || 'pending';
}

// ── computeTokenPct ──────────────────────────────────────────────────────────
// Returns { pct: number, colorClass: string } for a token budget meter.
// pct is capped at 100. colorClass is 'red' (>90), 'yellow' (>70), or 'accent'.

export function computeTokenPct(tokensUsed, tokenBudget) {
  if (!tokenBudget) {
    return { pct: 0, colorClass: 'accent' };
  }
  const pct = Math.min(Math.round((tokensUsed / tokenBudget) * 100), 100);
  const colorClass = pct > 90 ? 'red' : pct > 70 ? 'yellow' : 'accent';
  return { pct, colorClass };
}

// ── buildMetricPoints ────────────────────────────────────────────────────────
// Builds per-day metric points from agent token usage and activity events.
// Returns [{ date, actions, tokensUsed }] sorted chronologically.
// Returns [] when there are no activity events with timestamps.

export function buildMetricPoints(state) {
  const agents   = state.agents   || [];
  const activity = state.activity || [];

  if (!activity.length) return [];

  // Bucket activity events by calendar date.
  const buckets = {};
  for (const item of activity) {
    if (!item.timestamp) continue;
    const d = new Date(item.timestamp).toLocaleDateString('en-US', {
      month: 'short', day: 'numeric',
    });
    if (!buckets[d]) buckets[d] = { date: d, actions: 0, tokensUsed: 0 };
    buckets[d].actions++;
  }

  // Spread agent token totals evenly across available dates as a heuristic.
  const dates = Object.keys(buckets);
  if (dates.length > 0) {
    const totalTokens  = agents.reduce((s, a) => s + (a.tokensUsed || 0), 0);
    const tokensPerDay = Math.floor(totalTokens / dates.length);
    for (const d of dates) {
      buckets[d].tokensUsed = tokensPerDay;
    }
  }

  return Object.values(buckets).sort((a, b) => new Date(a.date) - new Date(b.date));
}
