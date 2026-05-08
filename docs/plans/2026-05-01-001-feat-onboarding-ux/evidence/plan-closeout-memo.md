# Plan 2026-05-01-001 close-out memo — onboarding UX (README "Run your first volley" + dispatch-from-plan CLI)

**Plan ID:** `2026-05-01-001-feat-onboarding-ux`
**Type:** `feat` · **Tier:** `local` · **agents:** `claude` + `codex`
**goal_type:** none declared (exempt-by-absence from F2 completion gate)
**Status flip:** `active` → `completed` on 2026-05-07 (UTC).

This memo synthesizes across F001 (README walkthrough) + F002 (`dispatch-from-plan` CLI) and records the platform/runtime classification of the volley terminal. The impl-time `evidence/f002/confirmation.md` is the F002-level evidence; this memo adds the plan-level cross-feature view + Q2 classification + brand drift note. Impl-time content is byte-untouched.

## Cross-feature outcome

| Feature | Path | Result |
|---|---|---|
| F001 — README "Run your first volley" + refreshed Setup checklist | Direct (per D003 lock) | `passes:true`. Walkthrough covers `quota-caps init` → `calibrate-claude` → `dispatch-from-plan` → INBOX → `approve`/`resume`. Verified live at README.md lines ~191–202 (canonical `dontpanic` command form) + line ~458 (Setup checklist) + line ~479 (CLI surface enumeration). |
| F002 — `dispatch-from-plan <plan-id>` CLI subcommand, strict dry-run unless `--confirm` | **Volley → Path 1 (manual cleanup + auditor-only confirmation)** | `passes:true` (operator-accepted). Volley terminated `stopped_diminishing_returns` at iteration 1; remediation via manual cleanup diff (`evidence/f002/manual-cleanup.diff`, 379 lines) addressed both i1 findings (ruff + help text). 11 ACs verified per `evidence/f002/confirmation.md`; 12 dispatch tests pass; full sweep 310/6 skipped (impl-time baseline). |

The two features land the calling pattern named in the plan thesis: an authored-plan operator can now run their first volley from README alone, with strict-dry-run preflight providing the 10-field context block before any actual dispatch is authorized.

## Q2 — terminal status classification (three layers, distinct)

This plan's terminal record carries three layers that classify differently and must not be conflated:

| Layer | What it is | Classification | Where it lives |
|---|---|---|---|
| 1. Volley breaker trip | `stopped_diminishing_returns` with auditor finding counts `[2, 3]` non-decreasing | **Platform artifact (since fixed)** | `audit/signoff-...json` (untracked) |
| 2. F002 / F001 implementation | 11 ACs verified by code reading + 12 dispatch tests + manual cleanup applied + 310/6 sweep | **Implementation result — clean** | `evidence/f002/confirmation.md` (tracked) + this memo |
| 3. Auditor-only i2 HIGH finding | Auditor's OWN summary header missing target-context prelude (F023 EC5 self-finding) | **META platform artifact (queued)** | `audit/claude-auditor-i2.json` (untracked) → D009 |

**Layer 1 is the now-fixed count-based breaker pattern.** The volley produced 2 findings at i0 then 3 different findings at i1 — disjoint signatures, legitimate volley-improvement shape. The OLD count-only breaker tripped because cardinality was non-decreasing. The signature-based breaker shipped by Plan 2026-05-02-004 (closed `5a0979b`) would NOT have tripped on this same envelope pair: the F002 confirmation memo's i0/i1 findings are disjoint, so signature-set intersection is empty, and the breaker would have allowed an i2 implementer pass. **This is concrete evidence that closing 2026-05-02-004 retroactively reclassifies this plan's volley terminal as the false-positive shape it was always was — but does not require re-running the volley to validate F002. The implementation evidence already cleared 11 of 11 ACs.**

**Layer 3 is a META concern recorded as D009.** The auditor-only i2 verdict (`audit_status: blocked`, one HIGH finding) names the auditor's own prompt template — its summary header lacked the `Repo: / Env: / Project: / Command:` target-context prelude that F023 EC5 requires before logged side-effect commands. The auditor flagged its own output. This is a prompt-template bug, not an F002 code defect. Closing this plan does NOT close that META concern; D009 stays queued.

**Layer 2 — the implementation — is what this close-out actually closes.**

## Onboarding-Q verification (operator-named)

> Does the shipped onboarding UX document and command surface match the actual current CLI behavior, without promising flows that are still draft, gated, or dependent on unclosed plans?

**Answer: yes.** Verified live this turn:

- README "Run your first volley" section exists at lines 191–202 with the locked walkthrough sequence: `dontpanic quota-caps init` → `dontpanic dispatch-from-plan <plan-id>` (dry-run preflight) → `dontpanic dispatch-from-plan <plan-id> --confirm` (actual dispatch).
- Setup checklist refreshed at line 458 enumerating supervisor maturity (F004/F005a/F006/F008/F023) + vendor-native quota tracker.
- `dontpanic dispatch-from-plan --help` rendering matches the F002 acceptance contract: `--feature`, `--implementer`, `--auditor`, `--max-iterations`, `--mode {interactive,autonomous}`, `--confirm` flags all present.
- **D006 deferral honored**: no `--ask` flag in shipped CLI surface (deferred per D006).
- **Out-of-scope items not promised**: zero hits in README for "Discord", "OpenRouter", "synthetic user", "stakeholder API". Plan B (Discord), Plan C (intake), and other future surfaces are not claimed as available.
- All commands shown in README map to existing CLI subcommands. The walkthrough is executable as written.

## Brand-rename drift note

This plan was authored 2026-05-01, **before** the canonical-module flip shipped at `8edd953` (Plan 2026-05-04-001, closed `ab7c7dc`). Therefore:

- **In-plan text** (plan.md, features.json, decisions, F002 confirmation memo) uses the legacy `python -m jarvis_orchestrate` invocation form. F001 acceptance #2 specifically says "Each command shown matches `python -m jarvis_orchestrate <subcommand> --help` output verbatim" — that was the canonical form at lock time.
- **Live README** (currently on disk) uses the post-rename canonical `dontpanic <subcommand>` form. The legacy `python -m jarvis_orchestrate` shim still works (with a one-shot `DeprecationWarning`), so the historical AC remains satisfied — just via the shim that re-exports from `dontpanic_orchestrate`.
- This is the same drift pattern that Plan 2026-05-05-001 (validator dispatch) recorded for `claude/shared/VERSION` (1.3.1 → 1.4.0): historical AC text intentionally NOT retro-updated; live state runs canonical; both forms remain valid.

Future readers comparing the README content (canonical `dontpanic`) to F001 acceptance #2 (legacy `python -m jarvis_orchestrate`) should expect that mismatch as expected drift forward, not a regression.

## Audit/INBOX disposition — intentionally untracked per F002 confirmation memo

The plan dir's `audit/` subtree (8 audit JSONs + transcript.md + gate-state.json) and `INBOX.md` are present in the worktree but **not tracked in HEAD**. This is intentional.

The 2026-05-01 F002 confirmation memo (impl-time, line 28+ of `evidence/f002/confirmation.md`) explicitly says:

> Items intentionally NOT staged with this commit:
> - `audit/gate-state.json` — gate-clearance state, not durable F002 evidence; mutates on every dispatch.
> - `audit/signoff-...json` — currently records `signoff: false, next_action: remediate` from the volley terminal. Conflicts with `passes: true` and will confuse future readers/tools.
> - The volley audit JSONs ... and `transcript.md` / `INBOX.md` similarly belong to dispatch state, not durable evidence.
> - If we want to archive the dispatch trace, do it under `evidence/f002/pre-remediation/` in a follow-up commit.

Honoring that guidance at this status-flip close-out: artifacts remain untracked. Future readers should treat the worktree-only audit/* files as **dispatch trace from the original volley, not durable acceptance evidence**. The acceptance evidence is in `evidence/f002/{confirmation.md, dispatch-from-plan-help.txt, manual-cleanup.diff}` (tracked).

The validator currently runs the worktree audit/* files green (since they validate against the schema in isolation, and the signature-based breaker would no longer trip). That green output is **not the close-out claim**; the close-out claim is the F002 confirmation memo + this plan-level memo.

If a future operator wants to archive the dispatch trace under `evidence/f002/pre-remediation/`, that is a separate commit per the F002 memo's deferred suggestion.

## What this plan does NOT solve

Per scope discipline + queued decisions:

- **D006 — `--ask` interactive flag** — explicitly deferred. Dry-run + `--confirm` is the v1 surface; `--ask` y/N prompt mode may layer on later if CLI ergonomics warrant it.
- **D008 — single-agent `--role auditor` cross-vendor invariant** — defaults to `agents_required[0]`, which broke the cross-vendor adversarial invariant for the i2 auditor-only confirmation (Claude graded Claude). Invariant only holds in `--volley` mode today. Queued as a Jarvis CLI improvement so `--role auditor` defaults to `agents_required[1]`. **NOT closed by this plan.**
- **D009 — F023 EC5 auditor-prompt prelude missing** — the auditor prompt template should auto-prepend `Repo: / Env: / Project: / Command:` before logged side-effects, just like the implementer template does. Both codex-i1 and claude-i2 produced the same self-finding. **NOT closed by this plan; queued as separate auditor-prompt-template fix.**
- **Discord integration (Plan B)**, **Plan-artifacts auto-dispatch**, **README translations**, **expanded CONTRIBUTING/COC content** — all explicitly out of scope per plan.md "Out of scope" section. None are claimed in shipped README.

## Cross-link to closed plans

- **2026-05-04-001 canonical-module flip** (closed `ab7c7dc`) — the rename that caused the brand drift between this plan's AC text and the live README.
- **2026-04-30-001 vendor-native quota tracker** (closed `7acb5c6`) — declared dependency; the `quota-caps init` and `calibrate-claude` steps in the README walkthrough rely on this plan's per-vendor signal extraction.
- **2026-05-02-004 signature-based diminishing-returns** (closed `5a0979b`) — retroactively reclassifies this plan's volley terminal `[2, 3]` as the false-positive shape (disjoint findings of similar count). Does NOT require re-running the volley; F002 implementation evidence already verified all 11 ACs.

## Outer plan close — exempt-flow path

```
$ dontpanic plan close docs/plans/2026-05-01-001-feat-onboarding-ux/
[plan close] goal_type=None is exempt from the F2 completion gate;
             status flipped active → completed without audit
```

Same exempt-flow path as the prior nine close-outs in this session.

## Sign-off

Plan 2026-05-01-001 ships clean. F001 + F002 both `passes:true`. README "Run your first volley" walkthrough is live with canonical `dontpanic` commands; `dispatch-from-plan` CLI subcommand ships strict-dry-run-by-default with the locked 10-field preflight + `--confirm` requirement. The volley terminal was a now-fixed count-based-breaker false-positive (signature-based breaker shipped by 2026-05-02-004 reclassifies it). Auditor-only i2 HIGH finding was a META auditor-prompt-template self-finding queued in D009, not an F002 code defect. D006 (`--ask` flag), D008 (cross-vendor `--role auditor` invariant), D009 (F023 EC5 auditor-prompt prelude) all remain queued — explicitly NOT closed by this plan.

— bayesian, 2026-05-07 UTC
