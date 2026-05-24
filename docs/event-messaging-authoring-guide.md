# Event messaging — copy authoring guide

How to add or revise a rendered event in DontPanic's layered notification
pipeline. Shipped by plan
[`2026-05-24-004-feat-event-messaging-v1`](plans/2026-05-24-004-feat-event-messaging-v1/plan.md)
(F005).

This guide is the entry point for a contributor who wants to:

- expose a currently-silent INBOX event on Discord, terminal-notifier, or
  the dashboard;
- revise the headline / why / action copy for an event that already
  renders;
- add a brand-new INBOX event kind from a new emit site.

It does not cover *implementing* a new sink or changing the
`RenderedEvent` contract — both belong in a follow-up plan, not in routine
copy work.

## Mental model

Every notification flows through three layers:

1. **INBOX truth-of-record** — `inbox.append_event()` writes the raw entry
   at the supervisor emit site. This is the durable, auditor-readable log;
   it never changes shape based on rendering decisions (D013).
2. **`event_copy.render()`** — a pure function that turns a `NotifyEvent`
   (which carries the same `event=` string the INBOX entry was written
   with, as `inbox_event`) into a `RenderedEvent`. The `RenderedEvent` is
   the layered representation: headline, why-it-matters, action command,
   technical metadata, plus a disposition tag.
3. **Per-sink renderers** — `notify_discord.notify()`,
   `notify.notify_event()`, `inbox.append_rendered_annotation()`, and
   `operator_console.write_event_action_sidecar()` each consume the same
   `RenderedEvent` and project it into their channel's wire format.

Adding new copy means editing the translation table inside
`scripts/dontpanic_orchestrate/event_copy.py`. The sinks need no changes.

## Step-by-step: extend the translation table

### 1. Decide the disposition

`event_copy.Disposition` has four values; pick exactly one per INBOX event
name:

| Disposition         | When to use it                                                                          |
| ------------------- | --------------------------------------------------------------------------------------- |
| `LIVE`              | Operator must see it within seconds. Renders to Discord + terminal + sidecar + INBOX.   |
| `DASHBOARD_ACTION`  | Operator-actionable but noisy on live channels. Renders to sidecar + INBOX annotation.  |
| `INBOX_ONLY`        | Operator-visible but no live notification. Raw INBOX entry only.                        |
| `AUDIT_ONLY`        | Auditor-reconstruction artifact. Not surfaced to the operator.                          |

Add the new key to `_DISPOSITIONS` in `event_copy.py` and to the
`INBOX_EVENT_KINDS` frozenset. Totality is enforced by
`tests/test_event_copy_f001.py` — every entry of `INBOX_EVENT_KINDS` must
have exactly one disposition.

### 2. Author the copy

Reference the canonical value-language copy map at
[`docs/design/dashboard-value-language-ia-v0/copy-map.md`](design/dashboard-value-language-ia-v0/copy-map.md)
§ 2.2 + § 2.7. Do not invent new vocabulary — reuse "Approval needed",
"Blocked work", "Setup drift", "Active AI work", "AI work finished",
"System warning", "Budget guardrail".

Add a `_Template` row to `_TEMPLATES` in `event_copy.py`:

```python
"my_new_kind": _Template(
    band=_NEEDS_ACTION,
    headline="Approval needed on {plan_label}",
    why=(
        "Supervisor recorded …. Operator must … before dispatch continues."
    ),
    action="dontpanic approve {plan_id} {gate}",
),
```

The `headline` and `why` strings are `str.format(**fields)` templates.
`_gather_fields()` populates a known field-set that includes `plan_id`,
`plan_label`, `feature_id`, `feature_display_name`, `breaker_kind`,
`subtype`, `iteration_count`, `iteration_label`, `aggregate_class`,
`blocking_label`, `target_env`, `target_project`, plus everything in
`NotifyEvent.technical_metadata`. Unknown field references render as `"-"`
to avoid KeyError.

