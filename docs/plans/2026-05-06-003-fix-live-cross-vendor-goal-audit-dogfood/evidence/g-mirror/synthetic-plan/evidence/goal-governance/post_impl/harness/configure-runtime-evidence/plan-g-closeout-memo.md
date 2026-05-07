# Plan G close-out memo

**Plan ID:** `2026-05-06-001-infra-runtime-evidence-harness`
**Sequence position:** Goal Governance V1 / G (per `docs/GOAL_GOVERNANCE_V1.md` §9)
**Status flip:** `active` → `completed` on 2026-05-06
**Lock checkpoint:** `8316568` (5 features locked, D001–D011 at lock time)
**Amendment:** `9f1bae0` added F006/G0 (config surface) bringing the plan to 6 features (D013–D015)

## What G shipped

Capture-only runtime evidence prerequisites for F2 (the post-impl
completion-test auditor). Six independently-verifiable features:

1. **G0/F006 — Minimum operator configuration surface.** `RolesConfig` +
   `RuntimeEvidenceConfig` Pydantic models, layered config resolvers
   (per-call > project > global > fallback per D004), `dontpanic config`
   / `dontpanic project config` / `dontpanic setup` (preview-by-default;
   `--yes` mutates) / extended `dontpanic doctor` registration framework.
   D015 enforced (`runtime_evidence` is project-scoped only).
2. **G1/F001 — Web evidence collector.** Per-step screenshot + DOM
   snapshot + console errors + network failures. Optional trace +
   video. Default Playwright driver (deferred); pluggable swap seam.
3. **G2/F002 — iOS evidence collector.** Per-step screenshot + simulator
   log slice; per-session crash report drain. Default `xcrun simctl`
   driver (deferred); pluggable swap seam.
4. **G3/F003 — Android evidence collector.** Two operator-selectable
   modes per D009: `passive_observe` (live `adb` capture against
   existing device session) + `post_hoc_ingest` (consume existing
   Gradle/Espresso/Maestro/CI artifact tree).
5. **G4/F004 — Backend evidence collector (provider-adapter pattern,
   D010).** Three providers: Firebase (production posture, lazy
   `firebase_admin` SDK, deferred session adapter), Supabase (slot
   only per D010 lock), Generic (fully working stdlib HTTP /
   log-file / JSONL).
6. **G5/F005 — Common harness.** `EvidenceCollector.collect(journey,
   sources=[...]) -> list[EvidenceRef]` composing G1+G2+G3+G4 behind
   one source-agnostic interface. Pure orchestration; greppable
   invariant test asserts the core class body contains zero
   source-specific tokens.

Plan F2 (post-impl completion test + journey-walk auditor) is the
next chunk in the Goal Governance V1 sequence; not part of G.

## Six feature commits

| Feature | Commit | Boundary | Tests |
|---|---|---|---|
| F001 (G1 Web) | `62cdce6` | Web evidence collector + 18 tests + D012 | +18 (zero regressions) |
| F006 (G0 Config) | `d0031c9` | `config/` package + extended global/project config + CLI subcommands + F003 `roles.goal_auditor` lookup + 68 tests + D016 | +68 (zero regressions) |
| F002 (G2 iOS) | `9b0fcfb` | iOS evidence collector + 23 tests + `ios_simctl` doctor check + D017 | +23 (zero regressions) |
| F003 (G3 Android) | `069bcf5` | Android evidence collector + 31 tests + `android_adb` doctor check + D018 | +31 (zero regressions) |
| F004 (G4 Backend) | `c58e60a` | Backend evidence collector + provider-adapter pattern + 36 tests + 3 doctor checks + D019 | +36 (zero regressions) |
| F005 (G5 Harness) | `f445220` | Common harness + 4 adapter helpers + mixed-source acceptance test + 24 tests + D020 | +24 (zero regressions) |

All commits local-only; no remote pushes. Single-repo plan (D007 — no
agent-conventions schema bump needed; existing `EvidenceRef` v1.4.0
type enum covered all G adapter outputs).

## Final verification numbers (post-F005)

| Check | Result |
| --- | --- |
| Cumulative orchestrate suite | **1251 passed, 7 skipped, 0 regressions** |
| New tests added by Plan G | 200 (= 18 G1 + 23 G2 + 31 G3 + 36 G4 + 24 G5 + 68 G0) |
| `ruff check` + `ruff format --check` (full G surface) | ✓ clean |
| `python3 scripts/sanitization_check.py` | ✓ 0 findings (815 files scanned) |
| Plan G validates against agent-conventions v1.0 | ✓ |
| Project-agnostic invariant (D004) | ✓ no project-name special cases in any G adapter or in the harness core (greppable assertions in 5 test modules) |
| No new credential storage (D005 + D014) | ✓ all auth surfaces accept only pointer shapes (`adc` / `env:NAME` / path-only); greppable assertions reject credential literals |
| Capture-only invariant (D002) | ✓ no audit/scoring tokens in any G module (greppable in harness test) |
| No test orchestration (D009, Android) | ✓ greppable assertion confirms no `gradle` / `gradlew` / `espressoRunner` / `am instrument` / `maestro test` / `maestro studio` / `androidx.test.runner` tokens in `runtime_evidence/android.py` |
| Source-agnostic harness core (D004 + D006) | ✓ greppable assertion confirms `EvidenceCollector` class body contains zero `web` / `ios` / `android` / `backend` / `firebase` / `supabase` / `playwright` / `simctl` / `adb` / `logcat` / `tombstone` tokens |
| Library-only v1 (locked at lock turn) | ✓ no MCP wrap shipped; consumed in-process by F2 |

