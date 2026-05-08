---
id: 2026-05-05-001-fix-plan-validator-audit-auxiliary-json
title: Fix — agent-conventions plan validator dispatches by artifact type, skips auxiliary audit JSON
type: fix
tier: cross-cutting
status: completed
date: "2026-05-05"
description: |
  Two-step coordinated fix for the plan validator's naive
  artifact-dispatch logic. Today the validator at
  `claude/shared/schemas/v1.0/validate.py` (v1.3.0) decides
  Signoff vs Audit purely by filename substring:

  ```python
  for f in sorted(audit_dir.glob("*.json")):
      data = json.loads(f.read_text())
      model = Signoff if "signoff" in f.name else Audit
      ok, line = _check(f"audit/{f.name}", model, data)
  ```

  Anything under `audit/` that isn't a signoff envelope and isn't
  a real audit envelope (e.g. `gate-state.json` written by F008's
  gate-pause protocol) gets force-validated against the Audit model
  and produces false validation failures. The pattern is generic —
  every repo that consumes agent-conventions and uses staged human
  gates hits it.

  **Step 1 — agent-conventions upstream patch (F001).** Replace the
  filename-substring dispatch with explicit artifact classification:

  - `signoff*.json` → Signoff model.
  - Real audit envelopes (filename matches the volley pattern,
    e.g. `claude-implementer-*.json`, `codex-auditor-*.json`,
    or any other `*-i\d+.json` shape) → Audit model.
  - **Known auxiliary files → skip with a clear info-line.** The
    v1 known-auxiliary list contains exactly one entry today:
    `gate-state.json` (D004). Future plans extend the list.
  - Unknown `audit/*.json` → warn + skip (not error) in v1
    (D005). Keeps the validator usable when new auxiliary names
    appear before they're added to the known list.

  Bumps agent-conventions to **v1.3.1** (semver patch — bug fix,
  no schema or Pydantic model changes; D007).

  **Step 2 — DontPanic subtree import (F002).** Pull the patched
  `claude/shared/` subtree into DontPanic. Add regression tests
  against the existing `audit/gate-state.json` files across
  Plans 001-005 + B + C (8+ natural fixtures already on disk).
  Confirm real audit envelopes still validate, real signoffs still
  validate, and `gate-state.json` no longer false-fails.

  Two separate commits — upstream patch first, subtree import
  second — to keep the commit boundary explicit (D006).

