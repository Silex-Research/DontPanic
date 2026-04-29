# Resolver

Trigger→skill routing table for the Jarvis agent orchestration framework.
See `claude/shared/resolver/SPEC.md` for format definition.

## Always-On

Skills that fire as ambient context or on every interaction.

| Skill | Path | When |
|---|---|---|
| conventions | `claude/shared/conventions/index.md` | Read before any cross-project work |
| continuous-learning | `claude/skills/continuous-learning/SKILL.md` | Extract patterns from every session |
| proactive-agent | `claude/skills/proactive-agent/SKILL.md` | Surface anomalies, deadline proximity |
| token-budget-tracker | `claude/skills/token-budget-tracker/SKILL.md` | Track token usage across agents |

## Intent Triggers

On-demand skills matched by user intent keywords.

| Trigger Keywords | Skill | Path | Precedence |
|---|---|---|---|
| "plan", "design", "architect", "approach" | brainstorm-gate | `claude/skills/brainstorm-gate/SKILL.md` | 1 |
| "plan", "implement", "build" | plan-artifacts | `claude/skills/plan-artifacts/SKILL.md` | 2 |
| "review pr", "pull request", "pr review" | pr-reviewer | `claude/skills/pr-reviewer/SKILL.md` | 1 |
| "fetch pr", "merge pr", "try pr", "github pr" | github-pr | `claude/skills/github-pr/SKILL.md` | 1 |
| "test", "run tests", "tdd" | test-runner | `claude/skills/test-runner/SKILL.md` | 1 |
| "tdd", "red green", "test driven" | tdd | `claude/commands/tdd.md` | 2 |
| "security", "vulnerability", "owasp" | security-review | `claude/skills/security-review/SKILL.md` | 1 |
| "review code", "code review", "review changes" | code-review | `claude/commands/code-review.md` | 1 |
| "research", "investigate", "deep dive" | autoresearch | `claude/skills/autoresearch/SKILL.md` | 1 |
| "research", "search", "look up" | research | `claude/commands/research.md` | 2 |
| "optimize prompt", "improve prompt", "tune prompt" | prompt-optimizer | `claude/skills/prompt-optimizer/SKILL.md` | 1 |
| "browse", "scrape", "web page", "screenshot" | browser-use | `claude/skills/browser-use/SKILL.md` | 1 |
| "agent browse", "structured extraction" | agent-browser | `claude/skills/agent-browser/SKILL.md` | 1 |
| "migrate", "migration plan", "move to" | migration-planner | `claude/skills/migration-planner/SKILL.md` | 1 |
| "create skill", "new skill", "add skill" | skill-creator | `claude/skills/skill-creator/SKILL.md` | 1 |
| "subagent", "parallel agents", "dispatch agents" | subagent-driven-dev | `claude/skills/subagent-driven-dev/SKILL.md` | 1 |
| "worktree", "isolate changes", "parallel branch" | worktree-isolation | `claude/skills/worktree-isolation/SKILL.md` | 1 |
| "eval", "evaluate", "grade", "benchmark" | eval-harness | `claude/skills/eval-harness/SKILL.md` | 1 |
| "stock", "price", "ticker", "market", "finance" | yahoo-finance | `claude/skills/yahoo-finance/SKILL.md` | 1 |
| "forecast", "time series", "ohlc", "kronos" | kronos-agent | `claude/skills/kronos-agent/SKILL.md` | 1 |
| "video", "remotion", "render video", "animation" | remotion-video-toolkit | `claude/skills/remotion-video-toolkit/SKILL.md` | 1 |
| "health", "production health", "app metrics" | product-health-agent | `claude/skills/product-health-agent/SKILL.md` | 1 |
| "cost projection", "spend forecast", "cost model", "project costs" | cost-model | `claude/skills/cost-model/SKILL.md` | 1 |
| "cost alert", "budget guard", "cost guard", "check budget", "budget breach" | cost-guard | `claude/skills/cost-guard/SKILL.md` | 1 |
| "revenue", "cash flow", "revenue check", "profitability" | revenue-check | `claude/skills/revenue-check/SKILL.md` | 1 |
| "build fix", "fix build", "compile error" | build-fix | `claude/commands/build-fix.md` | 1 |
| "clean up", "cleanup", "de-sloppify" | cleanup | `claude/commands/cleanup.md` | 1 |
| "plan", "implementation plan" | plan | `claude/commands/plan.md` | 3 |
| "verify", "check build", "lint" | verify | `claude/commands/verify.md` | 1 |
| "improve self", "self improve", "learn from" | self-improving-agent | `claude/skills/self-improving-agent/SKILL.md` | 1 |
| "git", "branch", "merge", "rebase", "stash" | git-essentials | `claude/skills/git-essentials/SKILL.md` | 1 |

<!-- overlap: "plan" matches brainstorm-gate (P1, design-first gate), plan-artifacts (P2, artifact trail), and plan (P3, implementation plan). Precedence resolves: ambiguous → brainstorm-gate; explicit implementation → plan-artifacts; simple plan → plan command -->
<!-- overlap: "research" matches autoresearch (P1, experiment loop) and research (P2, web search). autoresearch for code optimization; research for information lookup -->
<!-- overlap: "tdd" matches test-runner (P1, run tests) and tdd (P2, TDD workflow). test-runner for running; tdd for the full red/green cycle -->