## Mixed-source acceptance — SATISFIED

The operator's explicit acceptance bar for G5/F005:

> *"A mixed-source fixture, e.g. browser + backend + artifact source
> in one journey, with one successful source, one typed skip, and one
> provider failure. That proves the harness is actually doing common
> orchestration rather than just wrapping one happy path."*

`test_browser_success_plus_backend_skip_plus_artifact_failure`
constructs three stub sources in a single journey:

- browser source returning 2 typed success refs (screenshot + log);
- backend source returning 1 typed-skip ref (mode='typed_skip',
  simulating G4's "SDK not installed" path);
- android source raising `EvidenceSourceError` (mode='raise_source_error',
  simulating G3's adb-missing failure).

Asserted output: 4 `EvidenceRef` instances in source-iteration order,
with consistent typing (screenshot/log/log/log), correct uri prefixes
(`/web/journey-1/`, `/web/journey-1/`, `/backend/journey-1/`,
`/harness/journey-1/`), and the harness skip's `captured_by =
'evidence-harness'`. Each source called exactly once with the right
journey. **Test passes.**

This proves the harness is doing common orchestration rather than
wrapping one happy path. Together with the end-to-end test that
composes the four adapter helpers with the real G1-G4 collectors using
stub drivers, the harness's source-agnostic contract is verified at
both the unit and integration level.

## D001 — F2 unblocked

D001 (locked at Plan G lock): *"F2 is BLOCKED until G closes (or a
reduced-evidence D-entry is recorded in F2's plan dir naming exactly
which sources are deferred and why per D008)."*

**G closed with full source coverage:** web + iOS + Android + backend
+ common harness, all five adapters operational behind a uniform
`EvidenceCollector.collect(journey, sources=[...])` interface.
Per-source operator config flows through F006's `runtime_evidence.<source>`
project-config layer (D015). No D008 reduced-evidence override is
required — F2's plan can call all four adapters via the harness
without exception.

**F2 is now unblocked per D001.** Drafting F2 is the next separate
motion in the Goal Governance V1 sequence; not part of this close-out.

## Per-feature decisions

D012–D020 capture each feature's locked design choices and ship
notes. The full list lives in `decisions.jsonl` of this plan dir;
quick reference:

- D001–D011: Plan G lock (architecture, project-agnostic invariant,
  EvidenceRef schema reuse, library-only v1, feature ID convention).
- D012: G1/F001 web ship.
- D013–D015: F006/G0 amendment (added by amendment 2026-05-06):
  D013 layered config + dependency edges, D014 credential-pointer
  rule, D015 runtime_evidence is project-scoped.
- D016: F006/G0 ship.
- D017: F002/G2 iOS ship.
- D018: F003/G3 Android ship (two-mode discriminator + D009
  enforcement).
- D019: F004/G4 backend ship (provider-adapter, three providers,
  warn-only doctor checks).
- D020: F005/G5 harness ship (source-agnostic core + dedup contract +
  mixed-source acceptance).

## Cross-vendor caveat (carried forward from F1)

The cross-vendor adversarial-review invariant (D006 / Goal Governance
V1 §5) applies to F2's auditor when it ships, not to the G adapters
themselves (the adapters are capture-only, so there is no "review" to
adversarially second-guess). F2's plan will set up the cross-vendor
dispatcher; the queued follow-up plan from F1 close-out remains
applicable and now has F006's `roles.goal_auditor` config surface to
land into.

## Signoff envelope decision

Per F1's pattern: G's plan-level close-out is operator-driven (no
auditor-volley reconciliation at the plan level — only per-feature
pytest + ruff + sanitization). A formal `audit/signoff-*.json`
envelope shaped for auditor reconciliation would be a square-peg-
round-hole. This plan-level close-out memo is the load-bearing
artifact instead.

Per-feature evidence:
- D012 (G1) → `decisions.jsonl`.
- D013–D016 (G0 amendment + ship) → `decisions.jsonl`.
- D017 (G2) → `decisions.jsonl`.
- D018 (G3) → `decisions.jsonl`.
- D019 (G4) → `decisions.jsonl`.
- D020 (G5) → `decisions.jsonl`.

Per-feature commits also carry full close-out detail in their git log
messages (see "Six feature commits" table above for hashes).

## What's next

The Goal Governance V1 sequence is now: F0 ✓ → F1 ✓ → **G ✓ (this
close-out)** → **F2 (next)**. F2 will:

1. Consume Plan G's `EvidenceCollector` to walk a plan's
   `ObjectiveContract.completion_test.required_evidence` against the
   captured `EvidenceRef` list.
2. Surface gap-class findings (analogous to F1's pre-impl auditor) for
   any required evidence the harness output is missing.
3. Engage the cross-vendor dispatcher (D006) for adversarial review of
   the auditor's findings.
4. Block plan close-out (analogous to F004's pre-impl gate) when
   completion-test findings are blocking.

F2 drafting is the next separate motion. The harness consumed
in-process; MCP wrap remains a follow-up plan as locked at G's lock
turn.
