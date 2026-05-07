# Plan 2026-05-04-001 close-out memo — canonical-module flip

**Plan ID:** `2026-05-04-001-refactor-canonical-dontpanic-module`
**Type:** `refactor` (exempt from F2 completion gate)
**Status flip:** `active` → `completed` on 2026-05-07 (UTC).
**Outcome:** Clean close. Canonical Python module is now `dontpanic_orchestrate`; `jarvis_orchestrate` remains a thin compatibility shim that re-exports from canonical and emits a one-shot `DeprecationWarning` per process.

## What this plan delivered

The brand-rename refactor that flipped the implementation direction. Pre-plan: canonical module was `jarvis_orchestrate`, with `dontpanic_orchestrate/` as a thin alias re-exporting `__version__` and running `jarvis_orchestrate.cli.main`. Post-plan: those roles are reversed, and every subsequent platform-fix slice anchors on the canonical name.

This was the lead slice for the four queued platform fixes:

1. **2026-05-04-001 (this plan)** — canonical module flip ✓
2. **2026-05-04-002** — lifecycle-staged human-gate evaluation (1/1 pass; awaiting close-out, validation-debt repair needed first)
3. **2026-05-04-003** — subprocess timeout / envelope durability (3/3 pass; close-ready)
4. **2026-05-04-004** — EC5 classifier purity (1/1 pass; close-ready)

Subsequent slices anchor on `dontpanic_orchestrate` from day zero, no rebase against the rename.

## Acceptance — F001

All 11 locked acceptance criteria met (per features.json + f001-closeout-memo.md). Highlights:

- `from dontpanic_orchestrate import cli` and every other submodule import works without warnings.
- `from jarvis_orchestrate import cli` and every other legacy submodule import works AND emits exactly one `DeprecationWarning` per process via the shim's `__getattr__` lazy-relay.
- Console-script entrypoint `dontpanic-orchestrate` resolves to the canonical module.
- Packaging metadata (`pyproject.toml`, `setup.cfg`) lists canonical name; legacy name retained as a transitional alias.
- Live operator-facing docs (README, CLAUDE.md, GETTING_STARTED) updated to reference canonical name.
- **Historical plan folders, evidence strings, and committed audit envelopes were NOT renamed** — those are durable records (D004 boundary).
- AC #11 (added pre-lock per D007): no shim-side relay through `__getattr__` for sub-submodules; the deprecation warning fires exactly once at top-level shim import, then re-export proceeds without re-emission for downstream attribute lookups.

Per-feature evidence + verification numbers in `evidence/f001-closeout-memo.md` (the F001-level artifact, complementary to this plan-level memo).

## Verification numbers (post-ship, pre-close)

| Check | Result |
| --- | --- |
| Plan dir validates against agent-conventions v1.0 schemas | ✓ |
| F001 features.json | `passes:true` |
| Ship commit | `8edd953 refactor(jarvis): flip canonical Python module to dontpanic_orchestrate` |
| Cumulative orchestrate suite at ship time | green (per F001 close-out memo) |
| Worktree boundary at ship time | scoped to `scripts/jarvis_orchestrate/` ↔ `scripts/dontpanic_orchestrate/` move + packaging metadata + README/CLAUDE.md updates |
| Historical artifacts preserved (D004 boundary) | ✓ — no rename of `Jarvis/scripts/jarvis_orchestrate/` references in older plan dirs / decisions / audit envelopes |
| Documentation drift in OTHER plans noted but not chased | acceptable; doc-level legacy references are historical narrative |

## Cited commits

| Commit | Description |
|---|---|
| `8edd953` | F001 ship — canonical Python module flip (`jarvis_orchestrate` → `dontpanic_orchestrate`) |
| _(this commit)_ | Plan close-out — plan-closeout-memo + D008 + status flip via exempt-plan flow |

## Per-feature decisions (D001–D007 from lock cycle)

D001–D006: scoping decisions during draft (canonical module choice, shim relay strategy, console-script flip, packaging metadata, historical artifact preservation, doc drift policy).
D007: pre-lock tightening — AC #11 added (no shim relay through `__getattr__` for sub-submodules; one-shot deprecation only).
D008 *(this commit)*: plan-level close-out record.

## Outer plan close — exempt-plan flow

The plan does not declare a `goal_type`, so the F2 completion gate is a no-op (`goal_type=None` is exempt from the gated set); the status flip still proceeds via the exempt path:

```
$ dontpanic plan close docs/plans/2026-05-04-001-refactor-canonical-dontpanic-module/ --dry-run
[plan close] plan_dir=docs/plans/2026-05-04-001-refactor-canonical-dontpanic-module (dry-run)
[plan close] goal_type=None is exempt from the F2 completion gate;
             --dry-run would flip status active → completed
$ echo $? → 0
```

Same path used to close F2, Plan 003, the parser plan (2026-05-07-001), and the fair-fixture re-run (2026-05-07-002): in those cases `goal_type=infra` consumed the gate's exempt-by-listed-type branch; here `goal_type=None` (no goal-governance classification) consumes the exempt-by-absence branch. Both paths land identically on the status flip.

## Pattern-setter status

This is the first plan close-out in a tightened-discipline batch following the partial-clone worktree-damage lessons from the Goal Governance V1 sequence and operator-corrected close-out hygiene rules. Pattern established:

1. Validate plan dir exits 0.
2. Write `evidence/plan-closeout-memo.md` (this file) — plan-level summary, complementary to per-feature memos already in `evidence/`.
3. Append plan-level close-out D-entry to `decisions.jsonl`.
4. Run `dontpanic plan close <plan-dir>` for status flip via exempt-flow.
5. Re-validate (validator should still exit 0).
6. Commit only this plan dir.

Subsequent Tier 1 close-outs follow the same pattern. Each plan gets its own plan-local memo + D-entry; multi-plan commits permitted, but artifacts stay per-plan (no combined memos).

## Sign-off

I (bayesian, operator) confirm: Plan 2026-05-04-001 ships clean. Canonical Python module is now `dontpanic_orchestrate`; legacy `jarvis_orchestrate` remains as a thin compatibility shim with one-shot deprecation warning. Subsequent platform-fix slices anchor on the canonical name from day zero.

— bayesian, 2026-05-07 UTC
