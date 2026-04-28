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
3. **Run the test suite:** `pytest scripts/jarvis_orchestrate/tests/` —
   should be green before any change.

## Local CI Equivalent

The exact checks CI runs on every PR. Run them locally before pushing:

```bash
pytest scripts/jarvis_orchestrate/tests/    # unit + integration
ruff check scripts/jarvis_orchestrate/      # lint
ruff format --check scripts/jarvis_orchestrate/  # style
python -c "from jarvis_orchestrate import circuit_breakers, gate_pause, quota_admission; print('imports OK')"
```

If any of these fail, fix them — there is no allowed-failure lint job.

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

- Tests live in `scripts/jarvis_orchestrate/tests/test_*.py`
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
