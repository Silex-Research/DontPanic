# Event Messaging F001 Inventory Draft

Read-only inventory of the DontPanic notification / event substrate, prepared to inform a future plan that introduces value-first, layered messaging across Discord, INBOX, terminal, and dashboard sinks.

Scope: `scripts/dontpanic_orchestrate/` only. Adjacent subsystems (state projection, capability manifests, planning intelligence) were intentionally not surveyed. All file:line references resolve against the working tree as of 2026-05-24.

---

## 1. NotifyEvent Schema Today

Definition: `scripts/dontpanic_orchestrate/notify_event.py:68-106` (frozen dataclass + `__post_init__` invariants).

| Field         | Type                       | Optional | Notes / Invariants                                                                                                                                  |
|---------------|----------------------------|----------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| `kind`        | `str`                      | No       | Open vocabulary. Closed sub-set `PLAN_BOUNDARY_KINDS = {"volley_start","volley_terminal","signoff"}` (`notify_event.py:46-48`) controls level routing. |
| `severity`    | `str`                      | No       | Closed vocab `{"info","action_required","escalation"}` (`notify_event.py:37-42`). `escalation` requires `action_link` (constructor enforced).         |
| `plan_id`     | `str`                      | No       | The plan that emitted the event.                                                                                                                     |
| `feature_id`  | `str \| None`              | Yes      | `None` for plan-level events; populated for feature-scoped events.                                                                                  |
| `body`        | `str`                      | No       | Markdown content rendered by all sinks. No structured shape today.                                                                                  |
| `action_link` | `str \| None`              | Yes      | File path / `file://` URL. Required when `severity == 'escalation'` (`notify_event.py:100-106`).                                                    |
| `timestamp`   | `dt.datetime`              | No       | Caller passes tz-aware UTC; not auto-populated.                                                                                                     |

Closed severity vocab: `SEVERITY_INFO`, `SEVERITY_ACTION_REQUIRED`, `SEVERITY_ESCALATION` (`notify_event.py:37-42`).
Level filter: env `DONTPANIC_NOTIFY_LEVEL` (modern) → `JARVIS_NOTIFY_LEVEL` (legacy fallback) → default `normal` (`notify_event.py:109-126`). Matrix in `_allowed_at_level` (`notify_event.py:129-142`).

Dispatch: `dispatch_event(event, *, sinks=ALL_SINKS) -> dict[str,bool]` (`notify_event.py:150-194`). Documented INVARIANT: durable INBOX write must precede `dispatch_event`. Sink failures never propagate (caught, recorded `False`, single stderr line).

---

## 2. Event Kind Inventory

### Twin-channel pattern
Two distinct emission surfaces co-exist at most call sites:
- **INBOX** (`inbox.append_event(...)` → `<plan_dir>/INBOX.md`) is the durable, schemaless YAML-ish log with `event:` header.
- **NotifyEvent** (`notify_event.dispatch_event(NotifyEvent(...))` → terminal + Discord) is the live notification envelope.

INBOX event names and NotifyEvent `kind` values are **not aligned today** — e.g. INBOX uses `event="volley_terminal"` while the NotifyEvent kind switches to `"signoff"` on the signed-off path (`supervisor.py:1130-1141`). Some INBOX events have no NotifyEvent twin; some terminal-notifier pings happen via direct `notify.notify(...)` calls (without going through `dispatch_event`).

Severity is a NotifyEvent-only concept; INBOX entries take a free-form `severity` header at a few sites but no schema enforces it.

### Unique INBOX `event=` values (sorted)
Captured by grep of `event="..."` in non-test code:

`architecture_regen_failed`, `architecture_regenerated`, `auto_cleared_pre_impl`, `blocked_no_findings`, `breaker:patch_incomplete`, `breaker_tripped`, `calibration_required`, `config_required`, `defer_cleared`, `defer_tripped`, `environmental_blocker_short_circuit`, `error`, `feature_operator_resolved`, `gate_cleared`, `gate_hit`, `gate_state_reconciliation_failed`, `nested_child_pending`, `no_progress_classification`, `pre_impl_status_synced`, `quota_warn`, `resumed`, `unit_mismatch`, `verdict_blocked_reconciled`, `verdict_mismatch`, `volley_crash_caught`, `volley_start`, `volley_terminal`.

Note: `breaker:patch_incomplete` mixes a `:` separator (unlike every other event), and is documented at `patch_completeness_gate.py:261-269`. Treat as a one-off legacy shape.

### Unique NotifyEvent `kind=` values
Captured by grep of `NotifyEvent(` instantiations in non-test code:

`breaker_tripped` (`supervisor.py:354`), `gate_paused` (`supervisor.py:384`), `calibration_required` (`supervisor.py:573`), `signoff` (`supervisor.py:1132`, signed-off branch only), `volley_terminal` (`supervisor.py:1132`, non-signed-off branch), `volley_start` (`supervisor.py:1543`).

That's six NotifyEvent kinds vs. twenty-seven INBOX event names — the Discord/terminal surface today carries a small fraction of what INBOX records.

### Per-kind row table

The table below merges the two channels by the conceptual event. "Candidate Response" column verifies the operator command shape against `cli.py` (see Section 4 for parser layout). Where the command exists in code, the row cites `cli.py` line; "needs operator clarification" marks ambiguous defaults.

