---
id: 2026-06-17-001-feat-canonical-repo-discovery
title: Usage-driven canonical-repo discovery — ledger writer, backfill, discover --json
description: |
  Make the DontPanic fleet dashboard honest about *where DontPanic is actually
  being used*, without ever recommending throwaway temp worktrees as projects.
  The fleet dashboard today only renders explicitly-registered projects, so an
  operator dogfooding DontPanic from temp worktrees sees none of their real
  activity. The fix is NOT a dashboard-render-time reconciliation — observed
  paths are lossy (hashed + home-scrubbed) and temp worktrees are deleted before
  the dashboard runs. Instead, stamp a durable canonical-repo identity onto each
  invocation record at WRITE time (while the worktree still exists), backfill the
  historical records once, and expose a registry-vs-observed reconciliation as a
  metadata-only `discover --json` contract. Rich discovery UI is deferred until
  real multi-project usage data exists.
type: feat
tier: cross-cutting
status: draft
date: "2026-06-17"
goal_type: new_feature
surfaces:
  - infra
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
  no_progress_threshold: 2
  wall_clock_hours: 8
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-03-001-feat-global-install-project-registry
  - 2026-05-23-005-feat-dashboard-project-selector-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  objective_contract: ./objective_contract.json
---

# Usage-Driven Canonical-Repo Discovery

## Target

```yaml
target_env: dev
target_project: none
```

This plan operates entirely on the operator-local DontPanic install (the ledger,
the registry, and the `dontpanic` CLI on this host). There is no cloud project.

## Motivation

The fleet dashboard answers "what needs action across my projects?" but it only
models **registered** projects. It silently equates "registered projects" with
"where DontPanic is used" — and that equation is false. On the operator's own
install, every one of the last 51 invocations was DontPanic operating on itself,
run from temp worktrees (`/private/tmp/dontpanic-p2a` ×24,
`/private/tmp/dontpanic-p2-lock` ×17, the canonical checkout ×10). None of the
two registered projects had recent activity. The dashboard therefore showed the
two *least*-active repos and hid 100% of the real work. That breaks operator
trust: the surface presents curated registry state as if it were observed truth.

The naive fix — have the dashboard read the invocation ledger and recommend
untracked repos — fails against the real data, and fails in the worst possible
direction. Two confirmed facts:

1. **`path_key` is observation identity, not project identity.** It is
   `sha256(literal_abspath)[:16]` (`invocation_ledger.py`). The same repo run
   from three paths produces three different keys. Grouping on `path_key`
   fragments one repo into three phantom "projects."

2. **Observed evidence is lossy and ephemeral.** Records persist a home-scrubbed
   `path_display` and a one-way hash. Temp worktrees are deleted on cleanup, so
   a dashboard-time `git` probe cannot recover canonical identity — and a
   count-ranked recommender would surface the highest-volume temp paths first.
   That is exactly the regression we must prevent: "DontPanic is invisible"
   would become "DontPanic recommends `/private/tmp` junk."

The correct fix moves canonicalization to the **ledger writer**, where the repo
or worktree still exists on disk and `git rev-parse --git-common-dir` / origin
resolution succeed. Discovery then groups on a field that is present and
correct, never re-derived from lossy evidence. Observation identity
(`repo.path_key`) is preserved untouched for conflict/bucket semantics.

## Sequence

1. **F001 — Ledger writer stamps canonical repo identity** (prerequisite).
2. **F002 — One-time canonical backfill** of the 51 historical records, consuming
   the operator-local evidence captured while the temp worktrees still exist.
3. **F003 — Ledger adapter + pure reconciliation function**: read
   `invocations.jsonl` into `observed_canonical` rows, then join registry vs
   observed canonical repos into the four-state projection, thresholds/decay
   (C5), durability gating (C3), metadata-only (C6). No CLI, no formatting.
4. **F004 — `discover [--json]` CLI**: thin wrapper that renders F003's
   projection with the privacy boundary (C1) — scrubbed display + keys only,
   add-command path reconstructed operator-locally.

F003 and F004 are split so each fits a single sized dispatch (pure logic vs CLI
surface), per the sizing discipline; together they are the "discover --json"
step of the agreed sequence. Rich discovery UI (a collapsed What-Now advisory, a
selector count badge, a passive cwd nudge) is **explicitly deferred** to a later
demand-gated feature so that dismiss/decay policy is designed against real
multi-project signal, not a dogfooding artifact (see Deferred).

