# F010 — Buzz + DontPanic dogfood notes (2026-07-28)

Short capture after shipping F006/F007 (notify + caller recipe) and running this
plan’s multi-vendor volleys with the **Buzz CLI installed** on the host
(`~/.local/bin/buzz`) but **no** `~/.dontpanic/buzz.json` and **no**
`BUZZ_PRIVATE_KEY` in the agent environment (credential provisioning is
human-only). Live channel posts were therefore not exercised; the observed
usage pattern is the **fail-soft unconfigured** path plus product topology.

## What we actually ran

| Surface | Observed |
|--------|----------|
| Private community | Recommended default (Silex or any private team space). Not required for CLI delivery. |
| `buzz` binary | Present; `buzz --help` works. Relies on `BUZZ_RELAY_URL` + `BUZZ_PRIVATE_KEY` for relay I/O. |
| `notify_buzz` during dispatch | Fail-soft: `[notify_buzz] buzz.json not configured; sink silent.` — repeated across F014–F016 volleys; continued; no crash, no secrets leaked. **This is a real operational usage pattern.** |
| Public DontPanic community | **Not stood up** for this plan. No evidence it would help delivery; risk of noise/secrets if used as a notify default. |
| Gate bridge (F008) | Implemented off-by-default with signed-event ceremony; not dogfooded end-to-end against a live relay (no `buzz.json`). |
| Live status posts | **Blocked on human credentials** — no nsec/env key available to the agent session. Follow-up for the human: write `~/.dontpanic/buzz.json` pointing at a private community and re-run a single dispatch to confirm channel UX. |

## Patterns that worked (or are safe to recommend)

1. **Private community first.** Point `~/.dontpanic/buzz.json` at a private
   community for status projections and human gates. Keep agent reporter keys
   separate from human approver keys (F008 `agent_pubkeys` denylist).
2. **Fail-soft notify is the right default.** Unconfigured or missing `buzz`
   binary must never block implementer/auditor volleys. Operators opt in by
   writing `buzz.json`.
3. **Buzz as caller, not authority.** Dispatch and gate clearance stay on the
   DontPanic confirm-gated CLI (`examples/buzz-caller/`). Buzz posts
   *projections* (summaries, gate status, links) — never full transcripts or
   secrets (ECOSYSTEM.md).
4. **Signed ceremony for remote approve (F008).** If you enable the gate
   bridge, use the exact content `dontpanic approve plan=<id> gate=<gate>`
   under a BIP-340 signature. Reactions/emoji never auto-confirm.

## What broke or stayed incomplete

- No live `buzz.json` on the plan worktree → notify stayed silent; we could not
  validate channel UX (thread density, reaction fatigue) beyond unit tests.
- Public community still unproven; standing one up “because we can” would only
  create a support surface without a clear audience.
- Multi-vendor volleys hit patch-completeness friction on untracked tests more
  often than Buzz friction — operational, not Buzz-specific.

## Recommendation (closes D007 direction)

| Use | Channel |
|-----|---------|
| Real plans, gates, notify defaults | **Private** community (team/Silex private workspace) |
| Announcements / non-sensitive recipes | Optional public DontPanic community **later**, never as notify default |
| Agent status posts | Reporter key only; never human approver allowlist |
| Approve gates from Buzz | F008 bridge off-by-default; signed ceremony + allowlisted humans |

**Public DontPanic community:** defer. Worth running only if maintainers want a
support room and can keep it free of secrets and gate traffic. Not required for
product completeness.

## D007 status

Updated in `decisions.jsonl` to **resolved** with this private-first topology
as the stable pattern.
