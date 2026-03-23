# Cross-Project Entity Registry
<!-- Shared services, APIs, and patterns used across multiple projects -->
<!-- Updated: 2026-03-22 -->

## Firebase (used by: axiom, glam, spindineswift, quantre)

| Concern | Known Constraints | Source Project |
|---|---|---|
| Auth rate limiting | 17 requests before throttle in test environments | Glam |
| Cloud Functions cold start | ~3-5s on first invocation; use min_instances for critical paths | SpinDineSwift |
| Firestore `db.getAll()` | 500-doc limit per call; batch if larger | SpinDineSwift |
| Firestore batched writes | Max 500 operations per batch | SpinDineSwift, Glam |
| Scheduled functions (v2) | Self-configuring via `onSchedule` decorators, no firebase.json entry needed | AXIOM |
| RLS pattern | Tenant-scoped subcollections: `tenants/{id}/collection/{docId}` | AXIOM |
| Emulator ports | Auth:9099, Firestore:8080, Functions:5001, Hosting:5000 | All |

## Gemini / Vertex AI (used by: glam, spindineswift, axiom)

| Concern | Known Constraints | Source Project |
|---|---|---|
| Cost per call | ~$0.039/call (Gemini 2.0 Flash, 1024px output) | Glam |
| Image generation | Use `gemini-2.0-flash-exp` for editing; `imagen-3.0-generate-002` for generation | Glam |
| Rate limits | 10 RPM on free tier; 60 RPM on pay-as-you-go | Glam |
| Preview models | May disappear without notice; pin versions in production | Glam |

## Cloudflare (used by: axiom, moltworker)

| Concern | Known Constraints | Source Project |
|---|---|---|
| KV eventual consistency | Reads may lag writes by ~60s; use Firestore as source of truth, KV as cache | AXIOM |
| R2 bucket naming | `moltbot-data` kept for backward compat; prefix-namespaced by tenantId | AXIOM |
| Durable Objects | Standard-4 class, max 50 instances, SQLite storage | AXIOM |
| Worker secret header | `X-Gateway-Secret` for container→Worker auth | AXIOM |
| Containers | Sandbox container with CDP shim for browser rendering | AXIOM |

## iOS / Swift Patterns (used by: glam, spindineswift)

| Concern | Known Constraints | Source Project |
|---|---|---|
| DI failures | Singleton state leakage in tests; use protocol-based injection | Glam, SpinDineSwift |
| XCTest .contextMenu | Cannot tap context menu items in UI tests; known XCTest limitation | Glam |
| @MainActor | Use explicitly for UI-bound code; never DispatchQueue.main | Global rule |
| Structured concurrency | Prefer async/await + TaskGroup over GCD; cancel tasks in onDisappear | Global rule |
| Image caching | 3-tier: memory (NSCache) → disk (URLCache) → network | Glam |

## Supabase / PostgreSQL (used by: quantre)

| Concern | Known Constraints | Source Project |
|---|---|---|
| Mixed ID strategy | Serial integers for internal, UUIDs for external — causes inconsistency | QuantRE |
| Drizzle ORM | Type-safe schema; migrations in `migrations/drizzle/` | QuantRE |
| RLS | Row-level security on all user-facing tables | QuantRE |

## MCP Servers (used by: quantre)

| Server | Data Source | Status |
|---|---|---|
| census-server | US Census Bureau API | Production-ready |
| fred-server | Federal Reserve Economic Data | Production-ready |
| bea-server | Bureau of Economic Analysis | Production-ready |
| bls-server | Bureau of Labor Statistics | Production-ready |
| property-data-mcp | Property information | Production-ready |
| market-data-mcp | Market analytics | Production-ready |
