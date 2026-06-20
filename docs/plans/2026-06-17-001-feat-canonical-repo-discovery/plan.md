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
status: active
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
2. **F006 — Backfill evidence schema**: exact C4 evidence file shape and
   malformed/ambiguous classification.
3. **F002 — One-time canonical backfill engine** for the 51 historical records,
   consuming the operator-local evidence captured while the temp worktrees still
   exist.
4. **F003 — Ledger adapter + pure reconciliation function**: read
   `invocations.jsonl` into `observed_canonical` rows, then join registry vs
   observed canonical repos into the registry/usage projection, thresholds/decay
   (C5), durability gating (C3), metadata-only (C6). No CLI, no formatting.
5. **F004 — `discover [--json]` CLI**: thin wrapper that renders F003's
   projection with the privacy boundary (C1) — scrubbed display + keys only,
   add-command path reconstructed operator-locally.
6. **F005 — Backfill operator entrypoint**: exposes the C4-pinned migration
   command, default path resolution, status behavior, and report schema for the
   F002 engine.

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

Any `canonical_repo` written by the ledger writer or backfill MUST use the
scrubbed `path_display` produced by `make_path_pair` / the shared scrubber for
the reconstructed local path. A literal evidence display that resolves under
`Path.home()` is never copied through as raw text; it is normalized to the
`<home>`-scrubbed display before write. If the recomputed scrubbed display cannot
be produced or fails the path-key confirmation, the row is skipped rather than
persisting a raw path.

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
- Invocation records may carry an `observed_count` integer. Legacy records
  without the field count as `1`. `compact_ledger` must sum `observed_count`
  when it collapses duplicate records into one preserved row. Discovery uses
  summed `observed_count`, never raw row count, so C5 thresholds remain
  deterministic before and after ledger compaction.
- If a compaction bucket contains mixed canonical attribution (some rows have
  `canonical_repo` and some do not, or rows carry different `canonical_repo`
  keys), `compact_ledger` must preserve the existing observation bucket behavior
  but **must not** invent a canonical attribution for the compacted row. It marks
  the row `canonical_compaction_conflict=true`, omits canonical discovery fields
  from that compacted row, and discovery ignores it rather than inflating or
  dropping canonical usage counts silently.

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

The evidence file schema is exact:

```json
{
  "schema_version": "1.0",
  "canonical_repos": {
    "<canonical_path_key>": {
      "path_key": "<canonical_path_key>",
      "path_display": "<scrubbed-display>",
      "durable_checkout": true,
      "origin_key": "<optional-origin-key>",
      "observed_under_temp_prefix": true
    }
  },
  "observation_path_key_to_canonical": {
    "<observed_path_key>": ["<canonical_path_key>"]
  }
}
```

Required top-level keys are `schema_version`, `canonical_repos`, and
`observation_path_key_to_canonical`. `schema_version` must be `"1.0"`.
`canonical_repos` is a map keyed by canonical path key; each value may contain
only `path_key`, `path_display`, `durable_checkout`, optional `origin_key`, and
optional `observed_under_temp_prefix`. Required fields are `path_key` (string),
`path_display` (string), and `durable_checkout` (boolean). Optional
`origin_key`, when present, must be a hash-shaped string accepted by the shared
no-secret-shape assertion; raw origin URLs are malformed evidence and must never
be copied. Optional `observed_under_temp_prefix`, when present, is boolean.
`observation_path_key_to_canonical` is a map from observed path key to a list of
canonical path keys. Exactly one entry in that list is confirmable; zero, more
than one, a non-list value, an unknown canonical key, a missing or incorrectly
typed required field, a raw-secret-shaped value, or a canonical object whose
`path_key` differs from its map key is malformed/ambiguous and must skip with a
reason.

Evidence confirmation is deterministic and uses the evidence file as the sole
historical source of truth. For a ledger record lacking `canonical_repo`, a
backfill candidate is **CONFIRMED** iff:

