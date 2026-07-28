# Buzz + DontPanic: private-first community topology

**Status:** stable recommendation after plan 2026-07-27-001 F010 dogfood
(fail-soft unconfigured path + private-first topology; live posts deferred
to operator credentials)
**Audience:** operators wiring Buzz notify / gate bridge / caller recipes

## TL;DR

1. Create a **private** Buzz community for real DontPanic work.
2. Point `~/.dontpanic/buzz.json` at that community (relay + channels + reporter key).
3. Leave a public DontPanic community **optional** and **never** the notify default.
4. Keep gate clearance on allowlisted humans + signed ceremony (or the local `dontpanic approve` CLI).

## Why private-first

DontPanic posts **projections** (status, gate links, hashes) — not full agent
transcripts. Even so, plan titles, gate names, and error summaries are often
sensitive. A private community keeps that traffic out of public relays and
reduces the chance someone mistakes a support room for a work channel.

During F010 dogfood, unconfigured `buzz.json` correctly kept the notify sink
silent while multi-vendor volleys ran. That fail-soft path is intentional:
Buzz is an optional surface, not a hard dependency.

## Topology

```
┌─────────────────────────────┐     optional
│  Private team / Silex work  │◄──── public support room
│  • notify defaults          │      (announcements only)
│  • gate status / requests   │
│  • human approvers          │
└─────────────┬───────────────┘
              │ buzz.json
              ▼
        DontPanic CLI
   (dispatch / approve / doctor)
```

## Config sketch

```json
{
  "relay_url": "https://relay.your-team.example",
  "channels": ["<private-channel-uuid>"],
  "reporter_key_ref": "env:BUZZ_PRIVATE_KEY",
  "gate_bridge": {
    "enabled": false
  }
}
```

Enable `gate_bridge` only after human pubkeys and agent denylist are set; see
`docs/GETTING_STARTED.md` for the signed-event ceremony.

## What not to do

- Do not route `notify` defaults to a public community.
- Do not put agent nsecs in `approver_pubkeys`.
- Do not treat reactions/emoji as gate approvals.
- Do not auto-dispatch or auto-approve from Buzz messages without confirm.

## Related

- Plan evidence: `docs/plans/2026-07-27-001-feat-buzz-integration-agent-taxonomy/evidence/buzz-dogfood-f010.md`
- Decision **D007** (resolved) in that plan’s `decisions.jsonl`
- `docs/ECOSYSTEM.md` — Buzz non-goals and caller recipe
