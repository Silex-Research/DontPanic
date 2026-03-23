---
description: Create an implementation plan from a spec, issue, or description without writing code
argument-hint: <description of what to implement>
---

# Plan — Implementation Planning

Analyze `$ARGUMENTS` and create a detailed implementation plan. Do NOT write any code.

## Protocol

1. **Understand the requirement** — Parse the description. If ambiguous, list assumptions.

2. **Identify affected files** — Search the codebase for files that need changes. List each with:
   - File path
   - What changes are needed
   - Whether it's a new file or modification

3. **Identify dependencies** — What must be done before what? Flag circular dependencies.

4. **Break into steps** — Ordered checklist of implementation steps. Each step should be:
   - Small enough to be one commit
   - Testable independently
   - Clear about what "done" looks like

5. **Flag risks** — Anything that could go wrong:
   - Breaking changes
   - Migration needed
   - Performance implications
   - Security considerations
   - External service dependencies

6. **Estimate complexity** — Rate each step: trivial / straightforward / complex / needs-research

7. **Validate with reviewer** — Launch a reviewer subagent to check the plan:
   - Are steps small enough (each completable in 2-5 minutes)?
   - Are dependencies correctly ordered?
   - Are there missing steps (tests, migrations, config)?
   - Are risks adequately identified?
   - If the reviewer finds issues, revise and re-validate (max 3 iterations)

## Output Format

```
IMPLEMENTATION PLAN — <title>
=============================

## Assumptions
- ...

## Files to Touch
1. `path/to/file.ts` — modify (add new endpoint)
2. `path/to/new-file.ts` — create (new service)

## Steps
- [ ] 1. [straightforward] Description of step 1
- [ ] 2. [trivial] Description of step 2
- [ ] 3. [complex] Description of step 3

## Risks
- Risk 1: description + mitigation
- Risk 2: description + mitigation

## Open Questions
- Question that needs human input before proceeding
```
