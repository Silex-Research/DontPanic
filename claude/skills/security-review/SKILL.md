---
name: security-review
description: OWASP-informed security review adapted for Swift/iOS, TypeScript/Cloudflare/Firebase, Python, Ruby, SQL/Supabase. Can be invoked manually or triggered proactively when touching auth/security code.
disable-model-invocation: true
argument-hint: [--scope <path>] [--focus auth|injection|data|infra|all]
---

# Security Review — Stack-Specific Security Audit

You are a security reviewer. Perform a targeted security audit of the specified code, adapted to the actual stack in use.

## Inputs (from $ARGUMENTS)

| Param | Default | Description |
|-------|---------|-------------|
| --scope | changed files (git diff) | Path or glob to review |
| --focus | all | Focus area: `auth`, `injection`, `data`, `infra`, or `all` |

## Checklists by Language/Platform

### TypeScript / Cloudflare Workers / Firebase

**Injection (A03)**
- [ ] All user input validated with Zod or equivalent at API boundary
- [ ] No string interpolation in SQL, Firestore queries, or shell commands
- [ ] No `eval()`, `new Function()`, or dynamic `import()`
- [ ] HTML output sanitized (DOMPurify or framework escaping)

**Authentication & Authorization (A01, A07)**
- [ ] Firebase Auth or Supabase Auth used — no custom auth
- [ ] Admin endpoints check custom claims or role, not just auth status
- [ ] API keys scoped and rotated — no master keys in Workers
- [ ] CORS configured to specific origins, not `*`

**Data Protection (A02)**
- [ ] No secrets in source, wrangler.toml, or firebase.json
- [ ] Sensitive data encrypted at rest (Firestore, R2, KV)
- [ ] PII not logged — check console.log/logger calls near user data
- [ ] Firestore security rules match application logic

**Infrastructure (A05, A06)**
- [ ] Worker bindings use least-privilege (read-only KV if only reading)
- [ ] Firebase rules deny by default, allow specifically
- [ ] Rate limiting on public endpoints
- [ ] AppCheck enabled for client-facing functions

### Swift / iOS

**Transport (A07)**
- [ ] App Transport Security enabled — no HTTP exceptions without justification
- [ ] Certificate pinning on critical endpoints (auth, payment)
- [ ] No `URLSession` delegates that bypass certificate validation

**Storage (A02)**
- [ ] Secrets in Keychain, not UserDefaults or files
- [ ] Sensitive data cleared from memory after use
- [ ] No sensitive data in screenshots (use `isSecureTextEntry`, `hidden` in app switcher)
- [ ] CoreData/SQLite databases not included in backups if they contain PII

**Code (A03, A08)**
- [ ] No force-unwraps on external data — guard/optional chain
- [ ] Input validation on all text fields (length, character set)
- [ ] Deep links validated before navigation
- [ ] No hardcoded API keys or bundle IDs

### Python

**Injection (A03)**
- [ ] No `eval()`, `exec()`, `pickle.loads()` on untrusted data
- [ ] `subprocess.run(shell=False)` — never `shell=True` with user input
- [ ] SQL queries parameterized — no f-string SQL
- [ ] YAML loaded with `safe_load`, not `load`

**Dependencies (A06)**
- [ ] Dependencies pinned with hashes
- [ ] No known CVEs (run `pip-audit` or `safety check`)
- [ ] No unused dependencies that increase attack surface

### SQL / Supabase / PostgreSQL

**Access Control (A01)**
- [ ] RLS enabled on all user-facing tables
- [ ] RLS policies tested — both positive and negative cases
- [ ] Service role key never exposed to client
- [ ] Database user has minimum required privileges

**Queries (A03)**
- [ ] All queries parameterized — no string concatenation
- [ ] `SECURITY DEFINER` functions reviewed for privilege escalation
- [ ] No `GRANT ALL` — specific privileges only

### Ruby / Fastlane

- [ ] No `system()` or backticks with user input
- [ ] No `eval()` on untrusted strings
- [ ] Signing credentials in CI secrets, not in Fastfile
- [ ] Match/signing configured securely

## Output Format

```
SECURITY REVIEW — <scope>
==========================
Focus: <focus area>
Files reviewed: <N>

CRITICAL (fix before deploy):
  1. [A03] SQL injection in user_service.ts:45 — query uses string interpolation
  2. [A01] Missing auth check on /admin/export endpoint

HIGH (fix before merge):
  1. [A02] API key logged in debug statement at worker.ts:112
  2. [A07] CORS allows all origins in gateway config

MEDIUM (fix soon):
  1. [A06] 3 npm packages with known CVEs (run npm audit)

LOW / INFO:
  1. Consider adding rate limiting to /api/search

SCORE: <N>/10 (10 = no issues found)
```

## Proactive Trigger

This skill should be invoked automatically when:
- Editing files matching: `*auth*`, `*security*`, `*permission*`, `*rule*`, `*middleware*`, `*guard*`
- Adding new API endpoints or Cloud Functions
- Modifying Firestore rules, RLS policies, or CORS config
- Adding new dependencies
