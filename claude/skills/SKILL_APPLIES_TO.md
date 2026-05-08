# `applies_to:` — skill self-declaration shape

Plan **2026-05-08-002-feat-skill-applicability-v0** introduces the
`applies_to:` block in `SKILL.md` frontmatter. The block lets a skill
self-declare which plan surfaces and goal types it is advisory for.
At lock time, `dontpanic plan lock` runs the skill-applicability matcher
in `scripts/dontpanic_orchestrate/skill_applicability.py`; the matcher
reads each skill's `applies_to:` block and intersects it with the plan's
declared `surfaces:` (canonical enum from agent-conventions v1.5.0
`plan.schema.json`) and `goal_type:`. Matches land in
`<plan_dir>/evidence/applicable-skills.json` as advisory output.

The matcher is **advisory only**. It does NOT block lock or signoff,
escalate, or enforce skill invocation. Operators read the sidecar and
decide whether to invoke the matched skills. See plan 2026-05-08-002
decisions D001 (decentralized self-declaration), D003 (lock-time only,
no scope-change re-probe), D004 (advisory only) for rationale.

## Shape

```yaml
applies_to:
  surfaces: [<surface>, <surface>, ...]
  goal_types: [<goal_type>, <goal_type>, ...]
  external_cli:        # optional, inert metadata
    provider: <string>
    name: <string>
    command: <string>
    version_pin: <string>
```

`applies_to` is **optional** on every skill. Skills without the block
are silently skipped by the matcher (a one-line "skill has no
applies_to" rationale lands in the report's `skipped:` list); they
incur no penalty.

### `surfaces:`

A subset of the canonical 10-value enum from `plan.schema.json`:

```
web | ios | android | backend | infra | security | data | ux | ml | docs
```

A skill may declare any non-empty subset. The matcher emits a Match
when a plan's `surfaces:` list intersects with the skill's
`applies_to.surfaces` list (set-intersection, not subset).

### `goal_types:`

A subset of the canonical `goal_type` enum from `plan.schema.json`:

```
mechanical | infra | refactor | parity | new_feature | migration | incident
```

A plan declares exactly one `goal_type:` (or omits it). When omitted,
the matcher does not consider goal-type intersection — only
`surfaces:` need overlap.

### `external_cli:` (optional, inert)

Metadata-only hook for skills backed by an external command-line tool
(e.g., a Printing Press-style adapter). The matcher copies the four
sub-fields into matching report entries and sets
`provenance: "external"`; it does **not** install, invoke, allowlist,
verify, hash, or score the CLI in v0. Per D007, adapter execution
governance is reserved for a separate plan.

| Field | Description |
|-------|-------------|
| `provider` | Vendor / origin label (e.g., `printing-press`) |
| `name` | Human-readable adapter name |
| `command` | Argv-zero the adapter publishes (advisory only) |
| `version_pin` | SemVer constraint or fixed tag the adapter expects |

Skills without `external_cli:` are reported with `provenance: "internal"`.

## Examples

### `pr-reviewer` — backend + infra refactors

```yaml
applies_to:
  surfaces: [backend, infra]
  goal_types: [refactor, new_feature, fix]
```

Diff-based review surfaces best for backend / infra changes that
touch code paths. Matches `refactor`, `new_feature`, and `fix` plans.

### `eval-harness` — ml grading + ux acceptance

```yaml
applies_to:
  surfaces: [ml, ux]
  goal_types: [new_feature, parity]
```

ML changes that need offline accuracy criteria and UX flows that need
behavioral acceptance both benefit from a defined eval harness. The
`ux` declaration here exercises the motivating gap from plan
2026-05-08-002 (D007).

### `security-review` — security audits across the stack

```yaml
applies_to:
  surfaces: [security, backend, infra]
  goal_types: [new_feature, fix, refactor, migration]
```

OWASP-informed audit pass; advisory whenever a plan touches auth,
data flow, or infrastructure. Surfaces include `security` so plans
that explicitly declare a security surface get a guaranteed match.

### `cost-model` — infra forward projections

```yaml
applies_to:
  surfaces: [infra]
  goal_types: [infra, new_feature, migration]
```

Read-only spend projection. Useful for plans that change cost shape
(infra, new feature with new model usage, migrations).

### `agent-browser` — web automation with ux acceptance

```yaml
applies_to:
  surfaces: [web, ux]
  goal_types: [new_feature, parity]
```

Browser-automation skill for web flows. Declares `ux` so plans that
list `ux` in `surfaces:` get a match for browser-driven UX tests.

## Matcher behavior

Pseudocode (see `scripts/dontpanic_orchestrate/skill_applicability.py`
for the canonical implementation in F002):

```python
def match(plan_surfaces, plan_goal_type, skill_applies_to):
    if not skill_applies_to:
        return Skip("skill has no applies_to")
    surface_overlap = set(plan_surfaces) & set(skill_applies_to.surfaces)
    if not surface_overlap:
        return None  # not a match
    if plan_goal_type and skill_applies_to.goal_types:
        goal_overlap = {plan_goal_type} & set(skill_applies_to.goal_types)
        if not goal_overlap:
            return None
    else:
        goal_overlap = set()  # plan or skill didn't constrain
    return Match(
        skill_name=...,
        matched_surfaces=sorted(surface_overlap),
        matched_goal_types=sorted(goal_overlap),
        rationale=f"surfaces {sorted(surface_overlap)} overlap; "
                  f"goal_types {sorted(goal_overlap) or '∅'} overlap",
        provenance="external" if skill_applies_to.external_cli else "internal",
        external_cli=skill_applies_to.external_cli,
    )
```

## Adding `applies_to:` to a new skill

1. Decide which surfaces the skill is advisory for. Pick the smallest
   accurate subset — over-claiming inflates false-positive rate, which
   is the v0 false-positive budget (D004).
2. Decide which goal types the skill is advisory for. Omit
   `goal_types:` if the skill applies to any goal type.
3. Add the block to the SKILL.md frontmatter. Verify the frontmatter
   still parses by running `python3 -c "import yaml; yaml.safe_load(open('SKILL.md').read().split('---')[1])"`.
4. No registration step. The matcher discovers the skill at lock time.

## Adding a new surface value

Adding a new surface (e.g., `cli`, `pwa`, `marketing`) requires a
`plan.schema.json` schema bump in agent-conventions (v1.6.0+) plus
operator approval. See plan 2026-05-08-002 D002 for the lock decision.
