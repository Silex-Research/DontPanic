---
status: draft
date: "2026-04-20"
relates_to: F003, F021
blocked_by: Phase 0 verification panel (schema/tooling choices may shift based on findings)
---

# Phase 1 Design — plan-artifacts skill v1 update

> **Draft status.** Phase 0 (schema verification panel) may surface findings that change schema shape, codegen tooling, or canonicalization rules. Revisit this document after Phase 0 findings are folded into the promoted v1.0 schemas at `agent-conventions/schemas/v1.0/`. Treat the defaults below as starting positions, not decisions.

## Goals

1. New plans default to **directory format** validated against `agent-conventions/schemas/v1.0/`
2. **Backward-compatible**: existing v0 single-file `.md` plans remain readable; no forced migration
3. **Round-trip exact**: reading this inception plan (`2026-04-19-001-infra-cross-agent-orchestration`) and re-emitting produces byte-identical (or whitespace-normalized) files — the F021 dogfood test
4. **Schema evolution**: plans pin their schema version via `$schema` URI; supervisor can upgrade to v1.1+ cleanly later

## Non-goals

- Replacing `brainstorm-gate` for design decisions (stays human-driven for cross-cutting+ tiers)
- LLM-inferring features.json purely from plan narrative (too much judgment; skeleton + human fill is the pattern)
- Big-bang migration of existing v0 plans (400+ files; opt-in per-plan only)

## User-facing behavior

| User intent | Skill behavior |
|---|---|
| "Create a plan for X" | Ask tier → generate directory skeleton (plan.md + empty features.json + empty decisions.jsonl + audit/ + evidence/) → validate → return plan ID |
| "Add feature F00N with acceptance Y" | Append feature object to features.json (passes:false; no evidence required) → validate |
| "Mark F00N passing, evidence: [refs]" | Flip passes:true only if evidence_refs supplied → validate (schema enforces verified_by, verified_at, evidence_refs non-empty) |
| "Log decision D0NN on plan X" | Append object to decisions.jsonl → validate |
| "Promote plan X to ready_for_audit" | Require all features have acceptance strings; status:ready_for_audit; Stop hook picks up (Phase 6) |
| Read pre-existing `YYYY-MM-DD-NNN-*-plan.md` | Parse as v0 legacy; surface inline prompt: "upgrade to v1.0 directory? [y/N]" |
| "Migrate plan X" | Run migration helper with explicit confirmation of each inferred field |

**Tier cascades templated sections in plan.md:** `local` gets minimal template; `architectural` gets Problem / Motivation / Risks / Non-goals / Acceptance stubs.

## Internal structure

### Schema source of truth

- JSON Schemas live in `agent-conventions/schemas/v1.0/*.schema.json` (subtreed into Jarvis, AXIOM, Glam, Styln)
- Pydantic models generated at subtree-pull time via `agent-conventions/scripts/generate_models.py`
- Committed output: `agent-conventions/python/agent_conventions/models.py`
- Skill imports `from agent_conventions.models import Plan, Features, Audit, Signoff`

### Read path — `plan_io.read(plan_id)`

1. Detect format: directory = v1; `.md` file = v0
2. v1: parse plan.md YAML frontmatter → `Plan`; load features.json → `Features`; load decisions.jsonl → `list[Decision]`
3. v0: parse YAML frontmatter only; features/decisions absent
4. Return `PlanArtifact` dataclass

### Write path — `plan_io.write(artifact)`

1. Validate all components against their Pydantic models (raises on failure)
2. Emit canonical form (see rules below) — must match hand-written inception byte-for-byte for round-trip
3. Atomic write via temp-then-rename per file
4. Optional pre-commit hook invokes validator on all changed `docs/plans/**/*.json`

### Canonicalization rules (critical for round-trip)

- **JSON files**: `json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False)` — preserve declared field order, trailing newline
- **YAML frontmatter**: quote dates explicitly (lesson from D035); use block scalars for multi-line strings; preserve key order
- **JSONL**: one object per line, no trailing comma, final newline, no pretty-printing (single-line each)

## Backward compat strategy

