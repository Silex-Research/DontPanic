# North star

Date: 2026-08-12
Status: recommendation (rewritten — previous version was a framework, not a product)
Companions: `2026-08-12-future-readme.md`

## The sentence

**The agent can be right about the code and wrong about the product. DontPanic will not lock — or close — until you name the outcome, the slices that deliver it, and the proof for each.**

Rival review stays. It is how we catch a bad patch. This is how we catch a good patch for the wrong thing.

## Why the last version failed

It described DontPanic as eight platform capabilities and three operating modes. That is our architecture. Nobody opens a README for our architecture.

What a builder needs is one rule that applies to **their** plan — a checkout fix, a new app, a parity catch-up — without filling out a grant.

## The rule (every locked plan)

At lock, every plan is scored on three things. **In part or in whole**, depending on the size of the work.

| Ask | Meaning | A fix | A new product |
|---|---|---|---|
| **Outcome** | What becomes true, for whom | Inherit the parent. Add a one-line delta. | Must be explicit. No lock without it. |
| **Slices** | MECE capabilities that deliver that outcome | Usually one. “This is the slice; the rest is untouched.” | The full set. Overlap or a missing necessary slice is a sufficiency miss. |
| **Proof** | First-principle metric per slice — the cheapest measurement that would falsify “this landed” | One walk, one request, one named test | One proof per slice. Cheap by default. |

That is the contract. Features, audits, and gates hang off it. They are not a substitute for it.

`delivers[]` already names audience + capability + which features prove it. What it does **not** yet require is a **metric**: the measurement that would show the capability is actually true. That is the gap. Close still grades feature `passes` and heuristic evidence strings. It should grade the proofs.

## Cheap on purpose

If this is a form, we failed.

**Inherit.** A child, a fix, a follow-up starts from the parent’s outcome and slices. You only write the delta.

**Infer.** A PRD, issue, Figma, or repo should produce a *draft* contract. The builder confirms or edits. They do not compose from a blank schema.

**Minimum by size.**

| Work | What lock requires | What can wait |
|---|---|---|
| Trivial / mechanical | One sentence outcome (or `audience: none`) + one cheap proof | Journeys, extra slices |
| Local fix / incident | Inherited outcome + one slice + one proof | Full MECE of the product |
| Add a capability | Place the slice on the existing outcome. Show it doesn’t overlap. One new proof. | Re-deriving the whole product |
| New feature / parity / migration | Outcome + MECE slices + one proof each | High-fi design, analytics pipelines |

**Block on almost nothing.** Missing outcome → cannot lock. Everything else is a gap you can accept: “prove at close,” “overlap accepted,” “slice deferred.” Accepted gaps become close checks, not homework.

**Proofs are cheap.** The first-principle metric is the smallest thing that would prove you wrong:

- User-facing slice → walk the path on the target surface
- API slice → one request that must succeed
- Infra slice → named test or doctor probe
- `audience: none` → the probe that shows nothing user-facing broke

You do not need a warehouse, a dashboard, or a KPI committee. If the proof takes longer to define than the work, the proof is wrong.

**Do not write it twice.** Features map onto slices (`proof_refs`). If the draft inferred three slices from your brief, you do not also hand-author a parallel essay.

**Do not ask twice.** If the last plan on this repo already has the outcome, the next one starts there.

## How we ask (not a second product)

Same contract. Different amount of talking.

- You paste a feeling → we ask for the outcome, then stop.
- You paste a PRD → we show a draft contract and the two holes. Yes / edit.
- You paste a plan directory that already has `delivers[]` → we only ask for missing proofs, or we infer “walk the acceptance path.”
- You are fixing F014 on a parent that already locked → we inherit. You never see the interview.

Handholding and transparency follow that, not a mode switcher the user has to pick.

## What “assessed at lock” means

Sufficiency is a **score against this contract**, not a vibe and not a 20-field validator.

```
outcome     present | inherited | missing
slices      mece | overlap | missing-necessary | n/a (single-slice)
proofs      one-per-slice | inferred | accepted-gap | missing
```

Lock is allowed when `outcome` is present or inherited. The rest prints as a short report. Close fails any proof that was not accepted as a gap and did not run.

That is the whole ceremony. Rival implement/audit still runs. Experience still has to be walked if the slice is user-facing. Design still happens in Claude Design / Figma / a human — DontPanic only refuses to pretend the experience was specified if the proof needs it.

## What we refuse to become

A wizard. A second IDE. A design tool. A metrics platform.

If using DontPanic feels like more work than the change, the contract is too fat. Shrink the contract. Do not add a skip button that throws the outcome away.

Executable plan: `docs/plans/2026-08-13-001-feat-lock-outcome-slices-proof/` (draft).
Trust-increment sibling: `docs/plans/2026-08-12-001-infra-admitted-state-and-process-behaviors/`.

## What this changes in the schema (later, small)

- Each `delivers[]` item gains an optional `proof`: `{metric, method, surface?}`. Required to *close* user-facing work; at lock it may be inferred or accepted as a gap.
- Sufficiency reads this contract instead of only “is there a completion_test string.”
- Child/fix plans may set `inherits: <plan-id>` and only declare a delta slice.
- Trivial plans keep the lite path: one `delivers` or `audience: none` + one proof.

No eight-capability platform model in the user’s face. No new intake novel.

## Compelling test

If a stranger reads one paragraph and knows why they’d use this instead of Claude Code alone, it works:

> Claude Code will write the patch. DontPanic makes you say what capability that patch was for, and what would prove it landed — then a different model checks the work, and close fails if the proof never ran. A typo fix inherits the last outcome and adds one probe. A new product has to name the slices. You do not fill out a spec you don’t need.

If they still hear “framework,” rewrite again.
