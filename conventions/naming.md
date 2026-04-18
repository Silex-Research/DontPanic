# Naming Conventions

Cross-project naming rules for iOS+Firebase apps. Language-specific rules (Swift, TypeScript, Python, etc.) live in `~/.claude/rules/` — this file covers project-level naming patterns.

## Swift

- Classes/Structs: `PascalCase` — `PhotoManager`, `ClosetItem`
- Methods/Properties: `camelCase` — `uploadPhoto()`, `isProcessing`
- Protocols: `PascalCase` — `Cacheable`, `ExtractionRepositoryProtocol`
- Enums: `PascalCase`, cases `camelCase` — `enum Status { case queued, processing }`
- Files: match primary type — `PhotoManager.swift`

## TypeScript

- Functions: `camelCase` — `extractOutfit()`
- Interfaces/Types: `PascalCase` — `interface ClosetItem {}`
- Constants: `UPPER_SNAKE_CASE` — `const MAX_ITEMS = 8`
- Files: `kebab-case` — `extract-to-closet.ts`

## Firestore

- Collections: `snake_case`, plural — `users/{userId}/closet_items/{itemId}`
- Fields in Firestore: `snake_case` — `isolated_image_url`
- Fields in code: `camelCase` — `item.isolatedImageUrl`
- Document IDs: auto-generated or deterministic composite keys — never user-supplied strings

## Cloud Functions

- Export names: `verbNounVersion` — `extractToClosetV3`, `processExtractionJobs`
- Pattern: `export const functionNameV# = onCall(...)`
- Scheduled functions: `verbNounScheduled` or in `scheduled/` directory

## Skill Files

- Filename: `kebab-case.md` — `firebase-validate.md`, `standards-check.md`
- Frontmatter `name` field matches filename without `.md`

## Agent Files

- Filename: `PascalCase.md` — `Backend-Engineer.md`, `QA-Reviewer.md`
- Agent names match filenames in dashboards and task assignments

## Project-Specific Terminology

Each project may define a terminology table in `.claude/conventions/terminology.md` to enforce consistent naming across iOS UI, backend API, Firestore fields, and docs. Example:

```markdown
| Concept | iOS UI | Backend API | Firestore | Docs |
|---------|--------|-------------|-----------|------|
| User photos | "Your Photos" | personPhotos | person_photos | "user photos" |
```

Forbidden terms should be listed with the correct replacement.
