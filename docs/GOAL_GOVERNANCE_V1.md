# Goal Completion Governance — V1 Decisions

> Pre-implementation strategic decisions for the next DontPanic governance layer, above feature-level volley. This document defines the layer; subsequent plans (F / G / H) implement it.
>
> **Status:** decisions doc — V1 defaults proposed but tunable. Feature plans land after these decisions are confirmed.

---

## 1. Problem Statement

DontPanic's current verification pattern is feature-level. Each feature in `features.json` carries acceptance criteria, an implementer dispatches against those ACs, and (when volleyed) an auditor of a different vendor verifies the local patch. This works well for *implementation correctness* — does the diff do what the AC said.

It does not verify *goal satisfaction* — did the bundle of features, taken together, accomplish the user-facing thing the plan was actually for. For mechanical / infra / refactor plans (Plans A–E in the recent maintenance arc), the feature ACs *are* the goal, so the gap is invisible. For product / parity / migration plans, the gap is large and the operator has been filling it manually.

This doc proposes the layer above feature-level volley that closes the goal-completion gap.

---

## 2. Motivating Examples

**Spin & Dine — "Android reaches iOS parity"**

The plan decomposed parity into individual features, one per surface. Each feature passed feature-level audit. But parity is a matrix problem — source behavior × target behavior × UX states × wiring × edge cases × screenshots × navigation × data flows. A feature can pass while the parity goal remains incomplete. The operator became the implicit plan-level auditor.

**Glam — "Creator Hub works as an integrated product surface"**

The plan decomposed Creator Hub into create / edit / preview / publish / analytics / profile features. Each feature passed feature-level audit. Whether the Creator Hub *cohered* as an integrated product was never machine-checked. The operator was the integration auditor.

In both cases, feature-level audit was working as designed. The missing capability was a goal-completion governor one layer up.

---

## 3. Proposed Governance Layer

A two-pass goal audit, layered above feature-level volley.

### 3.1 Pass 1 — Pre-Impl Sufficiency Audit (cheap, no MCP)

Runs at plan-lock time, before any feature dispatches.

- **Input:** objective contract + features.json
- **Question:** *would this set of features, if all complete, satisfy the goal?*
- **Output:** sufficiency findings — missing user journeys, decomposition gaps, parity matrix holes, ambiguous completion tests.
- **Cost:** low — text-only walk of plan structure vs goal description.
- **Gate:** if findings are blocking, plan re-locks before any feature dispatches.

This catches decomposition errors before the expensive part. It is the most important addition.

### 3.2 Pass 2 — Post-Impl Completion Audit (expensive, MCP-dependent)

Runs after all features pass feature-level audit, before plan-level signoff.

- **Input:** objective contract + actual diffs + runtime evidence (screenshots, logs, journey walks).
- **Question:** *did the shipped patches satisfy the goal in practice?*
- **Output:** completion findings — missing journeys, unwired UI, parity gaps not surfaced as features, integration breaks.
- **Cost:** high — requires MCP integrations for runtime evidence.
- **Gate:** findings classify into inline fix / child plan / follow-up plan / operator-deferred (see §3.3).
- **Authoring:** how to record the typed refs this pass reads, including the reserved `journey_execution` execution proof, is in [`authoring-typed-evidence.md`](authoring-typed-evidence.md).

### 3.3 Gap Triage

Goal-audit findings are not features. Each finding classifies into one of:

| Triage | Trigger | Action |
|---|---|---|
| **Inline fix** | single small finding | adds an AC to existing feature; re-runs feature-level audit |
| **Child plan** | bounded gap cluster (see §6.3, §6.4) | spawns child plan via nested-orchestration; blocks parent signoff |
| **Follow-up plan** | gap is real but out of current plan's scope | creates queued plan dir; parent signs off |
| **Operator-deferred** | judgment call, not an objective gap | recorded in audit envelope; parent signs off |

---

## 4. Applicability Rule

Goal-completion governance is opt-in by `goal_type`, not universal.

