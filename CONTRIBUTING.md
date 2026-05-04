# Contributing to Jarvis

Thanks for your interest. Jarvis is an alpha-stage cross-agent orchestration
framework — issue reports, plan critiques, and small focused PRs are all
welcome. Larger changes should start as a plan under `docs/plans/`.

## Quick Setup

1. **Clone + bootstrap.** See `README.md` quickstart. You'll need:
   - Python 3.10+
   - `gcloud` CLI authenticated (`gcloud auth login`)
   - `firebase` CLI authenticated (`firebase login`)
   - A GCP project of your own (do NOT use `jarvis-a6ee1` — that's the
     campaign repo's project)
   - A billing account ID
2. **Verify your setup:** `python scripts/jarvis_doctor.py` — should print
   all green; if not, follow the remediation it prints. Use `--skip-auth`
   if you have not authenticated the gcloud/firebase CLIs yet (CI uses
   the same flag).
3. **Run the test suite:** `pytest scripts/dontpanic_orchestrate/tests/` —
   should be green before any change.

## Local CI Equivalent

The exact checks CI runs on every PR. Run them locally before pushing:

```bash
pytest scripts/dontpanic_orchestrate/tests/    # unit + integration
ruff check scripts/dontpanic_orchestrate/      # lint
ruff format --check scripts/dontpanic_orchestrate/  # style
python -c "from dontpanic_orchestrate import circuit_breakers, gate_pause, quota_admission; print('imports OK')"
```

If any of these fail, fix them — there is no allowed-failure lint job.

## Dependency maintenance

Dependabot (`.github/dependabot.yml`) manages weekly updates with two distinct framings — do not treat them as equivalent:

- **`github-actions` ecosystem — security-owned.** Every `uses:` in `.github/workflows/*.yml` is SHA-pinned with a tag comment (e.g. `actions/checkout@34e114876b...  # v4.3.1`). Dependabot is the canonical source of pin rotations: when a new release ships, the bot opens a PR that updates both the SHA and the tag comment atomically. **Do not hand-update workflow pins** without checking the bot first; manual edits race with bot PRs and risk pinning to the wrong SHA. If the bot is offline, regenerate pin resolutions via `gh api repos/<action>/git/ref/tags/<tag>` (see `docs/plans/2026-05-01-003-feat-security-baseline/evidence/f003/pin-resolutions.md` for the methodology).
- **`pip` ecosystem — configured but currently NO-OP, NOT dependency-security completion.** Dependabot's pip ecosystem requires a supported Python dependency manifest (requirements*.txt, pyproject.toml with a PEP 621 `[project]` table, Pipfile, etc.). Jarvis's `pyproject.toml` today carries only Ruff config — no `[project]` table — so the bot has nothing to maintain on the pip side. The entry stays configured so it activates the day a manifest lands; until then it is bookkeeping intent. Adding a `[project]` table changes Jarvis's packaging model (from "invoke as module" to "pip-installable") and is **deferred** to a future dep-security plan that also owns hash-pinning, lockfile enforcement, and `pip-audit`. **A green Dependabot pip PR is NOT supply-chain coverage even when one starts firing** — that gate belongs to the deferred plan (see plan `2026-05-01-003-feat-security-baseline` D004 deferral list).

Both ecosystems are operator-managed via PR review. The bot opens, you review and merge.

## Gate management

Plans can declare `human_gates: [pre_impl, pre_merge, ...]` in their plan.md frontmatter. Before any dispatch begins, the supervisor checks each declared gate plus any active circuit breakers (`breaker:*`) and admission defers (`defer:*`). Unmet gates pause the volley with a `gate_hit` INBOX event. Three CLI shapes clear gates:

- **Preferred — clear one gate (default operator action for partial clearance):**
  ```
  python -m dontpanic_orchestrate approve <plan-id> <gate>
  ```
  Use this whenever you want to release exactly one gate while keeping the rest armed. This is the safest default — it makes intent explicit per gate and matches the per-gate confirmation the supervisor was designed around.

- **Parity alias — clear one gate via `resume`:**
  ```
  python -m dontpanic_orchestrate resume <plan-id> --gate <gate>
  ```
  Functionally identical to `approve <plan-id> <gate>` (idempotent, refuses `breaker:global_circuit_breaker`, errors on unknown gates). Exists for ergonomic consistency with `--all` below; INBOX records the entry path so audit trails distinguish `approve`-cleared from `resume --gate`-cleared.

- **Explicit bulk-clear (the legacy bare-`resume` behavior, now behind a required flag):**
  ```
  python -m dontpanic_orchestrate resume <plan-id> --all
  ```
  Clears every plan-declared gate plus every active breaker/defer in one shot. Use when you've reviewed the full unmet set and intend bulk clearance.

**Bare `resume <plan-id>` (no flag) exits 2** with a usage message — it used to silently clear every gate, which once let an assistant bypass an operator-armed gate during dogfood (see plan `2026-05-02-001-feat-resume-gate-discipline`). The new contract forces explicit bulk-vs-partial intent. After clearing the last gate the operator must still re-run `dispatch-from-plan --confirm` (or the equivalent supervisor entry point); gate clearance does not auto-continue the volley.

## Plan-Driven Changes

Significant changes are gated by a *plan* under `docs/plans/<id>/`:

- `plan.md` — frontmatter (id, tier, status, agents_required, human_gates,
  loop_caps, privacy_tier) + a "Target" section declaring which environment
  + project the plan touches
- `features.json` — the inviolable machine-checkable spec. Each feature has
  `id`, `description`, `acceptance`, `steps`, `passes`, `depends_on`. A
  feature only flips to `passes:true` when its acceptance is demonstrably
  satisfied.
- `decisions.jsonl` — append-only record of locked design decisions

See `docs/plans/2026-04-19-001-infra-cross-agent-orchestration/` for the
canonical example.

## Testing

- Tests live in `scripts/dontpanic_orchestrate/tests/test_*.py`
- Run with `pytest`; the `conftest.py` autouse fixture isolates `~/.jarvis/`
  state per-test (breaker history, supervisor registry, interactive state,
  quota state). Tests run hermetically — no `~/.jarvis/` pollution.
- Each new module needs corresponding tests. AC scenarios from the plan's
  `features.json` should be reflected as test cases.

## Commits

- Sign your commits (SSH or GPG). The maintainer's setup uses 1Password's
  `op-ssh-sign` + a per-repo SSH signing key. See
  `~/.config/git/allowed_signers` for the verify-side config.
- Commit messages: short subject (≤70 chars), blank line, body explaining
  *why*. Reference the plan/feature ID when relevant (`F006`, `F023 EC11`,
  etc.).
- One logical change per commit. Mid-feature work-in-progress commits are
  fine; squash before merging if the history is noisy.

## Reporting Issues

- Bugs: include the plan ID + feature ID, expected vs. actual, the test
  that should reproduce it (or note if you couldn't write one).
- Schema/spec questions: reference the schema file under
  `claude/shared/agent-conventions/schemas/v1.0/`.

## Code of Conduct

Participation in this project is governed by `CODE_OF_CONDUCT.md`
(Contributor Covenant 2.1).

## Licensing

By contributing, you agree your contributions are licensed under the
project's Apache-2.0 license (see `LICENSE`).
