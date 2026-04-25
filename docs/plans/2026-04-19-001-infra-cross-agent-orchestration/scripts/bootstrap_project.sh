#!/bin/bash
# One-time bootstrap for a project to use the cross-agent orchestration framework.
# Pre-Phase-2 version — copies schemas + tools from the inception plan dir.
# After Phase 0 promotion, replace with: git subtree pull agent-conventions (v1.1.0+)
#
# Usage: bootstrap_project.sh <project-dir>
set -euo pipefail

PROJECT_DIR="${1:?Usage: bootstrap_project.sh <project-dir>}"
INCEPTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "Error: project dir not found: $PROJECT_DIR" >&2
  exit 1
fi

cd "$PROJECT_DIR"

# Dirs
mkdir -p docs/plans/.schemas docs/plans/.tools

# Copy draft schemas
cp "$INCEPTION_DIR/schemas/"*.schema.json docs/plans/.schemas/
echo "✓ Schemas → docs/plans/.schemas/"

# Copy tools
cp "$INCEPTION_DIR/scripts/validate_plan.py" docs/plans/.tools/
cp "$INCEPTION_DIR/scripts/new_plan.sh"      docs/plans/.tools/
chmod +x docs/plans/.tools/new_plan.sh docs/plans/.tools/validate_plan.py
echo "✓ Tools → docs/plans/.tools/"

# Quick-reference README
cat > docs/plans/.tools/README.md <<'EOF'
# Plan tools (pre-Phase-2 manual orchestration)

Scripts copied from the Jarvis inception plan. After Phase 0 promotion to
agent-conventions v1.1.0+, replace via subtree pull.

## Create a plan
```bash
docs/plans/.tools/new_plan.sh <tier> <type> <name>
# e.g.: docs/plans/.tools/new_plan.sh local fix closet-thumbnail-ghost
```

## Validate
```bash
python3 docs/plans/.tools/validate_plan.py <plan-id>
```

## Implement (Claude interactive)
```bash
claude
# Then in session:
# "Implement features per docs/plans/<plan-id>/features.json.
#  Flip passes=true only after verifying each feature; attach evidence_refs
#  (screenshot/test output/commit SHA) to each. Update decisions.jsonl with
#  anything non-obvious. Follow conventions in .claude/rules/."
```

## Audit (Codex headless)
```bash
PLAN_ID=<plan-id>
codex exec --json "You are the audit agent for $PLAN_ID in this repo.
Read docs/plans/$PLAN_ID/{plan.md,features.json,decisions.jsonl} and the
git diff since main. Audit for correctness (features claiming pass really
pass), side effects (did implementation break unrelated code?), test
coverage (new tests present and meaningful?), security.

Output ONE JSON object conforming to docs/plans/.schemas/audit.schema.json
with: task_id=$PLAN_ID, audit_id=$PLAN_ID#codex#0, agent=codex,
agent_role=auditor, iteration=0, audit_status, findings[], validation_performed[],
summary. No markdown fences." \
  > docs/plans/$PLAN_ID/audit/codex-review.json

python3 docs/plans/.tools/validate_plan.py $PLAN_ID
```

## 2-of-2 signoff (local tier)
Plan signs off if:
- All features in features.json have passes=true with evidence_refs
- Codex audit_status is `signed_off` AND no findings with severity critical|high
- Human (you) reviews final diff before merge

If Codex finds needs_changes → return to Claude for fix → re-audit. Max 1 loop
for local tier; escalate to cross-cutting (adds Gemini) if stuck.
EOF
echo "✓ README → docs/plans/.tools/README.md"

# Gitignore runtime audit artifacts (keep plan.md / features.json / decisions.jsonl in git; audit JSONs are regenerable)
if [[ -f .gitignore ]] && ! grep -qF "docs/plans/*/audit/" .gitignore; then
  cat >> .gitignore <<'EOF'

# Cross-agent orchestration runtime artifacts (regenerable)
docs/plans/*/audit/*.json
docs/plans/*/evidence/screenshots/
EOF
  echo "✓ .gitignore updated"
elif [[ ! -f .gitignore ]]; then
  cat > .gitignore <<'EOF'
# Cross-agent orchestration runtime artifacts (regenerable)
docs/plans/*/audit/*.json
docs/plans/*/evidence/screenshots/
EOF
  echo "✓ .gitignore created"
fi

# Deps check
if ! python3 -c "import jsonschema, yaml" 2>/dev/null; then
  echo ""
  echo "⚠  Install Python deps: pip3 install jsonschema pyyaml"
fi

if ! command -v codex >/dev/null; then
  echo "⚠  Codex CLI not found — install and auth before first audit"
fi

echo ""
echo "Bootstrap complete for $PROJECT_DIR"
echo "  Create first plan: cd $PROJECT_DIR && docs/plans/.tools/new_plan.sh local fix <name>"
