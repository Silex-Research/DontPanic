---
id: 2026-06-08-003-fix-audit-findings
title: Fix the 10 Codex-audit findings on the session's merged work
type: fix
tier: cross-cutting
status: active
date: "2026-06-08"
goal_type: bug_fix
description: >
  Remediate all 10 findings from the retroactive cross-model Codex audit of this
  session's six merged plans (PRs #23-#28). Two batched audits both returned
  needs_changes; every finding triaged as a real defect (zero false positives).
  Fix-forward on a branch, TDD, then ONE re-audit before merge.
---

## Target

```yaml
target_env: dev
target_project: none
```

## Findings fixed (all real defects)

Batch 1 — architecture reconciler:
- B1#1 (high): edges stamped confidence=high with no provenance + JS edges
  mislabeled python_import_crawler → high now REQUIRES a citation; `_stamp`
  honours an `extractor` override; JS edges cite the importer + js_import_crawler.
- B1#2 (high): javascript removed wholesale let .ts/.tsx/.jsx pass while the map
  read "high" → typescript/jsx are now tracked unextracted kinds that drop the
  ceiling; DontPanic's own map is honestly capped (it ships unextracted TS/JSX).
- B1#3 (med): JS regex matched imports in comments/strings → single-pass `_mask`
  scanner blanks comments + masks string bodies before the specifier regexes.
- B1#4 (med): dropped export-from / dynamic import() → now extracted (literal)
  or surfaced as unresolved (interpolated/non-literal); never dropped.
- B1#5 (med): reconcile_intent `_resolves` too loose (foo.missing→aligned) →
  exact membership only.
- B1#6 (med): unbounded rglob walked node_modules → os.walk with pruned dirs +
  entry cap.
- B1#7 (low): tautological test (`"javascript" not in <list-of-dicts>`) → asserts
  the evidence_kind set + adds .tsx ceiling-drop negative coverage.

Batch 2 — operator console:
- B2#1 (high): armed-terminal.js was dead code; the REAL dock (terminal-dock.js)
  had no alert semantics → role=alert + assertive aria-live wired into the real
  dock on arm (removed on disarm); terminal-dock.css raw hex → --dp tokens.
- B2#2 (med): surface-state present+null/unparseable timestamp → "ready"
  (fake-fresh) → now demoted to "stale".
- B2#3 (low): journey test was synthetic → new terminal-dock-armed-chrome test
  boots the REAL production dock IIFE with a mocked /terminal/session.

## Verification
Dashboard vitest 1195 + architecture py 395 green; raw audit streams in docs/audits/.
