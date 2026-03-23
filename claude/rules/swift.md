---
globs: "*.swift"
description: Swift/SwiftUI conventions for iOS apps (Glam, SpinDineSwift)
---

# Swift Rules

## Naming
- Files: `PascalCase.swift` matching the primary type (e.g., `TryOnViewModel.swift`)
- Types/Protocols: `PascalCase`
- Functions/properties: `camelCase`
- Boolean properties: read as assertions (`isLoading`, `hasPermission`, `canSubmit`)
- Protocols: noun for capability (`Loadable`), `-ing` for ongoing (`Processing`), `-able` for passive

## Error Handling
- Define domain-specific error enums conforming to `LocalizedError`
- Use `Result<T, Error>` for async operations that can fail
- No force unwraps (`!`) in production code — use `guard let` or `if let`
- `try?` only when you genuinely want to discard the error
- No empty catch blocks

## Architecture
- MVVM with `@Observable` (iOS 17+) or `ObservableObject` (older targets)
- ViewModels own business logic, Views are declarative
- Services as actors for thread safety — `actor NetworkService`
- No business logic in Views — extract to ViewModel or Service
- Use `@MainActor` explicitly for UI-bound code, not `DispatchQueue.main`

## SwiftUI
- Prefer smaller, composable Views over large monolithic ones
- Extract repeated view patterns into `ViewModifier` or helper Views
- Use `task { }` for async work, not `onAppear` with `Task { }`
- Prefer `@State` + `@Binding` over `@EnvironmentObject` for local state
- Use `LazyVStack`/`LazyHStack` inside `ScrollView` for large lists

## Concurrency
- Use structured concurrency (`async/await`, `TaskGroup`) over GCD
- Mark shared mutable state as `actor`-isolated or `@MainActor`
- No `DispatchQueue.main.async` — use `@MainActor`
- Use `Task.detached` only when you need to escape the current actor
- Cancel tasks in `deinit` or `onDisappear`

## Testing
- Framework: XCTest (or Swift Testing for new targets)
- Test files: `*Tests.swift` in a test target
- Use dependency injection — no singletons in testable code
- Mock protocols, not concrete types
- Test public interface, not private methods

## Security
- Store secrets in Keychain, not UserDefaults
- Enable App Transport Security — no HTTP exceptions without justification
- Validate server certificates — no `URLSession` trust-all delegates
- Use `Data` not `String` for sensitive values (keys, tokens)
- Clear sensitive data from memory when no longer needed
