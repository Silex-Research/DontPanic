// ── Jarvis Dashboard — HTML Escape Utility ──
// Safe for use in innerHTML template literals.

/**
 * Escapes a value for safe insertion into HTML.
 * Returns an empty string for null or undefined.
 * @param {*} str
 * @returns {string}
 */
export function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