- **Zero forced migration.** v0 plans remain readable indefinitely.
- **Opt-in upgrade**: prompted when a v0 plan is opened for modification.
- **Skill detects format** by directory-vs-file check; dispatches to correct parser.
- **Mixed repos OK**: `docs/plans/` can contain both `2026-03-*-plan.md` and `2026-04-*-infra-foo/` simultaneously.

## F021 round-trip dogfood test

```bash
# Phase 1 acceptance gate
python3 agent-conventions/scripts/roundtrip_test.py \
  Jarvis/docs/plans/2026-04-19-001-infra-cross-agent-orchestration
# Reads plan dir via skill's parser
# Re-emits to temp dir
# Diff must be empty (modulo explicitly normalized whitespace per canonicalization rules)
# Exit 0 = Phase 1 complete
```

If round-trip fails, the skill is buggy — the canonicalizer or parser has a bias. Iterate until green.

## Concrete deliverables

### In `agent-conventions/` (promoted after Phase 0 completes)

- `python/agent_conventions/models.py` — generated Pydantic v2 models from JSON Schemas
- `python/agent_conventions/plan_io.py` — read/write/validate plan directories
- `python/agent_conventions/canonicalize.py` — deterministic JSON / YAML / JSONL emission
- `python/agent_conventions/migrate_v0.py` — opt-in v0 → v1 migration
- `python/pyproject.toml` + build step (for subtree consumers to `pip install -e`)
- `scripts/generate_models.py` — codegen from JSON Schema → Pydantic
- `scripts/roundtrip_test.py` — F021 acceptance harness

### In `~/.claude/skills/plan-artifacts/`

- Updated `SKILL.md` with v1 format guidance, tier cascade defaults, when-to-use per plan type
- Invocation examples for each user intent above
- Pointer to `agent_conventions.plan_io` as the implementation

## Open design decisions

Most will be answered by Phase 0 panel findings; flagging upfront so they're tracked:

1. **Pydantic v1 vs v2?** v2 has cleaner JSON Schema import. Some OSS tooling still expects v1. **Default: v2.**
2. **Codegen tool** — `datamodel-code-generator` (mature, widely used) or hand-written generator? **Default: `datamodel-code-generator`** unless Gemini's SRE audit flags issues.
3. **Canonicalization strictness** — byte-exact round-trip, or whitespace-normalized? Byte-exact is stricter but brittle. **Default: whitespace-normalized for JSON (stable indent/spacing); byte-exact for JSONL and YAML frontmatter.**
4. **Skill name** — keep `plan-artifacts` (update in place) or introduce `plan-artifacts-v1` and deprecate old? **Default: update in place**, detect format, branch internally. One skill, two format handlers.
5. **Migration tooling scope** — one-shot batch migrator or per-plan on-demand? **Default: per-plan on-demand** (less risky; no big-bang migrations).
6. **Per-plan `schemas/` subdirectory** — does the v1 plan directory link to `agent-conventions/schemas/v1.0/` via `$schema` URIs only, or also copy schemas locally? **Default: URI-only** (no copies); the inception plan has `schemas/` only because we're bootstrapping before the promotion exists.

## Timeline estimate

(Contingent on Phase 0 finalization.)

- Codegen pipeline + generated Pydantic models: 2–3 hours
- `plan_io.py` read / write / validate: 3–4 hours
- Canonicalizer + round-trip test harness: 2 hours
- Skill SKILL.md update + integration test: 2 hours
- Migration helper (opt-in): 2 hours
- **Total: ~half a day of focused work**, started after Phase 0 promotes schemas to `agent-conventions/schemas/v1.0/`

## What Phase 1 will prove

- Schemas can express real plans faithfully (F021 dogfood passes)
- Skill update doesn't break existing workflows (v0 plans still read)
- Contract is durable — agents write plans the supervisor can read mechanically
- Round-trip test becomes the regression gate for any future schema revision

## Inputs that will refine this document

- Phase 0 panel findings on schema shape (may change field names, required sets, enum values)
- Phase 0 panel findings on tooling currency (Grok may flag datamodel-code-generator as outdated vs newer alternatives)
- Phase 0 panel findings on canonicalization edge cases (OSS fixture generation may expose parser biases)
- F001 promotion diff (what final schemas look like vs inception drafts)

Revisit this document when Phase 0 completes and fold findings into the decisions section above before starting implementation.
