---
globs: "*.ts,*.tsx,*.mts,*.cts"
description: TypeScript conventions for Cloudflare Workers, Firebase Functions, dashboards, n8n nodes
---

# TypeScript Rules

## Naming
- Files: `kebab-case.ts` (e.g., `try-on-processor.ts`)
- Types/Interfaces: `PascalCase` (e.g., `TenantConfig`, `DeploymentState`)
- Functions/variables: `camelCase`
- Constants: `UPPER_SNAKE_CASE` for true constants, `camelCase` for derived values
- Enums: `PascalCase` members (e.g., `Status.Active`), not `UPPER_SNAKE`

## Error Handling
- Use typed errors — extend `Error` with a `code` field, not raw strings
- Always handle promise rejections — no floating promises
- Use `Result<T, E>` pattern or explicit error returns over try/catch for business logic
- try/catch only at boundaries (HTTP handlers, queue consumers, Cloud Function entry points)

## Types
- No `any` — use `unknown` and narrow, or define proper types
- No type assertions (`as`) unless you've just done a runtime check
- Prefer `interface` for object shapes, `type` for unions/intersections
- Export types from `packages/shared` — don't redeclare across packages
- Use `satisfies` over `as` for compile-time validation without widening

## Imports
- Group: node builtins → external packages → internal packages → relative imports
- Use `type` imports for type-only imports (`import type { Foo }`)
- No barrel files (`index.ts` re-exports) in new code — direct imports only

## Testing
- Framework: Vitest (prefer) or Jest
- Test files: co-located `*.test.ts` or `__tests__/` directory
- Test names: `describe('functionName', () => { it('should do X when Y') })`
- No mocking Firestore/KV in integration tests — use emulators
- Snapshot tests only for serialization formats, never for UI

## Security
- Validate all external input with Zod at API boundaries
- No string interpolation in SQL/queries — use parameterized queries
- No `eval()`, `new Function()`, or `vm.runInContext()`
- Sanitize user content before rendering (DOMPurify or equivalent)
- No secrets in source — use `wrangler secret` or Firebase environment config

## Patterns to Avoid
- `export default` — use named exports
- Nested ternaries — use early returns or if/else
- `Object.assign` for immutable updates — use spread
- `forEach` with side effects — use `for...of` or `map`/`filter`/`reduce`
