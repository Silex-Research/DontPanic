# Roadmap — Install UX + Architecture Map v0 (revised v1)

**Date drafted:** 2026-05-19 (v0); revised same day per operator review (v1)
**Status:** draft — for operator approval
**Motivation:** First real user hit install friction (missing GitHub token, wrong Python version, no codex CLI). v4.1 closed the harness frictions; v5 candidates are speculative; the only item with *real user pain* attached is install UX.

---

## Revisions from v0

Operator review caught six sequencing + scope issues plus two use-case gaps:

1. **Plan 5 (agent-conventions remote) moved ahead of Plan 3 (schema fix)** — Plan 3 bumps the schema; needs a remote to ship it.
2. **Plan 3 (schema fix) moved ahead of Plan 2 (install UX)** — Plan 2 expands doctor into a first-touch authority. Don't widen the doctor on top of a known false-fail.
3. **Plan 2 split into F001 (ship-fast) vs F002-F004 (full polish)** — F001 alone materially improves first-user pain; subsequent features are additive.
4. **Plan 4 architecture auto-commit downgraded** — Supervisor regenerates the map into the working tree + emits INBOX event + doctor warning. NO automatic follow-on commits. Explicit `dontpanic architecture commit` or plan-owned commit policy required.
5. **Plan 4 R8 decided: track `architecture.json`, gitignore `architecture.html`** — Fresh clones get machine-readable context; humans regenerate HTML locally; no noisy HTML diffs.
6. **Plan 4 F005 pre-commit hook defaults to warn-only** — Detect stale map + print exact regen command. `--auto-regen` is opt-in. Hooks that silently mutate are footguns.
7. **Doctor adds `--profile=` filtering** — Firebase/gcloud is irrelevant for a terminal-only `--profile=core` user. Profiles: `core`, `discord`, `firebase-dashboard`, `openclaw`, `ci`.
8. **GitHub PAT scope is conditional on workflow** — `gh auth status` is enough for most flows; don't blanket-require a PAT.
9. **Hermes citation tightened** — Vocabulary table + link only. No rebrand, no origin story, no positioning paragraph.

---

## Executive Summary (revised order)

| Order | Plan ID | Title | Status | Cost | Why this slot |
|---|---|---|---|---|---|
| 1 | Plan 1 | Housekeeping + tiny Hermes vocab cite | not-locked | 0 paid | Free; clears noise |
| 2 | Plan 5 | agent-conventions GitHub remote | not-locked | 0 paid (~1 hr operator) | Prerequisite for Plan 3 |
| 3 | Plan 3 | Plan schema mismatch fix | not-locked | ~5-8M | Quiet timebomb; pairs with v1.9.0 schema release |
| 4 | Plan 2 F001 | Doctor widening (declarative probes + JSON + profiles) | not-locked | ~5-8M | Ship-fast; materially fixes first-user pain alone |
| 5 | Plan 2 F002-F004 | `init`, smoke test, HTML report | not-locked | ~10-15M | Polish layer on top of F001 |
| 6 | Plan 4 | Architecture map with drift detection | not-locked | ~10-15M | Validates HTML pattern + adds drift surface |
| **— parallel —** | Plan 6 | Credential setup [operator] | operator-only | ~30-60 min operator | Runs alongside #2-#6 |
| 7 | Plan 7 | Plan 004 F003-F005 + Plan 010 F003 | locked, gated | ~40-60M | Unlocks once credentials land |
| 8 | Plan 8 | v5 candidates | deferred | — | Wait for cluster trigger |

**Total paid LLM cost for #1-#6 ≈ ~30-45M tokens** (one v4.1-sized session). Plus #7 ≈ ~40-60M when credentials land.

---

## Plan 1 — Housekeeping + tiny Hermes vocab cite

**Plan ID candidate:** `2026-05-19-001-fix-housekeeping-hermes-vocab`
**Status:** not-locked
**Type:** fix / docs
**Dependencies:** none
**Estimated cost:** 0 paid LLM volleys (operator hand-edit, ~10 min)

### Core requirements