| Event Kind (INBOX `event=` / NotifyEvent `kind=`) | Emit Sites (file:line) | Subtype / Discriminator | Populated Fields | Context (what triggered) | Candidate Response |
|---|---|---|---|---|---|
| `gate_hit` (INBOX only) | `supervisor.py:976` (single-agent dispatch), `supervisor.py:1433` (upfront volley gate), `supervisor.py:1653` (pre_impl staged), `supervisor.py:1893` (pre_merge staged) | `stage` header: `"general"` / `"pre_impl"` / `"pre_merge"`; single-agent path omits `stage` | `body`, `unmet_gates` (comma-joined), `feature_id`, `stage`, `target_env`, `target_project` | Supervisor paused on declared / staged human gate before dispatching | `dontpanic approve <plan> <gate>` (single, preferred) or `dontpanic resume <plan> --all` (bulk). `_approve_main` at `cli.py:232-369`, `_resume_main` at `cli.py:514-699` |
| `gate_paused` (NotifyEvent only — Discord) | `supervisor.py:382-398` via `_emit_gate_paused_discord(...)` called from `supervisor.py:994`, `1455`, `1677`, `1917` | `stage` kwarg passed through to helper | `kind`, severity = `action_required`, `body` (markdown), `action_link` → `INBOX.md` | Mirrors every `gate_hit` INBOX write to Discord. Terminal sink fires separately via `notify.notify(...)`. | Same as `gate_hit` |
| `gate_cleared` (INBOX only) | `cli.py:353` (approve), `cli.py:480` (approve pre_resume_after_child), `cli.py:659` (resume --gate) | `gate` header records cleared name; `accept_non_satisfied` for the nested case | `body`, `gate`, `child_plan_id` (nested only), `accept_non_satisfied` | Operator successfully cleared a gate via `approve` or `resume --gate` | Informational; no further operator action |
| `resumed` (INBOX only) | `cli.py:683` (resume --all bulk path) | None | `body`, `cleared_gates` | Operator bulk-cleared all declared/active gates | Informational |
| `auto_cleared_pre_impl` (INBOX only) | `supervisor.py:191` | None | `body`, `actor`, `target_env`, `target_project`, `feature_id` | Direct CLI dispatch in dev/test auto-cleared the `pre_impl` lifecycle gate (narrow carve-out, `supervisor.py:_maybe_auto_clear_pre_impl`) | Informational |
| `pre_impl_status_synced` (INBOX only) | `supervisor.py:244` | None | `body`, `status="active"`, `feature_id` | Plan `status: active` flip → supervisor implicitly cleared `pre_impl` (plan 2026-05-09-002 F002) | Informational |
| `gate_state_reconciliation_failed` (INBOX only; terminal also fires) | `supervisor.py:291` + sibling terminal-notifier at `supervisor.py:302`; `cli.py:212` (approve/resume CLI path) | `kind` header (from `GateStateReconciliationError.kind`), `gate`, `stage` | `body` (from `gate_pause.format_reconciliation_inbox_body`), `kind`, `gate`, `stage`, `persisted_state_path`, `feature_id`, `cli` (cli-only path) | Persisted `gate-state.json` contradicts declared gates; raised before any state mutation | **Needs operator clarification** — typical guidance is to inspect `gate-state.json` and edit by hand, then re-run dispatch. No first-class CLI subcommand reconciles automatically. |
| `breaker_tripped` (INBOX + NotifyEvent) | `supervisor.py:326` (INBOX) + `supervisor.py:346-350` (terminal-notifier) + `supervisor.py:352-363` (Discord NotifyEvent) | `breaker_kind` header (one of `BreakerKind` enum value), `approval_required` ("true"/"false") | INBOX: `body`, `breaker_kind`, `feature_id`, `approval_required`. NotifyEvent: kind=`breaker_tripped`, severity=`escalation`, `action_link` → `INBOX.md` | Circuit breaker tripped via `_trip_breaker`. 6 of 7 breaker kinds add a synthetic gate; global breaker is hard-stop. | When `approval_required=true`: `dontpanic approve <plan> breaker:<kind>` or `dontpanic resume <plan> --all` (literal in body). Global hard-stop: "wait out the 24h window" — no clearance path (`cli.py:269-277`). |
| `calibration_required` (INBOX + NotifyEvent) | `supervisor.py:552` (INBOX) + `supervisor.py:571-587` (Discord NotifyEvent) | None | INBOX: `body`, `agent`, `window`, `feature_id`. NotifyEvent: kind=`calibration_required`, severity=`action_required` | Budget breaker confidence==`calibration_required`; weighted local proxy cannot convert to percent without manual sample | `python -m dontpanic_orchestrate calibrate-claude --window <window> --dashboard-pct N` (literal in body; verified in `cli.py:1310-1402`) |
| `unit_mismatch` (INBOX only) | `supervisor.py:589` | None | `body`, `agent`, `window`, `feature_id` | Budget breaker `BudgetCeilingKind.UNIT_MISMATCH` — cap.unit ≠ observed_unit | Edit `~/.jarvis/quota_caps.json` (body); no specific subcommand auto-fixes the mismatch. `dontpanic quota-caps show` at `cli.py:855-` for inspection. |
| `config_required` (INBOX only) | `supervisor.py:606` | `cause` header (e.g. `caps_file_missing` / `no_cap_for_signal` / `missing_vendor_block`) | `body`, `cause`, `feature_id` | Budget breaker `BudgetCeilingKind.CONFIG_REQUIRED` | `python -m dontpanic_orchestrate quota-caps init` (body), or hand-edit `~/.jarvis/quota_caps.json` |
| `quota_warn` (INBOX only) | `supervisor.py:411` via `_maybe_emit_quota_warn` | None | `body`, `agent`, `percent_weekly`, `threshold`, `feature_id` | Quota usage crossed `SOFT_THRESHOLD_PERCENT` and `JARVIS_QUOTA_ENFORCE=soft` (default) | Informational; volley continues. Set `JARVIS_QUOTA_ENFORCE=hard` to halt at threshold. |
| `defer_tripped` (INBOX only; terminal fires separately) | `supervisor.py:1383` + terminal-notifier at `supervisor.py:1392-1396` | `defer_gate` header (e.g. `defer:quota_threshold` / `defer:interactive_backoff`), `dispatch_class` | `body`, `defer_gate`, `dispatch_class`, `feature_id` | Admission deferral activated (quota threshold crossed, or interactive backoff window active) | `dontpanic approve <plan> <defer_gate>` or `dontpanic resume <plan> --all` (literal in body). Both subcommands accept synthetic `defer:*` names per `cli.py:307`. |
| `defer_cleared` (INBOX only) | `supervisor.py:1398` | `defer_gate` header | `body`, `defer_gate`, `dispatch_class`, `feature_id` | Admission condition no longer true; deferral auto-cleared | Informational |
| `volley_start` (INBOX twice + NotifyEvent) | `supervisor.py:1477` (initial INBOX before exec env), `supervisor.py:1532-1540` (second INBOX inside exec env, plan F003 emit point), `supervisor.py:1541-1551` (NotifyEvent → both sinks) | None | INBOX: `body`, `feature_id`, `implementer`, `auditor`. NotifyEvent: kind=`volley_start`, severity=`info`, action_link=`None` | Volley begins after admission + gates + breakers + executor resolution cleared. Note the **duplicate INBOX write** at 1477 + 1532. | Informational |
| `volley_terminal` / `signoff` (INBOX + NotifyEvent) | `supervisor.py:1103` (INBOX), `supervisor.py:1117-1121` (terminal-notifier), `supervisor.py:1130-1141` (NotifyEvent) | INBOX always uses `volley_terminal`. NotifyEvent kind switches: `signoff` when `final_status=="signed_off"` else `volley_terminal`. Severity matches (`info` vs `action_required`). | INBOX: `body`, `final_status`, `rounds`, `feature_id`. NotifyEvent: action_link → `signoff.json` | Every volley terminal state — signed_off, blocked, paused_on_gate, stopped_quota, stopped_cap, stopped_no_progress, stopped_environmental_blocker, blocked_no_findings | Depends on `final_status`. For `stopped_no_progress`: see `no_progress_classification` below. For `paused_on_gate`: same as `gate_hit`. For `signed_off`: informational. |
| `no_progress_classification` (INBOX only) | `supervisor.py:2303` | `aggregate` header (e.g. `implementation_defect` / `environmental_reproduction_failure`), `blocking` | `body` (taxonomy + close hint via `closeout.format_no_progress_close_hint`), `aggregate`, `blocking`, `feature_id` | No-progress breaker tripped; auditor taxonomy classified the final envelope | `dontpanic close --operator-resolved <plan> <feature> --reason <class>` (literal in body via `closeout.format_no_progress_close_hint` at `closeout.py:585`; verified subcommand at `cli.py:725-852`) |
| `environmental_blocker_short_circuit` (INBOX only) | `supervisor.py:2186` | `aggregate` header, `blocking` | `body` (from `auditor_taxonomy.format_inbox_body`), `aggregate`, `blocking`, `feature_id`, `iteration` | `needs_changes` verdict where every finding is `ENVIRONMENTAL_REPRODUCTION_FAILURE` advisory; volley short-circuits to env-blocker breaker before second implementer round (D003 of plan 2026-05-09-002) | Routed through `_trip_and_return(BreakerKind.ENVIRONMENTAL_BLOCKER, ...)` → fires `breaker_tripped` next. Operator response is `dontpanic approve <plan> breaker:environmental_blocker` or `dontpanic resume <plan> --all`. |
| `verdict_blocked_reconciled` (INBOX only) | `supervisor.py:2093` | `aggregate`, `blocking`, `original_verdict="blocked"` | `body`, `aggregate`, `blocking`, `feature_id`, `iteration`, `original_verdict` | Auditor returned `blocked` but every finding classified as advisory → promoted to `stopped_environmental_blocker` | Same as `environmental_blocker_short_circuit` (promoted into env-blocker breaker) |
| `blocked_no_findings` (INBOX only) | `supervisor.py:2016` | None | `body`, `feature_id`, `iteration`, `audit_path` | Auditor returned `blocked` with empty findings list. Supervisor refuses to auto-promote. | **Operator-choice**: (a) re-dispatch, (b) `dontpanic close --operator-resolved <plan> <feature> --reason environmental_reproduction_failure`, or (c) close as defect. Body lists these explicitly. |
| `verdict_mismatch` (INBOX only; terminal fires separately) | `supervisor.py:1841` + terminal-notifier at `supervisor.py:1852-1859` | `narrative_verdict`, `structured_status` | `body` (from `auditor_taxonomy.format_verdict_mismatch_inbox_body`), `narrative_verdict`, `structured_status`, `audit_path`, `feature_id`, `iteration` | Auditor's prose verdict disagrees with the structured `audit_status` field. Supervisor re-raises `VerdictMismatchError` to propagate. | **Needs operator clarification** — no first-class CLI subcommand reconciles this. Operator typically inspects audit envelope and the cited summary then either re-dispatches with corrected prompt, or hand-edits the structured field. |
| `error` (INBOX only) | `supervisor.py:1699`, `supervisor.py:1772` (quota hard-blocks on implementer/auditor), `supervisor.py:2822` (per-round executor failure inside `_run_round`) | None | `body`, `agent`, `role` (some sites), `iteration` (some sites), `feature_id` | Generic executor failure or quota hard-block. Note: site at 2822 emits even though the volley continues (audit JSON still landed). | Site-dependent. Quota hard-block → wait or `dontpanic claude-touch` / adjust caps. Executor failure → re-dispatch or inspect logs. **Needs operator clarification** for canonical command. |
| `volley_crash_caught` (INBOX only) | `supervisor.py:2386` (F003 ValueError backstop), `supervisor.py:2455` (F004 broad-Exception backstop) | `stage` (F004 only), `exception_class` (F004 only) | `body`, `feature_id`, `stage`, `exception_class` | Iter-loop exception caught; supervisor wrote a `terminal-state-iter{N}.json` checkpoint and produced a clean `blocked` terminal | `dontpanic close --operator-resolved <plan> <feature> --reason <class>` (literal in `_format_recovery_command` at `supervisor.py:2489-2500`; default class `environmental_reproduction_failure`) |
| `nested_child_pending` (INBOX only) | `supervisor.py:807` | `child_plan_id`, `spawn_reason` headers | `body`, `child_plan_id`, `spawn_reason` | Child plan dispatched; parent's `pre_resume_after_child` gate newly armed | `jarvis-orchestrate approve <parent> pre_resume_after_child --child <child>` (verbatim in body — note legacy `jarvis-orchestrate` brand). Actual command in `cli.py` is `dontpanic approve <parent> pre_resume_after_child --child <child> [--accept-non-satisfied]` (`cli.py:372-504`). **The body string needs a brand fix.** |
| `feature_operator_resolved` (INBOX only) | `cli.py:826` | `reason_class` | `body`, `feature_id`, `reason_class` | Operator ran `dontpanic close --operator-resolved` to close a stuck feature | Informational; body says "Edit the closeout memo's Rationale section before merging" |
| `architecture_regen_failed` (INBOX only) | `architecture_regen_hook.py:163` | None | `body`, `feature_id`, `matched_files`, `error_type` | Post-commit architecture regen hook threw; volley terminal unaffected | `dontpanic architecture regen` (body suggests re-running manually) |
| `architecture_regenerated` (INBOX only) | `architecture_regen_hook.py:214` | None | `body`, `feature_id`, `prior_fingerprint`, `new_fingerprint`, `files_added`, `files_removed`, `files_modified`, `total_modules`, `total_plans`, `state_transition` | Post-commit hook regenerated `architecture.json`. Hook does NOT auto-commit. | Informational; body says inspect `git status` and decide whether to amend/commit/discard |
| `breaker:patch_incomplete` (INBOX only — note `:` in name) | `patch_completeness_gate.py:261` | None | `body` (from `PatchCompletenessError._render`), `report_path` | Patch-completeness gate failed on signed-off path without override | Body is the rendered error; no canonical CLI. **Needs operator clarification** — gate enforce is at `patch_completeness_gate.enforce(...)` and the override knob is `allow_incomplete_patch_reason` passed at dispatch time (e.g. `--allow-incomplete-patch-reason <reason>` on `dispatch-from-plan`). |

