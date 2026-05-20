.PHONY: showcase

# Regenerate the dogfood showcase artifacts under docs/showcase/.
# Plan 2026-05-19-005 F002. See docs/showcase/README.md for what this
# produces and which sibling checkouts it expects.
showcase:
	python -m dontpanic_orchestrate showcase regen --all