## Contracts (binding — these gate implementation, not folklore)

These seven contracts MUST be satisfied by the implementation. Each is mirrored
as an accepted decision in `decisions.jsonl` and referenced by feature
acceptance. A change to any of them is a scope change requiring operator
sign-off.

### C1 — Storage / privacy boundary
Real absolute canonical paths are **local-only**. The ledger and any dashboard
state JSON keep the **sanitized display** (`<home>`-scrubbed `path_display`) plus
the **stable hashed key** (`canonical_repo_key`). No raw home path is ever written
to the ledger or mirrored into served dashboard JSON.

A real absolute path may appear in a generated `dontpanic projects add` command
only when reconstructed **operator-locally at read time**, by exactly one of
these rules (no other source; never fabricate a path):

- **Home-scrubbed display** (`path_display` contains the `<home>` token):
  reconstruct by substituting `str(Path.home())` for `<home>`. Emit the full
  `dontpanic projects add <name> <real_path>`.
- **Literal display** (no scrub token — e.g. a canonical path that lives outside
  `$HOME`): use `path_display` verbatim as the path. (Temp paths never reach
  here per C3; a literal non-temp path is a real durable directory.)
- **Non-reconstructable display** (contains a scrub token other than `<home>`,
  e.g. `<operator>` / `<host>`, that cannot be safely re-expanded locally): emit
  a **placeholder** command with a literal `<path>` argument (mirroring the
  existing `UnknownProjectError.add_command`) and mark the row needs-manual-path.
  Do **not** guess the path.

Render modality is binding:

- `discover --json` **never** serializes a reconstructed raw add path. It carries
  only scrubbed display, hashed keys, counts, recency, and a suggestion status
  such as `can_render_command` / `needs_manual_path`.
- Default human output may print a locally reconstructed
  `dontpanic projects add ...` command using the three rules above.

In every case the operator runs the command themselves (no dashboard mutation).
The reconstructed path is computed in the read-time process and never persisted
or served. This must pass the existing `_assert_no_secret_shapes` /
`scrub_secrets` checks.

### C2 — Canonical repo contract
- `repo` = the **observed execution directory** (the worktree/checkout the command
  ran in). `repo.path_key` is **observation identity**.
- `canonical_repo` = the **durable project identity** used for discovery, with
  fields `{ path_key, path_display, durable_checkout, origin_key? }`. It is
  **nullable**: a record may legitimately carry **no** `canonical_repo` (see C3
  case 3). Discovery treats an absent `canonical_repo` as "no attribution."
- `canonical_repo.durable_checkout` is a property of **the canonical repo**, NOT
  of the observed path: it is `true` iff the canonical repo root is a durable
  (non-temp, on-disk-stable) checkout. A temp *worktree* of a durable repo
  therefore yields `canonical_repo` = the durable repo with `durable_checkout =
  true` — that is exactly the dogfooding usage discovery must surface.
- `canonical_repo_key` **MUST NOT replace** `repo.path_key` in invocation
  bucket / conflict / locality logic. Observation identity and discovery
  identity are different equivalence classes and stay separate. Existing
  `_bucket_key` / conflict behavior is unchanged.

### C3 — Canonical attribution & durability gating (three disjoint cases)
A temp path (`/tmp`, `/private/tmp`, `/var/folders`) is **never stamped as a
`canonical_repo`** and is **never** recommended as a project. Resolution at write
time falls into exactly one of three named cases; each is implemented and tested
separately:

1. **Durable + git-resolvable** — observed path is NOT under a temp prefix and
   `git` resolves a canonical root: `canonical_repo` = that root,
   `durable_checkout = true`.
2. **Durable + non-git** — observed path is NOT under a temp prefix and is not a
   git repo: `canonical_repo` = **self** (the observed durable root),
   `durable_checkout = true`. (A real directory you operated in; discovery may
   surface it.)
