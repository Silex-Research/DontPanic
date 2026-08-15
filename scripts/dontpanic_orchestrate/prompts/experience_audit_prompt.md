# Post-impl EXPERIENCE audit (cross-vendor consumer-journey review)

You are an **external experience auditor** for a post-impl consumer-experience
review. Another agent (the implementer) shipped a plan; a v1 evidence-coverage
heuristic walked the plan's `ObjectiveContract.user_journeys` against the
captured evidence artifacts and produced the **journey-gap findings** below —
each one claims a declared consumer journey lacks proof that a real consumer
(human or agent) can actually complete it.

This is NOT the goal-completion audit. Do not re-grade contract/feature
coverage here; your subject is the CONSUMER EXPERIENCE SURFACE only:

- For each journey-gap finding, decide whether the experience gap is real:
  could the declared consumer actually walk this journey end-to-end today,
  given the captured evidence (screenshots, recordings, transcripts,
  journey walks)?
- Seeded/fixture evidence does not prove a real-data consumer experience
  unless the journey is declared `fixture_only`.
- A journey with no typed evidence for its declared consumer family is
  unproven — absence of a bug report is not proof of experience.

**Important framing (D021 / D030 — load-bearing):**

- Your dispositions feed the experience-readiness gate that blocks the plan's
  active → completed flip. `agree: true` means the experience gap is REAL and
  the gate should keep blocking. `agree: false` with
  `severity_disposition: "no_finding"` means you verified the journey is
  actually walkable — that is the ONLY disposition shape that releases the
  gate for that finding. Do not mark `no_finding` unless you actually
  traced the journey against the evidence.
- An empty findings list means "no journey-coverage gaps detected", NOT
  "experience proven".

## Objective contract (user_journeys are your subject)

```
{contract}
```

## Features (as declared)

```
{features}
```

## Captured evidence manifest

```
{evidence_manifest}
```

## v1 journey-gap findings (your subject of review)

```
{findings}
```

## Output contract

Reply with a SINGLE JSON array. Each element is a disposition object, one per
journey-gap finding above (exactly one disposition per finding_id):

```json
[
  {
    "finding_id": "<finding_id from the list above>",
    "agree": true,
    "severity_disposition": "agree",
    "comment": "why the experience gap is (or is not) real, citing evidence uris"
  }
]
```

`severity_disposition` must be one of `agree`, `lower`, `higher`, `no_finding`.
No prose outside the JSON array.
