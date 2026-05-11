# printing-press-adapter — Decision Tree

Four yes/no filters. **All four must answer YES** for this skill's
prescribed workflow to apply. A single NO is a hard skip: hand-roll
the handlers, pick a different pattern, or file a v2 expansion.

The filters are intentionally narrow — false positives inflate the
matcher's noise floor (the v0 false-positive budget set by plan
2026-05-08-002 D004) and push operators toward boilerplate they don't
need.

---

## Q1 — Is this an **external** API, or an in-process surface?

- **YES (external)** → continue to Q2.
- **NO (in-process)** → **SKIP**. Wrapping an in-process surface
  through a subprocess-bound MCP shim pushes the surface's policy
  enforcement (redaction, gates, registry safety) into a process
  boundary that can't enforce it.

**Worked anti-case (in-process):** DontPanic's own `dontpanic` CLI and
its MCP server (plan 2026-05-09-003 F004 / F005). DontPanic is the
policy bearer — it enforces `redact_level`, `approve_gate`, and the
INBOX-first invariant. Running our own surface through PP would put
policy on the wrong side of a subprocess. We hand-write that surface
on purpose. The ROADMAP names this explicit exception.

---

## Q2 — Does the target publish **OpenAPI**, or does its traffic
   capture cleanly as **HAR**?

- **YES** → continue to Q3.
- **NO** → **SKIP**. CLI Printing Press generates from a contract or
  a reproducible trace. Without either, the generator has nothing to
  shape its emitted CLI / MCP tools around, and the operator ends up
  hand-writing the surface anyway — at which point the PP detour is
  pure overhead.

**Worked anti-case (no contract, no capture):** a vendor portal whose
only "API" is a logged-in dashboard with WebSocket fan-out, no
documented schema, and traffic that re-keys session blobs on every
load. The HAR captured today doesn't replay tomorrow, and there is no
OpenAPI to fall back on. The right pattern is a thin screen-scraping
adapter authored directly against the live surface, or skipping the
integration entirely until the vendor ships a contract.

---

## Q3 — Are you wrapping **≥ 5 endpoints**?

- **YES** → continue to Q4.
- **NO (< 5 endpoints)** → **SKIP**. The fixed cost of generating a
  PP binary, authoring the DontPanic-side adapter wrapper, pinning a
  PP version, and registering in `~/.dontpanic/adapters.json` is real.
  Below five endpoints, that cost exceeds the cost of writing the
  handlers by hand.

**Worked anti-case (too few endpoints):** a status-page integration
that only ever needs `GET /status` and `GET /incidents`. Two
endpoints. The PP shim adds a Python wrapper module, a subprocess
boundary, a JSON-RPC framing layer, and a registry entry — for two
handlers that could be a ten-line `httpx.get(...)` call each. Just
write the handlers.

---

## Q4 — Are any of the wrapped endpoints **mutating**?

- **NO (read-only)** → **PROCEED** with the prescribed workflow in
  `SKILL.md`.
- **YES (any mutation)** → **SKIP for v0**. v0 of this skill is
  read-only by directive. Mutating endpoints require approval-gate
  templating (a per-tool `approve_gate` analog matching DontPanic's
  in-process gate semantics), which is reserved for the v2 expansion
  of this skill. File the v2 plan before proceeding.

**Worked anti-case (mutating endpoint in v0):** a Slack adapter whose
value is `chat.postMessage`. That endpoint mutates the target system
(posts to a channel) and needs operator confirmation before each
call. v0 has no approval-gate template — the wrapper in
`ADAPTER_TEMPLATE.md` hard-rejects any tool call that would mutate
without `confirm: true`. To actually ship the Slack adapter we need
v2: an approval-gate templating mechanism that lets the adapter
declare per-tool gate requirements and the DontPanic-side wrapper
enforce them. Until v2 ships, file the v2 plan rather than working
around v0.

---

## Summary table

| Filter | YES | NO |
|---|---|---|
| Q1 — External (not in-process)? | continue | skip — in-process belongs in-process |
| Q2 — OpenAPI or stable HAR? | continue | skip — nothing for PP to generate from |
| Q3 — ≥ 5 endpoints? | continue | skip — just write the handlers |
| Q4 — Read-only (no mutation)? | **PROCEED** | skip — file v2 expansion plan |

A YES on all four lands the operator at the five-step workflow in
`SKILL.md` § Steps, with `ADAPTER_TEMPLATE.md` as the wrapper
skeleton.
