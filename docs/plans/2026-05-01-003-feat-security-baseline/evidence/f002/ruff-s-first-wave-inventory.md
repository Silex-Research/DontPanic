# F002 first-wave inventory — stop rule TRIGGERED

**Plan:** `2026-05-01-003-feat-security-baseline`
**Feature:** F002 (Ruff `S` baseline security lint)
**Stop-rule reference:** D007 — "if `ruff check --select S scripts/` produces >25 findings OR touches >8 distinct files, F002 must STOP"

**Status:** STOPPED at inventory. F002 lands as `passes: false` with `signoff_reason: scope_split_required`. Follow-up plan queued (proposed: `2026-05-XX-NNN-feat-ruff-s-remediation`).

## Numbers

```
$ ruff check --select S scripts/
Found 853 errors.

distinct files: 30
```

Both stop-rule conditions triggered (853 ≫ 25; 30 ≫ 8).

## Rule-code breakdown

| Rule | Count | Description | Most likely fix shape |
|---|---|---|---|
| **S101** | **810** (95%) | `assert` in non-test code | Per-file-ignore for `**/tests/**` — `assert` is canonical pytest idiom; 810 → ~0 with one-line `pyproject.toml` ignore |
| S108 | 15 | Hardcoded `/tmp` paths | Convert to `tempfile.mkdtemp()` / pytest `tmp_path` fixture per occurrence |
| S603 | 14 | `subprocess` without `shell=False` explicit | Add `shell=False` arg or `# noqa: S603  # arg list, no shell` per call site |
| S607 | 13 | Start-process with partial executable path | Use absolute paths or `# noqa: S607  # PATH lookup intentional, env-controlled` |
| S310 | 1 | `urllib.request.urlopen` audit (http vs https) | Likely `smoke_test_storage.py` HTTPS verification; add `# noqa: S310  # validated https-only via assert above` |

## Why S101 dominates and what to do about it

Ruff's S101 fires on every `assert` outside the `**/tests/**` glob by default. Jarvis has 800+ `assert` statements concentrated in `scripts/jarvis_orchestrate/tests/` and `scripts/sanitization_check_test_*` files — none of these are real S101 violations because pytest USES assert as its primary assertion mechanism.

The standard remediation (one line in pyproject.toml):

```toml
[tool.ruff.lint.per-file-ignores]
"**/tests/**" = ["S101"]
"**/test_*.py" = ["S101"]
```

If S101 is ignored in test paths, **expected post-ignore inventory is ~43 findings across ~10 files** — still over the original threshold but small enough to remediate per-finding with named noqa comments. That's the target of the follow-up plan.

## Follow-up plan shape (proposed)

A new plan `feat-ruff-s-remediation` with two features:

**F001: per-file-ignore baseline.** Add `[tool.ruff.lint.per-file-ignores]` for test paths. Acceptance: post-ignore inventory falls below the stop-rule threshold (<25 findings, <8 files). Below-threshold inventory archived as evidence. This is mechanical; no code changes.

**F002: per-finding remediation of post-ignore wave.** Apply F002's original policy (fix / `# noqa: SXXX  # <rationale>` / per-file ignore) to the residual ~43 findings. Each suppression names the rule + carries one-line justification. Acceptance: `ruff check --select S scripts/` exits 0; SECURITY.md gains the "Security tooling" section framing this as baseline lint, not SAST.

The split honors the stop-rule intent: F002 of the security plan does NOT degenerate into a 853-finding mass-suppressions commit. The follow-up plan owns the bulk work as its own auditable scope.

## What this plan still ships under F002

Nothing code-side. F002 in plan 2026-05-01-003 ships only:
- This inventory memo (durable evidence)
- `evidence/f002/first-wave-raw.txt` (full ruff output, 853 lines)
- `features.json` F002 flipped to `passes: false` with `signoff_reason: scope_split_required` and an explicit `next_plan` evidence pointer

`pyproject.toml` is NOT modified. SECURITY.md is NOT modified. The stop rule prevented the noise from landing.

## Decision linkage

- D007 of this plan defines the stop rule that fired
- D002 of this plan reaffirms Ruff S is baseline security lint, NOT SAST — the framing carries forward into the follow-up plan
