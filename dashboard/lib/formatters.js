// ── Jarvis Dashboard — Shared Formatter Utilities ──
// Pure functions with no DOM or browser dependencies.

/**
 * Returns a human-readable relative-time string for a timestamp.
 * @param {number|string|null|undefined} timestamp - Unix ms or date string.
 * @returns {string}
 */
export function timeAgo(timestamp) {
  if (timestamp == null) return '--';
  const now = Date.now();
  const ts = typeof timestamp === 'string' ? new Date(timestamp).getTime() : timestamp;
  const diff = Math.floor((now - ts) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

/**
 * Formats a numeric value as a USD currency string.
 * @param {number|null|undefined} val
 * @returns {string}
 */
export function formatCurrency(val) {
  if (val == null) return '--';
  return '$' + Number(val).toFixed(2);
}

/**
 * Formats a large number with K / M suffixes.
 * @param {number|null|undefined} val
 * @returns {string}
 */
export function formatNumber(val) {
  if (val == null) return '--';
  if (val >= 1e6) return (val / 1e6).toFixed(1) + 'M';
  if (val >= 1e3) return (val / 1e3).toFixed(1) + 'K';
  return val.toString();
}