3. **Temp-observed** — observed path IS under a temp prefix:
   - 3a. If `git` resolves the temp worktree to a **durable** (non-temp)
     canonical root, `canonical_repo` = that durable root, `durable_checkout =
     true`. Usage is attributed to the durable repo (the dogfooding case).
   - 3b. If resolution fails **or** the resolved canonical root is itself under a
     temp prefix, **no `canonical_repo` is stamped** (field absent),
     `durable_checkout` is not set. Fail-closed: recommend nothing, never the
     temp path.

Discovery (C5) only ever recommends candidates whose `canonical_repo` is present
**and** `durable_checkout = true`. The self-canonical path is reserved for case 2
(durable non-git) only — a temp path is never self-canonicalized.

### C4 — Backfill source of truth
The captured `~/.dontpanic/canonical-backfill-evidence.json` is treated as
**local operator evidence, NOT committed** to the repo. The backfill command
consumes it **idempotently** (re-runnable, no duplicate mutation) and **refuses
ambiguous mappings** (a record whose observation key maps to more than one
canonical repo, or whose canonical repo cannot be confirmed, is left untouched
and reported, never guessed).

Evidence confirmation is deterministic and uses the evidence file as the sole
historical source of truth. For a ledger record lacking `canonical_repo`, a
backfill candidate is **CONFIRMED** iff:

- `record.repo.path_key` appears in `observation_path_key_to_canonical`;
- that observation key maps to exactly one canonical repo key;
- the referenced `canonical_repo` object contains only allowed fields
  `{path_key, path_display, durable_checkout, origin_key?, observed_under_temp_prefix?}`;
- `canonical_repo.path_key` matches the mapped canonical key;
- any `origin_key` present in multiple evidence entries for the same canonical
  key is identical; and
- `path_display` is reconstructable by the C1 home-token or literal-display
  rules, and recomputing the path pair from that reconstructed local path yields
  the same `path_key`.

Any absent observation key, conflicting canonical key, `path_key` mismatch,
`origin_key` mismatch, non-reconstructable scrub token, malformed field, or
failed path-key confirmation is **SKIP + report reason**. The backfill does not
probe deleted temp worktrees and does not parse `command`.

The implementation also adds a repo-local guard for overridden
`DONTPANIC_HOME`: `.gitignore` must ignore `.dontpanic/canonical-backfill-evidence.json`,
and tests/doc evidence must prove this operator evidence file is never tracked.

### C5 — Decay / thresholds
`discover --json` applies a **minimum recency and count policy from day one**,
even if conservative (e.g. observed within N days AND ≥ M invocations).
A repo that is merely present in the append-only ledger is **not** a
recommendation. Thresholds are explicit, documented, and tested — the ledger is
never treated as unbounded fresh product input.

### C6 — No command parsing
Discovery derives **only** from structured `repo` / `canonical_repo` metadata and
timestamps. It **never** reads, parses, or surfaces the free-text `command`
field (which can contain large narrative overrides and internal vocabulary).
This is an acceptance assertion, not a guideline.

### C7 — No unrelated install side effects in review
The architecture pre-commit hook that `dontpanic projects add` installs is
**out of scope** for this plan and was removed before branching (no prior hook
existed to chain). This plan does not depend on or modify git-hook behavior;
any hook change would be a separate plan.

## Non-goals

- No dashboard render-time worktree grouping (structurally impossible from lossy
  evidence — see Motivation).
- No one-click registration / dashboard mutation; registration stays a
  copyable, human-decided `dontpanic projects add`.
- No per-repo nagging ActionItems. Only `registered-path-missing` (an existing
  build warning) is a legitimate registry ActionItem, and it is out of this
  plan's scope.
- No Firebase / remote anything.

## Deferred (demand-gated, not in this plan)

- Dashboard honesty disclosure line ("Fleet dashboard shows registered projects
  only") and passive cwd "current repo not tracked" banner.
- One collapsed What-Now advisory consuming `discover --json`, plus a selector
  count badge (one producer, one `dedupe_key`, badge-not-rows).
- These ship once real multi-project usage data exists, so dismiss/ignore-list
  and decay policy are tuned against genuine untracked projects.

## Acceptance evidence

See `objective_contract.json`. Each feature is verified by the implementer
envelope, an independent codex audit, and operator sign-off, with file and test
evidence refs. F003's acceptance includes a metadata-only assertion (C6) and a
durability-gating fixture (C3) proving temp paths are never recommended; F004's
acceptance asserts no raw home path appears in the `discover --json` output (C1).