motivation: |
  Surfaced at Plan C F003 close-out (Plan C's D010): the
  validator was breaking `audit/gate-state.json` in any plan with
  staged human gates. Workaround so far has been "don't run the
  validator generically on `audit/`" — which silently disables a
  lot of useful checking. Plan E fixes this at the source.

  This is not DontPanic-specific. agent-conventions is consumed
  by Glam and SpinDineSwift too; both will hit the same false
  validation failure the moment they ship staged gates. Local
  wrapper in DontPanic (rejected option per D003) would mask the
  bug and leave Glam / SpinDineSwift broken.

agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 1
  no_progress_threshold: 1
  wall_clock_hours: 2
  hard_stop: false
privacy_tier: internal
protected_paths:
  # Same protected set as Plans A-D, with one explicit carve-out:
  # F002 modifies claude/shared/ via `git subtree pull` ONLY — no
  # free-form edits in the DontPanic working tree (D010).
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/dontpanic_orchestrate/target_context_prelude.py
  # Plan E does NOT modify ec5_classifier.py, audit_writer.py, or
  # supervisor.py — Plans C/D handled those.
---

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Two features, both direct path:

1. **F001 — agent-conventions upstream patch** (worktree:
   `$HOME/Documents/GitHub/agent-conventions/`).
   Modify `schemas/v1.0/validate.py` so:

   - The audit-dir loop classifies each `*.json` by explicit
     artifact type before model selection.
   - `signoff*.json` → Signoff model.
   - Volley-pattern envelopes (`*-i\d+.json` regex) → Audit model.
   - Known auxiliary names (v1 list: `gate-state.json`) → skip
     with `  ⊘ <name> — auxiliary, skipped` info line.
   - Unknown audit JSON → warn + skip with `  ⚠ <name> —
     unknown audit artifact, skipped` info line, **not error**.
   - Bump `VERSION` to `1.3.1`. No model or schema file changes.

   Tests in agent-conventions add at least 4 fixtures: real
   audit envelope, real signoff envelope, known auxiliary
   (`gate-state.json`), unknown audit JSON. Each asserts the
   correct dispatch decision + exit code.

2. **F002 — DontPanic subtree import + regression coverage**
   (worktree: `$HOME/Documents/GitHub/DontPanic/`).

   - `git subtree pull --prefix=claude/shared/ <agent-conventions remote>
     v1.3.1 --squash` after F001 lands.
   - Verify `claude/shared/VERSION` reads `1.3.1`.
   - Run the validator against every plan dir under
     `docs/plans/` that has an `audit/` directory. Capture
     baseline (pre-pull) error count vs post-pull error count.
     `gate-state.json` fixtures in Plans 001 / 002 / 004 / 005 /
     B / C must transition from false-fail → skipped.
   - Real volley audit envelopes + signoffs in those same plans
     must still validate green.

## Out of scope (deliberate)

- **Inventing a `gate-state.schema.json`.** D001 — the v1 fix is
  type-aware dispatch, not schema expansion. A future plan may
  add a real schema for gate-state envelopes if shape stability
  warrants it; Plan E does not.
- **Local DontPanic-side wrapper around the validator.** D003
  rejected the local-only option in favor of upstream-coordinated.
  No new file under `scripts/dontpanic_orchestrate/`.
- **Schema or Pydantic model changes in agent-conventions.** D007
  — the patch is a `validate.py` logic change only. v1.3.0 →
  v1.3.1 (semver patch).
- **Free-form edits in `claude/shared/` from the DontPanic
  worktree.** D010 — F002 modifies the subtree via `git subtree
  pull` only. The DontPanic-side commit's diff for
  `claude/shared/**` must match exactly the upstream v1.3.1 diff
  (modulo the squash commit's parent metadata).
- **Other queued caveats.** Per-plan `loop_caps.subprocess_timeout_seconds`
  (Plan C D003) and `jarvis_orchestrate` shim removal (Plan A D006)
  stay queued. Plan E is the validator-hygiene slice only.

## Cross-cutting tightenings (operator-supplied)

Per pre-draft conversation. Codified in D001-D010:

1. **Skip known auxiliary in v1; don't invent gate-state schema.**
   D001. The point is to make the validator type-aware, not to
   expand the schema set.

2. **Explicit artifact classification, not filename-substring
   shortcuts.** D002. The current `if "signoff" in f.name else
   Audit` collapses three categories into two — replace with
   explicit dispatch on each.

3. **Upstream-coordinated, NOT local wrapper.** D003. agent-
   conventions is a shared dependency; the bug is generic; fix
   it at source.

4. **v1 known-auxiliary list = `gate-state.json` exactly.** D004.
   Single entry today. Extending the list later is a one-line
   change + test fixture.

5. **Unknown audit JSON → warn + skip, not error.** D005. Keeps
   the validator usable as new auxiliary names appear (e.g. if
   F006 circuit_breakers ever writes an `audit/breaker-state.json`)
   before the known-auxiliary list catches up.

6. **Two commits, explicit boundary: upstream patch first,
   subtree import second.** D006. Lets either side roll back
   independently without reverting unrelated work.

7. **agent-conventions semver = v1.3.1 (patch).** D007. No
   schema or model changes; bug-fix only.

## Execution path

**Direct, both features.** Locked at Plan-E lock turn (D009).
F001 is a deterministic logic change with greppable acceptance.
F002 is a mechanical subtree pull + regression run. No semantic
decisions for an auditor to debate. Volley quota unjustified for
either surface.

## Acceptance summary

Binding contract is in `features.json`. Highlights:

- **F001:**
  - Validator dispatches by explicit artifact type; filename-
    substring fallback removed.
  - 4-fixture test suite passes in agent-conventions: signoff,
    audit envelope, known auxiliary (`gate-state.json`), unknown
    audit JSON.
  - `VERSION` reads `1.3.1`.
  - No diff to any `schemas/v1.0/*.schema.json` file.
  - No diff to any `schemas/v1.0/models/*.py` file.
  - Tag `v1.3.1` in agent-conventions repo.

- **F002:**
  - `claude/shared/VERSION` reads `1.3.1` after subtree pull.
  - Validator run against each plan dir under `docs/plans/`
    with an `audit/` directory: zero false-fails on
    `gate-state.json` (8+ existing fixtures: Plans 001, 002,
    004, 005, B, C, plus 2026-04-29-001-feat-changelog-skill,
    2026-05-02-001-feat-resume-gate-discipline).
  - Real audit envelopes (`claude-implementer-*.json`,
    `codex-auditor-*.json`) still validate green where they
    were green pre-pull.
  - Real signoffs still validate green where they were green
    pre-pull.
  - DontPanic working-tree diff confined to `claude/shared/**`
    + the new plan-E directory. No diffs to historical plan
    directories.

## Two-commit boundary

| Commit | Repo | Scope |
|---|---|---|
| 1 | agent-conventions | F001: validate.py + 4 test fixtures + VERSION bump + tag v1.3.1 |
| 2 | DontPanic | F002: subtree pull + Plan E close-out memo |

Each commit's diff is independently reviewable. Either side can
roll back without dragging the other.

## Queued — NOT addressed by Plan E

Three caveats remain queued, each as a future standalone slice:

1. Per-plan `loop_caps.subprocess_timeout_seconds` (Plan C D003).
2. `jarvis_orchestrate` shim removal timeline (Plan A D006).
3. Real `gate-state.schema.json` if shape stability warrants it
   (deferred per D001 — v1 skips by name; v2 may validate).