### Pure-terminal-notifier sites (no INBOX, no NotifyEvent)
These predate `dispatch_event` and only fire macOS terminal-notifier:
- `supervisor.py:302-306` (gate-state reconciliation contradiction) — INBOX fires too at 291; only the terminal sink is invoked, not Discord.
- `supervisor.py:346-350` (breaker title format `"jarvis: breaker {kind} — {plan_id}"`) — followed by NotifyEvent at 352 with Discord-only sink.
- `supervisor.py:989-993`, `1117-1121`, `1392-1396`, `1450-1454`, `1672-1676`, `1852-1859`, `1912-1916` — kind-specific titles for gate pauses, volley terminals, defer trips, pre_impl pauses, verdict mismatches, pre_merge pauses.
- The transitional pattern: emit sites fire `notify.notify(...)` directly for a richer kind-specific title and pass `sinks=(SINK_DISCORD,)` to `dispatch_event` so Discord still gets the same event without duplicating the terminal ping (`notify_event.py:155-162` docstring).

### Brand drift in operator-facing body strings
Body text routinely names commands as `jarvis approve ...` (legacy) when the working binary is `dontpanic`. Mixed examples:
- `supervisor.py:335-336` (`breaker_tripped` body): `"jarvis approve {plan_id} breaker:{kind.value}"`
- `supervisor.py:801-804` (`nested_child_pending` body): `"jarvis-orchestrate approve ..."`
- `supervisor.py:990-1004` `PausedOnGate` raise: `"clear via `jarvis approve {loaded.plan_id} <gate>`"`
- Several `notify.notify(title="jarvis: ...")` titles.