- Delete Finder dupes: `INBOX 2.md`, `events 2.jsonl`
- Add a small (≤20-line) "Vocabulary" section to README mapping DontPanic terms to Hermes terms. **Table only**: no positioning paragraph, no origin story, no "dependency" framing.
- One inline link to Saboo's cheat sheet for readers who want the conceptual framing.

### Acceptance principles

- Both dupe files removed; sanitization stays clean
- Vocabulary section is a table + link, nothing more. Reader who knows neither can scan it in 30s.
- Hermes is positioned as "the conceptual pattern, also known as." DontPanic is the product.

### Out of scope

- Larger README overhaul (deferred — see Open Questions)
- Any architecture diagram (that's Plan 4's job)

---

## Plan 5 — agent-conventions GitHub remote + public-readiness audit

**Plan ID candidate:** `2026-05-19-005-infra-agent-conventions-public-ready`
**Executes:** 2nd
**Status:** not-locked
**Type:** infra
**Dependencies:** none
**Estimated cost:** 0 paid LLM volleys (operator hand-work, ~2 hours)

### Motivation

agent-conventions is local-only. Plan 3 bumps the schema to v1.9.0; without a remote, downstream consumers (Jarvis, Glam, SpinDineSwift, DontPanic) can't pull it cleanly. Must precede Plan 3.

**Scope expanded per operator review:** once agent-conventions becomes the canonical schema source consumed by 4+ downstream projects, going public is a one-way door. Treat this as a full public-readiness audit, not just `git remote add`.

### Core requirements

- **R1 — Sanitization scan.** Run a sanitization sweep over the entire agent-conventions repo (all commits in history, not just `HEAD`): scan for secrets, API keys, tokens, personal email addresses, `jarvis-a6ee1` / other private project IDs, local machine paths (`/Users/bayesian/...`), and operator-private identifiers. Use `gitleaks` or equivalent for full-history scan; fix any hits before push (rewrite history if necessary, or decide to scrub-and-restart). Confirm `sanitization_check` patterns cover the relevant shapes.

- **R2 — History + tag review.** Walk every commit message in the v1.0.0 → v1.8.0 history. Confirm: no leaked secrets in commit messages, no internal project references that don't belong public, no Co-Authored-By entries with personal emails (use `noreply@anthropic.com` pattern from existing Claude commits). All 8+ tags push cleanly; no squashing.

- **R3 — README first-paragraph contract.** First paragraph (≤4 sentences) MUST state: "agent-conventions is a shared schema repository consumed via `git subtree` by downstream agent projects (DontPanic, Jarvis, Glam, SpinDineSwift). It defines the canonical schemas (plan, features, audit, environments, signoff, state-snapshot, objective-contract) and their Pydantic mirrors that those projects validate against." Reader who lands cold understands purpose in one paragraph.

- **R4 — License present or explicit deferral.** Add a `LICENSE` file (MIT, Apache 2.0, or operator-chosen) OR a top-level note in README explicitly stating "license TBD — do not depend on this repo until a license is added." Default suggestion: MIT (matches the DontPanic OSS-readiness pattern from existing F022). No quiet absence — readers must know the licensing posture.

- **R5 — CI validates schemas + models.** GitHub Actions workflow runs on every push + PR: validates all schemas with `jsonschema`, imports + smoke-tests every Pydantic model, runs any existing validator scripts (`validate.py`). Green CI is a prerequisite for downstream projects to trust a subtree-pull. Lift from existing F022 patterns where possible.

- **R6 — No local-machine paths or private project IDs in public-facing docs.** Grep every `*.md` file, `README.md`, `CHANGELOG.md`, any examples in `schemas/` for: `/Users/bayesian`, `~/Documents`, `jarvis-a6ee1`, `glam-styln-dev`, `glam-ac11e`, `axiom-workspace-5eebd`, `spindine-*`, the operator's email, or any GitHub user handle that isn't a generic placeholder. Replace with placeholders (`<your-project-id>`, `~/.your-app/`). Document the canonical placeholders in CONTRIBUTING.md.

- **R7 — Downstream consumers documented.** README lists known consumers (DontPanic, Jarvis, Glam, SpinDineSwift) + a "how to subtree-pull updates" section with the exact command pattern.