| `goal_type` | Objective contract required? | Pre-impl sufficiency? | Post-impl completion? |
|---|---|---|---|
| `mechanical` | no | no | no |
| `infra` | no | no | no |
| `refactor` | no | no | no |
| `parity` | yes | yes | yes |
| `new_feature` | yes | yes | yes |
| `migration` | yes | yes | yes |
| `incident` | yes | yes | optional (see §6.1) |

**Discipline:** *objective contract describes outcomes the user experiences; features.json describes mechanical artifacts produced.* If a plan can't articulate user-facing outcomes (e.g. an internal subprocess timeout fix), it's mechanical/infra and doesn't need this layer. Otherwise, you'll grow a parallel features.json that just paraphrases the existing one.

### 4.1 Objective Contract Schema (proposed)

Per the goal-type rules above, opted-in plans add an `objective_contract` block to `plan.md` frontmatter or as a sibling `objective_contract.json`. Fields:

| Field | Type | Notes |
|---|---|---|
| `goal_type` | enum | parity / new_feature / migration / incident |
| `source_of_truth` | string \| ref | e.g. iOS app for parity work; PRD path for new_feature |
| `user_journeys` | list | flows the user can complete end-to-end |
| `required_evidence` | list | screenshots / logs / journey walk artifacts the post-impl audit must produce |
| `non_goals` | list | explicit out-of-scope items to prevent scope creep findings |
| `completion_test` | string | one-sentence prose answer to "how do we know this is done" |
| `cluster_overrides` | optional | overrides §6.3 default coherence rule when needed |

---

## 5. Goal Auditor Vendor Policy (locked)

Default policy:

- **Feature implementer:** primary coding agent (today: Claude Code).
- **Feature auditor (when volleyed):** different agent (today: Codex CLI).
- **Goal auditor:** **cross-vendor required by default** — different vendor from the implementer, preferably different from the feature auditor too.
- **Mechanical / infra / refactor plans:** no goal auditor (per §4 applicability rule).
- **Quota fallback (gated):** same-vendor goal audit is allowed *only* with an explicit operator override. The override is expensive on purpose so it doesn't become habit:
  - Envelope records `independence_level`, `override_reason`, `approved_by`.
  - Same-vendor goal audits **cannot auto-clear blocking goal findings** — operator must explicitly review and dispose each blocking finding before plan signoff.

Rationale: goal-level auditing is product-completeness review (decomposition quality, integration gaps, parity matrix coverage). Independent model bias matters most where the question is interpretive, not mechanical. Permissive same-vendor fallback would erode the very property the layer exists to provide.

Schema additions:

- **New artifact:** goal-audit envelope mirroring the feature-audit shape but with goal-completion findings.
- **Filename pattern:** `<agent>-goal-auditor-<feature_id>-i<n>.json` (e.g. `claude-goal-auditor-F001-i0.json`). This matches Plan E's volley regex `*-i\d+.json`, so the patched v1.3.1 validator dispatches it as an Audit envelope without any further validator changes.
- **New envelope fields:** `independence_level: "same_vendor" | "cross_vendor"`, `override_reason: string | null`, `approved_by: string | null`.

---

## 6. Open Decisions

Each question below has a V1 default proposed in §7, but defaults are provisional and tunable.

### 6.1 Milestone definition (when does post-impl audit run?)

Options:
- **Operator-marked** — operator declares "this plan is feature-complete, run goal audit." Simple; adds a manual step.
- **Auto-detected** — goal audit fires when all `passes: true`. No manual step; risks running prematurely if features pass with stale assumptions.
- **Hybrid** — auto-suggested when all features pass; operator confirms before goal audit starts.

V1 default proposed: **hybrid**.

### 6.2 Sampling selection (which user journeys does goal audit walk?)

Options:
- **Operator-picked** — operator lists 1–2 high-risk journeys from the objective contract.
- **Auto-ranked** — auditor selects from `user_journeys` ranked by: (a) cross-platform parity coverage, (b) auth / payment / destructive paths, (c) state machines with multiple branches.
- **Full walk** — every journey gets walked. Most thorough; most expensive.

