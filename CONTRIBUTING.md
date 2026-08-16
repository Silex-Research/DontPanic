# Contributing to DontPanic

DontPanic is in private alpha. Issue reports, plan critiques, documentation
fixes, and small focused PRs are welcome. Larger changes should start as a plan
under `docs/plans/`.

## Quick Setup

1. Clone and install:

   ```bash
   git clone https://github.com/Silex-Research/DontPanic.git
   cd DontPanic
   python3 -m pip install -e ".[dev]"
   ```

2. Configure local roles:

   ```bash
   dontpanic setup --implementer claude --auditor codex --goal-auditor codex
   dontpanic setup --implementer claude --auditor codex --goal-auditor codex --yes
   ```

3. Verify the local surface:

   ```bash
   dontpanic --help
   dontpanic doctor --skip-auth
   python3 claude/shared/schemas/v1.0/validate.py examples/plans/hello-dontpanic
   ```

Cloud CLIs are optional unless your change touches Firebase/backend evidence or
project-specific deployment paths.

## Local CI Equivalent

Run these before opening a PR:

```bash
PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/ -q
ruff check scripts/dontpanic_orchestrate/
ruff format --check scripts/dontpanic_orchestrate/
python3 scripts/sanitization_check.py
```

If any of these fail, fix them. There is no allowed-failure lint job.

## Eval suites

Two offline suites live in `scripts/dontpanic_orchestrate/smoke/scenarios/`:

- **regression** — must stay green. `scripts/run-eval-suite.sh regression`
  failing fails CI. Add a scenario here only after it has been stably passing
  as a capability scenario.
- **capability** — may fail. `scripts/run-eval-suite.sh capability` never
  fails the build. New recorded failures start here (`suite: capability` in
  that scenario's own `scenario.json`).

Set `suite` in the scenario file. There is no default. See
`docs/authoring-corpus-scenario.md`.

## Dependency Maintenance

Dependabot (`.github/dependabot.yml`) manages weekly updates with two distinct
framings:

- `github-actions` pins are security-owned. Dependabot should rotate the SHA
  and tag comment together. Do not hand-update workflow pins unless the bot is
  unavailable and you have verified the new SHA.
- `pip` dependencies are now declared in `pyproject.toml`. A green dependency
  PR still needs normal review; it is not automatic supply-chain signoff.

## Gate Management

Plans can declare `human_gates: [pre_impl, pre_merge, ...]`. Before dispatch,
the supervisor checks declared gates plus active circuit breakers and admission
defers. Unmet gates pause the volley with an `INBOX.md` event.

Clear one gate:

```bash
dontpanic approve <plan-id> <gate>
```

Clear one gate via the resume alias:

```bash
dontpanic resume <plan-id> --gate <gate>
```

Bulk-clear only after reviewing the full unmet set:

```bash
dontpanic resume <plan-id> --all
```

Bare `resume <plan-id>` exits 2. Gate clearance does not auto-dispatch; rerun
`dontpanic dispatch-from-plan <plan-id> --confirm` after review.

## Plan-Driven Changes

Significant changes are gated by a plan directory:

- `plan.md` — frontmatter, target, scope, non-goals, sequencing.
- `features.json` — machine-checkable acceptance source of truth.
- `decisions.jsonl` — append-only decision log.
- `audit/` and `evidence/` — machine and human proof.

Start with [`docs/AUTHORING_PLANS.md`](./docs/AUTHORING_PLANS.md) and the safe
sample at `examples/plans/hello-dontpanic/`.

## Testing

- Tests live in `scripts/dontpanic_orchestrate/tests/test_*.py`.
- Tests isolate `~/.dontpanic/` and legacy `~/.jarvis/` state per test.
- Each new module needs corresponding tests. Acceptance scenarios from the
  plan's `features.json` should be reflected as test cases.

## Commits

- Commit messages: short subject, blank line, body explaining why.
- Reference the plan and feature ID when relevant.
- One logical change per commit. Mid-feature work-in-progress commits are fine;
  squash before merging if the history is noisy.

## Reporting Issues

- Bugs: include the plan ID and feature ID, expected vs. actual behavior, and
  the test that should reproduce it.
- Schema/spec questions: reference the schema file under
  `claude/shared/schemas/v1.0/`.

## Code of Conduct

Participation is governed by [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).

## Licensing

By contributing, you agree your contributions are licensed under Apache-2.0.
