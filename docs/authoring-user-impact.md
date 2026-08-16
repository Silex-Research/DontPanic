# Authoring `user_impact`

Plan 2026-08-09-002 F009. Referenced from the plan-artifacts skill.

`user_impact` is the one field the renderer cannot invent. It is what the
operator reads at a gate. A restated description is not an impact.

## The four audience values

| Audience | Means | Requires |
|---|---|---|
| `end_user` | A person using the product feels this | `summary` ≥ 10 chars + non-empty `surfaces` + `description_hash` |
| `operator` | The person running DontPanic feels this | same |
| `agent` | A worker or auditor agent feels this | same |
| `none` | Nobody outside the team feels this | **omit** `summary` and `surfaces` — the word is the whole declaration |

`audience: none` is a complete answer. Do not invent ten characters of
prose about a change with no external consequence.

## Useful summary vs restated description

A useful summary names an observable difference for the audience:

- Good: "Opening Closet starts on the last outfit they wore, not a blank grid."
- Bad: "Persist the last-worn look id and hydrate Closet from that id on launch."

The bad line is the feature description. The operator already has that in
`what_changes`. The summary answers "so what?"

## Surfaces

Reuse the plan-level surface enum. Name where the audience meets the
change (`ux`, `ios`, `web`, `android`, `docs`, `backend`). Do not list
every layer the patch touches.

## Staleness

`description_hash` is SHA-256 of the feature `description` (UTF-8, no
normalization). If you edit the description, recompute the hash or the
gate will mark the declaration possibly-stale rather than present old
copy as current.

```python
import hashlib
print(hashlib.sha256(description.encode("utf-8")).hexdigest())
```
