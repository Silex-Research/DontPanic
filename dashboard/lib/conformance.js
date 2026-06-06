// Plan 2026-06-05-003 F004 — dashboard conformance detectors.
//
// Two pure checks that would have caught the audit's worst bug class:
//  (a) emitted-class → CSS-rule resolution — a class that renders but has no rule
//      produces an unstyled element (the Repair / sr-* / cap-card-* failures).
//  (b) token-only values — a raw hex/rgba color, or a px font-size / spacing value,
//      used OUTSIDE a :root token-definition block is design-token drift.
//
// Both are advisory primitives; the test layer decides what is blocking vs. ledgered.

/** Every class name that has at least one CSS rule in `cssText`. */
export function definedClasses(cssText) {
  const out = new Set();
  // .class-name in any selector position (handles .a.b, .a .b, .a:hover, .a > .b).
  const re = /\.(-?[_a-zA-Z][\w-]*)/g;
  let m;
  while ((m = re.exec(cssText)) !== null) out.add(m[1]);
  return out;
}

/** Every class name actually present in a rendered DOM subtree. */
export function emittedClasses(rootEl) {
  const out = new Set();
  if (!rootEl) return out;
  const walk = (el) => {
    if (el.classList) for (const c of el.classList) out.add(c);
    for (const child of el.children || []) walk(child);
  };
  walk(rootEl);
  return out;
}

/** Emitted classes with no matching CSS rule in the union of `definedSets`. */
export function unresolvedClasses(emitted, ...definedSets) {
  const defined = new Set();
  for (const s of definedSets) for (const c of s) defined.add(c);
  return [...emitted].filter((c) => !defined.has(c)).sort();
}

// Strip every :root{ ... } block — those are the SANCTIONED home of raw token values.
function stripRootBlocks(cssText) {
  return cssText.replace(/:root\s*\{[^}]*\}/g, '');
}

/**
 * Raw design values used outside :root: hex/rgb(a) colors, px font-sizes, and px
 * margin/padding/gap. Times (0.12s), 1px borders, and transforms are intentionally
 * NOT flagged — the audit's drift was color + type + spacing, not those.
 */
export function rawValueOffenders(cssText) {
  const body = stripRootBlocks(cssText);
  const offenders = [];
  const push = (kind, value) => offenders.push({ kind, value });
  for (const m of body.matchAll(/#[0-9a-fA-F]{3,8}\b/g)) push('hex-color', m[0]);
  for (const m of body.matchAll(/\brgba?\([^)]*\)/g)) push('rgb-color', m[0]);
  for (const m of body.matchAll(/font-size:\s*[^;}]*\d+px/g)) push('px-font-size', m[0].trim());
  for (const m of body.matchAll(/\b(?:margin|padding|gap)[a-z-]*:\s*[^;}]*\d+px/g)) push('px-spacing', m[0].trim());
  return offenders;
}

/** Convenience: does this CSS pass the token-only check (no raw offenders)? */
export function isTokenOnly(cssText) {
  return rawValueOffenders(cssText).length === 0;
}
