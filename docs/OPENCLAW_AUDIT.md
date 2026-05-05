# OpenClaw Audit — V1

> Bounded capability check against the seven questions in `GOAL_GOVERNANCE_V1.md` §8. Output: comparison table + recommendation section. Not a product teardown.
>
> **Source:** OpenClaw README at `https://github.com/openclaw/openclaw` (fetched 2026-05-05).
> **Methodology:** single-pass README extraction. Per-question evidence cites README text or marks "not addressed."
> **Scope limit:** does not include OpenClaw's deeper docs (skill registry, A2UI spec, control-plane internals). Deeper reads only if a "partial" cell turns out to gate a Plan H / F0 decision; flagged in §5 below.

---

## 1. OpenClaw positioning (per README)

> "A personal AI assistant you run on your own devices. It answers you on the channels you already use."

**Main components:** local-first Gateway (control plane), multi-channel inbox (20+ messaging platforms), multi-agent routing (isolated agents via workspaces), voice + companion apps, Live Canvas / A2UI, Skills registry (ClawHub).

**Explicit non-goals / boundaries from README:**
- "Treat inbound DMs as untrusted input" — single-user-default security posture; not designed for open multi-user systems.
- Sandboxing (`agents.defaults.sandbox.mode: "non-main"`) required for non-primary sessions.
- Not a general application hosting platform — focus is personal-assistant-on-existing-channels.

This is consistent with the `PLATFORM.md` / `PRODUCT.md` positioning that DontPanic is *called by* OpenClaw, not a competitor or substitute.

---

## 2. Capability comparison

| § | Capability | OpenClaw status | Lands in |
|---|---|---|---|
| 8.1 | Human routing across multiple DontPanic instances | **not provided** | DontPanic / Plan H |
| 8.2 | Discord / approval surface | **partial** (Discord is a channel; no approval workflow) | DontPanic ships sink (`2026-05-01-002`); OpenClaw optionally one routing endpoint |
| 8.3 | Cross-instance coordination | **not addressed** | DontPanic / Plan H or new plan |
| 8.4 | Agent task discovery (DontPanic gates → other agents) | **partial** (`sessions_list` etc. exist; not DontPanic-aware) | DontPanic CLI/MCP already exposes this directly; no OpenClaw dependency |
| 8.5 | Dashboard / status (plan/volley/signoff state) | **partial** (Live Canvas + Control UI exist; not plan-aware) | DontPanic / Plan H |
| 8.6 | Remote execution | **partial** (Tailscale + companion apps; can invoke CLI) | OpenClaw can be a *caller*; DontPanic ships no daemon |
| 8.7 | MCP tool calling | **partial** (MCP Registry exists; brokering across agents not detailed) | DontPanic exposes MCP via `dontpanic mcp serve`; OpenClaw can consume it as one client of many |

---

## 3. Per-question evidence

**8.1 Human routing across instances** — README discusses DM pairing/allowlisting for inbound message security. No mechanism for routing notifications across N DontPanic instances. **Not OpenClaw's job by design.**

**8.2 Discord / approval surface** — Discord listed in supported channel set; Discord tools mentioned. No explicit approval workflow ("operator approves a gate via Discord reply") documented in the README. The Discord *transport* exists; the approval *protocol* would need to be DontPanic-side. Aligns with `2026-05-01-002-feat-discord-notification-sink` as already drafted.

**8.3 Cross-instance coordination** — README does not mention coordination across separate agent invocations. Single-user assistant model assumes one instance per user / device.

**8.4 Agent task discovery** — `sessions_list`, `sessions_history` tools exist for OpenClaw's *own* sessions. Nothing about exposing pending DontPanic gates / INBOX items to external agents. Existing DontPanic `dontpanic ps` + INBOX files + MCP surface already solve this directly without OpenClaw mediation.

**8.5 Dashboard / status** — "Live Canvas" and "Control UI" exist for OpenClaw's session/channel state. README does not describe rendering plan-locked workflow state (volley iterations, signoff history, gate-pause status). Not the right substrate for plan-level visibility.

**8.6 Remote execution** — OpenClaw companion apps (macOS menu bar, iOS/Android) + Tailscale-referenced remote access. These can shell out to a local CLI. So OpenClaw is *one* viable caller for `dontpanic intake / dispatch / approve` — but `Claude Code`, `Codex CLI`, `Cursor`, etc. are equally viable callers. DontPanic's ECOSYSTEM.md already documents the OpenClaw-as-caller recipe.