These are downstream to fix but worth surfacing because the future event_copy module will inherit them unless translated.

---

## 3. Sink Rendering Today

### Terminal (`notify.py`)

Entry: `notify_event(event)` at `notify.py:75-92`. Projection:
- **Title** = `f"Jarvis [{event.plan_id}]"` (note: still hardcoded "Jarvis", not "DontPanic")
- **Subtitle** = `event.kind` (verbatim — e.g. `breaker_tripped`, `gate_paused`, `volley_start`)
- **Message** = `event.body[:140]` (terminal-notifier UX limit)
- **Group** = `event.plan_id` (per-plan stack, batch-clearable)

Sample for a `breaker_tripped` event (synthesized from `supervisor.py:354-361` payload):
```
Title:    Jarvis [2026-05-24-001-feat-foo]
Subtitle: breaker_tripped
Message:  **Breaker** `no_progress` — auditor verdict identical to last round (no_progress threshold reached after 3 iter…
```

For direct `notify.notify(...)` calls (legacy pattern) the title is per-site (e.g. `"jarvis: breaker no_progress — <plan>"`) and message is truncated reason text. See `supervisor.py:346-350`.

### Discord (`notify_discord.py`)

Entry: `notify(event)` at `notify_discord.py:158-206`. Body formatter `_format_content` at `notify_discord.py:209-232`:

