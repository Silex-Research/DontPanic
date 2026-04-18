# .claude.md Standards

How to build, maintain, and evolve the `.claude.md` file for any project.

## Why This Matters

Research consistently shows that large instruction files degrade AI agent performance:
- ETH Zurich/DeepMind (2026): LLM-generated context files reduced success rates 2-3%, increased costs 20%+
- Chroma: Every frontier model tested gets worse as input length grows (30%+ accuracy drop mid-context)
- Anthropic: "Bloated CLAUDE.md files cause Claude to ignore your actual instructions"

Target: **under 120 lines**. The test for every line: "Would removing this cause Claude to make mistakes?"

## Architecture

```
~/.claude/rules/              # Global per-language conventions (auto-loaded by language)
  swift.md                    # Naming, MVVM, concurrency, testing, security
  typescript.md               # Naming, types, imports, testing, security
  python.md, sql.md, etc.

project/.claude.md            # Project-specific gotchas ONLY (<120 lines)
project/.claude/agents/       # Role-specific agents (loaded on demand)
project/.claude/commands/     # Skills/slash commands (loaded on demand)
project/docs/GLOBAL_STANDARDS.md  # Comprehensive standards (loaded by skills on demand)
project/docs/architecture/ADR-*   # Decision records (loaded when relevant)
```

The key insight: **global rules handle conventions, .claude.md handles gotchas, everything else is on-demand.**

## What Goes in .claude.md

### 1. Project Identity (3-5 lines)
What this project is, one sentence. Core tech stack.

### 2. Surfaces Table
Every development surface the agent might touch. This prevents the agent from being blind to surfaces it hasn't been told about.

```markdown
| Surface | Path | Tech |
|---------|------|------|
| iOS app | `ios/` | Swift/SwiftUI, CocoaPods |
| Backend | `functions/` | TypeScript, Node 20, firebase-functions v2 |
| Admin UI | `admin/` | React 19, Vite, MUI |
| Pipeline | `functions/src/pipeline/` | 7-stage batch enrichment |
```

### 3. Non-Obvious Gotchas
Things the agent WILL get wrong without explicit instruction:
- Deprecated APIs that still exist in code (e.g., "Use AuthenticationService, not AuthenticationManager")
- Intentional rule violations (e.g., "Admin functions use enforceAppCheck: false — this is intentional")
- Data model constraints not obvious from code (e.g., "Firestore path uses geohash precision 5")
- Domain terminology requirements (e.g., "Closet not Wardrobe in all UI strings")
- Architectural decisions that contradict common patterns (e.g., "Business logic in UseCases, not ViewModels")

### 4. Security Boundaries
Rules the agent must never violate:
- Auth patterns (what to use, what's forbidden)
- Logging requirements (structured logger vs console)
- App Check / security enforcement rules

### 5. Build Commands
How to build and test — especially when it differs from convention (e.g., .xcworkspace vs .xcodeproj).

### 6. Skills List
One line listing available slash commands so the agent knows they exist.

### 7. Reference Docs Pointers
Where to find comprehensive standards, ADRs, and plans — loaded on demand, not inlined.

## What Does NOT Go in .claude.md

| Category | Why Not | Where Instead |
|----------|---------|---------------|
| Language conventions (naming, error handling, patterns) | Covered by `~/.claude/rules/*.md` | Global rules |
| Architecture descriptions inferrable from code | Agent can read the source | The code itself |
| Code examples showing standard patterns | Agent knows standard patterns | Remove entirely |
| Meta-process ("always search before coding") | Agent already does this | Remove entirely |
| Session handoff / context management templates | Agent manages its own context | Remove entirely |
| Full security rules / Firestore rules code | Only needed for specific tasks | `docs/GLOBAL_STANDARDS.md` |
| Performance benchmarks / targets | Only needed for perf work | `docs/GLOBAL_STANDARDS.md` |
| Test naming conventions / coverage targets | Only needed when writing tests | `docs/GLOBAL_STANDARDS.md` |
| Detailed accessibility checklists | Only needed for UI work | `docs/GLOBAL_STANDARDS.md` |
| Commit message format | Handled by Claude Code harness | Remove entirely |
| Skill invocation protocols | Already in each agent definition | `.claude/agents/*.md` |
| Generic decision frameworks | Not actionable instructions | Remove entirely |

## How to Evolve .claude.md

### Adding a Line
Before adding, ask:
1. Is this already covered by a global rule in `~/.claude/rules/`?
2. Can the agent figure this out by reading the code?
3. Does this only matter for a specific type of task? (If yes, put it in an agent or skill file)
4. Has the agent actually made this mistake? (If not, don't preemptively add it)

If it passes all four checks, add it with a brief "why" if non-obvious.

### Removing a Line
Periodically audit (~monthly or when the file grows past 100 lines):
- Is this still true? (Code may have changed)
- Has this been enforced by a linter/CI rule instead? (Move enforcement to tooling, remove from .claude.md)
- Is the deprecated API/pattern it warns about finally removed from code? (Remove the warning)

### After an ADR
When a new Architecture Decision Record is created:
1. Does it introduce a gotcha the agent would get wrong? Add a one-liner to .claude.md pointing to the ADR.
2. Does it contradict existing .claude.md content? Update the relevant line.
3. Is it a standard pattern the agent would follow anyway? Don't add anything — the ADR is reference material.

### After a Bug Caused by the Agent
If the agent made a mistake that correct .claude.md content would have prevented:
1. Add the minimal instruction that would prevent the mistake.
2. Check if the same information already exists but was buried — if so, the file may be too long.
3. Do NOT add the fix recipe — add the constraint that prevents the bug class.

## Anti-Patterns

**Context Rot:** Rules accumulate without removal. Each observed failure adds a new rule, creating contradictions and bloat. Prune regularly.

**Skill Invocation Duplication:** Putting skill invocation protocols in BOTH .claude.md AND each agent file. Put it in agent files only — the root file just lists available skills.

**Architecture Handbook:** Turning .claude.md into a comprehensive engineering handbook. That's what `docs/GLOBAL_STANDARDS.md` is for. The root file is a cheat sheet, not a textbook.

**Teaching Claude to Be Claude:** Instructions like "always search before coding", "analyze before implementing", "manage your context". Claude already does this. These lines waste context budget.

**Copy-Paste Across Projects:** Duplicating the same patterns across multiple project .claude.md files. If it applies to all projects, put it in `~/.claude/rules/`.

## Layered Context Model

```
Always loaded (budget: ~150 lines total)
  ~/.claude/rules/*.md          # ~50 lines per language, loaded by relevance
  project/.claude.md            # <120 lines of project gotchas

Loaded per agent invocation
  .claude/agents/Backend-Engineer.md   # Role-specific constraints
  .claude/agents/QA-Reviewer.md        # Quality gate definitions

Loaded per skill invocation
  .claude/commands/standards-check.md  # References GLOBAL_STANDARDS.md
  .claude/commands/security-audit.md   # Security-specific checks

Loaded on demand (agent reads when needed)
  docs/GLOBAL_STANDARDS.md             # Comprehensive standards
  docs/architecture/ADR-*              # Decision records
  docs/plans/                          # Implementation plans
```

Each layer loads only when relevant, keeping the always-on context budget small and the agent's attention focused on the actual task.