### 3. Set `action` honestly (D008)

`action` is either a `str.format` template that yields a real DontPanic
CLI command **or** `None` — never a fake. If no canonical CLI exists for
your event (e.g. a verdict reconciliation, an environmental blocker
inspection), use `action=None` and write the next step into the `why`
copy.

The renderer enforces this: every non-`None` `exact_command` is passed
through `command_validation.validate_command_tokens()` (the F001 token
validator) before being placed on the `RenderedEvent`. Validation
failures collapse `exact_command` to `None`, so a bad template silently
disables the copy-paste field instead of shipping a broken command. The
operator-facing copy still renders.

### 4. Run the command-validation harness

If you authored a non-`None` `action`, validate it deliberately:

```python
from dontpanic_orchestrate import command_validation

result = command_validation.validate_command_tokens(
    ["approve", "<plan_id>", "<gate>"]  # token list, prefix stripped
)
assert result.ok, result.reason
```

The validator is token-only and never invokes subcommand handlers (D021).
When you add a brand-new subcommand or flag to `cli.py`, you must also
update the validator's per-subcommand expected-args/flag-prefix map in
`command_validation.py` in the same PR — drift between the CLI and the
validator is mitigated by code review, not by a runtime check.

### 5. Add (or extend) a snapshot fixture

`scripts/dontpanic_orchestrate/tests/test_event_messaging_snapshots_f005.py`
parametrizes one snapshot per `(kind × channels it renders to)`. To add
your new kind:

1. Add an entry to `KIND_BUILDERS` keyed by a stable fixture name. Use
   `_ev(...)` to construct the `NotifyEvent` with the field set your
   template references.
2. Regenerate snapshots (preferred — matches the convention used by
   pytest snapshot plugins like syrupy / pytest-snapshot):

   ```bash
   python -m pytest --snapshot-update \
       scripts/dontpanic_orchestrate/tests/test_event_messaging_snapshots_f005.py
   ```

   The `--snapshot-update` CLI flag is registered in
   `scripts/dontpanic_orchestrate/tests/conftest.py`. The legacy
   `DONTPANIC_SNAPSHOT_UPDATE=1` env var is still honored for any
   scripts already wired to it.

3. Inspect the generated JSON file under
   `scripts/dontpanic_orchestrate/tests/fixtures/event_messaging_snapshots/`.
   The diff is the artifact a reviewer signs off on in code review — pin
   the snapshot only after you've eyeballed every channel.
4. Re-run without the env var to confirm the comparison branch passes.

The fixture suite enforces totality: every `LIVE` / `DASHBOARD_ACTION`
disposition in `DISPOSITION_TABLE` must have a matching `KIND_BUILDERS`
entry. A missing entry fails
`test_all_live_and_dashboard_action_kinds_are_covered`.

### 6. Sanitization sweep

The snapshot suite includes
`test_no_secret_shapes_in_any_pinned_snapshot`, which walks every fixture
file and asserts no string matches any of the 9 secret-shape regexes
from `scripts/sanitization_check.SECRET_REGEXES`. If you accidentally
construct a fixture with secret-shaped content (e.g. a 36-char hex
string that happens to match the AWS key regex), the test fails — fix the
fixture, do not allowlist the leak.

## Sink-specific notes

You only edit the sinks when changing the *shape* of an output (a new
embed field, a different sidecar dict layout). Routine copy work doesn't
touch them.

### Discord

`notify_discord._build_payload()` consumes the `RenderedEvent` and emits a
Discord rich embed. Color is taken from the IA copy map's 4-band taxonomy
via inline hex literals in `notify_discord.py` (D022 — there is no
`dp-tokens.css` to import from). The 2000-character payload total is
enforced by `_enforce_payload_total_limit()`, which trims description and
footer first; `exact_command` is **never** truncated because the operator
copy-pastes it.

### Terminal-notifier