- Username: `"Jarvis"` (constant `_USERNAME` at `notify_discord.py:59`; not "DontPanic")
- Allowed mentions: empty (`{"parse": []}`) — `@here` / `<@id>` rendered as literals
- User-Agent: `"DontPanic-Webhook/1.0 (+https://github.com/Silex-Research/DontPanic)"` — needed to bypass Cloudflare 1010 block (`notify_discord.py:66-68`)
- Content envelope:
  ```
  **[<plan_id>]** `<feature_id>` `<kind>`
  <event.body trimmed>
  → `<action_link>`
  ```
  Backticks intentional around `kind` to dodge Discord's italic parser eating `_`. Truncated to 1800 chars (Discord 2000 limit).

Sample for a `gate_paused` event (synthesized from `supervisor.py:382-396`):
```
**[2026-05-24-001-feat-foo]** `F002` `gate_paused`
**Gate pause** (pre_impl) — awaiting: pre_impl
Clear: `dontpanic approve 2026-05-24-001-feat-foo <gate>` or `dontpanic resume 2026-05-24-001-feat-foo --all`
→ `/path/to/plan/INBOX.md`
```

### INBOX (`inbox.py`)

Entry: `append_event(plan_dir, event, *, plan_id, body, timestamp=None, **extra_headers)` at `inbox.py:71-123`.
Output format (literal):
```
---
timestamp: 2026-05-24T12:34:56Z
event: <event>
plan_id: <plan_id>
<extra_headers as `key: stringified-value` lines>
---

<body, rstripped if present>

===
```
- File header lazily written on first append: `# INBOX — <plan_id>\n\nOperator-facing event log written by the supervisor.\n\n`
- All extra-header values stringified via `str()`; `None` values omitted
- `===` is the body terminator separator
- Reader: `read_events(plan_dir)` returns `list[InboxEntry]` (`inbox.py:126-179`) tolerant of operator edits to body content

Sample `gate_hit` entry (from `supervisor.py:976-988`):
```
---
timestamp: 2026-05-24T12:34:56Z
event: gate_hit
plan_id: 2026-05-24-001-feat-foo
unmet_gates: pre_impl
feature_id: F002
---

Single-agent dispatch paused before run.

Awaiting: ['pre_impl']

Clear one (preferred): python -m dontpanic_orchestrate approve 2026-05-24-001-feat-foo <gate>
Clear all (explicit):  python -m dontpanic_orchestrate resume 2026-05-24-001-feat-foo --all

===
```

### Dashboard ActionItem (`operator_console.py`)

ActionItem definition: `operator_console.py:169-233`. Fields: `id`, `source`, `band` (`Band` enum: `NEEDS_ACTION`/`ADVISORY`/`INFO`/`READY`), `title`, `detail`, `exact_command`, `automatable`, `human_required_reason`, `evidence_uri`, `updated_at`, `project_name`, `display_name`. Constructor invariants at `operator_console.py:201-217` enforce source-vocab membership and the `automatable ↔ human_required_reason` mutual-exclusion.

**ActionItems are NOT built from NotifyEvent today.** The dashboard providers consume already-loaded subsystem state, NOT events:
- `provide_gate_actions(gates, ...)` at `operator_console.py:246-297` — input is `state_snapshot_model.GateEntry`-shaped entries from the state projection layer. Each unmet gate → `band=NEEDS_ACTION`, `title=f"Gate {gate_name} on {plan_id} needs approval"`, `exact_command=f"dontpanic approve {plan_id} {gate_name}"`, `evidence_uri=<plan_dir>/audit/gate-state.json`.
- `provide_capability_actions(envelope, ...)` at `operator_console.py:300-385` — input is a `capabilities_status.StatusEnvelope`; maps `blocked`/`needs_setup` → `NEEDS_ACTION`, `not_installed` → `ADVISORY`, skips `ready`/`optional`. Command shape: `dontpanic capabilities status <cap_id>`.
- `provide_reconcile_actions(check_result, ...)` at `operator_console.py:388-485` — input is `reconcile.CapabilityCheckResult`; drift-kind → band mapping; command shape: `dontpanic reconcile baseline --yes` / `dontpanic capabilities status`.
- `provide_supervisor_actions(supervisors, ...)` at `operator_console.py:488-531` — input is `active_supervisors.list_active()` entries; band always `INFO`, command `dontpanic ps`.
- `provide_architecture_actions(arch_status, ...)` at `operator_console.py:534-568` — input is dict from `architecture.status()`; stale/absent → `ADVISORY`, command `dontpanic architecture regen`.

**Implication for the planned event_copy → RenderedEvent → ActionItem mapping**: there is currently NO bridge between NotifyEvent and ActionItem. A future RenderedEvent shape will need either (a) a new event-driven provider that reads INBOX or a future events.jsonl, or (b) an in-process hook called from `dispatch_event` that materializes an ActionItem and lands it in a cache. The current cache writer (`write_cache` at `operator_console.py:665-687`) writes JSON to `<dontpanic_home>/dashboard/what-now.json`.