- `record.repo.path_key` appears in `observation_path_key_to_canonical`;
- that observation key maps to exactly one canonical repo key;
- the referenced `canonical_repo` object contains only allowed fields
  `{path_key, path_display, durable_checkout, origin_key?, observed_under_temp_prefix?}`;
- required fields are present with the exact C4 types, optional fields have the
  exact C4 types when present, and `_assert_no_secret_shapes` passes over the
  object before any field is copied;
- `canonical_repo.path_key` matches the mapped canonical key;
- `path_display` is reconstructable by the C1 home-token or literal-display
  rules, and recomputing the path pair from that reconstructed local path yields
  the same `path_key`;
- the reconstructed canonical path is NOT under a temp prefix (`/tmp`,
  `/private/tmp`, `/var/folders`); and
- the canonical display to be written is the recomputed scrubbed display, not the
  raw evidence display.

`origin_key` is copied only from the single confirmed canonical evidence object;
because the schema is keyed by one canonical path key, there is no separate
`origin_key` conflict cell. Any absent observation key, conflicting canonical
key, missing required field, type mismatch, raw-secret-shaped value, `path_key`
mismatch, non-reconstructable scrub token, malformed field, or failed path-key
confirmation is **SKIP + report reason**. A reconstructed
canonical path under a temp prefix, or an evidence row that claims
`durable_checkout=true` for such a temp canonical path, is also **SKIP + report
reason** because it contradicts C3. The backfill does not probe deleted temp
worktrees and does not parse `command`.

The implementation also adds a repo-local guard for overridden
`DONTPANIC_HOME`: `.gitignore` must ignore `.dontpanic/canonical-backfill-evidence.json`,
and tests/doc evidence must prove this operator evidence file is never tracked.

The backfill operator surface is:

```bash
dontpanic projects backfill-canonical [--dry-run] [--json] \
  [--ledger <path>] [--evidence <path>]
```

Default paths are resolved through the same `DONTPANIC_HOME` / global-config
logic as the ledger writer: ledger defaults to `invocation_ledger.ledger_path()`;
evidence defaults to `$DONTPANIC_HOME/canonical-backfill-evidence.json`. `--dry-run`
performs all validation and reports without writing. Exit code contract:

- `0`: command completed; report may include skipped rows.
- `2`: usage error, missing/malformed evidence file, unreadable ledger, or
  atomic write failure.

The JSON report shape is stable for tests and operator use:

```json
{
  "would_stamp": 0,
  "stamped": 0,
  "already_stamped": 0,
  "would_skip": 0,
  "skipped": [{"path_key": "...", "reason": "..."}],
  "ledger_path": "<scrubbed-display>",
  "evidence_path": "<scrubbed-display>",
  "dry_run": true
}
```

Write mode must coordinate with the live invocation writer through the dedicated
**sidecar lock file** defined in C8 — NOT a lock on the ledger data-file inode.
The backfill command acquires the C8 sidecar lock and holds it across the full
read/validate/write/temp-file/rename critical section. Because every writer
acquires the same sidecar lock BEFORE opening the ledger data file, no concurrent
writer can hold a stale data-file inode across the backfill rename. A concurrent
invocation append is therefore serialized after the backfill, or the backfill
fails without replacing the ledger; it can never be lost by an uncoordinated
rename.

Evidence defects split into two tiers. **File-fatal** defects abort the whole run
with exit 2 and stamp nothing: not valid JSON / parse error, missing required
top-level keys, `schema_version != "1.0"`, or a top-level structural type error
(`canonical_repos` not a map, `observation_path_key_to_canonical` not a map).
**Row-level** defects are per-record SKIP + report (exit 0, listed in `skipped`):
an absent observation key, a list mapping to zero or multiple canonicals for that
record, an unknown canonical reference, a missing/mistyped required field or
raw-secret-shaped value on the referenced canonical, a `path_key` mismatch, a
non-reconstructable scrub token, a failed path-key confirmation, or a temp /
durable-contradiction canonical. Row-level skips never abort the run.

