# Resolver Specification

A resolver is a routing table that maps triggers to skills. Every project that consumes `claude-conventions` maintains a project-local `RESOLVER.md` following this format.

## Purpose

1. **Skill discovery** — agents read the resolver at session start to know what capabilities exist
2. **Hook integration** — pre-commit and post-edit hooks match file patterns against resolver rows
3. **Drift prevention** — the validator ensures every skill is reachable and no triggers overlap

## RESOLVER.md Format

```markdown
# Resolver

## Always-On
Skills that fire on every interaction or are read as ambient context.

| Skill | Path | When |
|---|---|---|
| conventions | `.claude/shared/conventions/index.md` | Read before any brain-writing operation |

## Intent Triggers
On-demand skills matched by user intent keywords.

| Trigger Keywords | Skill | Path | Precedence |
|---|---|---|---|
| "review", "audit", "check" | standards-check | `.claude/commands/standards-check.md` | 1 |
| "test", "coverage", "tdd" | test-gen | `.claude/commands/test-gen.md` | 1 |
| "secure", "auth", "vulnerability" | security-audit | `.claude/commands/security-audit.md` | 1 |

## File-Pattern Triggers
Hook-driven skills matched by staged/changed file paths.

| Glob Pattern | Skill | Path | Phase |
|---|---|---|---|
| `firebase/functions/**/*.ts` | firebase-validate | `.claude/commands/firebase-validate.md` | pre-commit |
| `**/ViewModels/**/*.swift` | test-gen | `.claude/commands/test-gen.md` | pre-commit |
| `docs/architecture/ADR-*.md` | standards-check | `.claude/commands/standards-check.md` | post-edit |

## Error-Signal Triggers
Pipeline/runtime error routing (optional, for projects with enrichment pipelines).

| Stage:ErrorCode | Skill | Path |
|---|---|---|
| `investigate:timeout` | investigate-timeout-handler | `.claude/commands/investigate-timeout-handler.md` |
| `hours:parse_failed` | hours-schema-fixer | `.claude/commands/hours-schema-fixer.md` |
```

## Column Definitions

| Column | Required | Description |
|---|---|---|
| **Trigger Keywords** | intent rows | Comma-separated keywords that match user message content |
| **Glob Pattern** | file-pattern rows | Standard glob matching staged/changed file paths |
| **Stage:ErrorCode** | error-signal rows | `stageName:errorCode` for pipeline error routing |
| **Skill** | all | Skill name (matches filename without `.md` extension) |
| **Path** | all | Relative path from project root to the skill file |
| **Phase** | file-pattern | `pre-commit`, `post-edit`, `post-merge`, or `on-demand` |
| **Precedence** | intent rows | Integer 1-9. When multiple skills match, lower number wins. Equal = run both. |

## Rules

### Reachability
Every skill file in the skills directory must have at least one row in RESOLVER.md. A skill with no resolver entry is unreachable — agents cannot discover it.

### File Existence
Every row in RESOLVER.md must point to a real file via its Path column. Dangling references cause silent failures.

### MECE (Mutually Exclusive, Collectively Exhaustive)
No two intent-trigger rows may share identical keywords unless they have different precedence values. File-pattern rows may overlap if they have different phases. Document any intentional overlap with a `<!-- overlap: reason -->` comment.

### Always-On Exceptions
Skills listed in the Always-On section are exempt from MECE checks. They fire unconditionally and are expected to coexist with all other skills.

### Convention Referencing
Skills that address topics covered by shared conventions (security, error handling, testing, naming) must reference the convention file (`See .claude/shared/conventions/security.md`) rather than inlining the rules. The validator flags inlining violations.

## Agent Skill Tables and the Resolver

Agent definitions (`.claude/agents/*.md`) should reference the resolver rather than maintaining independent skill catalogs:

```markdown
## Skill Integration
Consult `.claude/RESOLVER.md` for applicable skills. Apply this ordering:
1. [Role-specific pre-gates]
2. Resolver-matched skills (in precedence order)
3. [Role-specific post-gates]

Skip: [skills not relevant to this role]
```

Role-specific ordering and exclusions remain in agent definitions. The resolver provides the shared catalog; agents provide role-specific judgment.

## Validation

Run the validator from any consuming project:

```bash
python3 .claude/shared/resolver/validate.py \
  --resolver .claude/RESOLVER.md \
  --skills-dir .claude/commands/ \
  --conventions-dir .claude/shared/conventions/ \
  --local-conventions-dir .claude/conventions/
```

See `validate.py` for check details and exit codes.