The ActionItem field shape is a near-perfect superset of the RenderedEvent shape described in the brief (band, title, detail, exact_command, evidence_uri all map directly). The two add-ons ActionItem requires beyond RenderedEvent: `automatable` + `human_required_reason` (mutually exclusive), and `id` (stable provenance prefix).

---

## 4. CLI Parser Extraction Assessment

**File**: `scripts/dontpanic_orchestrate/cli.py` (3,292 lines).

**Top-level shape**: `def main(argv: list[str] | None = None) -> int` at `cli.py:3090-3288`. Dispatch is a long `if raw[0] == "<cmd>"` ladder (`cli.py:3105-3175`) followed by an inline `argparse.ArgumentParser` for the legacy bare-dispatch path (`cli.py:3177-3223`).

**Per-subcommand pattern**: each subcommand has a `_<name>_main(argv: list[str]) -> int` function that constructs its OWN `argparse.ArgumentParser` inline (e.g. `_resume_main` at `cli.py:514` builds parser at 532; `_close_main` at `725` builds at 736; `_plan_lock_main` at `2021` builds at `2024`; etc.). Some subcommands (`_approve_main` at `cli.py:232`) do positional parsing by hand without argparse.

**Side-effect coupling**: each `_*_main` function does:
1. Parser construction (pure).
2. `parser.parse_args(argv)` (pure aside from `sys.exit` on parse error).
3. Calls into business logic (heavy side effects — plan loader, gate state mutations, subprocess dispatch, network).

Parser construction and handler invocation are tangled inside the same function. There is **no `build_parser()` factory**, no central registry of subcommands beyond the `if raw[0] == "..."` chain in `main`, and no `add_subparsers()` tree. The top-level `--version` / `--help` path (`cli.py:3094-3104`) is hand-rolled too.

**Feasibility of a side-effect-free `build_parser()`**: feasible but non-trivial. Two approaches:

1. **Per-subcommand parser-factory extraction** (recommended).
   - Refactor each `_*_main` into two functions: a pure `_build_<name>_parser() -> argparse.ArgumentParser` and the existing `_<name>_main(argv)` which calls the factory then dispatches. The factory adds args, sets `prog=`, defaults, choices — no business calls.
   - Top-level `build_parser()` enumerates the subcommand→factory map and either returns an `ArgumentParser` with `add_subparsers()` wiring each factory in, or returns a dict `{subcommand: parser}` for direct token validation.
   - Estimated cost: ~18 subcommand functions × ~10 LoC of mechanical movement = manageable mechanical refactor. Tests in `tests/test_cli_*.py` (not surveyed exhaustively here) will need to keep working against `_*_main` invariants.
   - Side-effect note: a few subcommand parsers import lazily (e.g. `from dontpanic_orchestrate import planning_readiness` inside `_next_main` at line 3013). Moving these into a factory is safe — the import stays inside the existing `_*_main` body — but if the factory needs constants from a heavy module, the lazy-import shape may need preserving to keep `build_parser()` cheap.

2. **Token-only validator helper** (cheaper, narrower).
   - Skip parser extraction entirely. Add a `validate_command_tokens(tokens: list[str]) -> ValidationResult` helper that consults a hardcoded subcommand vocabulary (the same set the dispatch ladder enumerates) plus a per-subcommand expected-arg-count + flag-prefix map. This validates the command-shape in copy without parsing argparse — sufficient if the event_copy module's only need is "this token sequence looks like a valid `dontpanic` invocation."
   - Estimated cost: ~1 day to enumerate the vocab + per-subcommand shape, plus tests pinning each subcommand's shape against `_*_main` accepting it.
   - Tradeoff: drift risk — if a `_*_main` adds a new flag and the validator helper isn't updated, advisory misses the change. Mitigation is a test that round-trips every subcommand through both surfaces.

**Recommendation**: approach 1 is cleaner long-term and unlocks dashboard-side command-shape validation, `dontpanic help <cmd>` auto-generation, and shell completion. Approach 2 is sufficient for v1 if the goal is only "is this command well-formed enough to render in copy". For F001 inventory purposes, marking the recommended approach is enough — actual extraction is a separate plan.

**File scope**: changes confined to `cli.py` (3,292 lines). No new files required for approach 1; approach 2 could live in a new `command_validation.py` module.

---

## 5. Sanitization Pattern

**Canonical regex source**: `scripts/sanitization_check.py:92-102` exports `SECRET_REGEXES: tuple[re.Pattern[str], ...]` containing exactly **9** patterns:
1. `_AWS_ACCESS_KEY_RE` (`AKIA...`) — line 45
2. `_GH_PAT_RE` (`ghp_...`) — line 49
3. `_GH_FINE_GRAINED_RE` (`gh[osur]_...`) — line 54
4. `_ANTHROPIC_API_KEY_RE` (`sk-ant-api03-...AA`) — line 58
5. `_OPENAI_API_KEY_RE` (`sk-...T3BlbkFJ...`) — line 64
6. `_SLACK_TOKEN_RE` (`xox[baprs]-...`) — line 68
7. `_PEM_PRIVATE_KEY_RE` (`-----BEGIN ... PRIVATE KEY-----`) — line 73
8. `_JWT_RE` (`eyJ...`) — line 81
9. `_DISCORD_WEBHOOK_RE` (`discord.com/api/webhooks/...`) — line 86

