#!/bin/bash
# Scaffold a new plan directory in the current project.
# Usage: new_plan.sh <tier> <type> <kebab-name>
#   tier:  trivial | local | cross-cutting | architectural | p0
#   type:  feat | fix | refactor | migration | infra
#   name:  kebab-case-short-name
# Run from project root. Creates docs/plans/YYYY-MM-DD-NNN-<type>-<name>/
set -euo pipefail

TIER="${1:?tier required (trivial|local|cross-cutting|architectural|p0)}"
TYPE="${2:?type required (feat|fix|refactor|migration|infra)}"
NAME="${3:?name required (kebab-case)}"

case "$TIER" in
  trivial|local|cross-cutting|architectural|p0) ;;
  *) echo "Error: tier must be trivial|local|cross-cutting|architectural|p0" >&2; exit 2 ;;
esac
case "$TYPE" in
  feat|fix|refactor|migration|infra) ;;
  *) echo "Error: type must be feat|fix|refactor|migration|infra" >&2; exit 2 ;;
esac
if [[ ! "$NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "Error: name must be kebab-case (a-z, 0-9, hyphens)" >&2; exit 2
fi

DATE=$(date +%Y-%m-%d)
PLANS_DIR="$(pwd)/docs/plans"
if [[ ! -d "$PLANS_DIR" ]]; then
  echo "Error: $PLANS_DIR not found. Run bootstrap_project.sh first." >&2
  exit 1
fi

# Compute next NNN for today
NNN=$(ls -d "$PLANS_DIR"/${DATE}-* 2>/dev/null | wc -l | tr -d ' ')
NNN=$(printf "%03d" $((NNN + 1)))

PLAN_ID="${DATE}-${NNN}-${TYPE}-${NAME}"
PLAN_DIR="$PLANS_DIR/$PLAN_ID"

if [[ -d "$PLAN_DIR" ]]; then
  echo "Error: $PLAN_DIR already exists" >&2
  exit 1
fi

mkdir -p "$PLAN_DIR/audit" "$PLAN_DIR/evidence"

# Tier-specific defaults
case "$TIER" in
  trivial)        AGENTS='  - claude'; GATES='  - pre_merge'; LOOP_MAX=0 ;;
  local)          AGENTS=$'  - claude\n  - codex'; GATES='  - pre_merge'; LOOP_MAX=1 ;;
  cross-cutting)  AGENTS=$'  - claude\n  - codex\n  - gemini'; GATES=$'  - pre_impl\n  - pre_merge'; LOOP_MAX=2 ;;
  architectural)  AGENTS=$'  - claude\n  - codex\n  - gemini\n  - grok'; GATES=$'  - pre_impl\n  - pre_merge\n  - on_escalation'; LOOP_MAX=1 ;;
  p0)             AGENTS=$'  - claude\n  - codex\n  - gemini\n  - grok'; GATES=$'  - pre_impl\n  - pre_merge\n  - on_escalation\n  - cost_trigger'; LOOP_MAX=3 ;;
esac

cat > "$PLAN_DIR/plan.md" <<EOF
---
id: $PLAN_ID
title: TODO — one-line title under 120 chars
type: $TYPE
tier: $TIER
status: draft
date: "$DATE"
description: TODO — what does this plan do and why
motivation: TODO — the problem this solves
agents_required:
$AGENTS
human_gates:
$GATES
loop_caps:
  max_iterations: $LOOP_MAX
  no_progress_threshold: 2
  wall_clock_hours: 72
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# TODO — Title

## Problem

TODO — what's wrong today

## Proposed approach

TODO — how you plan to fix it

## Acceptance

Each feature in \`features.json\` flips \`passes: true\` with evidence. Audit status must be \`signed_off\`.
EOF

cat > "$PLAN_DIR/features.json" <<EOF
{
  "task_id": "$PLAN_ID",
  "schema_version": "1.0",
  "features": [
    {
      "id": "F001",
      "category": "functional",
      "phase": 0,
      "description": "TODO — describe the first feature/fix",
      "steps": [
        "TODO — specific verification steps"
      ],
      "acceptance": "TODO — machine-checkable condition (e.g., 'test X passes', 'screenshot Y matches spec', 'no new lint errors in file Z')",
      "passes": false,
      "depends_on": []
    }
  ]
}
EOF

touch "$PLAN_DIR/decisions.jsonl"

echo "✓ Created $PLAN_DIR"
echo ""
echo "Next steps:"
echo "  1. Edit: $PLAN_DIR/plan.md"
echo "  2. Edit: $PLAN_DIR/features.json"
echo "  3. Validate: python3 docs/plans/.tools/validate_plan.py $PLAN_ID"
echo "  4. Branch: git checkout -b plan/$PLAN_ID"
echo "  5. Implement via Claude (see docs/plans/.tools/README.md)"