`notify.notify_event()` sets the title to `DontPanic [{plan_id}]` (D010
brand fix — never `Jarvis [...]`), the subtitle to `event.kind`, and the
message to the first 140 chars of `RenderedEvent.headline`. Brand drift in
source body strings is normalized at render time
(`event_copy.normalize_brand_drift()`); do not edit `supervisor.py`
strings.

### INBOX rendered annotation

`inbox.append_rendered_annotation()` appends only the rendered markdown
block (with a `<details>` fold for technical metadata) — it never writes a
duplicate raw header (D018). The raw entry comes from the
`append_event()` call at the emit site, and that call still happens
unchanged.

### Dashboard sidecar

`operator_console.write_event_action_sidecar()` projects the
`RenderedEvent` into an `ActionItem`-shaped dict and appends one JSON
line to `~/.dontpanic/dashboard/event-actions.jsonl`. The sidecar is
merged into `what-now.json` at both `dashboard.build()` and
`operator_console.write_cache()` (D019) — neither site is optional; both
must call `merge_with_event_sidecar` or the served dashboard goes stale.

## Brand-drift translation (D010)

The renderer rewrites `jarvis approve` → `dontpanic approve`,
`jarvis-orchestrate approve` → `dontpanic approve`, and `Jarvis [` →
`DontPanic [` on every rendered string. Do not edit source body strings
in `supervisor.py` to fix brand drift; the translation happens
exclusively at the render boundary.

## Legacy `breaker:patch_incomplete` (D009)

The only legacy colon-separated INBOX event name authorized for
normalization is `breaker:patch_incomplete`. The renderer rewrites it
internally to `breaker_tripped` + `breaker_kind=patch_incomplete`. Any
other `breaker:<unknown>` value misses the `DISPOSITION_TABLE` lookup
and `render()` returns `None`, so unknown breaker kinds never produce a
fake live notification.

If you genuinely need to add a new breaker kind, add it to
`circuit_breakers.BreakerKind` and rely on the existing
`breaker_tripped` template — the kind is interpolated via
`{breaker_kind}`.

## Sanitization wiring (F004 reference)

Two modes apply at the render boundary:

- **Raise mode** at the sidecar write
  (`operator_console.write_event_action_sidecar` →
  `_assert_no_secret_shapes`) — the operator-fixable boundary. A
  secret-shape match rejects the write.
- **Substitute mode** at every live channel (`notify_discord.notify`,
  `notify.notify_event`, `inbox.append_rendered_annotation`) —
  `state_projection.scrub_secrets` rewrites matches to `[REDACTED]` and
  never raises so the supervisor can't fail-hard on a transient ping.

Routine copy edits don't need to revisit these — they wrap the rendered
output regardless of which template produced it.

## Where everything lives

| File | Role |
| ---- | ---- |
| `scripts/dontpanic_orchestrate/event_copy.py` | RenderedEvent contract, disposition table, translation table, render() function |
| `scripts/dontpanic_orchestrate/command_validation.py` | Token-only CLI validator gating exact_command |
| `scripts/dontpanic_orchestrate/notify_event.py` | NotifyEvent dataclass + dispatch_event() router |
| `scripts/dontpanic_orchestrate/notify_discord.py` | Discord embed sink |
| `scripts/dontpanic_orchestrate/notify.py` | Terminal-notifier sink |
| `scripts/dontpanic_orchestrate/inbox.py` | INBOX append_event + append_rendered_annotation |
| `scripts/dontpanic_orchestrate/operator_console.py` | Dashboard sidecar + cache writers |
| `docs/design/dashboard-value-language-ia-v0/copy-map.md` | Canonical IA value-language vocabulary |
| `scripts/dontpanic_orchestrate/tests/test_event_messaging_snapshots_f005.py` | Cross-channel snapshot harness |
| `scripts/dontpanic_orchestrate/tests/fixtures/event_messaging_snapshots/` | Pinned per-kind snapshot JSON |
