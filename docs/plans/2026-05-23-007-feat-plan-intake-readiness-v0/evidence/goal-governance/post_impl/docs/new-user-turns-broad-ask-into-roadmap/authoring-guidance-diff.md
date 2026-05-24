# Authoring Guidance Evidence

F001 updated `docs/AUTHORING_PLANS.md` so a user or agent can classify an ask
as a roadmap, implementation plan, investigation, design/product spec, or
operator setup task.

Evidence summary:

- Roadmap guidance explains that strategic, multi-release asks should become
  tracking parents with executable child plans.
- Child-plan guidance names dispatchable implementation slices separately from
  future trigger-gated milestones.
- The V0 schema caveat states that `plan_kind` is guidance-only for now; the
  roadmap schema remains a future milestone.
- The release-impact prompt now points to `docs/RELEASE_IMPACT.md`.