V1 default proposed: **auto-ranked**, capped at 3 journeys per audit pass. Operator override allowed.

### 6.3 Gap cluster coherence (when do findings group?)

Options:
- **Same subsystem** — findings sharing a code subsystem cluster.
- **Same user journey** — findings on the same flow cluster.
- **Both required (intersection)** — findings cluster only if same subsystem AND same journey. Stricter, cleaner clusters; risks under-clustering.

V1 default proposed: **same subsystem AND same journey** (intersection rule), with `cluster_overrides` field on objective contract for plans where the rule doesn't fit.

### 6.4 Child-plan threshold (when does a cluster become a child plan?)

Options:
- **Severity-based** — spawn if any finding in cluster ≥ medium severity.
- **Count-based** — spawn if cluster has ≥ N findings.
- **Both required** — spawn if cluster has ≥ N findings AND any ≥ medium severity. Fewer false positives.

V1 default proposed: **count ≥ 3 findings in same cluster AND any single finding ≥ medium severity** → child plan. Below: inline fix or follow-up plan.

### 6.5 Goal auditor vendor independence

Locked per §5.

### 6.6 MCP prerequisite scope (which MCPs does goal auditor need?)

Options:
- **Web only** — Playwright. Cheapest.
- **Web + iOS** — adds XcodeBuild + simulator screenshots.
- **Web + iOS + Android** — adds Android equivalent (Espresso? Maestro?).
- **Web + iOS + Android + backend** — adds Firebase Cloud Logging MCP.

V1 default proposed: **runtime evidence supports Web (Playwright) + iOS (XcodeBuild + simulator) + Backend (Firebase Cloud Logging)**. Android runtime evidence is not in V1.

Coverage by surface:

| Surface | F1 pre-impl sufficiency | F2 post-impl runtime audit |
|---|---|---|
| Web | full | full (Playwright) |
| iOS | full | full (XcodeBuild + simulator) |
| Backend | full | full (Firebase Cloud Logging) |
| Android | full (text/static decomposition check) | **limited** — text/diff only; no runtime walks until G5 lands |

Spin & Dine is the primary motivating example, so Android parity remains a partial story until an Android MCP ships:

- Android plans still benefit from F1 sufficiency (decomposition / matrix / journey-coverage gaps).
- F2 against an Android plan produces a goal audit explicitly marked `runtime_evidence_level: limited` and lists the journeys that *would* have been walked if the Android MCP existed.
- **G5 (Android MCP) is queued as high-priority follow-on** — if Spin & Dine becomes the F1 dogfood (per §9 Plan F1 acceptance), G5 jumps to the front of the post-V1 queue.

### 6.7 OpenClaw boundary (resolved per OpenClaw Audit V1, 2026-05-05)

The §8 audit (full doc at `docs/OPENCLAW_AUDIT.md`) resolves this from "open" to **decided**:

- **OpenClaw is a caller / personal-assistant control plane, not the governance layer.** It owns channels, voice, multi-channel inbox, multi-agent isolation per workspace, and single-instance session state.
- **DontPanic owns the routing protocol, approval semantics, plan-aware status surfaces, and goal-governance artifacts** (objective contract, audit envelopes, signoff, gap-triage classifications, INBOX, gate state).
- **OpenClaw may relay or invoke DontPanic, but does not define the protocol.** The OpenClaw-as-caller recipe in `docs/ECOSYSTEM.md` (a thin OpenClaw skill that shells out to `dontpanic intake / dispatch / status / approve`) is the integration contract.

Three downstream consequences:

1. Plan H ships the H-DontPanic variant (see §9 Plan H entry).
2. Cross-instance coordination is a confirmed DontPanic gap, not an OpenClaw deferral.
3. F0 / F1 / G / F2 lock with no OpenClaw dependency.

---

## 7. V1 Default Policy (provisional)

Codified for the V1 implementation. All values tunable.

