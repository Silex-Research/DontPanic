# Error Handling Conventions

Cross-project rules for error handling in iOS+Firebase apps.

## iOS Error Types (MANDATORY)

- Every service/UseCase defines its own error enum conforming to `LocalizedError`
- All cases provide `errorDescription` for user-facing messages
- Never expose internal errors to users; wrap in generic message

```swift
enum ServiceError: LocalizedError {
    case networkFailure(Error)
    case quotaExceeded
    case invalidInput(String)
    var errorDescription: String? { /* user-friendly text */ }
}
```

## Async Error Handling (MANDATORY)

- Never use `try!` in production code (FORBIDDEN)
- `try?` only when failure is genuinely acceptable and the error carries no information
- All async operations in ViewModels MUST surface errors (e.g., `@Published errorMessage`)
- Catch specific errors before generic fallback

```swift
do {
    let result = try await service.fetchData()
} catch ServiceError.quotaExceeded {
    // Specific handling
} catch {
    // Generic fallback with logging
}
```

## Backend Error Standards (MANDATORY)

- Use `HttpsError` with standard codes: `invalid-argument`, `unauthenticated`, `permission-denied`, `not-found`, `resource-exhausted`, `internal`
- Never expose internal errors: catch, log with context, throw generic `HttpsError("internal", "An error occurred")`
- All backend functions include error handling block
- Log errors with structured context: `logger.error("Operation failed", { error: error.message, userId, functionName })`

## Cloud Function Pattern (MANDATORY)

```typescript
try {
    const result = await mainOperation();
} catch (error) {
    logger.error("Operation failed", { error: error.message, stack: error.stack });
    throw new HttpsError("internal", "An error occurred");
}
```

## Error Classification (for AI/pipeline projects)

Projects with AI pipelines or enrichment stages should classify errors:

| Class | Action |
|---|---|
| `RETRYABLE_RATE_LIMIT` | Re-enqueue with exponential backoff + jitter |
| `RETRYABLE_TRANSIENT` | Re-enqueue with linear backoff |
| `PERMANENT_AUTH` | Dead letter, alert |
| `PERMANENT_SAFETY` | Dead letter, log for review |
| `PERMANENT_INPUT` | Dead letter, notify user |
| `PERMANENT_MODEL` | Dead letter, try alternate model |

- Retries exceeding `MAX_RETRIES` go to dead letter with idempotent credit refund
- Route all mid-work errors through a centralized error handler that releases resources before re-enqueue
