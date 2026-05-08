# Plan close-out memo - 2026-05-08

Plan: `2026-05-04-002-fix-supervisor-lifecycle-staged-gates`

## Status-flip context

F001 is already `passes:true` and the implementation evidence lives in `evidence/f001-closeout-memo.md`. This plan is being closed as part of the DontPanic plan-alignment cleanup after the follow-up plans it pointed at have also landed:

- Plan C, `2026-05-04-003-fix-subprocess-timeout-envelope-durability`, closed the 600s timeout / timeout-with-work classifier caveat.
- Plan D, `2026-05-04-004-fix-ec5-classifier-purity`, closed the EC5 purity caveat that older verification sweeps excluded.
- Plan E, `2026-05-05-001-fix-plan-validator-audit-auxiliary-json`, fixed the validator's `gate-state.json` false-fail behavior. This close-out separately repairs this plan's legacy string-shaped `evidence_refs`.

## Validation repair

Preflight validation failed on `features.json` because F001's first five `evidence_refs` were legacy strings, not v1.0 `EvidenceRef` objects. The repair is schema-conformance only:

- The same ten URIs remain present.
- Audit-envelope and signoff artifacts are now typed as `audit_json`.
- Transcript and close-out memo artifacts are typed as `log`.
- Test files are typed as `file`.
- No acceptance text, pass status, verification timestamp, or evidence content changed.

This mirrors the Plan 005 D016 repair discipline: surface the validator failure, apply the narrow local repair, document the reason, and do not broaden into an all-plans schema-debt sweep inside the close-out commit.

## Lifecycle boundary

| Boundary | Closed by this plan | Not claimed |
|---|---|---|
| Human gates | `pre_impl` evaluates before implementation; `pre_merge` evaluates only on candidate-success before writing `passes:true`. | New stages such as `pre_audit` or `post_merge`. |
| Failure evidence | Non-success terminals write failure evidence without consulting `pre_merge`. | `pre_merge` as a generic merge-approval gate for failed runs. |
| Breakers | Breaker timing is unchanged; `circuit_breakers.py` remained untouched for this plan. | Lifecycle staging for `breaker:*` gates. |
| Resume discipline | Bare `dontpanic resume <plan>` remains an explicit usage error; named `approve`, `resume --gate`, and `resume --all` are the clearance surfaces. | Any bare-resume auto-walk through lifecycle. |
| Compatibility | Legacy `cleared_gates`-only state is treated as already cleared for in-flight plans. | Historical migration of old gate-state files. |

## Cross-plan citations

The plan is cited by several later records as the owner of lifecycle-staged human gates. Closing it resolves the earlier Phase A caveat that `pre_merge` was being cleared upfront, and it makes the abandoned `2026-04-29-003-fix-f008-phased-gates` disposition coherent: that older plan is superseded by this one.

The close-out does not rewrite those dependent plans. Their historical memos remain accurate records of what was open at the time; this plan is the owning close-out record.

## Terminal classification

The original volley terminal was `stopped_no_progress` with a non-success signoff envelope. That terminal is a platform-runtime artifact of the pre-Plan-C timeout/envelope behavior, not the final implementation verdict. D012 accepted the work on direct review after operator-machine verification, and the subsequent Plan C close-out explains the timeout-with-work class more precisely.

This status flip therefore closes the plan on implementation evidence, not on the historical volley terminal.