```yaml
goal_governance:
  applicability:
    requires_objective_contract:
      - parity
      - new_feature
      - migration
      - incident
  passes:
    pre_impl_sufficiency:
      runs_at: plan_lock
      mcp_required: false
      blocking: true
    post_impl_completion:
      runs_at: all_features_pass
      milestone_mode: hybrid     # auto-suggest, operator confirms
      mcp_required: true
      blocking: true
  sampling:
    journey_selection: auto_ranked
    max_journeys_per_pass: 3
    operator_override: allowed
  clustering:
    coherence_rule: subsystem_and_journey
    override_field: objective_contract.cluster_overrides
  triage:
    child_plan_threshold:
      min_findings: 3
      min_severity: medium
    classifications:
      - inline_fix
      - child_plan
      - follow_up_plan
      - operator_deferred
  vendor_policy:
    feature_implementer: primary
    feature_auditor: different_agent_when_volleyed
    goal_auditor:
      vendor: different_from_implementer    # required, not preference
      prefer_different_from: feature_auditor
      same_vendor_fallback:
        allowed: only_with_operator_override
        envelope_fields:
          - independence_level    # "same_vendor" | "cross_vendor"
          - override_reason       # required when independence_level == "same_vendor"
          - approved_by           # required when independence_level == "same_vendor"
        auto_clear_blocking_findings: false
  envelope_filename_pattern: "<agent>-goal-auditor-<feature_id>-i<n>.json"
  mcp_v1:
    - playwright           # web — full runtime evidence
    - xcodebuild           # iOS — full runtime evidence
    - firebase_logging     # backend — full runtime evidence
  platform_runtime_coverage:
    web: full
    ios: full
    backend: full
    android: limited       # F1 sufficiency works; F2 runtime walks deferred to G5
  queued_high_priority_followon:
    - g5_android_mcp       # promoted to front of post-V1 queue if Spin & Dine is F1 dogfood
```

---

## 8. OpenClaw Audit Questions

To be answered by an OpenClaw audit pass after this doc is locked. Each question has a binary "covered upstream / not covered" outcome that determines whether the capability lands in Plan H or is treated as out-of-scope.

1. **Human routing** — does OpenClaw route operator notifications / approvals across multiple DontPanic instances?
2. **Discord / approval surface** — does OpenClaw provide a Discord bridge for async approvals?
3. **Cross-instance coordination** — can OpenClaw broker "instance A pauses on a gate that instance B can approve" across separate DontPanic invocations?
4. **Agent task discovery** — does OpenClaw expose pending DontPanic gates / INBOX items to other agents (Claude Code, Cursor, Codex CLI)?
5. **Dashboard / status** — does OpenClaw render plan / volley / signoff state visually?
6. **Remote execution** — can OpenClaw trigger DontPanic dispatch from a remote surface (mobile, web)?
7. **MCP tool calling** — does OpenClaw broker MCP tool access, or does each DontPanic instance own its own MCP layer?

The doc should be re-read after the OpenClaw audit and §6.7 + Plan H scope amended accordingly.

---

## 9. Candidate Plan Sequence

Drafted, not locked. Lock order: **F0 → F1 → G (planned during F1, ships before F2) → F2 → H.**

### Plan F0 — Nested orchestration configuration for goal governance

Small plan. Does **not** rebuild nested orchestration — that substrate already shipped via `2026-05-02-003-feat-nested-orchestration-v1` (4 patterns: linear / sidecar / fan_out / matrix; per-stage caps; depth/cycle/repeated-finding guards). F0 *configures* that substrate for the goal-governance use case so F1 and F2 can spawn child plans through disciplined rails rather than improvising.

Without F0, F1's sufficiency auditor can detect "this should be a child plan," but the system has not been taught how to consistently spawn / charter / return-from a child in this new governance context. That mismatch is exactly the place where governance layers grow ad-hoc patches.

