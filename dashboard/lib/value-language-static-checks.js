// ── Value-Language Static Checks — Pure helpers ──
// Implements the forbidden-token contract documented in
// docs/design/dashboard-value-language-ia-v0/copy-map.md §5.
//
// Plan: 2026-05-24-001-feat-dashboard-value-language-ia-v0 (F001).
// F002 (shell rebrand) and F003 (page rewrites) consume these helpers to
// prove that Layer-1 / first-read text does not include internal-only
// DontPanic vocabulary, and that user-visible shell text does not carry
// Jarvis-era branding.
//
// Layer 2 contexts (details rows, source/provenance footers, exact-command
// chips, tooltips) are *expected* to contain these tokens — the scanner
// only flags substrings that appear in the input it is given. Callers are
// responsible for slicing out the Layer 1 / shell-text region they want
// to validate.
//
// All exports are pure: same input → same output, no DOM access, no I/O.

/**
 * Tokens that must not appear as Layer 1 / first-read labels in V0.
 * Allowed (and often required) in Layer 2: metadata rows, tooltips,
 * source/provenance footers, exact-command chips, details sections.
 *
 * Keep in sync with copy-map.md §5.
 */
export const FORBIDDEN_FIRST_READ_TOKENS = Object.freeze([
  'gate',
  'supervisor',
  'volley',
  'manifest',
  'quota',
  'pre_impl',
  'pre_merge',
]);

/**
 * Brand strings that must not appear in user-visible shell text
 * (page titles, header, footer, nav labels) regardless of layer.
 *
 * Keep in sync with copy-map.md §5.
 *
 * Note: the bare identifier `Jarvis` is intentionally NOT included
 * here — it may legitimately appear as a JavaScript object name on
 * window (`window.Jarvis`) or as a localStorage key prefix
 * (`jarvis.selectedProject`) for cache compatibility. Callers that
 * want to enforce the no-`Jarvis` rule on prose / shell text should
 * use {@link scanShellTextForViolations} which lowercases its input
 * before matching against `JARVIS`-as-brand and the compound brand
 * phrases below.
 */
export const FORBIDDEN_SHELL_BRAND_PHRASES = Object.freeze([
  'JARVIS',
  'Personal Control Dashboard',
  'Silex Research',
]);

/**
 * Page-registration nav labels that must not appear as Layer 1
 * registered labels in V0. Each entry maps to a V0 disposition
 * in copy-map.md §4.5 (rename, fold into Health, hide, or remove
 * from core nav).
 *
 * The page module file itself may remain on disk for path stability,
 * but the `label:` field passed to `Jarvis.registerPage({...})` must
 * be updated (or the page de-registered from V0 core nav) so that the
 * runtime `<nav>` never displays one of these phrases as a first-read
 * tab label.
 *
 * Phrases are intentionally multi-word / distinctive to keep the
 * scanner safe to run against any user-visible nav slice without
 * false-positives in technical Layer 2 disclosure.
 *
 * Keep in sync with copy-map.md §4.5.
 */
export const FORBIDDEN_STALE_NAV_LABELS = Object.freeze([
  'What Now',
  'Mission Control',
  'Command Center',
  'Capability Center',
  'Cloud Costs',
  'Financial Analysis',
]);

const WORD_BOUNDARY = /[A-Za-z0-9_]/;

function isWordChar(ch) {
  return typeof ch === 'string' && WORD_BOUNDARY.test(ch);
}

function findWholeWordMatches(haystack, needle) {
  const matches = [];
  if (typeof haystack !== 'string' || haystack.length === 0) return matches;
  if (typeof needle !== 'string' || needle.length === 0) return matches;

  let from = 0;
  while (from <= haystack.length - needle.length) {
    const idx = haystack.indexOf(needle, from);
    if (idx < 0) break;
    const before = idx > 0 ? haystack[idx - 1] : '';
    const after  = idx + needle.length < haystack.length
      ? haystack[idx + needle.length]
      : '';
    if (!isWordChar(before) && !isWordChar(after)) {
      matches.push({ token: needle, index: idx });
    }
    from = idx + needle.length;
  }
  return matches;
}

/**
 * Scan a slice of *Layer 1* text for forbidden first-read tokens.
 * Returns an array of `{ token, index }` for each whole-word match.
 *
 * The check is case-insensitive but whole-word: `gate` matches
 * "Gate name", "PRE_IMPL gate", "gate", but not "gateway".
 *
 * @param {string} text — Layer 1 / first-read text to validate.
 * @param {string[]} [tokens] — token list (defaults to FORBIDDEN_FIRST_READ_TOKENS).
 * @returns {Array<{token: string, index: number}>}
 */
export function scanForFirstReadViolations(text, tokens = FORBIDDEN_FIRST_READ_TOKENS) {
  if (typeof text !== 'string') return [];
  const lowered = text.toLowerCase();
  const violations = [];
  for (const token of tokens) {
    const lowerToken = String(token).toLowerCase();
    for (const m of findWholeWordMatches(lowered, lowerToken)) {
      violations.push({ token: lowerToken, index: m.index });
    }
  }
  violations.sort((a, b) => a.index - b.index);
  return violations;
}

