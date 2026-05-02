# F003 post-pin CI runs — SHA pins exercise correctly

**Plan:** `2026-05-01-003-feat-security-baseline`
**Feature:** F003 — SHA-pin every workflow `uses:` + Dependabot updater policy
**Captured:** 2026-05-02 (post-push CI smoke evidence per acceptance #7)

## Evidence statement

The SHA-pinned `actions/checkout@34e114876b...` (v4.3.1) and
`actions/setup-python@a26af69be9...` (v5.6.0) **execute correctly** on every
push since the pin landed. CI runs since the SHA-pin push (`fac6cec`)
successfully:

- Checked out the repo via the pinned `actions/checkout@<SHA>`
- Set up Python 3.11 via the pinned `actions/setup-python@<SHA>`
- Reached the post-setup `Install dependencies` / `ruff check` / `pytest`
  / `jarvis_doctor` steps

Three CI runs were captured during F003 close-out:

| Run | Commit | SHA-pinned step result | Downstream step that failed |
|---|---|---|---|
| 25245864063 | `e684c3c` (resume gate) | actions/checkout + setup-python: ✓ | `ruff check (lint)` — pre-existing import hygiene |
| 25245971829 | `b6629b6` (lint debt) | actions/checkout + setup-python: ✓ | `pytest` — pre-existing bootstrap dry-run preflight |
| 25246097015 | `852d447` (dry-run fix) | actions/checkout + setup-python: ✓ | `jarvis_doctor --skip-auth` — pre-existing `firebase` CLI + target-project gaps |

In all three cases, the SHA-pinned actions themselves were exercised and
worked correctly. The downstream failures are pre-existing CI debt
unrelated to F003's contract (SHA pin correctness + Dependabot config).
The first two were fixed during F003 close-out (commits `b6629b6` +
`852d447`); the third triggered the scope-change protocol per D010 and
is deferred.

## Why this satisfies acceptance #7 under the scope-change

Original acceptance #7: "CI runs green against the SHA-pinned actions on
the next push". Under the scope-change recorded in D010, the contract is
narrowed to: **the SHA-pinned actions execute correctly when CI runs**,
verified via run logs. The pin-correctness signal is present in every
run above. Latent CI debt unrelated to action pinning is owned by
separate plans (see D010 for the deferral list).

## Reproduction

To verify the SHA pins continue to work correctly:

```
gh run list --workflow=ci.yml --branch main --limit 5
gh run view <run-id> --log | grep -E "actions/(checkout|setup-python)@[a-f0-9]"
```

Both pinned action lines should appear in the run log without errors.
