---
status: operator_resolved
reason_class: spec_ambiguity
plan_id: 2026-05-30-001-feat-universal-agent-repo-onboarding-v0
feature_id: F011
closed_at: 2026-06-02T15:02:55Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 / F011

## Operator decision

F011-core (skill-invocation engine — narrowed per D060: validated `invocation:`
SKILL.md frontmatter schema + pure SkillInvocationEvaluator + typed SkillAction +
risk precedence + never_suggest + representative fixtures) is closed
`operator_resolved` (class `spec_ambiguity`).

The volley ran three codex rounds and the implementer fixed REAL defects across
them: (i0→i1) unsafe `exact_command` emitted off the safe path is now suppressed;
(i1→i2) `never_auto`/`never_suggest` now win in risk precedence over
missing-input blocking, matching the documented and AC6 precedence. The terminal
was `stopped_no_progress`, but note the underlying findings genuinely CHANGED each
round — the breaker fired on the verdict *string* (`needs_changes`) repeating, not
on a static finding (a known harness friction: verdict-string no_progress vs
findings-actually-moved).

The residual i2 finding is a **spec-clarification, not a defect**. The auditor
inferred `evidence_target` must be required for ALL modes because AC1 listed it as
a schema field and only marked `command_template` "optional". But the
implementation correctly requires `evidence_target` ONLY for the auto-eligible
modes (`auto_readonly`, `auto_safe`) via `_auto_modes_require_evidence_target`,
and leaves it optional for `suggest`/`approval_required`/`never_auto`/
`never_suggest` — which never auto-execute and therefore have no evidence to
target. Requiring it on a `never_suggest` skill would be a nonsensical authoring
burden. The code is right; the AC text was ambiguous. Resolution per the
spec-drift convention: sharpen AC1 (commit `9820613`) to codify the operator
intent, operator-accept — do NOT change correct code or burn another paid audit.

## Operator action (commit 9820613)

- AC1 sharpened: `evidence_target` is REQUIRED for auto-eligible modes
  (`auto_readonly`, `auto_safe`) and OPTIONAL for suggest/approval_required/
  never_auto/never_suggest.
- F011-core deliverables committed: `skill_invocation.py`,
  `tests/test_skill_invocation_f011.py`, and the `tests/fixtures/skill_rubrics/`
  representative-skill fixtures.

## Return Condition

status: satisfied

F011-core returns complete when:

- A validated `invocation:` SKILL.md frontmatter schema exists and is a no-op for
  metadata-less skills (AC1); evidence_target conditionality matches AC1 as
  sharpened.
- A pure `SkillInvocationEvaluator` emits typed `SkillAction` records with the
  five recommendation values from an injected `SkillInvocationContext`, with no
  I/O or execution (AC2); metadata-less skills never `auto_run` (AC3).
- Risk precedence is deterministic and tested: `never_auto`/`never_suggest` win;
  external-write/paid/loop/credentialed/network/repo-mutation/missing-input
  downgrade or block; contradictory metadata yields a diagnostic SkillAction
  (AC6). The allowlist check is consumed as an injected predicate (owned by F015).
- `never_suggest` opt-out suppresses recommendations (AC12); representative skill
  fixtures exist (AC13); engine-level tests cover each recommendation class, the
  no-auto fallback, never_suggest, precedence with contradictory metadata, and
  missing-input handling (AC14a).

## Verification

- `pytest test_skill_invocation_f011.py` → 50 passed; ruff clean on
  `skill_invocation.py` + the test file.
- Operator independently confirmed the residual is the documented spec-drift class
  (read `_auto_modes_require_evidence_target` + the AC1 text; verified the i0/i1
  defects were genuinely fixed, not re-raised).

## Evidence references

- `audit/codex-auditor-F011-i0.json` / `-i1.json` / `-i2.json` — verdicts
  `needs_changes`; findings moved i0(3)→i1(1)→i2(1).
- `audit/signoff-…json` — operator-resolved signoff envelope (class `spec_ambiguity`).
- commit `9820613` — F011-core deliverables + AC1 clarification.
- decisions `D060` (F011 3-way split), `D061` (this close).