/**
 * Scan user-visible *shell text* (page titles, header, footer, nav)
 * for Jarvis-era branding. Returns an array of `{ phrase, index }`
 * for each match.
 *
 * Matching is case-insensitive on the *phrase* level (so `JARVIS`
 * matches `Jarvis` and `jarvis` in prose), but the caller is
 * responsible for excluding JS identifiers / localStorage keys
 * before invoking this helper — see the FORBIDDEN_SHELL_BRAND_PHRASES
 * doc comment.
 *
 * @param {string} text — shell text region (title/header/nav/footer).
 * @param {string[]} [phrases] — phrase list (defaults to FORBIDDEN_SHELL_BRAND_PHRASES).
 * @returns {Array<{phrase: string, index: number}>}
 */
export function scanShellTextForViolations(text, phrases = FORBIDDEN_SHELL_BRAND_PHRASES) {
  if (typeof text !== 'string') return [];
  const lowered = text.toLowerCase();
  const violations = [];
  for (const phrase of phrases) {
    const lowerPhrase = String(phrase).toLowerCase();
    if (lowerPhrase.length === 0) continue;
    let from = 0;
    while (from <= lowered.length - lowerPhrase.length) {
      const idx = lowered.indexOf(lowerPhrase, from);
      if (idx < 0) break;
      violations.push({ phrase, index: idx });
      from = idx + lowerPhrase.length;
    }
  }
  violations.sort((a, b) => a.index - b.index);
  return violations;
}

/**
 * Scan a slice of registered nav-label text for stale V0 nav labels
 * (see {@link FORBIDDEN_STALE_NAV_LABELS}). Returns an array of
 * `{ label, index }` for each match.
 *
 * Matching is case-insensitive phrase-substring. Useful as a
 * companion to {@link extractRegisteredPageLabel} when validating
 * the set of page modules that participate in V0 core nav.
 *
 * @param {string} text — concatenated registered nav-label text.
 * @param {string[]} [labels] — label list (defaults to FORBIDDEN_STALE_NAV_LABELS).
 * @returns {Array<{label: string, index: number}>}
 */
export function scanForStaleNavLabels(text, labels = FORBIDDEN_STALE_NAV_LABELS) {
  if (typeof text !== 'string') return [];
  const lowered = text.toLowerCase();
  const violations = [];
  for (const label of labels) {
    const lowerLabel = String(label).toLowerCase();
    if (lowerLabel.length === 0) continue;
    let from = 0;
    while (from <= lowered.length - lowerLabel.length) {
      const idx = lowered.indexOf(lowerLabel, from);
      if (idx < 0) break;
      violations.push({ label, index: idx });
      from = idx + lowerLabel.length;
    }
  }
  violations.sort((a, b) => a.index - b.index);
  return violations;
}

/**
 * Extract the `label:` value passed to `Jarvis.registerPage({...})`
 * from a page module's JS source.
 *
 * Limits matching to the first 400 characters after `registerPage({`
 * so chart, table, and form labels deeper in the file are not
 * mistaken for the registered nav label. Returns the literal string
 * (no normalization) or `null` if no registered label is found.
 *
 * @param {string} jsSource — page module JS source code.
 * @returns {string|null}
 */
export function extractRegisteredPageLabel(jsSource) {
  if (typeof jsSource !== 'string') return null;
  const re = /registerPage\s*\(\s*\{([\s\S]{0,400})/g;
  let m;
  while ((m = re.exec(jsSource)) !== null) {
    const labelMatch = m[1].match(/\blabel\s*:\s*(['"])([^'"]+)\1/);
    if (labelMatch) return labelMatch[2];
  }
  return null;
}

/**
 * Convenience: extract the user-visible shell text regions from an
 * HTML string — `<title>`, `<h1>`, `<header>`, `<nav>`, `<footer>`,
 * `<subtitle>` — and return them joined with newlines.
 *
 * The regex set is intentionally narrow: it targets the V0 shell
 * regions defined in copy-map.md §2.1, not arbitrary page bodies.
 * Page-body assertions belong on per-page snapshots, not here.
 *
 * @param {string} html — raw HTML source.
 * @returns {string} concatenated shell-text regions, newline-separated.
 */
export function extractShellTextRegions(html) {
  if (typeof html !== 'string') return '';
  const regions = [];
  const patterns = [
    /<title[^>]*>([\s\S]*?)<\/title>/gi,
    /<h1[^>]*>([\s\S]*?)<\/h1>/gi,
    /<header[^>]*>([\s\S]*?)<\/header>/gi,
    /<nav[^>]*>([\s\S]*?)<\/nav>/gi,
    /<footer[^>]*>([\s\S]*?)<\/footer>/gi,
    // The shell ships a free-floating `<span class="subtitle">` inside
    // the header — covered by <header> above, but also match standalone
    // subtitles in case the shell HTML is sliced before scanning.
    /<span[^>]*class=["'][^"']*subtitle[^"']*["'][^>]*>([\s\S]*?)<\/span>/gi,
  ];
  for (const re of patterns) {
    let m;
    while ((m = re.exec(html)) !== null) {
      // Strip nested tags inside the captured region so the violation
      // index reflects the visible text, not the markup.
      const visible = m[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
      if (visible.length > 0) regions.push(visible);
    }
  }
  return regions.join('\n');
}