**8.7 MCP tool calling** — MCP Registry exists in the OpenClaw navbar. README does not detail MCP brokering across multiple agents. DontPanic's existing `dontpanic mcp serve` (Phase B) is callable by any MCP-aware client; OpenClaw is one such client.

---

## 4. Recommendations

### 4.1 Plan H (visibility surface) — H-OpenClaw variant is ruled out

OpenClaw does not render plan/volley/signoff state. Plan H must ship its own visibility surface — the **H-DontPanic variant** from `GOAL_GOVERNANCE_V1.md` §9. The two candidates remain wterm CLI dashboard and an Axiom dashboard repoint per `2026-05-03-002` F004; neither blocked by the OpenClaw audit outcome.

### 4.2 Discord notification sink — keep as already drafted

Plan `2026-05-01-002-feat-discord-notification-sink` (currently 0/4 draft) ships DontPanic's own Discord protocol. OpenClaw can optionally relay to Discord too, but DontPanic owns the message-shape + approval-protocol. No dependency on OpenClaw.

### 4.3 Cross-instance coordination — confirmed gap, owned by DontPanic

OpenClaw doesn't broker "instance A pauses on a gate that instance B can approve." This is genuinely missing. **Lands in Plan H or as a follow-on plan**, not in F0 (F0 is per-plan child-spawning rules, not cross-instance). Worth flagging now: the cross-instance design needs its own slice — likely a global INBOX broker + a shared approval registry — and is bigger than what Plan H currently scopes.

### 4.4 Plan F0 — proceed with no OpenClaw dependency

F0's nested-orchestration configuration (child-plan charters, return-condition templates, cap rules) is internal to a single DontPanic instance walking a parent → child plan chain. OpenClaw's coordination model doesn't reach into this layer. F0 lock can proceed without further OpenClaw research.

### 4.5 OpenClaw remains a first-class caller, not a dependency

Existing positioning holds. ECOSYSTEM.md's OpenClaw integration recipe (a thin OpenClaw skill that shells out to `dontpanic intake / dispatch / status / approve`) is the contract. Nothing in F0 / F1 / G / F2 / H needs to assume OpenClaw is present.

---

## 5. What this audit did NOT investigate

Honest caveats — flag for follow-up only if a downstream plan needs the answer:

- **OpenClaw skill API for sub-call orchestration.** A deeper read of ClawHub skill conventions could reveal patterns DontPanic should align with for the OpenClaw-as-caller recipe. Not blocking; relevant only if Plan H pursues OpenClaw-side rendering.
- **A2UI spec for Live Canvas.** If a future plan considers shipping plan-state rendering as A2UI components, this would matter. Not relevant to F0 / F1 / G / F2.
- **MCP Registry behavior under multiple servers.** Whether OpenClaw can host `dontpanic mcp serve` alongside other MCPs and route correctly. Relevant only if the MCP surface becomes a primary integration path; current ECOSYSTEM.md treats CLI as primary.
- **Discord approval round-trip latency / reliability.** Engineering question for the time `2026-05-01-002` ships.

---

## 6. Decisions register

The audit produces these durable decisions for `GOAL_GOVERNANCE_V1.md` §6.7 (OpenClaw boundary, previously "open until §8 audit completes"):

1. **DontPanic produces structured outcomes** (objective contract, audit envelopes, signoff, gap-triage classifications, INBOX items, gate state). OpenClaw is *one viable consumer* of those outcomes, not the canonical renderer.
2. **OpenClaw owns: channels, voice, personal-assistant routing, multi-channel inbox, single-instance session state.** Out of DontPanic's scope.
3. **Cross-instance coordination is a confirmed DontPanic gap.** Plan H scope expands to include this OR a follow-on plan picks it up explicitly.
4. **Plan H ships H-DontPanic variant** (wterm + optional Axiom integration) — H-OpenClaw is ruled out.
5. **Discord notification sink stays a DontPanic-owned protocol** with OpenClaw as an optional relay.
6. **F0 / F1 / G / F2 lock with no OpenClaw dependency.** OpenClaw integration recipe in ECOSYSTEM.md is sufficient and stable.

These should be folded back into `GOAL_GOVERNANCE_V1.md` §6.7 (resolve "open" → "decided") and §9 (Plan H scope updated to include cross-instance coordination or split it out).
