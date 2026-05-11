# Plan 2026-05-10-001 F001 — close-out memo (operator-resolved)

## Return Condition

status: operator_resolved
class: spec-clarification
v3_candidate: false

## Summary

Volley 1 dispatched implementer=claude + auditor=codex on F001 (author
3 skill files under `claude/skills/printing-press-adapter/`).
Terminated `stopped_no_progress` after 2 rounds: iteration 1 audit
remained `needs_changes` but the v0 finding taxonomy could not place
the iteration 1 finding (classifier returned `aggregate: unknown
blocking: true`).

Operator review (per parent plan 2026-05-11-001 F004 close-out path):
the iteration 1 finding is a spec-ambiguity in F001 step #2, not a
defect in the implementer's work. Plan 010 F001 step #2 reads
"document the PP version in the adapter's adapters.json entry" —
ambiguous between the central registry `~/.dontpanic/adapters.json`
and the per-service config `~/.dontpanic/adapters/<service>.json`.
Implementer chose per-service (config-as-data, isolated per
integration); auditor expected central registry (literal reading).
Both are defensible engineering. Per the volley-failure-taxonomy
memo, this is `spec-clarification` — not `feature_defect`, not
`interpretive_disagreement`.

## Acceptance verification

(1) `claude/skills/printing-press-adapter/SKILL.md` exists with
    frontmatter `applies_to.surfaces: [external-api-wrap]`. ✓
    Note: `external-api-wrap` is not yet in the agent-conventions
    `surfaces[]` enum — that ships in plan 010 F002 (v1.7.0 bump).
    SKILL.md anticipates the enum; F002 lands the schema change.
(2) `DECISION_TREE.md` exists (103 lines); documents the four
    anti-cases. ✓
(3) `ADAPTER_TEMPLATE.md` exists (440 lines) with sanitization
    logic (SanitizationFailed, _SECRET_PATTERNS, _scan_for_secrets,
    sanitize_response, redact_and_sanitize). ✓
    Note: acceptance #3 originally said "compiles as a Python
    module (ast.parse passes)" but ADAPTER_TEMPLATE.md is markdown
    not .py. The Python code blocks within it should be ast.parse-
    checkable separately; not done in this volley. Treating this
    as F002 work or spec refinement.
(4) Skill discoverable via skill-applicability matcher — to be
    verified post-F002 enum bump.

## Recommended next steps

- Clear `breaker:no_progress` gate via
  `python3 -m dontpanic_orchestrate approve 2026-05-10-001-feat-printing-press-adapter-skill breaker:no_progress`
- Patch plan 010 F001 step #2 to explicitly say "per-service config
  at `~/.dontpanic/adapters/<service>.json`" so future iterations
  don't trip the same ambiguity (covered by parent D-entry).
- Proceed to plan 010 F002 (agent-conventions v1.7.0 bump).