- **F0.1:** Codify the §3.3 gap-triage decision rules into a classifier module — finding shape × cluster context → {inline_fix, child_plan, follow_up_plan, operator_deferred}. Implements the §6.3 coherence rule + §6.4 threshold.
- **F0.2:** Child-plan charter template for goal gaps — required fields: parent objective-contract reference, gap-class, return condition, cluster scope, severity, surfaces affected.
- **F0.3:** Return-condition template — what the child plan must produce for the parent to accept fan-in (default: "child's objective contract satisfied AND parent's named gap class addressed").
- **F0.4:** Cap rules:
  - max child plans per parent goal-audit pass: default 3.
  - max nesting depth: default 2 (parent → child; no grandchildren without operator override).
  - max findings per child-plan cluster: enforces §6.4 threshold (≥3 findings, ≥1 medium severity).
- **F0.5:** Required `why_child_plan_not_feature` rationale field on every spawned child charter — prevents reflexive child-plan spawning when an inline fix would suffice.
- **F0.6:** Evidence path conventions — `evidence/goal-governance/<pass>/<artifact>` so goal-governance evidence is separable from feature-audit evidence in the plan dir.
- **F0.7:** Parent fan-in memo template — must reference the objective contract by ID and restate which gap class the child closed.

**Sequencing rationale:** F0 ships before F1 because F1's dogfood acceptance (F1.5–F1.7) may surface gap clusters in Spin & Dine or Glam that warrant child-plan spawning. F0 is the rails for that. F1's dogfood becomes the proof point for *both* F0 (substrate works) and F1 (sufficiency auditor catches the right gaps).

### Plan F1 — Objective contract + pre-impl sufficiency audit (no MCP)

Ships independently of any MCP work.

- **F1.1:** Objective contract schema + Pydantic model addition to agent-conventions.
- **F1.2:** Plan-lock validator extension — fail if `goal_type ∈ {parity, new_feature, migration, incident}` and objective contract is missing.
- **F1.3:** Pre-impl sufficiency auditor — text-only model walk of objective contract vs features.json; produces sufficiency-findings sidecar.
- **F1.4:** Gate wiring — sufficiency findings ≥ blocking severity prevent the plan from leaving `draft` status.

**F1 close-out acceptance (gating, not optional):**

- **F1.5:** Retroactively author objective contracts for Spin & Dine parity and Glam Creator Hub. Run the sufficiency auditor against each.
- **F1.6:** Auditor must identify at least one materially correct gap class in each:
  - **Spin & Dine:** parity matrix incompleteness — at least one Android-vs-iOS coverage gap not represented as a feature.
  - **Glam:** integrated Creator Hub journey-coverage gap — at least one cross-feature integration concern, not just per-feature completeness.
- **F1.7:** If the auditor misses both, F1 close-out fails and the sufficiency prompt or objective-contract schema needs revision before re-attempting F1 close-out. Synthetic test fixtures alone do not satisfy F1.

This is the strongest available proof that the layer addresses the actual failure mode.

### Plan G — MCP integration prerequisites

Scoped down from `2026-04-19-001` F009/F010/F011 to exactly what F2 needs.

- **G1:** Playwright MCP (web UI walks).
- **G2:** XcodeBuild MCP + simulator screenshot capture (iOS).
- **G3:** Firebase Cloud Logging MCP (backend observability).
- **G4:** Goal auditor's evidence-collection harness — invokes MCPs from auditor prompt context; captures screenshots / logs / DOM diffs as audit evidence files.

**Sequencing:** can be **planned** in parallel with F1, but **cannot ship in parallel as a hard prerequisite to F2**. F2 lock is blocked on either G close-out, or an explicit operator decision to lock F2 with reduced runtime evidence (e.g. ship F2 against backend-only evidence first, with F2.x remediation features tracked for the missing surfaces). The latter is a deliberate compromise, not a fallback path.

### Plan F2 — Post-impl completion audit + gap triage

Depends on Plan G. **F2 lock blocked on G close-out or an explicit reduced-evidence decision recorded in a D-entry.**