### C5 — Decay / thresholds
`discover --json` applies a **minimum recency and count policy from day one**,
with concrete defaults: `window_days = 14`, `min_count = 2`, timestamp field =
`last_seen`. A used-unregistered candidate passes iff
`observed_count >= min_count` **and** `last_seen >= now - window_days` (inclusive
boundary). Missing or invalid `last_seen` fails closed and is excluded from
recommendations. The `discover` command wires these defaults and exposes
overrides (`--window-days`, `--min-count`) that feed the same policy object used
by tests. A repo that is merely present in the append-only ledger is **not** a
recommendation; the ledger is never treated as unbounded fresh product input.

Projection identity is explicit:

- `used_unregistered`, `registered_active`, and `registered_stale` rows are keyed
  by `canonical_repo_key`.
- `registered_path_missing` and `registered_unresolved` rows cannot be keyed by
  `canonical_repo_key` because the path cannot be probed/canonicalized or
  canonicalization failed despite path existence. They are keyed by
  `registry_path_key = sha256(normalized stored registry path)[:16]` plus
  `registry_name`; their `canonical_repo_key` is `null`. F004 JSON preserves this
  shape so missing/unresolved registry rows cannot masquerade as canonical repo
  rows.

Suggested project names are deterministic and safe:

- Derive the base from the basename of the scrubbed canonical `path_display`
  (`<home>/src/DontPanic` -> `DontPanic`; literal outside-home paths use their
  basename). Lowercase it, replace every non-`[a-z0-9-]` character with `-`,
  collapse repeated hyphens, trim leading/trailing hyphens, and use `project` if
  the result is empty.
- The result must match `^[a-z0-9][a-z0-9-]{0,63}$`. If it collides with a
  registered project name or another suggested row, append
  `-<canonical_repo_key[:8]>`, truncating the base so the whole name stays at
  most 64 characters.
- `discover --json` may include `suggested_name` because it is derived from
  scrubbed display + hashed key only. The real path remains human-output only per
  C1.

Registered-row classification is a pinned matrix:

- Missing registered path (`path_exists=false`) -> `registered_path_missing`
  keyed by `registry_name + registry_path_key`, with `canonical_repo_key=null`
  and `canonicalization_status="missing"`.
- Registered path exists, but canonicalization fails -> `registered_unresolved`
  keyed by `registry_name + registry_path_key`, with `canonical_repo_key=null`
  and `canonicalization_status="unresolved"`.
- Explicitly inactive registry entries (`active=false`) -> no
  `registered_active` or `registered_stale` row; they remain inventory only.
- Registered, path exists, not inactive, and no observed row -> `registered_stale`.
- Registered, path exists, not inactive, observed row has missing/invalid
  `last_seen` -> `registered_stale`.
- Registered, path exists, not inactive, observed row has
  `observed_count < min_count` -> `registered_stale`.
- Registered, path exists, not inactive, observed row has
  `last_seen < now - window_days` -> `registered_stale`.
- Registered, path exists, not inactive, and observed row passes both inclusive
  thresholds (`observed_count >= min_count` and
  `last_seen >= now - window_days`) -> `registered_active`.

Emitted observed fields are pinned. A `registered_stale` (or `registered_active`)
row that has **no** observed row emits `observed_count = 0` and `last_seen = null`
(never omitted, never an inflated value). `registered_path_missing` and
`registered_unresolved` rows carry **no** `observed_count`/`last_seen` at all:
their `canonical_repo_key` is `null`, so no observed usage can be joined to them;
they expose only `registry_name`, `registry_path_key`, `path_display`, and
`canonicalization_status` (matching F004's pinned JSON row schema for those two
states). The ledger adapter, when aggregating observed rows by
`canonical_repo_key`, **skips** any contributing record whose `last_seen` is
missing or unparseable rather than letting one bad timestamp fail the whole
canonical row; if every contributing record has an invalid `last_seen`, the
aggregated `last_seen` is `null` and the row fails the recency threshold
(fail-closed).

