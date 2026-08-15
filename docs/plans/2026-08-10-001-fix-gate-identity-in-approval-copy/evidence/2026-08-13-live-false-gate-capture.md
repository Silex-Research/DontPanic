# Live capture: false gate in approval copy (post-F005 state)

**Captured:** 2026-08-13, from the real `supervisor._emit_gate_paused_discord`
and `event_copy.render`, with `notify_event.dispatch_event` spied.
**Occasion:** the `pre_merge` pause of plan `2026-08-13-001-feat-lock-outcome-slices-proof`
F001 — the first instance looked for in the wild rather than in a probe.

## Why this capture supersedes the plan's original motivation

The motivation written on 2026-08-10 recorded `technical_metadata == {}` at the
emit site and concluded the real gate "appears nowhere in the rendered output".
Both statements described the pre-F005 emitter. Plan `2026-08-09-002` F005 has
since landed and **already publishes the pending gate**:

```python
gate_reference = {k: v for k, v in (
    ("pending_gates", ", ".join(pending_gates)),
    ("stage", stage),
) if v}
...
technical_metadata=gate_reference,
```

F005 also routed `_reference_gate_stage` to read `pending_gates` first, so the
*reference line* now names the real gate. What F005 deliberately did **not**
touch — its acceptance 7 forbade moving any exact command — is
`event_copy._gather_fields`, which still derives the `{gate}` format field from
`gate` / `subtype` only. `subtype` is the stage.

So the defect is no longer "a missing fact at the emit site plus a permissive
fallback". The fact is present in the event, one key away from the renderer.
**It is now purely a renderer bug.** Correcting this is the point of the
capture: this plan exists because 2026-08-09-002 was written against an
idealized render, and it must not repeat that by being written against a
superseded one.

## The pause that prompted the capture is honest — by coincidence

`docs/plans/2026-08-13-001-.../INBOX.md`, `gate_hit` block, verbatim:

```
unmet_gates: pre_merge
stage: pre_merge
Supervisor paused at lifecycle stage 'pre_merge' ...
Awaiting: ['pre_merge']
Clear one (preferred): python -m dontpanic_orchestrate approve <plan> <gate>
```

Nothing false here. Two reasons, neither of them a fix:

1. This call site (`supervisor.py:2641`) passes `stage="pre_merge"` while the
   pending gate is also `pre_merge`, so the subtype→gate alias lands on the
   right answer **by coincidence**.
2. The INBOX body prints a literal `<gate>` placeholder rather than
   substituting a value, so the alias is never exercised on that path.

The falsehood requires `stage != gate`. That is not a hypothetical.

## Call-site survey: two of four sites can never match

`grep -A6 "_emit_gate_paused_discord(" supervisor.py`:

| site | `stage` passed | `pending_gates` passed | can diverge? |
|---|---|---|---|
| `supervisor.py:2352` | `"pre_impl"` | `pre_impl_info.pending` | no |
| `supervisor.py:2641` | `"pre_merge"` | `pre_merge_info.pending` | no |
| `supervisor.py:1316` | `"general"` | `gate_check.unmet` | **always** |
| `supervisor.py:2021` | `"upfront"` | `gate_check.unmet` | **always** |

`general` and `upfront` are stage labels. Neither is a member of the gate
vocabulary (`pre_impl`, `pre_merge`, `on_escalation`, `tier_promotion`,
`cost_trigger`, `breaker:*`, `defer:*`). At those two sites the rendered
command is not merely *wrong* — it names a token that no approve invocation
can ever accept.

## Rendered output, all three real stage values

Driven through `supervisor._emit_gate_paused_discord` → `event_copy.render`:

| call site | truth: `pending_gates` | `technical_metadata` at emit | rendered gate | rendered `exact_command` |
|---|---|---|---|---|
| `:2641` `stage="pre_merge"` | `["pre_merge"]` | `{'pending_gates': 'pre_merge', 'stage': 'pre_merge'}` | `pre_merge` ✓ | `dontpanic approve <plan> pre_merge` ✓ |
| `:1316` `stage="general"` | `["pre_merge"]` | `{'pending_gates': 'pre_merge', 'stage': 'general'}` | **`general`** | **`dontpanic approve <plan> general`** |
| `:2021` `stage="upfront"` | `["breaker:iteration_cap"]` | `{'pending_gates': 'breaker:iteration_cap', 'stage': 'upfront'}` | **`upfront`** | **`dontpanic approve <plan> upfront`** |

Full detail line for the `general` case:

```
Supervisor paused at gate `general` (stage `general`).
Operator must approve before dispatch continues.
exact_command='dontpanic approve 2026-08-13-001-feat-lock-outcome-slices-proof general'
```

Note the rendered `technical_metadata` on the `RenderedEvent` itself:

```
mappingproxy({'pending_gates': 'pre_merge', 'stage': 'general', 'feature_id': 'F001',
              'subtype': 'general', 'inbox_event': 'gate_hit',
              'plan_id': '2026-08-13-001-feat-lock-outcome-slices-proof'})
```

`pending_gates: 'pre_merge'` and the rendered gate `general` are in the **same
mapping**, disagreeing with each other. The renderer carries the truth and
prints the falsehood beside it.

## Consequence for this plan

- **F001's emit-site half is already done** by 2026-08-09-002 F005. Publishing
  the gate again would be a no-op at best. F001 collapses to the renderer
  change: `_gather_fields` must derive `{gate}` from `pending_gates`, and stop
  falling back to `subtype`.
- **The `stage='implement'` scenario in the original acceptance is synthetic.**
  No call site passes `implement`. The acceptance is re-pinned to
  `stage='general'` and `stage='upfront'`, which are the real divergent sites.
- **Severity is higher than "names the wrong gate".** At `:1316` and `:2021`
  the printed command names a non-gate, so it fails rather than misfires. That
  is the better failure of the two, but it is still a command the operator is
  told to run that cannot work.
- The multi-gate question is now concrete: `gate_check.unmet` is a set, and
  `technical_metadata['pending_gates']` is already a comma-joined **string**.
  A naive `{gate}` substitution of that string yields
  `dontpanic approve <plan> pre_merge, on_escalation`, which is also not
  runnable. F001 must define this, not inherit it.

## Reproduction

```python
from dontpanic_orchestrate import supervisor, event_copy, notify_event
cap = []
notify_event.dispatch_event = lambda ev, **k: cap.append(ev)
supervisor.notify_event.dispatch_event = notify_event.dispatch_event
supervisor._emit_gate_paused_discord(
    plan_dir=PLAN_DIR, plan_id=PLAN_DIR.name, feature_id="F001",
    pending_gates=["pre_merge"], stage="general",
)
print(event_copy.render(cap[-1]).exact_command)
# dontpanic approve 2026-08-13-001-feat-lock-outcome-slices-proof general
```