- **F2.1:** Goal auditor agent (different vendor from feature auditor by default per §5; same-vendor only with operator override per §5 quota fallback rules).
- **F2.2:** Audit envelope shape — `<agent>-goal-auditor-<feature_id>-i<n>.json` (matches Plan E `*-i\d+.json` regex), with `independence_level`, `override_reason`, `approved_by` fields.
- **F2.3:** Gap triage classifier — finding → {inline_fix, child_plan, follow_up_plan, operator_deferred}.
- **F2.4:** Token controls — milestone definition, sampling selection, child-plan threshold caps.

### Plan H — Visibility surface (locked: H-DontPanic variant)

**Locked per OpenClaw Audit V1 (2026-05-05).** H-OpenClaw variant ruled out — OpenClaw renders its own session/channel state, not plan-locked workflow state. DontPanic ships its own visibility surface.

- **H1 — wterm CLI dashboard** (primary, ships first). Local terminal surface for plan / volley / signoff state. Most aligned with PRODUCT.md's "no custom daemon" principle. Smallest scope.
- **H2 — Axiom dashboard repoint** (optional, follow-on). Per `2026-05-03-002` F004; repoints Axiom's existing dashboard surface at the personal DontPanic/OpenClaw setup. Web/hosted UI. Operator-installable, not bundled with DontPanic OSS.

**Cross-instance coordination — explicitly called out as separate scope:**

The OpenClaw audit confirmed that cross-instance coordination ("instance A pauses on a gate that instance B can approve") is a real DontPanic gap, not an OpenClaw deferral. Decision pending at Plan H lock time:

- **Option A: expand Plan H scope** — bundle a global INBOX broker + shared approval registry into H, alongside the wterm/Axiom rendering work.
- **Option B: split as Plan I** — keep H focused on single-instance visibility; open `Plan I — Cross-instance coordination` as a separate slice.

Option B is cleaner (smaller H, separable design) but pushes the cross-instance gap further out. Operator decision required at H lock time. Default expectation: Option B, with Plan I queued as immediate follow-on if H ships.

---

## 10. Stale plan triage (pre-Plan-F housekeeping)

Four plans on disk are likely superseded and should be closed as housekeeping (markdown-only, no code work):

- `2026-04-25-001-infra-jarvis-firebase-bootstrap` — bootstrap work landed under parent-plan tasks.
- `2026-04-25-002-infra-trivial-orchestration-test` — early dogfood, superseded.
- `2026-04-26-006-infra-f023-ec5-evidence` — closed by Plan D EC5 purity work.
- `2026-04-29-003-fix-f008-phased-gates` — closed by Plan B lifecycle-staged gates.

**Rationale:** operator clarity and queue hygiene. The sufficiency auditor inspects only candidate plans it is explicitly given; it does not auto-scan all historical plans. So stale entries don't *trip* the auditor — they just clutter the queue and make the master plan sequence harder to read. Closing them is good hygiene before Plan F1 locks, not a blocker.

---

## 11. Next Steps

1. ✅ **Commit decision register** — `docs/GOAL_GOVERNANCE_V1.md` committed at `28880ab` (2026-05-05).
2. ✅ **OpenClaw audit** — `docs/OPENCLAW_AUDIT.md` committed at `7e5ef30` (2026-05-05); decisions folded back into §6.7 + §9 Plan H.
3. **Stale plan triage** (§10) — markdown housekeeping. Next concrete action.
4. **Lock Plan F0** — nested orchestration configuration for goal governance. Configures the already-shipped substrate (`2026-05-02-003`) for the new governance use case. No OpenClaw dependency (per §6.7).
5. **Lock Plan F1** — objective contract + pre-impl sufficiency audit. F1 dogfood (F1.5–F1.7) proves both F0 and F1 land correctly.
6. **Plan Plan G** — MCP prerequisites — drafted during or after F1 lock; ships before F2.
7. **F1 + G close-out → Lock Plan F2** — post-impl completion audit + gap triage. F2 lock blocked on G close-out OR explicit reduced-evidence decision recorded as a D-entry.
8. **F2 close-out → Lock Plan H** — H-DontPanic variant (wterm + optional Axiom). Decide at H lock time whether to expand H scope to include cross-instance coordination, or split it as Plan I (default expectation: split).
