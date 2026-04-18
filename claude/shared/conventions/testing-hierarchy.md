# Testing Hierarchy Conventions

Cross-project rules for testing in iOS+Firebase apps.

## Red/Green/Refactor (MANDATORY)

- **Red**: Write failing test that reproduces the bug or describes the feature. Confirm FAIL for the right reason.
- **Green**: Write minimum code to pass test. No speculative helpers or abstractions.
- **Refactor**: Clean up with test as safety net. Re-run after each change.
- Never back-fill tests that pass on first run — that's not TDD.
- Bug fixes: regression test MUST run red on broken code first.
- Task naming convention: `Phase N TDD: write red tests for X` → `Phase N: make tests green`

## Test Categories and Coverage

| Category | Minimum | Target | What to Test |
|---|---|---|---|
| Unit tests | 60% | 80% | Business logic, UseCases, ViewModels |
| Integration tests | — | 100% critical paths | Repository→backend round-trips |
| UX contract tests | — | 100% compound flows | Multi-step operations, progress, error surfacing, terminal state |
| E2E tests | — | 5 core journeys | Full user flows against staging |
| Protocol contracts | — | 100% | All protocol implementations |
| Error paths | — | 100% | Every catch block exercises the error |

## Mock Boundaries (MANDATORY)

- **Unit tests**: Mock at Repository/Service boundary. Dependency-inject mocks.
- **Integration tests**: Real repositories + Firebase staging backend or in-memory state. No mocking Firebase.
- **Compound flow tests**: Mock at boundary (ViewModel → UseCase → Repository) with real dependencies above/below.
- **E2E tests**: Real backend + real staging project.
- FORBIDDEN: Mocks in production code. Mocks exist only in test targets.
- FORBIDDEN: Mocking builtins (FileManager, URLSession directly). Use dependency injection or protocol wrappers.

## Protocol-Based Testing

For testable services, create protocol + implementations:
- Production implementation (real dependencies)
- Mock implementation (test target only, injected via DI)
- Factory with environment detection for debug/staging/production

## Firebase Integration Tests

- Run against staging Firebase project using a test service account
- Reuse auth sessions across tests (Firebase rate-limits rapid sign-ins at ~17/minute)
- Tag test data with `testRun_{timestamp}`, delete in `tearDown`
- CI runs on push to main, develop, release/*

## UX Contract Tests (MANDATORY for compound flows)

Compound user flows (multi-step operations, async pipelines, modal sequences) must have contract tests that enforce behavioral invariants. These catch the user-facing bugs that unit tests miss.

### Required Contracts

| Contract | Invariant | Failure Mode It Prevents |
|---|---|---|
| **OperationProgress** | Progress reaches 100% ~1s before result; starts at 0%; `updateStageProgress()` called before `complete()` | Progress bar stuck at 0% or jumping |
| **CompoundAction** | Multi-step flows stop on first error; no silent mid-chain failures | User sees success toast but data wasn't saved |
| **ErrorSurface** | Every async operation sets an error state on failure; ViewModels never swallow errors | Spinner spins forever with no feedback |
| **TerminalState** | Every enqueued operation reaches `complete()` or `fail()` within timeout | Banner/spinner hangs indefinitely |
| **SheetConsistency** | Modal sheets dismiss cleanly; @State vs @Binding behavior documented | Sheet reopens immediately after dismiss |

### How to Write UX Contract Tests

1. **Identify the compound flow** — any operation with 2+ async steps or user-visible state transitions
2. **Define the invariant** — what must always be true from the user's perspective
3. **Write the contract test** — assert the invariant holds across happy path, error path, and timeout path
4. **Test against real timing** — use `XCTestExpectation` with realistic timeouts, not instant mocks

### When to Add a UX Contract

- Any new multi-step async operation (try-on, extraction, upload + process)
- Any flow with user-visible progress indicators
- Any flow that crosses ViewModel boundaries (Sheet A → triggers operation → updates Sheet B)
- After any bug where "it worked in tests but users saw a hang/flash/error swallow"

## QA Review Protocol

For P0/P1, security, lifecycle, and trust-boundary changes, enforce this ordering:

1. Behavioral proof — validate the proof contract exists
2. Red test evidence — test fails on parent commit, passes on current
3. Second-reviewer audit (if applicable)
4. **Only after 1-3 pass**: syntactic gates (`/standards-check`, `/security-audit`, `/perf-check`, `/test-gen`)

Running syntactic gates first creates the failure mode: syntax-green markers with no behavioral proof.
