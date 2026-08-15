# DontPanic — future-state README (draft)

> Not the live GitHub README. The north-star front page.
> Recommendation: `docs/brainstorms/2026-08-12-north-star.md`.

---

# DontPanic

> The agent can be right about the code and wrong about the product.

One model builds. A different vendor reviews it. Before any of that,
DontPanic makes you name **what capability this was for** and **what
would prove it landed**. Close fails if that proof never ran.

A typo fix inherits the last outcome and adds one probe. A new product
has to name the slices. You never fill out a spec you don’t need.

Local-first. Multi-vendor. Nothing leaves your machine unless you send it.

**Never let the same AI that wrote the code be the only one that says
the capability exists.**

## The failure

AI coding agents will:

- ship a correct patch for a capability nobody named
- mark a journey done because the unit tests are green
- review their own work and agree
- spend a day on a plan that never said what “done” is

Claude Code, Codex, Cursor, Replit make generation cheap. They do not
ask what the work was *for*. They do not notice two features are the
same slice. They do not require a measurement that would prove you
wrong. They do not make a second model family look.

## The rule

**Every locked plan names an outcome, the slices that deliver it, and
the proof for each — in part or in whole.**

| | What it is | Small change | New product |
|---|---|---|---|
| **Outcome** | What becomes true, for whom | Inherit. One-line delta. | Required. No outcome, no lock. |
| **Slices** | Capabilities that compose it. Necessary, no overlap. | Usually one: “this, nothing else.” | The set. Overlap or a hole is a miss. |
| **Proof** | Cheapest measurement that would falsify “this landed” | One walk, one request, one named test | One per slice |

That is the whole contract. Features hang off slices. Audits hang off
features. Gates hang off risk. None of them replace the contract.

You can start from a feeling, a PRD, a Figma, a repo, “add this,” or
“fix that.” DontPanic drafts the contract from what you already have.
You confirm. You do not compose a blank schema.

## It stays light

If this feels like a form, we failed.

- **Inherit.** Fixes and children start from the parent. You write the delta.
- **Infer.** A brief or a repo produces a draft. Yes / edit — not a wizard.
- **Block on one thing.** No outcome (and nothing to inherit) → cannot lock. Missing proofs and messy slices are gaps you can accept and pay at close.
- **Proofs are cheap.** Walk the path. Hit the endpoint. Run the named test. If defining the proof is harder than the work, the proof is wrong.
- **Write once.** Features map to slices. We do not ask for the essay and the ticket.

Design still happens in Claude Design, Figma, or a human. DontPanic
does not open a canvas. It will not lock user-facing work that has no
way to *prove* the path, and it will not close if that path was never
walked.

## Why not just the harness

A harness writes code. DontPanic holds the reason the code exists.

Same-vendor swarms are faster and share one blind spot. DontPanic is
the layer on top: outcome first, a different family on the audit, a
human only when the risk is real, close that can fail after a “green”
patch.

## See it

```text
$ dontpanic intake "people drop checkout when they add a bag"

Outcome:  a shopper can add a bag and still pay
Slice:    add-bag → pay
Proof:    walk that path on ios staging
Inherited from: (none — new)
Gaps:     none required. Design is your call.

$ dontpanic lock
Locked.

$ dontpanic dispatch --confirm
Implementer: Claude
Auditor:     Codex
…
Gate: Codex could not complete pay-after-add-bag.
      Proof failed. Waiting for you.
```

A one-line fix looks like this instead:

```text
$ dontpanic intake --fix "revoke session 500s on staging"

Inherited: operators can revoke a session without a build
Slice:     revoke returns 2xx
Proof:     curl the revoke on staging
```

No interview. No second outcome. The parent already paid for that.

## Start

Python 3.10+, git, one local agent CLI to dispatch. No plan directory
required.

```bash
pip install -e ".[dev]"
dontpanic setup --implementer claude --auditor codex --yes
dontpanic projects add myapp .
dontpanic intake
```

`intake` with nothing pasted starts a short placement. A file, a URL,
`--fix`, or `--add` skips the questions we can already answer.

Already have a plan? `dontpanic lock` scores it against the contract
and tells you the one thing that would block. `dispatch --confirm`
still requires you to see the outcome first.

## What you get

| | |
|---|---|
| Start from anything | `dontpanic intake` |
| See if you may spend | `dontpanic lock` — scores outcome / slices / proofs |
| Cheapest next proof | `dontpanic next` |
| Build + rival review | `dontpanic dispatch --confirm` |
| Close only on proof | `dontpanic close` |

The dashboard still *shows*. It does not pretend to be the product.
Firebase, Discord, Linear, OpenClaw, Figma are opt-in.

**Always surface the outcome before `confirm=true`. Do not auto-confirm.
Do not lock with no outcome and nothing to inherit.**

## Not this

Not an IDE. Not a canvas. Not a chat OS. Not a metrics platform.
Not a spec you fill in for a typo.

## License

Apache-2.0.
