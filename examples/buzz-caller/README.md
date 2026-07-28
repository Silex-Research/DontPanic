# Buzz-as-caller: thin skill recipe (dontpanic-delivery)

This is the committed, operator-followable version of the
[ECOSYSTEM § Buzz-as-caller sketch](../../docs/ECOSYSTEM.md#concrete-integration-recipe-buzz-as-caller-sketch)
(plan `2026-07-27-001` F007). It documents the **full confirm-gated flow**
for driving DontPanic *from* a Buzz workspace: a thin Buzz agent/workflow
that discovers the local DontPanic install, previews a plan, waits for an
explicit human approval, dispatches, polls status, and surfaces gate
pauses back into the room. You should be able to follow it without
reading the orchestrator source.

> **THE safety rule (load-bearing, non-negotiable):**
> **Never auto-confirm.** Always surface the plan to the user before
> calling `dispatch(confirm=true)`. `dispatch(confirm=true)` and
> `approve_gate(confirm=true)` require explicit, allowlisted **human**
> intent every single time. Message reactions, emoji, chat text
> heuristics, timeouts, and retries never count as approval.

## Division of labor

```text
Buzz       =  where humans + agents sit and approve (rooms, keypairs, channels)
DontPanic  =  plan lock, volley, evidence, gates, signoff (local delivery)
```

DontPanic ships nothing on the Buzz runtime — no SDK, no embedded
library, no relay client. The Buzz side is a thin agent/workflow
(`buzz-cli` speaks JSON) that either shells out to the `dontpanic` CLI or
connects as an MCP client. This recipe uses the MCP surface; every tool
has a CLI equivalent noted below.

## Prerequisites

1. A local DontPanic install with the agent manifest present:
   `~/.dontpanic/agent-manifest.json` (or run `dontpanic manifest show --json`),
   and the target repo **registered** (`dontpanic projects add <name> <path>`).
   The MCP server resolves `plan` arguments only inside registered projects'
   plans directories — there is no cwd fallback, and out-of-tree paths refuse.
2. A **private** Buzz community for your operator work (see
   [ECOSYSTEM § Community model](../../docs/ECOSYSTEM.md#community-model-private-by-default)
   and [GETTING_STARTED § Buzz setup](../../docs/GETTING_STARTED.md#buzz-strongly-recommended-private-community-setup)).
   Public communities are discovery/support only — never a work surface.
3. Optional but recommended: the F006 notify sink configured at
   `~/.dontpanic/buzz.json` (`relay_url`, `channels`, `reporter_key_ref`)
   so gate pauses are *pushed* into the room; this recipe still works
   without it by polling `status`.
4. The MCP server registered in the Buzz-side runtime that will make the
   tool calls:

   ```json
   {
     "mcpServers": {
       "dontpanic": {
         "command": "dontpanic",
         "args": ["mcp", "serve"]
       }
     }
   }
   ```

## MCP tool map

| Step | MCP tool | Args | Mutates? | CLI equivalent |
|---|---|---|---|---|
| Discover projects | `list_projects` | none | No | `dontpanic projects list` |
| Validate + preview plan | `validate_plan` | `plan` | No | `python3 claude/shared/schemas/v1.0/validate.py <plan-dir>` |
| Dry-run preview | `dispatch` | `plan`, `feature` (**no** `confirm`) | No — dry-run is the default | `dontpanic dispatch-from-plan <plan-id>` |
| Dispatch for real | `dispatch` | `plan`, `feature`, `confirm: true` (optional `implementer`, `auditor`, `max_iterations`, `mode`) | **Yes** | `dontpanic dispatch-from-plan <plan-id> --confirm` |
| Poll progress + gates | `status` | optional `plan` | No | `dontpanic status` |
| Clear a human gate | `approve_gate` | `plan`, `gate`, `confirm: true` | **Yes** | `dontpanic approve <plan-id> <gate>` |
| Read evidence for the room | `read_evidence` | `plan`, `file` | No | read `<plan-dir>/evidence/<file>` |

Both mutating tools (`dispatch`, `approve_gate`) default to dry-run and
return a structured `intent` payload; `confirm: true` is the only
mutation path. That default is the safety architecture — the thin skill
uses the dry-run output as its preview surface and never sets
`confirm: true` from anything other than a fresh, explicit human approval.

## The confirm-gated flow

An agent/workflow in the Buzz workspace named e.g. `dontpanic-delivery`:

1. **Discover.** Read `~/.dontpanic/agent-manifest.json` to find the
   `dontpanic` CLI / MCP entry point. Call `list_projects` to resolve the
   registered project and its plans directory. If the target repo is not
   listed, stop and ask the operator to register it — the skill never
   registers projects on its own.
2. **Validate.** Call `validate_plan {plan: "<plan-id-or-dir>"}`. On
   `valid: false`, post the error to the room and stop — never dispatch
   an invalid plan.
3. **Preview.** Call `dispatch {plan, feature}` **without** `confirm`.
   Post the returned intent into the private community channel: plan ID,
   tier, `target_env` / `target_project`, feature, implementer/auditor
   roles, and declared `human_gates` (`pre_impl`, `pre_merge`). This
   preview is what the human approves — nothing else.
4. **Wait for explicit human approval.** Approval must come from an
   allowlisted human operator key, as a deliberate action on the
   previewed intent (e.g. a signed "approve <plan-id> <feature>"
   message). Reactions/emoji never auto-confirm. No approval → no
   dispatch, ever; there is no timeout-to-yes.
5. **Dispatch.** Only after step 4, call the same `dispatch` again with
   `confirm: true`. Post the volley result summary (final status, rounds,
   audit paths) back to the room.
6. **Poll + surface gate pauses.** Poll `status {plan}` and post
   transitions. When `gate_status.paused` is true, post the unmet gate(s)
   to the gates channel (e.g. `#dontpanic-gates`) with a link to the
   plan's `INBOX.md` / evidence. If the F006 notify sink is configured,
   `gate_paused` events are also pushed to the room; treat the push as a
   prompt to re-poll `status`, not as state.
7. **Gate approval maps back to a human.** When an allowlisted human
   operator explicitly approves a paused gate, call
   `approve_gate {plan, gate, confirm: true}`. Same rule as step 4: the
   human action is the trigger; chat text and reactions never trigger it
   automatically. Use the dry-run (`confirm` omitted) to show
   `currently_cleared` / `would_clear` before asking.

That is the **whole** integration — the same shape as the OpenClaw
caller recipe, with Buzz channels as the approval room.

## Safety checklist

Identical to the OpenClaw caller recipe
([ECOSYSTEM § Safety rules for agent callers](../../docs/ECOSYSTEM.md#safety-rules-for-agent-callers));
run through it before enabling the skill:

- [ ] Treat DontPanic as a **human-gated delivery system**, not a
      background deploy button.
- [ ] **Always surface the plan to the user before calling
      `dispatch(confirm=true)`. Do NOT auto-confirm.**
- [ ] Use `validate_plan`, `status`, and dry-run `dispatch` output as the
      preview surface before asking for approval.
- [ ] Keep approval explicit: `dispatch(confirm=true)` and `approve_gate`
      are the points where the caller must have user intent — from an
      allowlisted human operator key, never inferred.
- [ ] Reactions, emoji, chat-text heuristics, timeouts, and retries never
      trigger `confirm: true`.
- [ ] Do not auto-lock, auto-dispatch, or auto-close plans without
      surfacing the decision to the user.
- [ ] No secrets on relays: posts carry projections only (summaries,
      hashes, gate links) — never API keys, home paths, raw audit JSON,
      or full transcripts. Default to the operator's **private**
      community; self-host the relay for high-sensitivity work.
- [ ] Do not store API keys in DontPanic config — role names, provider
      names, paths, or env-var names only (`reporter_key_ref` is a
      reference, never key material).
- [ ] Do not treat a single model's success message as signoff; DontPanic
      writes the audit, evidence, and gate artifacts.
- [ ] Buzz community membership is **not** authorization — the harness
      registry and role config remain the sole source of truth for who
      can be dispatched (see [Agent Capability Matrix](../../docs/AGENT_CAPABILITY_MATRIX.md)).

## Non-goals (locked)

Per [ECOSYSTEM § Buzz non-goals](../../docs/ECOSYSTEM.md#buzz-non-goals-locked):
no relay/Nostr client inside DontPanic, no forced join of
maintainer-owned communities, no auto-confirm from chat, no secrets on
relays. This recipe adds no Buzz-side state beyond the thin skill itself.

## Verification

A manual smoke checklist for this recipe (no live Buzz required) is
committed at
[`docs/plans/2026-07-27-001-feat-buzz-integration-agent-taxonomy/evidence/F007-manual-smoke-checklist.md`](../../docs/plans/2026-07-27-001-feat-buzz-integration-agent-taxonomy/evidence/F007-manual-smoke-checklist.md).
