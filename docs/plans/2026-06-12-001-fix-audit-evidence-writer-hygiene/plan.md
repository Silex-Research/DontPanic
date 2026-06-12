---
id: 2026-06-12-001-fix-audit-evidence-writer-hygiene
title: Audit evidence-writer hygiene — capture-time sanitization + re-audit iteration preservation
type: fix
tier: cross-cutting
status: completed
date: "2026-06-12"
goal_type: new_feature
description: >
  Two trust-boundary fixes in the completion-audit evidence writer, both standing
  follow-ups from the PR #46 hollow-verdict incident: (1) envelopes and transcripts
  are sanitized AT CAPTURE TIME (workstation paths and user@host identity become
  placeholders before the first byte is persisted) so committed audit evidence never
  carries PII and never needs post-hoc editing; (2) a re-audit writes the NEXT
  iteration's files instead of overwriting the previous envelope/transcript, so the
  audit trail is append-only across iterations.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
privacy_tier: internal
links:
  features: ./features.json
  objective_contract: ./objective_contract.json
  decisions: ./decisions.jsonl
---

# Audit evidence-writer hygiene

## Target

```yaml
target_env: dev
target_project: none
```

## Problem

The audit layer just caught one real hollow verdict (PR #46). Two adjacent defects
sit in the same trust boundary:

1. **PII at capture time.** `_write_envelope` persists `transcript_path`,
   `envelope_path`, and `raw_response` verbatim — committed envelopes carry
   `/Users/<name>/...` and `user@host`. The standing convention says committed
   evidence is immutable, so the ONLY correct fix point is the writer.
2. **Re-audit overwrite.** Re-running the completion audit writes
   `audit-<auditor>-1.json` again, destroying the prior envelope/transcript in the
   working tree (observed live on plan 2026-06-11-001: the grounded re-audit
   overwrote the hollow iteration-1 artifacts; only git history preserved them).
   An audit trail must be append-only.

## Non-goals

- No retroactive editing of already-committed envelopes (immutability holds).
- No change to envelope schema fields or the disposition parser.
- No change to the secrets scrubber (this is path/identity hygiene, a different class).
