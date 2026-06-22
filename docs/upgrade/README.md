# Upgrade Release Manifest — authoring guide

This directory holds the **upgrade release manifest** (`releases.json`): the
machine contract that makes a DontPanic instance update-aware. When an operator
`git pull`s a new version, `dontpanic doctor` reads this manifest to tell them
what changed, which operator actions are **required** vs **advisory**, the exact
copyable commands to run, and whether each required migration is already
satisfied on their instance.

The manifest — **not** the prose `CHANGELOG.md`, and **not** the plan ledger — is
the single source of truth for upgrade *intent* (D002). The CHANGELOG stays prose
and links here; the manifest owns the structured action data doctor executes
against.

- **Authoritative copy:** [`docs/upgrade/releases.json`](./releases.json) (this
  directory) — the human-authored manifest.
- **Packaged mirror:** `scripts/dontpanic_orchestrate/data/releases.json` — kept
  byte-identical to the authoritative copy so the installed CLI/wheel loads
  exactly what was authored (a drift test guards equality). Edit the docs copy,
  then mirror it.
- **Schema:** `claude/shared/schemas/v1.0/upgrade-releases.schema.json`
  (canonical) + a byte-identical mirror in
  `scripts/dontpanic_orchestrate/data/`.
- **Loader / model:** `release_manifest.load_release_manifest()` parses and
  validates against the `UpgradeManifest` Pydantic model
  (`upgrade_releases_model.py`). The loader resolves the *packaged* resource via
  `importlib.resources` (D045), so it works from a pip-installed wheel, off-git,
  and from any working directory.

## When does a release need a manifest entry?

Add a manifest entry when a release lands an **operator-visible change that an
upgrading instance should be told about** — the same bar as a root `CHANGELOG.md`
entry (see [`docs/RELEASE_IMPACT.md`](../RELEASE_IMPACT.md)). In particular:

- The release requires the operator to **run something** after pulling (a
  backfill, a migration, a config write, a re-onboard). → a `required` action.
- The release changes operator-visible behavior the operator should **know
  about** but need not act on (a new gate enforced at close, a new advisory). →
  an `advisory` action.
- The release introduces **new CLI surfaces** worth announcing
  (`introduced_commands`).

You do **not** need an entry for internal-only changes (supervisor refactors,
test fixtures, evidence, ledger files) — the same exclusions as the changelog.

The advisory **drift lint** (`upgrade_drift_lint.py`, see below) exists to catch
the omission: it warns when an operator-visible CHANGELOG dated section after the
baseline has no matching manifest entry.

## Manifest shape

```jsonc
{
  "baseline_release": "2026-06-13-pre-experience-readiness",  // see "Baseline scope"
  "baseline_date": "2026-06-13",
  "releases": [
    {
      "id": "2026-06-17-001-canonical-discovery",  // stable, unique manifest-wide (D030)
      "date": "2026-06-17",                          // real YYYY-MM-DD calendar date
      "plan_refs": ["2026-06-17-001"],               // plan ids this release rolls up
      "summary": "…",                                // human one-liner (mirrors CHANGELOG)
      "show_on_first_run": false,                    // first-run advisory policy (see below)
      "actions": [ /* … */ ]
    }
  ]
}
```

Releases are authored **oldest → newest**. Release `id`s must be unique
manifest-wide and action `id`s must be unique within their release (D030), so the
stable surface id `upgrade:<release>:<action>` never collides.

## The full action field set

Every action carries enough for doctor to tell the operator **WHY** it matters,
**WHETHER it applies** to their instance, **WHAT to run**, and **WHAT success
looks like** — not just a bare command.

| Field | Type | Meaning |
|---|---|---|
| `id` | string (required) | Action id, unique within its release (D030). |
| `kind` | `required` \| `advisory` (required) | `required` = the operator must act and the action is probe-gated; `advisory` = informational. |
| `severity` | `critical` \| `recommended` \| `optional` (optional) | Priority hint for rendering/sorting. |
| `title` | string (required) | Short imperative headline. |
| `detail` | string (required) | **The WHY** — why this action exists / what changed. |
| `commands` | `UpgradeCommand[]` | Ordered, exact, copyable commands (see below). Empty for advisories. |
| `introduced_commands` | string[] \| null | New CLI surfaces this release adds, for discovery. Omit (or `null`) on advisories that introduce nothing. |
| `applies_when` | predicate key \| null | **Applicability** predicate. `null` = always applies. Fails OPEN (unknown → show it). |
| `status_probe` | predicate key \| null | **Satisfaction** predicate — the ONLY authority for whether a `required` action is cleared (D004). `null` = no probe (advisory). Fails CLOSED (unknown → still pending). |
| `success_message` | string \| null | Shown when the probe is satisfied. |
| `failure_message` | string \| null | Shown when the probe is unsatisfied. |
| `human_next_step` | string \| null | Plain next step for the operator. |
| `docs_url` | string \| null | Pointer to deeper docs (e.g. `CHANGELOG.md#2026-06-17`). |
| `evidence_uri` | string \| null | Optional pointer to an artifact the action references. |

### `UpgradeCommand`

```jsonc
{ "label": "preview|apply|verify|run", "command": "dontpanic …", "description": "…" }
```

`command` must be a **non-blank** exact string (D047) — it is rendered for the
operator to copy-paste verbatim. `description` is optional human context.

### Required-action invariants (enforced by the model)

A `required` action (`kind: "required"`) is held to extra invariants so it can
never be un-clearable or render an unrunnable checklist:

- **must name a non-empty `status_probe`** (D021) — otherwise no live probe could
  ever clear it.
- **must have a non-empty `commands[]` including an `apply`-labeled command**
  (D029).
