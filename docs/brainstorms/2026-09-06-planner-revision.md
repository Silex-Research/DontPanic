# Opt-in revision of an existing plan — proposed design

Status: design only. General brief-to-plan Phase C intake remains abandoned.
The existing design volley supports an optional planner, but production lock
supplies only the auditor. No planner executor or feature rewrite is introduced
by this document.

## Recommended flow: propose, inspect, then apply
1. An explicit revision command selects an existing plan and configured planner
   worker. No inferred role, automatic fallback or implicit paid call.
2. Snapshot the complete original contract and its digest. Run at most two
   auditor/planner rounds within configured invocation, token/cost and wall-time
   bounds. Stop on exhausted/unknown enforceability rather than promising a
   dollar cap the subscription harness cannot measure.
3. Validate proposed features against schema, unique IDs, dependency DAG, scope
   and feature sizing. The planner cannot assert passes=true, author reviewer
   evidence, grant approvals, change reserved decisions, widen target paths or
   raise budgets. Return invalid proposals as findings.
4. Persist proposal, original digest, structured diff, estimated impact, raw
   redacted transcripts, stop reason and validation result in a unique revision
   directory. Preview never modifies the live plan or approval state.
5. A separate explicitly authorized apply operation compares the original digest
   again, refuses concurrent edits, applies the reviewed proposal and invalidates
   approvals/evidence that no longer match the contract. Default conservatively
   to re-locking and re-audit for scope or acceptance changes.
6. Use an append-only application journal and recovery marker so a crash cannot
   leave revised features with apparently valid old approvals. Rollback restores
   contract files, but cannot recreate prior approvals without their original
   matching digest. Append a decision describing exactly what changed.

## Alternatives
Direct in-place edits inside plan lock are shorter to implement but harder to
review, recover and bound. Keep them out of v0. An operator editing a proposal
manually remains supported through existing plan authoring and scope review.

## Acceptance before implementation can count as delivered
Drive the public proposal/apply paths with synthetic executors and assert:
no paid execution without explicit authorization; schema-invalid/cyclic/duplicate
or scope-widening output refused; no preview mutation; bounded rounds and stop
behavior; current diff shown; stale-base refusal; deterministic approval
invalidation; crash recovery; no forged pass/signoff; and revision history
surviving a new process. Then record one separately authorized live planner run
with its actual cost/usage and independent review. Mocked volley tests alone
cannot close the integration claim.
