# Firestore Security Conventions

Cross-project rules for iOS+Firebase apps using Firestore.

## Authorization (MANDATORY)

- Verify `auth.uid === userId` for ALL user-scoped data access before proceeding
- Admin functions verify custom claims: `if (!token.admin) throw new HttpsError("permission-denied", "Admin access required")`
- Never trust client-supplied userId — always derive from `request.auth.uid`

## App Check (MANDATORY)

- `enforceAppCheck: true` on ALL Cloud Functions in production
- Environment-aware override allowed: `enforceAppCheck: isProduction()`
- Never `enforceAppCheck: false` in deployable code

## Transaction Ordering (MANDATORY)

- ALL `transaction.get()` calls MUST precede ALL writes within a transaction
- Multiple writes to same document reference MUST consolidate into single write using `FieldValue.increment()`
- Pattern: read phase → write phase (separate operations)
- FORBIDDEN: write then read in same transaction

## Query Safety (MANDATORY)

- Every `.get()` / `.getDocuments()` requires explicit `.limit(n)`
- Exception: single-document `.document(id).getDocument()`
- Cursor-based pagination only: `startAfter(lastDocument)` — never offset
- Snapshot listeners MUST include `.limit(n)` (recommended: 50-99)
- Batch operations flush every 499 operations (buffer for 500-op Firestore limit)

## Write Reliability (MANDATORY)

- FORBIDDEN: fire-and-forget writes for user data (`Task { try await db.setData(...) }` with no error handling)
- FORBIDDEN: `Task.detached` with persistence operations
- REQUIRED for user-facing collections:
  ```swift
  Task { @MainActor in
      do {
          status = .persisting
          try await persistence.save(data)
          markPersisted()
      } catch {
          markFailed()
          handleUploadFailure()
      }
  }
  ```
- Non-critical background enrichment (analytics, cache warming) may use fire-and-forget WITH error logging

## Firestore Rules

- Client CANNOT write to admin-controlled collections (subscriptions, credits, referral codes)
- User-scoped paths: `/users/{userId}/{collection}/{docId}`
- Rules must have corresponding test coverage (`firestore-security.test.js`)