Per-pattern test matrix lives at `scripts/dontpanic_orchestrate/tests/test_f001_secret_shapes.py` with 9 `CASES` rows × parametrized positive + negative + end-to-end tests.

**Re: the "45 cases" reference in the brief**: this matches the `tests/test_notify_discord_sink.py` synthetic-event matrix per plan `2026-05-01-002` (`plan.md:77`) — "3 levels × 3 webhook states × 5 event kinds = 45 cases" — NOT the sanitization regex count. The sanitization matrix is 9 patterns. The brief conflated the two.

**Render-boundary application**:

The sanitization is consumed via three surfaces today:
1. `state_projection.py:97-103` — imports `SECRET_REGEXES` directly and runs `_redact(s)` to substitute `[REDACTED]` (`state_projection.py:578`+).
2. `operator_console.py:100-112` (lazy-load) + `_assert_no_secret_shapes(payload)` at `operator_console.py:693-709` — recursively walks every string in a payload dict via `_walk_strings` (`operator_console.py:712-721`) and **raises `ValueError`** if any regex matches. This is the render-time check for the dashboard cache.
3. `projects_dashboard.py:538`, `595`, `1102` + `architecture_view_state.py:421`, `487` — call `operator_console._assert_no_secret_shapes(payload)` (intentional SLF001 ignore) before persisting.

**Applicability to a future event_copy render boundary**: the existing `_assert_no_secret_shapes` walker plus the `SECRET_REGEXES` tuple can apply unchanged — the function is generic over `dict[str, Any]` and walks every nested string. The only adjustment needed is:
- If the future `RenderedEvent` dataclass is the input to render, call `_assert_no_secret_shapes(rendered.to_dict())` at the boundary.
- If render produces raw markdown strings (Discord/INBOX paths), use `state_projection._redact(s)`-style replacement (substitute → `[REDACTED]`) instead of raise, since live notifications shouldn't fail-hard the supervisor.

Both modes are already implemented. No regex changes required; this is purely a wiring decision.

**Caveat**: the regex tuple is loaded by absolute path through `sys.path.insert(...)` (`operator_console.py:104-109`). Future code that consumes the tuple should follow the same lazy-import pattern or a shared loader to avoid duplicating the `sys.path` shim.

---

## 6. NotifyEvent Metadata Gaps

The current NotifyEvent envelope carries only enough fields for "title + free-form markdown body + link". Building layered copy (headline / why / action / technical detail) keyed off structured discriminators requires the following:

| Proposed Field | Type | Needed By Event Kinds | Currently Available Via | Plumbing Cost |
|---|---|---|---|---|
| `subtype` (or `stage`) | `str \| None` | `gate_hit` / `gate_paused` (`general` / `pre_impl` / `pre_merge`), `gate_state_reconciliation_failed` (`stage`), `volley_crash_caught` (`stage`) | INBOX header `stage` is already passed at every relevant call site (`supervisor.py:1666`, `1907`, etc.). NotifyEvent does NOT carry it — `gate_paused` is rendered with `stage` only in the body string at `supervisor.py:389`. | Low: add `subtype: str \| None = None` to NotifyEvent dataclass, thread one kwarg at the 6+ existing emit sites. |
| `breaker_kind` | `str \| None` | `breaker_tripped`, `environmental_blocker_short_circuit`, `verdict_blocked_reconciled` (when promoted) | INBOX header `breaker_kind` populated at `supervisor.py:342`. NotifyEvent embeds the kind only inside the body (`f"**Breaker** `{kind.value}` — ..."` at `supervisor.py:358`). | Low: add `breaker_kind: str \| None = None`; populate from `kind.value` at the trip site. |
| `iteration_count` | `int \| None` | `volley_terminal`/`signoff` (final round count), `no_progress_classification`, `verdict_mismatch`, `environmental_blocker_short_circuit`, `volley_crash_caught` | INBOX header `rounds` / `iteration` populated at most sites. NotifyEvent embeds via body string only (`f"rounds: {result.rounds}"` at `supervisor.py:1136`). | Low: add `iteration_count: int \| None = None`; existing sites already compute the value. |
| `capability_id` | `str \| None` | Not directly emitted by NotifyEvent today, but ActionItem `provide_capability_actions` consumes capability_id from a different source. If event_copy is to render capability-related events (a future expansion: capability_status_changed, capability_setup_required), this field gates the bridge. | NOT in NotifyEvent. Inferred from the capability envelope path (`StatusEnvelope.capabilities[i].capability_id`). | Medium: requires a future event-kind expansion (capability subsystem doesn't emit NotifyEvent today). Out of scope until a capability event kind is added. |
| `feature_display_name` | `str \| None` | All feature-scoped events (`gate_hit`, `breaker_tripped`, `volley_terminal`, etc.). Today only `feature_id` (raw `F001` style) is carried. | Available via `loaded.feature(feature_id)["description"]` at every supervisor site that already loads `loaded`. NotifyEvent does NOT carry it. | Low-Medium: each emit site has `loaded` in scope but currently passes only `feature_id`. Adds one `feature.get("description")` lookup per emit. |
| `evidence_uri` | `str \| None` | Every event that references an artifact: INBOX.md, signoff.json, gate-state.json, audit envelope, terminal-state-iter{N}.json | Already populated under the name `action_link` on every escalation-severity NotifyEvent (constructor enforced). The semantic overlap is total. | Zero — recommend renaming `action_link` → `evidence_uri` (or making them aliases) rather than adding a new field. ActionItem already uses `evidence_uri`. |
| `command_suggestion` | `str \| None` | Every action-required / escalation event. Today the literal command is embedded in the body string (multiple variants: `python -m dontpanic_orchestrate approve ...`, `dontpanic approve ...`, `jarvis approve ...` — see brand drift). | Body string only. Construction varies site-by-site. | Medium: extract a per-kind command builder (the event_copy module's responsibility per the brief). Trivial to add the field; consolidating the per-site logic is the real work. |
| `severity` (already exists) | `str` | All | Constructor enforces. | No change. |
| `aggregate_class` / `blocking` | `str \| None` / `bool \| None` | `no_progress_classification`, `verdict_blocked_reconciled`, `environmental_blocker_short_circuit` | INBOX headers `aggregate` + `blocking` populated at every taxonomy emit. NotifyEvent doesn't carry these (taxonomy never makes it to Discord today). | Low: add `aggregate_class: str \| None`, `blocking: bool \| None`. |
| `target_env` / `target_project` | `str \| None` / `str \| None` | `gate_hit` (all stages), `auto_cleared_pre_impl`, `verdict_*` | INBOX headers populated at most relevant sites. NotifyEvent doesn't carry them. | Low: add both; thread from `effective_env` / `effective_project` already in scope. |

### Coverage gap: kinds with no NotifyEvent surface today

The Discord/terminal sink today only fires for 6 of the 27 INBOX event names: `breaker_tripped`, `gate_paused` (= INBOX `gate_hit`), `calibration_required`, `signoff` (= INBOX `volley_terminal` signed-off branch), `volley_terminal` (= INBOX `volley_terminal` non-signed-off), `volley_start`.

Twenty-one INBOX events have no live Discord notification today. For each, the future plan should decide: live-notify or INBOX-only. High-value candidates that the operator likely wants on Discord/terminal:
- `verdict_mismatch` (terminal-only today; nothing on Discord even though severity is high)
- `no_progress_classification` (silent on Discord; carries the operator-actionable close-out command)
- `environmental_blocker_short_circuit` + `verdict_blocked_reconciled` (silent; only fire `breaker_tripped` downstream)
- `gate_state_reconciliation_failed` (terminal-only today; high severity)
- `architecture_regen_failed` (INBOX only; advisory but worth a quiet notification)
- `feature_operator_resolved` (INBOX only; useful confirmation)

### Coverage gap: double-write at `volley_start`

`supervisor.py:1477` and `supervisor.py:1532-1540` both emit INBOX `event=volley_start` within the same dispatch. Operator INBOX.md will show two consecutive entries. Either this is intentional (one before exec env, one after) or it's a latent duplicate-write bug. **Worth operator clarification.**

---

## 7. Open Questions for Operator

1. **Canonical command for `gate_state_reconciliation_failed`.** No CLI subcommand reconciles automatically — the body shows the structured conflict but no fix-it command. Is the recommended response a hand-edit + re-run, or does a separate `dontpanic reconcile-gate-state` subcommand belong on the roadmap?

2. **Canonical command for `verdict_mismatch`.** Same question — supervisor re-raises but body provides no operator command. Likely a re-dispatch with corrected prompt, but is there a planned automated path (e.g. `dontpanic plan reaudit`)?

3. **Canonical command for `error` events.** Three call sites (`supervisor.py:1699`, `1772`, `2822`) with different contexts (quota hard-block vs executor failure inside `_run_round`). The third (`_run_round`) fires even though the volley continues — is this an INBOX-only audit-trail entry, or should it produce a NotifyEvent too?

4. **`breaker:patch_incomplete` event name.** Unlike every other event, this one uses `:` as a separator (mirroring the gate name `breaker:patch_incomplete`). Should this be normalized to `patch_incomplete` (event name) + `breaker_kind="patch_incomplete"` (structured field) for v1, or kept as-is for backward compat with existing INBOX parsers?

5. **Duplicate `volley_start` INBOX write** at `supervisor.py:1477` + `1532`. Intentional or latent bug?

6. **Brand drift in body strings.** Body text routinely names `jarvis approve ...` / `jarvis-orchestrate approve ...`. Confirmed out of scope per brief, but worth flagging that the future event_copy module will inherit this unless translated.

7. **Should ActionItem absorb NotifyEvent, or remain decoupled?** Today the dashboard providers read subsystem state (gate-state.json, capabilities-status.json, etc.), not the event stream. The future RenderedEvent → ActionItem bridge could either (a) introduce an event-driven provider that reads INBOX.md or a future events.jsonl, or (b) materialize an ActionItem in-process at `dispatch_event` time and land it in a cache the dashboard reads. Choice has implications for cross-machine operator UX (Discord posts an event from machine A; does machine B's dashboard see the ActionItem?).

8. **`action_link` vs `evidence_uri` semantic overlap.** Recommend collapsing into a single field. Acceptable to rename or alias?

9. **`feature_display_name` plumbing**. Every supervisor emit site has `loaded.feature(feature_id)` available but currently extracts only `feature_id`. Confirm the future RenderedEvent should carry `feature_description` (or a separate `display_name` field) — and decide whether to compute it at the emit site or in the event_copy module.

10. **Capability events**. The capability subsystem currently emits no NotifyEvent — ActionItems are built from `StatusEnvelope` directly. If capability state changes should also trigger live notifications (e.g. `capability_blocked`, `capability_ready_after_setup`), a new event kind plus its emit site needs scoping. Out of scope for F001 inventory but worth flagging for the v1 plan's surface decision.