- **must include both `apply` and `verify`, in canonical order**
  `preview → apply → verify → run` (D036) — the safe checklist: preview the
  change, apply it, verify it cleared.

Advisory actions may omit `status_probe` and carry empty `commands[]`.

## `show_on_first_run` + the first-run policy

The per-instance marker (`~/.dontpanic/upgrade-state.json`) records
`last_seen_release`, `last_seen_commit`, `dismissed_advisories[]`, and
`first_initialized_at`. The report is a pure **"releases since the marker"** diff.

On a **first run** (no marker yet), DontPanic bootstraps the marker to the latest
release and shows only the advisories whose release has `show_on_first_run: true`.
This prevents an **advisory flood** as the manifest grows — a brand-new instance
should not be hit with every historical advisory. Set `show_on_first_run: true`
only for an advisory genuinely worth showing someone who is starting fresh.

**Required actions are exempt from the first-run dampening.** Their pending-ness
comes ONLY from the live `status_probe`, regardless of the marker (D004/D012), so
a fresh instance still surfaces required migrations that its probe reports as
unsatisfied. `--acknowledge` advances the marker and silences advisory noise
ONLY; it never clears a probe-failing required action.

## How to add a detection predicate

Predicates live in `upgrade_predicates.py`. A predicate is a stable key mapped to
a read-only callable returning a `PredicateResult`
(`{satisfied, detail, evidence_uri, error}`). Two namespaces, two fail directions:

- **`status_probe`** (satisfaction). The SOLE authority for whether a `required`
  action is satisfied — the marker NEVER satisfies a required action (D004). Fails
  **CLOSED**: an unknown key / undeterminable read / raising predicate resolves to
  `satisfied=False` (a typo or degraded read can never silently mark a migration
  done, D026). Register in `STATUS_PROBES`.
- **`applies_when`** (applicability). Gates whether an action is shown to this
  instance at all; `satisfied` is read as *applies*. Fails **OPEN**: an unknown
  key / undeterminable read / raising predicate resolves to `satisfied=True` /
  *applies* (a typo can never silently HIDE required work, D026). Register in
  `APPLIES_WHEN`.

To add one:

1. Write a function `def my_probe(ctx: PredicateContext) -> PredicateResult`. It
   MUST be strictly **read-only** (D028) — never write registry, evidence,
   config, ledger, or any on-disk state. Use the read-only loaders / DI seams on
   `PredicateContext` (`registry`, `ledger_records`, `projection`,
   `evidence_path`) so it is testable without touching real state.
2. Populate `detail` with a human explanation in EVERY branch (so a
   fail-closed/fail-open/unknown result is never an opaque bare boolean). Set
   `error=True` only on a degraded/fail-direction result, not on a clean negative.
3. Register the key in `STATUS_PROBES` or `APPLIES_WHEN`.
4. Reference the key from the action's `status_probe` / `applies_when`.

Resolution always goes through `resolve_status_probe` / `resolve_applies_when`,
which wrap every call so a raising predicate degrades to its fail direction
instead of crashing report assembly.

The seeded examples:

- `canonical_discovery_registered_active` — an **outcome** `status_probe`:
  satisfied iff THIS instance resolves to `registered_active` via the
  canonical-discovery reconcile READ path (it never reads the backfill-evidence
  file; evidence validity does not gate the outcome).
- `canonical_backfill_evidence_valid` — the separate evidence-consuming probe.
- `has_tracked_projects` — an `applies_when` gate (the canonical backfill action
  only applies when the registry has tracked projects).

## Baseline scope

The manifest carries a top-level **baseline** (`baseline_release` +
`baseline_date`) that makes the coverage promise explicit and lint-enforceable
(D018). The baseline sits **strictly below** the earliest seeded release (D039),
so every seeded release is in-scope (above the baseline), and CHANGELOG history
at/before the baseline is intentionally **not** seeded.

v0 coverage = the selected seed releases (the Experience-Readiness +
canonical-discovery rollout) **+ all future manifest-authored releases**. Older
history is out of scope by design — the manifest seeds the rollout *forward* from
the baseline, it does not reconstruct the whole changelog.

## No-mutation boundary (v0)

v0 is **DETECT + EXPLAIN + COPYABLE COMMANDS, NO MUTATION** (D007). `dontpanic
doctor` and every predicate are strictly read-only observations: doctor never
runs a backfill, migration, or config write itself, and a `status_probe` never
writes anything (D028). The manifest provides the exact commands; the **operator**
runs them. Auto-remediation is deferred (it would need per-action safety tiers)
and is explicitly out of scope here.

## Drift lint (advisory, warn-only)

`upgrade_drift_lint.py` asserts that every operator-visible CHANGELOG dated
section **after the baseline** has a matching `releases.json` entry (matched by
date). It is:

- **baseline-scoped** — sections at/before `baseline_date` are exempt (D018);
- **warn-only in v0 (D008)** — it returns advisory findings and never blocks,
  never raises on drift, and its CLI entry point always exits 0.

Run it ad hoc:

```bash
PYTHONPATH=scripts python3 -m dontpanic_orchestrate.upgrade_drift_lint
```

A hard gate would over-constrain before the manifest format settles; drift is
surfaced as advice the release author confirms, not a wall. When you add an
operator-visible CHANGELOG section, the lint reminds you to author the matching
manifest entry here.

## Relationship to the changelogs

- **`CHANGELOG.md`** (repo root) — the prose, product-facing record of
  operator-visible change. It links here and its dated sections are what the drift
  lint checks against the manifest.
- **`docs/RELEASE_IMPACT.md`** — the path/surface checklist that decides whether a
  change needs a changelog entry (and now, a manifest entry).
- **`claude/shared/CHANGELOG.md`** — the agent-conventions subtree changelog
  (schemas / conventions); unrelated to upgrade intent.