- **R8 — Repo lives at operator-chosen org.** See Open Question 1.

### Acceptance principles

- Full-history sanitization scan returns zero hits (or all hits resolved)
- All 8+ existing tags (v1.0.0 → v1.8.0) visible on the remote
- A fresh clone passes CI on first push
- README first paragraph matches R3 contract; passes operator readability check ("would a stranger understand this in 30s?")
- LICENSE file present, or README explicitly defers
- No `/Users/bayesian/`, `jarvis-a6ee1`, or operator-email strings in any `.md` outside `docs/plans/` (or other documented exception locations)
- CI workflow green on the first commit pushed to the remote

### Out of scope

- Marketing the repo, writing a launch post, or driving stars
- Migrating consumers off of subtree to a different distribution mechanism (e.g., PyPI package) — that's a v1 candidate
- Auto-publishing schemas as a npm/PyPI package on tag push — future enhancement

---

## Plan 3 — Plan schema mismatch fix

**Plan ID candidate:** `2026-05-19-003-fix-plan-schema-orchestration-fields`
**Executes:** 3rd
**Status:** not-locked
**Type:** fix
**Dependencies:** Plan 5 (needs remote to ship the schema bump cleanly)
**Estimated cost:** 1 paid volley, ~5-8M tokens

### Motivation

Every locked plan since v3 uses `orchestration`, `child_charter`, `commit_policy` keys in plan.md frontmatter. Runtime accepts them; strict `jsonschema.validate` rejects them as `additionalProperties not allowed`.

Quiet timebomb: if a future doctor or CI step hardens validation (Plan 2 may do exactly this), every locked plan since v3 fails. Plan 2's doctor widening should NOT land on top of a known false-fail — fix this first.

### Core requirements

- **R1 — Additive only.** Add the three properties to `plan.schema.json` as documented `object` types with internal structure. No new `required` fields. Existing plans validate after fix.
- **R2 — Both repos in sync.** Bump agent-conventions VERSION 1.8.0 → 1.9.0. Subtree-pull into DontPanic `claude/shared/`. Operator pushes upstream after merge (Plan 5 makes this possible).
- **R3 — Backfill doctor check.** New `dontpanic doctor --validate-plans-strict` mode walks all locked plans + runs full jsonschema validation. Defaults to advisory. After this fix, all locked plans pass.
- **R4 — Document field shapes.** Each new property has a `description` in the schema explaining purpose + example. Future authors don't guess.

### Feature outline

- **F001 — Extend plan.schema.json + Pydantic mirror.** Add `orchestration`, `child_charter`, `commit_policy` as documented properties. Update `agent-conventions/schemas/v1.0/models/plan_model.py`. Bump VERSION + CHANGELOG.
- **F002 — Subtree sync into DontPanic.** Same operator-handled pattern as v4.1 F001/D003 (implementer edits DontPanic mirror; operator handles upstream push out-of-band).
- **F003 — Doctor strict-validate check.** Walks locked plans, runs full jsonschema validation, emits findings. Default = advisory; `--validate-plans-strict` = blocker.

### Acceptance principles

