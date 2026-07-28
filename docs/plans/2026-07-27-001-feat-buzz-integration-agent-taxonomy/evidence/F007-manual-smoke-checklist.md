# F007 — Buzz-as-caller recipe: manual smoke checklist

Scope: verifies the committed caller recipe
(`examples/buzz-caller/README.md`) against the **local** MCP surface.
Automated E2E against a live Buzz relay is explicitly out of scope for
F007 acceptance; the Buzz-side steps are desk-checked (marked *paper*).

Run from the repo root with a registered project (the MCP server only
resolves `plan` args inside registered projects' plans directories —
`dontpanic projects add <name> <path>` first if needed). The examples
below use `PLAN=<a plan id under a registered project's plans dir>`;
substitute any plan you can see via `list_projects`. Every executable
step is read-only / dry-run — nothing here dispatches or clears gates.

## A. Local MCP surface (executable)

- [ ] **A1 — Tool surface matches the recipe's tool map.**
  ```bash
  PYTHONPATH=scripts python3 -c "from dontpanic_orchestrate import mcp_server; print(mcp_server.list_tool_names())"
  ```
  Expect at minimum: `list_projects`, `validate_plan`, `dispatch`,
  `status`, `approve_gate`, `read_evidence`.

- [ ] **A2 — `validate_plan` resolves and validates a registered plan.**
  ```bash
  PYTHONPATH=scripts python3 -c "from dontpanic_orchestrate import mcp_server; import json; print(json.dumps(mcp_server.dispatch_tool('validate_plan', {'plan': '$PLAN'}), indent=2))"
  ```
  Expect `"valid": true` with `plan_id`, `tier`, `human_gates`,
  `feature_ids`. Bonus check: an out-of-tree path (e.g.
  `examples/plans/hello-dontpanic` when only `docs/plans` is registered)
  must **refuse** with "not found in any registered project".

- [ ] **A3 — `dispatch` without `confirm` is a dry-run (the preview
  surface).**
  ```bash
  PYTHONPATH=scripts python3 -c "from dontpanic_orchestrate import mcp_server; import json; print(json.dumps(mcp_server.dispatch_tool('dispatch', {'plan': '$PLAN', 'feature': 'F001'}), indent=2))"
  ```
  Expect `"dry_run": true`, a structured `intent` (plan, feature,
  target_env, human_gates, tier), no volley started, and the message
  "Always surface the plan to the user before confirming."

- [ ] **A4 — `approve_gate` without `confirm` is a dry-run.**
  ```bash
  PYTHONPATH=scripts python3 -c "from dontpanic_orchestrate import mcp_server; import json; print(json.dumps(mcp_server.dispatch_tool('approve_gate', {'plan': '$PLAN', 'gate': 'pre_impl'}), indent=2))"
  ```
  Expect `"dry_run": true` with `currently_cleared` / `would_clear` in
  the intent; no gate state mutated.

- [ ] **A5 — `status` returns active supervisors + per-plan gate state.**
  ```bash
  PYTHONPATH=scripts python3 -c "from dontpanic_orchestrate import mcp_server; import json; print(json.dumps(mcp_server.dispatch_tool('status', {'plan': '$PLAN'}), indent=2))"
  ```
  Expect `active_supervisors` (may be empty) and a `gate_status` block
  with `paused` / `declared` / `cleared` / `unmet` — the fields the
  recipe's step 6 surfaces to the gates channel.

## B. Recipe honesty (desk check)

- [ ] **B1** — README's tool map matches A1 (names + which tools mutate).
- [ ] **B2** — README documents dry-run-by-default for both mutating
  tools and shows `confirm: true` only *after* the explicit-human-approval
  step.
- [ ] **B3** — The non-auto-confirm rule appears prominently (top callout
  + flow step 4 + safety checklist) and forbids reactions/emoji/timeouts
  as approval.
- [ ] **B4** — Safety checklist items cover every rule in
  ECOSYSTEM § "Safety rules for agent callers" (same list the OpenClaw
  recipe points at) plus the Buzz-specific locked non-goals.
- [ ] **B5** — All cross-links resolve (ECOSYSTEM anchors,
  GETTING_STARTED Buzz setup, AGENT_CAPABILITY_MATRIX, this checklist).

## C. Buzz-side steps (paper only — no live relay required)

- [ ] **C1** — Preview posted to the **private** community channel
  contains plan_id / tier / target / gates, and no secrets or home paths.
- [ ] **C2** — Approval comes from an allowlisted human operator key as a
  deliberate action on the previewed intent; the workflow ignores
  reactions and unsolicited chat text.
- [ ] **C3** — Gate pauses land in the gates channel with a pointer to
  INBOX.md / evidence; F006 notify-sink pushes (if configured) are
  treated as re-poll prompts, not state.

## Run log

| Date | Operator | A1 | A2 | A3 | A4 | A5 | B | C | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 2026-07-28 | claude-implementer (F007 i0) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | paper | `PLAN=2026-07-27-001-feat-buzz-integration-agent-taxonomy`; outputs below |

### 2026-07-28 captured outputs (abridged)

```text
A1: ['list_projects', 'validate_plan', 'dispatch', 'status', 'approve_gate',
     'read_evidence', 'state_snapshot', 'state_stream', 'capabilities.get_status']

A2: valid=True  plan_id=2026-07-27-001-feat-buzz-integration-agent-taxonomy
    tier=cross-cutting  human_gates=['pre_impl', 'pre_merge']
A2 refusal check: plan 'examples/plans/hello-dontpanic' →
    MCPError "not found in any registered project; MCP does not consult cwd/docs/plans"

A3: dry_run=True
    message="dry-run; pass confirm=true to invoke supervisor.dispatch_volley.
             Always surface the plan to the user before confirming."
    intent keys: auditor, feature_id, human_gates, implementer, max_iterations,
                 mode, plan_dir, plan_id, target_env, target_project, tier

A4: dry_run=True
    intent: gate=pre_impl currently_cleared=True would_clear=False (no mutation)

A5: keys=['active_supervisors', 'gate_status']
    gate_status: paused=False declared=['pre_impl','pre_merge']
                 cleared=['pre_impl','pre_merge'] unmet=[]
```
