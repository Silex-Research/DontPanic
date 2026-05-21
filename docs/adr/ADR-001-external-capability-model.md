# ADR-001: External Capability Model

Status: proposed

Date: 2026-05-21

## Context

DontPanic now integrates with several things it does not own or bundle:
agent CLIs, Discord webhooks, Firebase realtime dashboard infrastructure,
Printing Press generated adapters, PM tools such as Linear, and broker
runtimes such as OpenClaw.

Those integrations already share a shape, but the shape is currently
spread across several surfaces:

- `prereq_registry.py` verifies whether a capability is usable.
- `~/.dontpanic/adapters.json` records locally installed adapters.
- Category contracts, such as the PM-tool contract, define adapter ports.
- Plan-level references, such as `external_refs[]`, bind work to an
  external system.

Without one manifest convention, each new integration becomes bespoke
wiring across doctor, init, adapters, plan frontmatter, and docs. That
is already visible: Discord shipped as direct webhook configuration,
Firebase is an adapter but lives outside DontPanic core, and Linear uses
the Printing Press/PM-tool path.

## Decision

DontPanic models every external or optional integration as an
**external capability** declared by a manifest under `capabilities/`.

The manifest is the source of truth for these questions:

- What is this capability?
- Is setup required?
- Which profiles include it by default?
- What does DontPanic core own?
- What does the adapter own?
- What must the operator configure?
- How is the capability verified?
- How may it mutate state, if at all?

This is a lightweight ports-and-adapters convention, not a plugin
runtime and not a new CLI surface. The first version adds manifests and
documentation only. Existing primitives consume those manifests over
time:

- doctor/init consume `verify` and `default_in_profiles`.
- adapter registration consumes `id`, `kind`, and `category`.
- category contracts consume `category`.
- plan references consume stable capability IDs.
- docs and agents consume `owner_boundary`, `setup_required`, and
  `setup_doc`.

## Required Manifest Fields

Every manifest starts with:

- `schema_version`: manifest schema version, initially `"1.0.0"`.
- `id`: stable capability ID.
- `kind`: broad shape:
  - `agent_cli`: operator-installed agent runtime invoked by DontPanic.
  - `notification_sink`: push-only notification target.
  - `service_adapter`: API/CLI wrapper for an external service, with no
    operator-deployed infrastructure.
  - `external_adapter`: adapter with operator-deployed infrastructure,
    such as Cloud Functions, Firestore rules, or a hosted sync process.
- `category`: category port when applicable, such as `pm-tool` or
  `dashboard-realtime`.
- `setup_required`: whether an operator must configure anything before
  use.
- `setup_doc`: path to the setup or integration documentation.
- `default_in_profiles`: doctor/init profiles that include this
  capability by default.
- `requires`: external commands, services, files, env vars, auth, or
  config needed by the capability.
- `verify`: how doctor or an agent verifies readiness.
- `owner_boundary`: explicit split between DontPanic core, adapter, and
  operator responsibilities.
- `mutation_boundary`: how state changes are allowed, or a statement
  that the capability is read-only / push-only.

## Boundary Rule

External capabilities must not write into DontPanic local state except
through a governed DontPanic path. In particular, they must not perform
ungoverned direct writes to:

- no direct writes to `docs/plans/**`
- no direct writes to `~/.dontpanic/**` except their own registered
  adapter config
- no direct mutation of gate or signoff state

Mutations must pass through DontPanic MCP tools, explicit governed
DontPanic commands, the supervisor executor/audit-writer path, or an
adapter command that writes a durable evidence record. Mirrors and
dashboards may read state projection output, but they do not become the
source of truth.

## Consequences

Positive:

- Humans and agents get one place to inspect what an integration needs.
- Firebase can be clearly modeled as an optional realtime adapter, while
  the static dashboard remains core.
- Discord, Linear, Firebase, and agent CLIs use the same declaration
  convention despite having different runtime shapes.
- Future `dontpanic capabilities list/show` can be built from the
  manifests if operator demand appears.

Negative:

- Existing integrations need a backfill pass.
- Doctor/init/adapters must avoid duplicating manifest facts as they
  gradually consume this convention.
- The manifest is another artifact authors must keep current.

## Non-Decisions

This ADR does not add:

- a plugin marketplace
- automatic adapter installation
- `dontpanic capabilities` CLI
- hosted control plane
- MCP-only integration requirements

Discord webhooks, Firebase Cloud Functions, and Printing Press generated
MCP servers remain different runtime shapes. The manifest only unifies
their declaration and setup boundaries.

## Initial Manifests

The first manifest set spans the current integration classes:

- `capabilities/discord-notify.json`
- `capabilities/firebase-dashboard.json`
- `capabilities/linear.json`
- `capabilities/agent-claude-cli.json`

These examples are intentionally concrete enough for doctor/init/plan
lock consumers to adopt later without defining a new registry service.
