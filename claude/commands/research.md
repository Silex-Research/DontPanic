---
description: Deep research on a topic using web search — returns structured summary with sources
argument-hint: <topic to research>
---

# Research — Deep Web Research

Research `$ARGUMENTS` thoroughly using web search. Synthesize findings into actionable knowledge.

## Protocol

1. **Search** — Run 3-5 web searches with different angles on the topic:
   - Direct query
   - "best practices" variant
   - "vs alternatives" variant
   - Recent/2026 variant for freshness

2. **Read** — Fetch and read the top 3-5 most relevant results

3. **Synthesize** — Combine findings into a structured summary

4. **Evaluate** — Note consensus vs. controversy. Flag outdated information.

## Output Format

```
RESEARCH — <topic>
==================

## Summary
<2-3 sentence overview>

## Key Findings
1. Finding with detail
2. Finding with detail
3. Finding with detail

## Recommendations
- For our stack specifically: ...
- General best practice: ...

## Trade-offs
| Option | Pros | Cons |
|--------|------|------|
| A      | ...  | ...  |
| B      | ...  | ...  |

## Sources
- [Title](URL) — relevance note
- [Title](URL) — relevance note
```
