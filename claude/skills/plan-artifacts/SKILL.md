---
name: plan-artifacts
description: Structured artifact trail for plans, brainstorms, and solutions. Triggers when creating plans or documenting learnings. New plans default to directory format with schema-validated plan.md + features.json (agent-conventions v1.0). Single-file v0 plans remain readable.
---

# Plan Artifacts — Structured Knowledge Trail

Plans, brainstorms, and solutions live as dated artifacts under `docs/`. New
plans default to **directory format** (v1) with machine-checkable
ground truth in `features.json`. Older single-file plans (v0) remain readable.

## Directory layout

```
docs/
├── plans/          # Implementation plans (executable contracts)
│   ├── <YYYY-MM-DD-NNN-type-name>/      # v1 directory format (preferred)
│   │   ├── plan.md                      # frontmatter validated by plan.schema.json
│   │   ├── features.json                # validated by features.schema.json
│   │   ├── decisions.jsonl              # append-only decision log
│   │   ├── audit/*.json                 # per-agent audit reports
│   │   └── evidence/                    # small artifacts; large → cloud storage
│   └── <YYYY-MM-DD-NNN-type-name>-plan.md   # v0 single-file (legacy, still readable)
│
├── brainstorms/    # Design explorations and requirements (from brainstorm-gate)
└── solutions/      # Learnings post-implementation (root-cause + fix)
```

If `docs/` doesn't exist at the repo root, create it.

## When to use which format

| Plan tier | Format | Why |
|---|---|---|
| `trivial` | v0 single-file OK | Low ceremony; just a checklist |
| `local` | v0 OR v1 | Operator preference |
| `cross-cutting` and above | v1 directory **required** | Multi-agent panel + signoff need machine-checkable contract |
| Any plan that will be audited by another agent | v1 required | Auditors read `features.json`, not prose |

When in doubt, use v1.

## v1 directory format

### Naming
Directory: `YYYY-MM-DD-NNN-<type>-<kebab-name>/`
- `NNN`: zero-padded sequence number for the day (001, 002, …)
- `type`: `feat | fix | refactor | migration | infra`
- `name`: lowercase kebab-case

ID inside `plan.md` frontmatter MUST match the directory name.

### `plan.md` template

```markdown
---
id: 2026-04-25-001-feat-example-name
title: Short descriptive title
type: feat
tier: local
status: active
date: "2026-04-25"
description: >=10 chars, what + why in one paragraph
motivation: optional longer context
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-04-19-001-infra-cross-agent-orchestration   # parent or upstream plans (optional)
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# <Title>

## Problem / Motivation
## Proposed Approach
## Scope (in)
## Scope (out)
## Acceptance
## Risks
```

Frontmatter must validate against `plan.schema.json`. **Quote the `date` value** so YAML keeps it as a string (unquoted dates parse to `datetime.date` and fail string+format:date validation).

Allowed enums:
- `type`: feat, fix, refactor, migration, infra
- `tier`: trivial, local, cross-cutting, architectural, p0
- `status`: draft, active, ready_for_audit, in_audit, completed, abandoned, blocked
- `human_gates`: pre_impl, pre_merge, on_escalation, tier_promotion, cost_trigger
- `privacy_tier`: public, internal, secret
- `agents_required`: claude, codex, gemini, grok, oss-qwen, oss-gemma4, oss-nemotron, oss-llama-guard, oss-nomic-embed

### `features.json` template

```json
{
  "task_id": "2026-04-25-001-feat-example-name",
  "schema_version": "1.0",
  "features": [
    {
      "id": "F001",
      "category": "infra",
      "phase": 0,
      "description": "What this feature does (>=10 chars)",
      "steps": [
        "Concrete verification step 1",
        "Concrete verification step 2"
      ],
      "acceptance": "Machine-checkable condition — the exact test for passes=true",
      "passes": false,
      "depends_on": []
    }
  ]
}
```

Allowed `category`: functional, infra, schema, test, doc, security, observability, tooling.

When flipping `passes: false → true`, the schema requires `verified_by`, `verified_at`, and **non-empty** `evidence_refs` (each entry an object with at least `type` + `uri`). Allowed `evidence_refs[].type`: screenshot, log, test_output, diff, audit_json, commit, url, file.

Feature IDs use `F001`-`F999` per file. Collisions across plans are scoped by `task_id`.

### `decisions.jsonl`

One JSON object per line, append-only:

```jsonl
{"id": "D001", "date": "2026-04-25", "question": "...", "answer": "...", "status": "resolved"}
```

Status: `open`, `resolved`, `deferred`. Include a `rationale` field when the answer surprised you.

## Schema validation

Before claiming a plan is ready for audit, validate it. Discover the schemas in this priority order:

1. `claude/shared/schemas/v1.0/` (Jarvis subtree pattern)
2. `.claude/shared/schemas/v1.0/` (other projects with subtree at `.claude/shared/`)
3. `agent-conventions/schemas/v1.0/` (canonical repo cloned alongside the project)
4. `docs/plans/.schemas/` (bootstrapped via `agent-conventions/scripts/bootstrap_project.sh`)

Run:

```bash
python3 <schemas-dir>/validate.py docs/plans/<plan-id>
```

If schemas can't be found in any of the locations above, tell the user — don't fabricate validation. The fix is one of:
- Add the agent-conventions subtree (recommended): `git subtree add --prefix=claude/shared <conventions-repo> v1.1.0 --squash`
- Or run the bootstrap script: `bash agent-conventions/scripts/bootstrap_project.sh .`

Python deps: `pip3 install pydantic jsonschema pyyaml` (if not already present).

## v0 backward compat (legacy single-file plans)

Existing `<YYYY-MM-DD-NNN-type-name>-plan.md` files remain readable. **Do not migrate** unless:
- The plan is becoming cross-cutting+ (audit panel needs `features.json`)
- The user explicitly asks

When migrating v0 → v1: create the directory, move `<…>-plan.md` to `<dir>/plan.md`, derive `features.json` from the existing checklist, log a D### entry recording the migration.

## Brainstorms (`docs/brainstorms/`)

Write when brainstorm-gate explores options or a design discussion produces requirements. Format: `YYYY-MM-DD-<topic>-requirements.md`. Single-file is fine — brainstorms aren't audited.

## Solutions (`docs/solutions/`)

Write when a non-obvious bug is fixed, a pattern is discovered, or a technology decision is made with important context. Format: `YYYY-MM-DD-<topic>.md`.

```markdown
---
title: <what was solved>
tags: [relevant, tags]
date: YYYY-MM-DD
---

# <Title>
## Problem
## Root Cause
## Solution
## Key Learnings
## References
```

## Rules

- Always check `docs/solutions/` before planning — a prior solution may apply.
- Update plan `status` to `completed` or `abandoned` when done.
- Validate v1 plans against schemas before declaring them ready for audit.
- When flipping `passes: false → true`, supply `verified_by`, `verified_at`, and `evidence_refs` (objects, not bare strings) — schema enforces this.
- Capture the *why* in decisions.jsonl, not just the *what*.
- Keep artifacts concise — a 20-line solution doc beats a 200-line one nobody reads.
- Never delete artifacts — they're the project's institutional memory.
