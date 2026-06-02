---
status: signed_off
reason_class: feature_complete
plan_id: 2026-05-30-001-feat-universal-agent-repo-onboarding-v0
feature_id: F008
closed_at: 2026-06-02T02:30:00Z
latest_audit_status: signed_off
---

# Closeout memo — 2026-05-30-001-feat-universal-agent-repo-onboarding-v0 / F008

## Operator decision

F008 (CLI/dashboard config-inventory action parity) is closed `signed_off`. codex
signed off on run10 iter0 after the operator resolved the run9 residuals (D047–D050).
The class-wide non-optimistic-status invariant is implemented by construction via the
shared `config_inventory.derive_status(StatusFacts)` helper, through which every
provider — config AND secret/auth — routes its `present`/`loadable`/`valid` facts.

## Return Condition

F008 returns complete when, by construction, **no inventory provider can report `ok`
on an invalid/incomplete/unrunnable underlying state**, and the dashboard action
surface is honest:

- Every provider derives status through the single shared `derive_status` helper; a
  registry-coverage guard test (`test_every_provider_is_listed_in_the_invariant_suite`)
  forbids adding a provider without an invariant case.
- The exhaustive parametrized suite (`_NON_OPTIMISTIC_CASES`) drives a real
  invalid/incomplete/unrunnable state for EVERY provider — including present-but-
  unloadable config, a tripped breaker, quota caps-without-calibration / state-missing /
  state-unloadable, non-runnable global defaults, invalid manifest, stale onboarding,
  and the secret surfaces (absent / malformed credfile / non-webhook URL / unloadable
  SA key) — each asserting a non-ok status.
- Anthropic auth probes a real credential artifact (API key / `~/.claude/.credentials.json`
  / macOS keychain), never the `claude` binary on PATH (codex i2).
- A malformed REQUIRED secret keeps `NEEDS_SETUP` but is `human_required`, so the
  response-level dashboard hint fires (operator ruling D050).
- `dontpanic roles set` (the dashboard safe-edit route) validates via the registered
  `_ROLES_SPEC`; quota emits no `safe_command` when fully configured (the non-runnable
  `quota-caps init` affordance is removed).
- No `dashboard/*` or `settings/*` files are edited (AC2d scope held).

## Verification

- 159 F008 + command-validation tests pass; F008 source + test files are ruff-clean.
- Independent operator check: malformed required secret → `status=needs_setup`,
  `human_required=True`; quota fully-configured → `safe_command is None`;
  `roles set <role> <executor> --global` → `validate_command_tokens.ok == True`.
- Cross-agent: codex `signed_off` on run10 iter0.

## Evidence references

- `audit/codex-auditor-F008-i0.json` (run10) — verdict `signed_off`
- `scripts/dontpanic_orchestrate/config_inventory.py` — `derive_status`, `_secret_provider`, `provider_quota`
- `scripts/dontpanic_orchestrate/command_validation.py` — `_ROLES_SPEC`
- `scripts/dontpanic_orchestrate/tests/test_config_inventory_f008.py` — `_NON_OPTIMISTIC_CASES` + coverage guard
- decisions `D045`–`D050`
