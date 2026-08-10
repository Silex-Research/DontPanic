# agent-conventions

agent-conventions is a shared schema repository consumed via `git subtree` by downstream agent projects (DontPanic, Jarvis, Glam, SpinDineSwift). It defines the canonical schemas (plan, features, audit, environments, signoff, state-snapshot, objective-contract) and their Pydantic mirrors that those projects validate against, plus the resolver spec, conventions, and skill standards.

**License:** MIT (see `LICENSE`). **Versioning:** tagged releases (v1.0.0+). Always pin subtrees to tags; never pull HEAD into production projects.

## Known downstream consumers

| Project | Subtree path | Notes |
|---|---|---|
| DontPanic | `claude/shared/` | Schema authority; defines canonical orchestration shapes |
| Jarvis | `claude/shared/` | Legacy name; same shape as DontPanic |
| Glam (Styln) | `.claude/shared/` | iOS + Firebase consumer |
| SpinDineSwift | `.claude/shared/` | iOS + Firebase consumer |

To register a new consumer: open a PR adding a row to the table above. Subtree path convention: `claude/shared/` (DontPanic-family) or `.claude/shared/` (Styln-family). Tag-pinned pulls only.

## What's Inside

```
resolver/
  SPEC.md          — Format definition for project-local RESOLVER.md files
  validate.py      — Universal validator (reachability, MECE, conformance, conventions)

conventions/
  index.md         — One-liner per convention; skills reference this
  firestore-security.md
  error-handling.md
  testing-hierarchy.md
  naming.md
  security.md

skill-standard/
  CONFORMANCE.md   — Required structure for skill files
  TEMPLATE.md      — Skeleton for new skills

claude-md/
  STANDARDS.md     — How to build and maintain .claude.md files (<120 lines)
```

## Consuming This Repo

### First-time setup

```bash
cd your-project
git subtree add --prefix=.claude/shared \
  git@github.com:yourorg/agent-conventions.git v1.0.0 --squash
```

### Updating to a new version

```bash
git subtree pull --prefix=.claude/shared \
  git@github.com:yourorg/agent-conventions.git v1.1.0 --squash
```

### Project layout after adoption

```
your-project/
├── .claude/
│   ├── shared/              ← this repo (subtree, don't edit in-place)
│   ├── RESOLVER.md          ← project-local trigger→skill routing table
│   ├── conventions/         ← project-local convention extensions
│   ├── agents/              ← role-specific agent definitions
│   └── commands/            ← skill files
├── .claude.md               ← project gotchas (<120 lines)
└── docs/
    ├── GLOBAL_STANDARDS.md  ← comprehensive standards (loaded by skills)
    └── architecture/ADR-*   ← decision records
```

## Running the Validator

```bash
python3 .claude/shared/resolver/validate.py \
  --resolver .claude/RESOLVER.md \
  --skills-dir .claude/commands/ \
  --conventions-dir .claude/shared/conventions/ \
  --local-conventions-dir .claude/conventions/
```

Exit codes: 0 = pass, 1 = failures, 2 = usage error.

## Versioning

Tagged releases (v1.0.0, v1.1.0, etc.). Pin to tags when pulling subtrees. Never pull HEAD into production projects.

## Design Principles

1. **Shared conventions, local resolvers** — conventions are universal; skill routing is project-specific
2. **Reference, don't inline** — skills reference convention files; the validator flags inlining
3. **Agent tables filter the resolver** — role-specific ordering/exclusions stay in agent definitions; the resolver provides the shared catalog
4. **Stability via tags** — subtrees are inert snapshots; bad commits don't propagate until explicitly pulled
