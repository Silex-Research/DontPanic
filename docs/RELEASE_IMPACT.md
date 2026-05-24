# Release Impact Checklist

DontPanic plans land on operator-visible surfaces — CLI commands, dashboard,
README, onboarding flow, capability manifests, schemas, public metadata. This
document is the canonical checklist plans use before lock, and the source of
truth for the advisory checker shipped with `dontpanic next`
(plan 2026-05-23-007 F003).

Release-impact advice is **advisory**. A draft-time advisory uses the plan's
declared intent (`surfaces`, `allowed_paths`, and feature step path tokens).
A lock-time advisory may additionally use the staged/unstaged git diff for
precision. Neither blocks plan lock or dispatch.

## Surfaces

Surfaces are the user-visible places a change might need to land alongside
the code change.

| Surface | What it means | Typical owner |
|---|---|---|
| `root_changelog` | Entry in this repo's root `CHANGELOG.md` (product-facing). | Plan author |
| `shared_changelog` | Entry in `claude/shared/CHANGELOG.md` (agent-conventions subtree). | Plan author + agent-conventions maintainer |
| `readme` | `README.md` at repo root. | Plan author |
| `onboarding` | `docs/GETTING_STARTED.md`, `docs/AGENT_QUICKSTART.md`, `init`/`doctor` CLI flow text. | Plan author |
| `architecture` | `docs/architecture/**` map snapshots, `docs/architecture.json`. | Architecture-regen hook + plan author |
| `dashboard` | Anything under `dashboard/**` or `scripts/dontpanic_orchestrate/dashboard*.py`. | Plan author |
| `capability_manifest` | `capabilities/*.json` manifest files. | Capability owner |
| `cli_help` | Argparse `help=` strings, command names, flag names, `--help` output. | Plan author |
| `schemas` | `claude/shared/schemas/v1.0/*.schema.json` and Pydantic mirrors. | Schema maintainer |
| `public_metadata` | Repo description, social preview image, topics, discoverability assets. | Maintainer |

## When to update which changelog

The first decision is *whether the change touches a public/product surface at
all*. Internal-only changes — supervisor refactors, additional tests, ledger
files, evidence — usually need neither changelog.

| Pattern (any path matches) | Suggested surfaces | Reasoning |
|---|---|---|
| `README.md`, `docs/GETTING_STARTED.md`, `docs/AGENT_QUICKSTART.md`, `docs/PRODUCT.md`, `docs/USE_CASES.md`, `docs/ECOSYSTEM.md`, `docs/DISCOVERABILITY.md` | `root_changelog`, `readme` or `onboarding` | Public docs surface — what a new user sees. |
| `dashboard/**`, `scripts/dontpanic_orchestrate/dashboard*.py`, `scripts/dontpanic_orchestrate/state_projection.py`, `scripts/dontpanic_orchestrate/operator_console.py` | `root_changelog`, `dashboard` | Operator console behavior or state shape. |
| `capabilities/*.json` | `root_changelog`, `capability_manifest` | Capability surface — declared setup steps and bindings are public. |
| `claude/shared/schemas/**/*.json`, `claude/shared/schemas/**/models/*.py` | `shared_changelog`, `schemas` (and `root_changelog` if the CLI starts enforcing) | Agent-conventions schema change. Root entry only when DontPanic's own behavior changes too. |
| `scripts/dontpanic_orchestrate/cli.py` (argparse `help=`, new subcommand, flag rename) | `root_changelog`, `cli_help` | CLI is the canonical operator surface. |
| `docs/architecture/**`, `docs/architecture.json` | `architecture` | Architecture map; auto-regenerated, but a major refactor that changes the architecture-map contract belongs in the root changelog too. |
| Repo metadata files (`.github/repository.yml`, social preview, topics, `pyproject.toml` description) | `root_changelog`, `public_metadata` | Discoverability signals. |
| `scripts/dontpanic_orchestrate/**` interior modules NOT named above (planner, breakers, runner, executors), `tests/**`, `evidence/**`, `audit/**`, `docs/plans/**`, `decisions.jsonl`, ledger files | usually none | Internal implementation — neither changelog required. |
| `firestore.rules`, `firestore.indexes.json`, `firebase.json`, `storage.rules` | `root_changelog` if it changes operator-visible behavior; otherwise none | Deployable surfaces. |

`shared_changelog` is sufficient (and root is **not** required) when a change
is strictly inside `claude/shared/**` and does NOT alter DontPanic's CLI,
dashboard, or operator-visible flow. The most common case is a backward-
compatible schema field addition that DontPanic's runtime ignores until
operators opt in.

`root_changelog` is required (in addition to `shared_changelog` if the change
spans `claude/shared/**`) for everything else with a public surface:
operator-visible CLI flags or text, dashboard behavior, README/onboarding,
capability manifests, public metadata.

## Authoring checklist

Before locking a plan, the author answers:

1. **README / public docs.** Does this change what a new user reads on the
   landing page or in the getting-started flow?
2. **Onboarding / init / doctor.** Does the change touch `dontpanic init`,
   `dontpanic doctor`, or the documented bootstrap?
3. **Architecture map.** Does it add a new top-level module, rename a
   surface, or change cross-module wiring enough that the architecture map
   should be regenerated and reviewed?
4. **Dashboard.** Does it change anything an operator can see in the
   dashboard, or the JSON shape the dashboard reads?
5. **Capability manifests.** Does it add, rename, or remove a capability,
   change a setup step, or alter a manifest field?
6. **CLI help.** Does it add, rename, or remove an operator-facing
   command, flag, subcommand, or `--help` text?
7. **Schemas.** Does it touch `claude/shared/schemas/**` or the matching
   Pydantic models? If the schema is strictly additive, mark the version
   bump appropriately and check whether the DontPanic runtime now enforces
   the new field.
8. **Public metadata.** Does it change the repo description, social preview,
   topics, discoverability copy, or any other public-facing identity surface?
9. **Changelog.** Based on the answers above, does this require a root
   `CHANGELOG.md` entry, a `claude/shared/CHANGELOG.md` entry, or both?

If the answer to any of 1-8 is yes, the plan's feature acceptance MUST name
the surface and the update it ships. "We will remember to update the README"
is not an acceptance clause. The release-impact advisory in `dontpanic next`
exists to catch obvious omissions, not to replace this answer.

## How the advisory checker is used

- `dontpanic next` is the **primary** surface. Each not-yet-passing feature
  carries a draft-time advisory derived from the plan's `surfaces`,
  `allowed_paths`, and feature step path tokens.
- Plan-lock messaging is the **secondary** surface. When `dontpanic plan
  lock` runs and a git diff is available, the same checker can be invoked
  against the changed paths for a more precise advisory. There is no v0
  sidecar requirement; the messaging is informational.
- The checker writes nothing. It produces a `ReleaseImpactAdvisory` value
  the calling surface decides how to render.
- Advisory false positives are expected. A plan whose `allowed_paths`
  include `docs/**` will get a `root_changelog` advisory even if the docs
  change is internal-only. The operator is expected to confirm rather than
  follow blindly.