- All existing locked plans validate clean against the updated schema (no regressions)
- New properties documented with shapes + examples
- Doctor strict-validate finds zero blockers across the current locked plan set
- agent-conventions VERSION bumped + subtree clean diff
- v1.9.0 tag pushed upstream (via Plan 5's remote)

---

## Plan 2 — Install UX hardening v0  ★ PRIMARY ★

**Plan ID candidate:** `2026-05-19-002-feat-install-ux-hardening-v0`
**Executes:** 4th (F001) + 5th (F002-F004)
**Status:** not-locked
**Type:** feat
**Dependencies:** Plan 3 (schema fix must land first; otherwise doctor's strict mode false-fails)
**Estimated cost:** 2-3 paid volleys, ~15-25M tokens total (F001 alone is ~5-8M)

### Sequencing within Plan 2

**F001 ships independently and is the first material improvement to first-user pain.** Operator can pause after F001 to assess actual delta before committing tokens to F002-F004. The full polish layer is sequenced after F001 closes.

### Motivation

First real user hit three install blockers in sequence:
1. GitHub PAT missing (silently, until first `git push`)
2. Python version wrong (3.10+ required for `|` union types; firebase_admin warned of 3.10.13 deprecation)
3. Codex CLI not installed (silent until first `--auditor codex` dispatch)

Each blocker was *discoverable* only after a failure. The doctor exists but doesn't probe these three.

### Design principles (Clawy-inverted)

**Steal:**
- Declarative prereq table (one component, N rows)
- Inline version-aware error copy
- Per-prereq optional screencast
- "Skip for now" escape hatches

**Invert:**
- Auto-detect first, prompt second
- Bounded preflight (≤10s) instead of "60 seconds" marketing
- Re-runnable after each fix without restart

### Core requirements

- **R1 — Doctor probes external dependencies, profile-aware.** Probe table (initial). Each row: `{name, probe_command, version_constraint, fix_url, fix_command, auto_install_safe, why_needed, required_for_profiles}`. Profiles:
  - `core` — Python ≥3.10, claude CLI, git user.email, network to api.anthropic.com
  - `discord` — adds Discord webhook URL + sanitization regex
  - `firebase-dashboard` — adds Firebase auth, gcloud, SA key, target-project
  - `openclaw` — adds OpenRouter key, openclaw CLI (if applicable)
  - `ci` — adds GitHub Actions runner constraints
  
  Default profile = `core`. Selecting a profile filters which prereqs are red vs irrelevant. **Firebase auth is not a blocker for `--profile=core`.**

- **R2 — GitHub auth is conditional on workflow.** `gh auth status` is sufficient for most flows. Don't require a separate PAT unless the selected profile/workflow needs scoped pushes (e.g., `--profile=ci` or `--workflow=push-required`). Don't flag PAT-missing as red for read-only use.

- **R3 — Output is dual-channel.** Pretty terminal output for humans (red/green checkboxes, copy-paste commands), structured JSON for agents (`dontpanic doctor --json` with stable schema, exit code 0 = ready / 1 = warnings / 2 = blockers).

- **R4 — `dontpanic init` is interactive + idempotent.** Runs doctor for selected profile, presents checklist, offers safe auto-fixes (`brew install codex`, `pip install -e .`), prompts copy-paste for unsafe ones (token creation, SA key). Re-runnable mid-install. `--non-interactive` flag for agent installs that errors with structured output instead of prompting.

- **R5 — Smoke test post-install.** Synthetic plan dispatch using mocked executors (no paid API calls). Exercises supervisor end-to-end. Confirms install actually works before user wastes tokens.

- **R6 — HTML install report** (Thariq pattern). Single-page artifact: green/red prereq checklist, copy-paste fix commands, "what's next" panel, link to README + Hermes cheat sheet. Generated by `dontpanic init` and `dontpanic doctor --report`.

- **R7 — Bounded preflight time.** Full sweep ≤10s. Network probes capped at 2s each, run in parallel.

- **R8 — No silent failures.** Every probe has a `fix_url` and `fix_command` (or escalation message). Doctor exits with structured "what to do next" if anything is red.

### Feature outline

- **F001 — Declarative prereq table + doctor widening + profile filtering + JSON output.** ★ Independently shippable ★
  Adds `PrereqProbe` dataclass, profile registry, ~10 initial probes, `--profile=` flag, `--json` flag with stable schema. Network probes parallel + capped. Default profile = `core`. Conditional GitHub auth language. **Land + assess delta before committing to F002-F004.**
- **F002 — `dontpanic init` interactive installer.** New CLI subcommand. Runs doctor, renders checklist, executes safe auto-fixes, prompts for unsafe ones. `--non-interactive` mode. Idempotent re-runs.
- **F003 — Smoke test harness.** Synthetic plan + mocked executors that exercises `dispatch_volley` end-to-end without paid API calls. Wired into `dontpanic init` as the final step + available standalone as `dontpanic smoke`.
- **F004 — HTML install report.** Single-page artifact generated by `dontpanic init --report` or `dontpanic doctor --report`. Joyful design (per Thariq), mobile-responsive, copy-paste-friendly.

### Acceptance principles

- F001 alone: new user running `dontpanic doctor --profile=core --json` gets accurate red/green for the three blockers the first user hit, in ≤10s
- F002-F004 fully integrated: new user with zero DontPanic-specific setup can run `git clone && cd DontPanic && dontpanic init` and get to either (a) ready-to-dispatch state or (b) a precise list of what to fix
- Agent installer can call `dontpanic doctor --json --non-interactive --profile=<x>` and act programmatically
- Smoke test catches the three first-user blockers
- HTML install report renders cleanly in Chrome/Safari/Firefox on macOS + Linux

### Out of scope

- Auto-creating GitHub PATs (operator decision — too sensitive)
- Auto-generating SA keys for jarvis-a6ee1 (existing bootstrap.sh handles this)
- Installing dependencies outside safe scopes (no `sudo`, no system Python modifications)
- Windows support (macOS + Linux only for v0)
- Reusable profile authoring UX (operator-defined custom profiles) — v1 candidate

---

## Plan 4 — Architecture map with drift detection

**Plan ID candidate:** `2026-05-19-004-feat-architecture-map-with-drift-v0`
**Executes:** 6th
**Status:** not-locked
**Type:** feat
**Dependencies:** Plan 2 F002 (uses init patterns), Plan 3 (uses schema validation)
**Estimated cost:** 2 paid volleys, ~10-15M tokens

### Motivation (operator-clarified)

Static snapshot is insufficient. The map must:
1. **Validate against drift** — user may build outside DontPanic; map must detect when source has changed since last regen
2. **Auto-regenerate on DontPanic-driven changes** — but **never auto-commit** (footgun risk per operator review)

This turns "static snapshot" into "self-healing surface with explicit commit gates."

### Design principles

- **HTML is the human artifact** (Thariq pattern). Joyful, navigable, mobile-responsive. SVG diagrams.
- **JSON is the agent artifact.** Stable schema, version-stamped, fingerprinted. Next agent loads `architecture.json` to understand the code.
- **Track JSON, gitignore HTML.** (Decided per operator review.) Fresh clones get machine-readable context; humans regenerate HTML locally; no noisy HTML diffs in PR review.
- **Fingerprint is the drift signal.** Hash of source tree at last regen, stored in JSON header. Doctor compares.
- **Auto-regen runs into the working tree, never commits.** Supervisor + pre-commit hook regenerate, emit INBOX event, surface in doctor. **No automatic follow-on commits.** Operator runs `dontpanic architecture commit` explicitly, or a plan's commit_policy includes the map in its commit set.
- **Pre-commit hook defaults to warn-only.** Detects stale map + prints exact regen command. `--auto-regen` is opt-in via flag during `dontpanic init`.
- **Idempotent regen.** Same source → same output (deterministic SVG, stable JSON key order).
- **Cheap.** Full regen ≤5s on this codebase.

### Core requirements

- **R1 — `dontpanic architecture` CLI.** Subcommands: `regen` (default), `commit` (explicit commit of latest regen), `status` (show drift state), `diff` (compare current source to stored fingerprint without regenerating).

- **R2 — Source fingerprint.** SHA256 over the normalized source tree (sorted file list, file content hashes). Stored in JSON header.

- **R3 — Drift detection in doctor.** New probe: `architecture_drift`. Reads stored fingerprint, computes current hash, classifies as `fresh` / `stale_minor` (<5% files changed) / `stale_major` (≥5%). Advisory by default; blocker via `--strict`.

- **R4 — Supervisor regen-to-working-tree (no commit).** After `dispatch_volley` commits, supervisor inspects the just-committed diff. If any committed file matches architecture-relevant globs, run `dontpanic architecture regen` into the working tree. Emit INBOX `architecture_regenerated` event. **Do NOT commit the regenerated map.** Operator sees the changed file in `git status`, reviews, and decides whether to amend or commit separately.

- **R5 — Pre-commit hook: warn-only by default.** When source-tree files are staged, hook checks fingerprint and either:
  - Default: prints `architecture map appears stale; run \`dontpanic architecture regen\` to refresh, or commit anyway` (does NOT block commit, does NOT mutate)
  - Opt-in `--auto-regen` mode (set during `dontpanic init`): regenerates + stages the JSON, prints what changed, does NOT silently amend

- **R6 — Stable JSON schema.** `architecture.json` is versioned (`schema_version: "1.0"`), validated against a schema in agent-conventions. Downstream agents rely on shape.

- **R7 — HTML is joyful** (per Thariq). Navigable, SVG diagrams (module map, plan flow, supervisor state machine), syntax-highlighted code snippets, mobile-responsive.

- **R8 — JSON tracked, HTML gitignored.** Track `docs/architecture/architecture.json`. Add `docs/architecture/architecture.html` to `.gitignore`. Doctor reminds operator to regen HTML locally if missing.

### Feature outline

- **F001 — `dontpanic architecture` CLI + crawler + JSON output.** Walks `scripts/dontpanic_orchestrate/`, `claude/shared/`, `docs/plans/`. Builds module dependency graph, plan inventory, supervisor surface. Emits `architecture.json` with stable schema + source fingerprint header. Subcommands: `regen`, `commit`, `status`, `diff`.
- **F002 — HTML renderer.** Consumes `architecture.json`, emits joyful single-page HTML with SVG diagrams. Per Thariq's effectiveness principles. **HTML is gitignored; regenerated locally on demand.**
- **F003 — Drift detection probe in doctor.** New `architecture_drift` probe. Compares source hash to stored fingerprint. Configurable thresholds. Advisory by default.
- **F004 — Supervisor regen-to-working-tree (no auto-commit).** Post-commit hook in `dispatch_volley`. Triggers `dontpanic architecture regen` if architecture-relevant files changed. Writes to working tree, emits INBOX event. **No automatic commit.** Operator-explicit commit only.
- **F005 — Opt-in pre-commit hook (warn-default).** Installer in `dontpanic init`. Default behavior: detect stale, warn with exact regen command, do not block. Opt-in `--auto-regen` mode regenerates + stages JSON before commit.

### Acceptance principles

- Running `dontpanic architecture regen` from a clean clone produces a valid HTML + JSON in ≤5s
- Doctor catches drift when a file is edited outside DontPanic (state moves `fresh` → `stale_minor`/`stale_major` correctly)
- Supervisor auto-regen fires when a dispatched plan edits architecture-relevant files; does NOT fire for docs-only changes
- **Supervisor never auto-commits the regenerated map.** Map lands in working tree; operator decides what to do.
- Pre-commit hook (default mode) warns on stale map but does NOT block or mutate
- `architecture.json` is tracked; `architecture.html` is gitignored
- HTML renders cleanly in Chrome/Safari/Firefox; SVG diagrams scale on mobile
- JSON schema validates; downstream agent can load + traverse

### Out of scope

- Real-time architecture-map streaming
- Cross-repo architecture maps
- Diff visualization (v1 candidate)
- Architecture-map as audit envelope evidence (v1 candidate)

---

## Plan 6 — Credential setup [operator parallel track]

**Status:** operator-only, not a coding plan; runs in parallel with Plans 2-4
**Dependencies:** none
**Estimated cost:** ~30-60 min operator time

### What you do

1. Create/confirm GCP project access for `jarvis-a6ee1`
2. Generate Firebase service account key with documented roles
3. Place SA key in `~/.dontpanic/.secrets/` (gitignored — verify before any commit)
4. Run `firebase login` + `gcloud auth login` if not already authenticated
5. Run `dontpanic doctor --profile=firebase-dashboard` to confirm green
6. Optional: stub Firestore data for the dashboard smoke test

### Why parallel

You start this while Plans 1-3 are landing. By the time I'm done with Plan 4, your credentials are real and Plan 7 unblocks.

---

## Plan 7 — Plan 004 F003-F005 + Plan 010 F003 (credential-gated)

**Status:** locked plans, blocked on Plan 6
**Dependencies:** Plan 6 complete
**Estimated cost:** 4 paid volleys, ~40-60M tokens

### Sequence (deploy-dependency order)

1. **Plan 004 F003** — Cloud Functions for kanban column-flips, gate-approve, dispatch-trigger. Foundational.
2. **Plan 004 F004** — Firestore security rules. Depends on F003 endpoints.
3. **Plan 004 F005** — End-to-end smoke against `jarvis-a6ee1`. Depends on F003 + F004.
4. **Plan 010 F003** — printing-press-adapter follow-up. Orthogonal; parallelizable.

---

## Plan 8 — v5 candidates [deferred]

**Status:** parked per demand-driven planning principle
**When to revisit:** next cluster trigger (≥3 distinct frictions of the same shape)

Five carry items from v4.1 D-entries:

1. **D003 — Doctor regex widening** for extensionless tokens. *Partially subsumed by Plan 2 F001 doctor widening.*
2. **D004 — iter0-blocked-with-advisory-only auto-promote** via F003 taxonomy.
3. **D031 — Subprocess-timeout pre-flight check.** Cheapest of the candidates.
4. **D005 #2 — Post-F003 envelope re-capture.** Narrow value.
5. **D005 #1 — Strict-pin spec language clarification.** Needs explicit operator spec call BEFORE coding (third recurrence of a design disagreement).

---

## Cross-cutting design decisions

### HTML / Markdown / JSON policy

- **Markdown:** Plans, features.json, decisions.jsonl, README, this roadmap. Human-editable + agent-editable + diffs cleanly.
- **HTML:** Generated artifacts only — install reports, architecture maps. Joyful, navigable, NOT edited by humans. **Gitignored by default; regenerate locally.**
- **JSON:** Machine contracts — schemas, audit envelopes, architecture.json. Validated against schemas. Tracked in git.

Rule: if a human will edit it, use markdown. If a human will only *read* it, HTML is fine. If an agent will consume it, use JSON.

### Hermes positioning

Tiny vocabulary table in README. Link to Saboo's cheat sheet for conceptual framing. NOT a rebrand, NOT a dependency, NOT an origin story. Plan 1 scope.

### Sequencing discipline

- Fix known false-fails before widening the front door (Plan 3 → Plan 2)
- Ship the upstream channel before the upstream release (Plan 5 → Plan 3)
- Ship-fast within a plan when feasible (Plan 2 F001 ships independently)
- Auto-commits are footguns (Plan 4 F004 regenerates but does not commit)

### Drift detection as a primitive

Plan 4's fingerprint pattern generalizes. Future applications:
- Plan/feature acceptance drift
- Schema drift (downstream consumers behind upstream)
- Memory drift (agent memory files reference removed code)

v0 scopes to architecture only. Future plans lift the pattern.

---

## Open questions for operator (down from 5 → 3 after v0 review)

1. **Plan 5 — repo name + org.** `GodEquation/agent-conventions`? `Silex-Research/agent-conventions`? New org? *Decision needed before Plan 5 starts.*
2. **Plan 7 sequencing — single bundled close or per-feature commits?** Plan 7's four features are independent; operator preference?
3. **README rewrite scope.** Plan 1 is just the Hermes vocab table. Larger "what + why" rewrite for first-time visitor — defer or include later? *Suggested deferral; revisit after Plan 2 F001 lands and we see how `dontpanic init` reshapes onboarding.*

(Resolved in v1: Plan 4 R8 git-track decision, hook behavior default, profile filtering, GitHub PAT scope.)

---

## Next actions

If this roadmap looks right:
1. Operator approves
2. I knock out Plan 1 (housekeeping + tiny Hermes vocab table) in this session — ~10 min
3. Operator handles Plan 5 (agent-conventions remote) — ~1 hr operator time, can happen anytime
4. I draft + lock Plan 3 (schema fix) and dispatch — ~5-8M tokens
5. I draft + lock Plan 2 F001 (doctor widening) and dispatch — ~5-8M tokens
6. **Operator pause point:** assess Plan 2 F001 delta before authorizing F002-F004
7. If F001 delivered material delta, I dispatch F002-F004 sequentially — ~10-15M tokens
8. I draft + lock Plan 4 (architecture map) and dispatch — ~10-15M tokens
9. Operator's Plan 6 credentials run in parallel anywhere from step 3 onward
10. Plan 7 dispatches once credentials are real

If the roadmap needs more revision, mark + iterate.
