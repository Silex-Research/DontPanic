"""F003 — EC5 (target-context prelude) severity classifier + finding-aggregation
downgrade. Pure helpers, no I/O.

The classifier returns one of three abstract verdicts for a given audit envelope:

  * ``'none'`` — struct validates AND a canonical prelude block is present in
    the summary AND the parsed prelude values match the struct rendering.
    No EC5 finding should be filed. Drop any EC5-coded finding.

  * ``'i0'`` — struct validates AND the summary either has NO detectable
    prelude OR has a structurally-malformed prelude (wrong field order,
    mistyped labels, missing line, missing trailing blank). F002's auto-
    injection would normalize this on next persist; the auditor finding is
    cosmetic. Downgrade an EC5 i1 finding to severity 'advisory' and
    preserve the original description (D008).

  * ``'i1'`` — struct INVALID (missing target_context, empty env with
    commands, empty project with commands, commands_run without target
    metadata) OR struct valid but the parsed prelude's values disagree with
    the struct rendering (case-g — 'narrow' downgrade rule per D005 + D010).
    Leave EC5 finding's severity as authored.

The aggregation helper applies these verdicts to a list of findings, treating
findings with explicit ``code: "EC5"`` and (acceptance #10 backwards-compat)
findings without ``code`` whose ``issue`` text matches a target.context.prelude
heuristic.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from dontpanic_orchestrate.target_context_prelude import (
    TargetContextError,
    parse_prelude_block,
    render_prelude,
    validate_target_context,
)

EC5Verdict = Literal["none", "i0", "i1"]
EC5_CODE = "EC5"

# Maps the classifier's abstract 'i0' verdict to an audit.schema.json severity
# enum value. 'advisory' is the lowest non-blocking severity and matches the
# semantic intent ("informational; format-only; F002 will normalize on next
# persist"). 'i1' has no entry — the original auditor severity is preserved
# verbatim per acceptance #4.
EC5_VERDICT_SEVERITY: dict[str, str] = {"i0": "advisory"}

# Backwards-compat heuristic for legacy auditor outputs that don't carry a
# `code` field. Matches issue text that names the EC5 surface (target context
# prelude) regardless of word order or separator (space, hyphen, period,
# underscore between "target" and "context"). Intentionally conservative —
# anchored on the bigram "target<sep>context" + "prelude", so generic phrases
# like "missing prelude" alone don't match unrelated findings.
_EC5_TEXT_HEURISTIC = re.compile(
    r"(target[\s\-._]?context[^.]*prelude|prelude[^.]*target[\s\-._]?context)",
    re.IGNORECASE,
)


def classify_ec5_severity(envelope: dict[str, Any]) -> EC5Verdict:
    """Return the abstract EC5 verdict for an audit envelope. Pure function."""
    tc = envelope.get("target_context")
    try:
        validate_target_context(tc)
    except TargetContextError:
        return "i1"

    # validate_target_context guarantees tc is a dict here.
    if not isinstance(tc, dict):
        return "i1"  # defensive — should not reach

    summary = envelope.get("summary") or ""
    try:
        parsed = parse_prelude_block(summary)
    except TargetContextError:
        # Header present but body malformed — F002 detects this now and
        # raises on persist; from the classifier's perspective it's a
        # format-only issue (re-rendering would fix it).
        return "i0"

    if parsed is None:
        return "i0"  # no detectable prelude

    # Canonical block present + struct valid. Compare parsed-from-summary
    # values against canonical-from-struct rendering. Any divergence is a
    # value-mismatch (case-g / D008) and stays i1 — the narrow-downgrade rule.
    #
    # Plan 2026-05-04-004 D002: classifier-local pure repo derivation.
    # Previously this called the prelude module's git-shelling helper,
    # which broke (a) classifier purity and (b) historical
    # ``Repo: Jarvis`` fixtures after the DontPanic directory rename —
    # the cwd-derived basename became ``DontPanic`` while the prelude
    # still said ``Jarvis``. The classifier now picks ``repo`` purely
    # from envelope data: struct first, parsed prelude second
    # (preserves historical fixtures per D005), None otherwise.
    repo = _derive_classifier_repo(tc, parsed)
    rendered = render_prelude({**tc, "repo": repo})
    expected = parse_prelude_block(rendered)
    # render_prelude is the canonical generator — its output MUST round-trip
    # through parse_prelude_block. If this assert ever fires it means the two
    # helpers have drifted apart and F001's own tests will catch it; we keep
    # the guard rather than silently returning a wrong verdict.
    assert expected is not None, "render_prelude output failed parse_prelude_block round-trip"

    if parsed != expected:
        return "i1"

    return "none"


def _derive_classifier_repo(
    tc: dict[str, Any],
    parsed: dict[str, Any] | None,
) -> str | None:
    """Pick the ``repo`` value used for canonical render comparison.

    Pure function — never reaches the filesystem (Plan 2026-05-04-004 D002).
    Selection order:

    1. ``tc['repo']`` if present and truthy — the structured-target path.
    2. ``parsed['repo']`` if a prelude was parsed and contains a ``repo``
       — preserves historical ``Repo: Jarvis`` fixtures predating the
       DontPanic rename (D005). Comparing parsed-against-itself is correct
       here because we're checking whether the prelude is internally
       consistent with the struct, and the struct's ``repo`` (when
       absent) is by definition whatever the prelude claims.
    3. ``None`` — caller passes through to ``render_prelude`` which
       handles the missing-repo case per its own contract.
    """
    if tc and tc.get("repo"):
        return tc["repo"]
    if parsed is not None and "repo" in parsed:
        return parsed["repo"]
    return None


def is_ec5_finding(finding: dict[str, Any]) -> bool:
    """True when ``finding`` is EC5-coded or matches the EC5 text heuristic.

    Detection order:
      1. Explicit ``code == "EC5"`` field — cheapest, used by F003-aware
         auditors that learn the EC5 paragraph from the prompt template.
      2. Backwards-compat: ``issue`` text matches the EC5 prelude heuristic
         (acceptance #10) — handles legacy auditor outputs.
    """
    if finding.get("code") == EC5_CODE:
        return True
    issue = finding.get("issue") or ""
    return bool(_EC5_TEXT_HEURISTIC.search(issue))


def apply_ec5_classifier_to_findings(
    findings: list[dict[str, Any]],
    envelope: dict[str, Any],
) -> list[dict[str, Any]]:
    """Drop / downgrade EC5 findings per the classifier's verdict.

    Per D008: severity is the only field mutated on downgrade; description /
    issue / evidence / recommendation / code all survive verbatim. The input
    list is not mutated — callers retain access to the pre-classification
    findings if needed for evidence packaging.

    Non-EC5 findings pass through identically (same dict reference).
    """
    verdict = classify_ec5_severity(envelope)
    out: list[dict[str, Any]] = []
    for finding in findings:
        if not is_ec5_finding(finding):
            out.append(finding)
            continue

        if verdict == "none":
            continue  # drop — the auditor false-positived on a golden envelope

        if verdict == "i0":
            downgraded = dict(finding)
            downgraded["severity"] = EC5_VERDICT_SEVERITY["i0"]
            out.append(downgraded)
            continue

        # verdict == "i1" — auditor's reading stands; pass through unchanged.
        out.append(finding)

    return out


__all__ = [
    "EC5_CODE",
    "EC5_VERDICT_SEVERITY",
    "EC5Verdict",
    "apply_ec5_classifier_to_findings",
    "classify_ec5_severity",
    "is_ec5_finding",
]
