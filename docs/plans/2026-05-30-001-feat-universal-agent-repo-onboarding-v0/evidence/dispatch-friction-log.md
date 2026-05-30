# Dispatch Friction Log — 2026-05-30

Primary-source record of the operator experience while trying to run
`dontpanic` on this very plan (the plan that exists to fix onboarding).
The dispatch did **not** complete: the plan was locked and reviewed, but the
F001 paid volley was blocked at the quota-calibration gate (operator-only
input). Captured so the friction feeds back into this plan and successors.

Severity legend: 🔴 blocker (stopped progress) · 🟠 major (forced detour /
multiple round-trips) · 🟡 minor (confusing but worked).

## Timeline of friction (in the order hit)

1. 🟠 **"orchestrate" is not a command.** The product is named after a verb
   the CLI does not expose. Real path is `dispatch-from-plan`. A fresh agent
   (Grok) searched, found nothing, and fell back to the IT/Kubernetes meaning
   of "orchestrate." → This plan's F002 directly fixes it (teaching gateway).

2. 🟠 **Two config homes disagree.** `~/.dontpanic/config.json` says
   implementer=`Grok-Builder`/auditor=`Codex-Auditor`; `~/.jarvis/config.json`
   says implementer=`codex`/auditor=`claude`; `agent-manifest.json` lives only
   in `~/.jarvis`. An agent inspecting the system gets contradictory answers.
   → F005 (config-home reconciliation) targets this.

3. 🟡 **Roles name non-existent executors.** `roles.implementer="Grok-Builder"`
   resolves to nothing (`AGENT_REGISTRY = {claude, codex}` only), yet `doctor`
   reported all-green and never flagged it. → F004 (roles.* validation).

4. 🟡 **Dispatch silently masks the broken role.** `dispatch-from-plan` resolved
   implementer=claude/auditor=codex from the plan's `agents_required`, so the
   broken global `Grok-Builder` never surfaced. The thing that would have caught
   the original incident was itself bypassed. → recorded as D008; F004 must
   validate config independently of any plan override.

5. 🔴 **Lock points at a dead entrypoint.** `plan lock` REFUSED with
   "run F003 sufficiency auditor first (see sufficiency_auditor.py)", but
   `run_sufficiency_audit` has **no production CLI entrypoint** and requires an
   injected `dispatch=` callable — it is referenced only by itself and tests.
   The error tells the operator to run something that cannot be run. Every prior
   locked plan satisfied the gate via a hand-authored
   `operator-critical-review` findings file (0 `override.json` exist anywhere).
   This is undiscoverable without reading the source. → recorded as D009.

6. 🟡 **Findings schema is undocumented at point of use.** First hand-authored
   `sufficiency-findings.json` failed Pydantic validation: wrong field names
   (`category`/`title`/`detail`/`feature_id` rejected; needs
   `journey_id`/`gap_class`/`description`/`feature_refs`) and an invalid
   severity (`info` → must be `advisory`). The required shape
   (`SufficiencyFinding`, severity vocab, `GapClass` Literal) is only knowable
   by reading `sufficiency_auditor.py` + `sufficiency_gate.py`. A near-miss:
   `severity:"medium"` is BLOCKING (`{medium,high,critical}`), so an
   emphasis-level note would have wrongly blocked the lock.

7. 🔴 **Quota gate blocks dispatch and `--mode interactive` does NOT bypass it.**
   `dispatch-from-plan --confirm` refused with `quota_readiness=config_required`.
   The remediation it prints — `quota-caps init` — is a **no-op when the caps
   file already exists** ("pass overwrite=True or delete first"), so following
   the on-screen instruction does nothing.

8. 🔴 **Caps exist but for the wrong windows.** Readiness requires a cap for each
   dispatched vendor's *observed-signal* window. Observed signal is on
   `codex.plus.rolling_7d` + `claude.max_20x.rolling_5h`, but caps existed only
   for `codex.plus.rolling_5h` + `claude.max_20x.rolling_7d` (mismatched).
   `doctor` surfaced this as two warnings but did not connect them to "this is
   why dispatch will refuse." Adding the codex `rolling_7d` cap (doctor's exact
   recommended value) cleared codex but not claude.

9. 🔴 **Final wall is operator-only and undiscoverable up front.** Claude's
   `rolling_5h` cap is `unit: percent_of_plan`, which requires
   `calibrate-claude --window rolling_5h --dashboard-pct N`, where N must be read
   off the human's claude.ai usage dashboard. None of this is surfaced until you
   have already locked the plan and attempted `--confirm`. There is no
   up-front "before you can dispatch, you need: X, Y, calibration Z" preflight.

## Cross-cutting observations

- **Gates are individually correct but collectively undiscoverable.** Each
  refusal (sufficiency, quota-config, quota-calibration) is the trust system
  working — but they are encountered one at a time, late, each with a
  remediation string that is incomplete (dead entrypoint, no-op init) or
  assumes source-reading. There is no single "what do I need to dispatch this
  plan?" preflight that lists every gate at once.
- **Error messages point at the wrong fix.** D009 (dead module) and #7 (no-op
  init) are the sharpest: both tell the operator to run something that does not
  do what the message implies.
- **`doctor` is falsely reassuring.** It reported 1/36 failed (unrelated
  gcloud auth) and green on roles + quota, while three dispatch-blocking
  conditions (unrunnable role, two mismatched quota windows) sat unflagged.
  doctor should predict dispatch-blockers, not just static file validity.

## Recommendations (beyond current plan scope)

- **R1. A `dontpanic preflight <plan>` (or extend dispatch-from-plan dry-run)**
  that lists *every* gate between draft and a green `--confirm` at once:
  sufficiency artifact present? roles resolve? quota caps cover observed
  windows? calibration current? — each with the exact command to satisfy it.
- **R2. Fix remediation strings to point at runnable commands.** The
  sufficiency-gate message must name the real way to produce findings (or ship
  a real `dontpanic plan audit-sufficiency` entrypoint). `quota-caps init`
  remediation must mention `--overwrite` / the per-window edit when the file
  exists.
- **R3. `quota-caps init` should reconcile windows, not bail.** When the file
  exists but observed-signal windows lack caps, it should offer to add the
  missing window entries (it already computes the codex value) rather than
  refuse wholesale.
- **R4. doctor should run a dispatch-readiness lens** (roles resolve to
  executors; caps cover observed windows; calibration fresh) and mark which
  findings will block a real dispatch.
- **R5. Make the sufficiency-findings schema authorable.** Either a
  `dontpanic plan audit-sufficiency` command that generates the file, or a
  documented template + `--validate` so operators don't reverse-engineer
  Pydantic from source.

## Outcome

- Plan **locked** (`status: active`) via an honest Claude-authored,
  operator-accepted `sufficiency-findings.json` (3 advisory/low findings).
- F001 paid volley **not run** — stopped at the operator-only Claude quota
  calibration gate by operator choice.
- Live `~/.jarvis/quota_caps.json` reverted to pre-interaction state (the
  codex `rolling_7d` cap added during the attempt was rolled back).
- Decisions D008–D011 record the dogfood signal.