Duplicate canonicalization is deduped deterministically, and dedup is applied
**only to the set eligible for a `registered_active`/`registered_stale` row** —
i.e. entries with `active=true`, `path_exists=true`, and successful
canonicalization. Inactive (`active=false`), path-missing, and unresolved entries
are **excluded** from the canonical-key dedup and handled solely by their own
matrix rows; an inactive (or path-missing/unresolved) entry can therefore **never**
suppress an active entry for the same `canonical_repo_key`, regardless of
lexicographic order. When two or more such **eligible active** entries canonicalize
to the same `canonical_repo_key`, reconcile emits exactly **one** registered row
for that key, choosing the entry whose `registry_name` sorts lexicographically
first as the winner; the row carries `registry_conflict = true` and
`conflicting_registry_names` (the sorted list of all colliding **active** names) so
the collision is visible rather than silently dropped. Reconcile never emits
multiple rows sharing one `canonical_repo_key`. (Active/inactive eligibility is
determined before winner selection, so the dedup order can never invert the
truth-table outcome.)

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

F004 (`discover`) and F005 (`backfill-canonical`) must carry negative tests or
doc evidence proving they do not install, modify, remove, chain, read, or depend
on git hooks as part of their command paths.

### C8 — Ledger write coordination (sidecar lock)
**Every** writer of `invocations.jsonl` coordinates through a single dedicated
**sidecar lock file** (`<ledger>.lock`, acquired with `flock`), NEVER a lock on the
ledger data-file inode. There are exactly three writers and all three MUST join the
protocol: (1) the **live invocation writer** (F001's append path), (2) the
**ledger compaction** (`compact_ledger`, also F001-owned), which rewrites the whole
ledger via temp-file + atomic rename, and (3) the **one-time backfill** (F002
engine, owned by F005), which also rewrites via temp-file + rename. The protocol:
acquire the sidecar lock BEFORE opening the data file, hold it across the write,
release after. The live append path holds it across open+append; **`compact_ledger`
holds it across its full read+rewrite+temp-file+rename sequence**; the backfill
holds it across read+validate+write+temp-file+rename. Because compaction and
backfill are both whole-file rewrites that end in a rename, each MUST hold the
sidecar across the rename so a concurrent append or the other rewrite can never
strand a stale inode or be lost. Locking a sidecar file (not the data
inode) is what makes the atomic rename safe — a writer can never open the old
inode before the rename and write to the orphaned inode after replacement,
because it must hold the sidecar lock to open at all, and the rewriter (compaction
or backfill) holds that lock across the rename. **This changes the live writer
contract:** both F001's append path AND F001's `compact_ledger` must adopt the
sidecar lock; those changes are in scope and tested (concurrent-append
serialization, and a compaction-vs-append / compaction-vs-backfill race). On any
platform where `flock` is unavailable, any rewriter (compaction or backfill) fails
closed (exit 2) rather than performing an uncoordinated rename.

## Prepared prerequisites

The canonical-backfill evidence file (`~/.dontpanic/canonical-backfill-evidence.json`,
consumed by F002 per C4) is a **prepared operator prerequisite that was already
captured on 2026-06-17**, while the temp worktrees still existed on disk. It was
produced by resolving each observed repo path to its canonical repo via
`git -C <path> rev-parse --git-common-dir` (plus origin) and persisting the
`{observed_path_key -> canonical_repo}` mapping locally (uncommitted, C4). This
capture is a **one-time, time-sensitive operator action**: once `/tmp` is reaped
the temp worktrees vanish and the mapping is unrecoverable, which is why it was
done up front rather than left to implementation time. It is a declared
prerequisite for F002, not a feature this plan builds; F002 consumes it and fails
closed if it is absent or malformed (C4).

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
