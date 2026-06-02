---
status: operator_resolved
reason_class: operator_judgment
plan_id: 2026-05-30-001-feat-universal-agent-repo-onboarding-v0
feature_id: F016
closed_at: 2026-06-02T16:43:01Z
latest_audit_status: needs_changes
---

# Closeout memo — 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 / F016

## Operator decision

F016 (skill recommendation SURFACES + migration — split from F011 per D060) is
closed `operator_resolved` (class `operator_judgment`).

The volley implementer **over-scoped** F016 — it TIMED OUT at 600s on BOTH rounds
(`claude-implementer-F016-i0/i1.json`: `DISPATCH TIMED OUT after 600s`,
`audit_status: blocked`, zero validation commands). This is the 4th over-scope
event of the arc and the strongest evidence yet for the plan-review pre-dispatch
sizing gate (F016 was *itself* already a split of F011). The ~80% the implementer
landed (a 755-line `skill_recommendation.py` + CLI `skills recommend` + the
build-side `write_skill_recommendations`) was kept; the operator finished the
codex auditor's 6 concrete, REAL gaps (NOT a no-defect close) and independently
verified.

## Operator action (commit f1865e3)

1. **AC9 dashboard parity** — `dashboard/core.js` loads `skill-recommendations.json`
   into a pure `dashboard/lib/skill-recommendations-logic.js` render module wired
   into the Settings page; a Python parity test asserts the JS-consumed JSON equals
   the CLI `report.to_dict()` (mirrors F013's config-inventory pattern).
2. **AC10 external-binary blocker** — `explain_blockers` probes the binary
   (`shutil.which`, injectable) and synthesizes a SPECIFIC capability blocker when
   it is absent.
3. **AC10 blocker specificity** — only the required credential/binary/capability is
   named, not the whole unavailable set.
4. **AC11 doctor advisory** — non-blocking `dontpanic_doctor.check_skill_rubrics_advisory`
   lists high-value skills missing rubrics and suggests `skills rubric --suggest`.
5. **AC11 rubric required_inputs** — `_derive_required_inputs` harvests from
   `argument-hint`/triggers/explicit lists (prose deliberately not parsed).
6. **ruff** — dropped unused `field` import; justified the advisory try/except.

## Return Condition

status: satisfied

F016 returns complete when:

- Missing inputs produce ONE concise ActionChoice naming only the missing blocker
  (AC8); the build-side merges it into the dashboard what-now action queue.
- CLI (`dontpanic skills recommend --format text|json`) and the dashboard render the
  SAME SkillAction data — skill, recommendation, reason, risk, exact_command,
  approval_required, evidence_target (AC9). Proven by the JSON-shape parity test.
- The recommender uses the F008 config inventory to explain unavailable
  credentials/binaries/capabilities — matching the SPECIFIC required resource,
  including external CLIs absent from PATH (AC10), via F007 dedup.
- A migration path exists: `dontpanic skills rubric --suggest <skill>` derives safe
  starting `required_inputs`, and a non-blocking doctor advisory flags high-value
  skills missing rubrics (AC11).
- Tests cover dashboard JSON shape parity, missing-input handling, the external-binary
  blocker, blocker specificity, doctor advisory output, and rubric derivation (AC14c).

## Verification

- 23 pytest (`test_skill_recommendation_f016.py`, 13 original + 10 new) + 8 vitest
  (new `skill-recommendations-logic.test.js`) + 200 broader Python (skill + dashboard
  F013 + config-inventory F008 + command-validation) all pass.
- Dashboard full vitest suite: 936 pass (no regressions). ruff clean on the in-scope
  Python files. `skills recommend`/`skills rubric --help` exit 0; live doctor emits a
  non-blocking WARN.
- Operator independently read the 4 substantive fixes (external-binary synth blocker,
  doctor advisory, rubric derivation, JS↔CLI parity test) — real implementations, not
  stubs or test-weakening. Mechanical multi-file implementation was delegated to a
  subagent; verification was performed directly by the operator.

## Evidence references

- `audit/codex-auditor-F016-i0.json` / `-i1.json` — verdicts `needs_changes`
  (implementer timed out both rounds).
- `audit/signoff-…json` — operator-resolved signoff envelope (`operator_judgment`).
- commit `f1865e3` — F016 deliverables (engine + CLI + dashboard Python/JS + doctor + tests).
- decisions `D060` (F011 3-way split), `D063` (this close).
