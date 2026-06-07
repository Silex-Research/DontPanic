---
id: 2026-06-06-003-feat-architecture-auto-refresh
title: Architecture auto-refresh — kill the "run regen" human card
type: feat
tier: cross-cutting
status: completed
date: "2026-06-06"
goal_type: new_feature
description: >
  The Architecture tab showed "NO SYSTEM MAP YET → run `dontpanic architecture regen`,
  then rebuild" — a deterministic, no-creds, cwd=repo_root command wrongly assigned to a
  human. The regen infra exists (crawler + pre-commit-hook installer + supervisor
  post-commit hook) but is not wired to run on its own: the hook installer is opt-in and
  installed nowhere, the supervisor hook only fires for orchestrated child commits, and the
  dashboard build only READS the map (a missing/stale one becomes a permanent human card).
  This plan makes architecture refresh automatic. F001 (shipped): the build self-heals a
  missing/stale map into the dashboard CACHE only — never the tracked repo's working tree —
  so the tab always reflects current truth without a human command. F002/F003 (next):
  watch architecture.json so the serve refreshes live, and auto-install the pre-commit hook
  on `projects add` so every tracked repo stays committed-fresh. Cache-only-for-display +
  hook-commits chosen by operator (no surprise git changes in tracked repos).
links:
  objective_contract: ./objective_contract.json
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
---

## Context

Operator hit "NO SYSTEM MAP YET" on the quantre-migration Architecture tab. Root cause was
threefold: (1) they ran regen in the DontPanic repo, not the project the tab is scoped to;
(2) DontPanic is not a registered project; (3) the serve watcher ignores architecture.json.
The deeper issue: a fully-automatable refresh was a human chore. See decisions.jsonl D001.

## Features

- **F001 (done)** regen-on-build, cache-only: build self-heals missing/stale maps into the
  dashboard cache; tracked repo working tree untouched; fingerprint check keeps fresh
  builds cheap.
- **F002 (next)** watch architecture.json: include each project's snapshot in the serve's
  watched sources so a hook-commit / manual regen retriggers the rebuild live.
- **F003 (next)** auto-install the pre-commit hook on `projects add` (with `--no-hooks`
  opt-out) so every tracked repo auto-regens + stages the committed map on commit.
