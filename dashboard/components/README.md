# Redesign component layer (plan 2026-06-06-004)

CSS + markup for the operator-console redesign components (F003+: the ActionItem card/row,
the cockpit, the inspect panel, the gate/dock). **Token-only — no raw hex.** Every colour
comes from `../tokens.css` via `--bucket-* / --freshness-* / --scope-* / --run-* / --dp-*`.
A unit test (`tests/unit/tokens.test.js`) enforces the no-raw-hex rule for this directory.

The legacy page stylesheets (`../core.css`, `../pages/*`) are migrated onto the token layer
in F006 (domain regroup); until then they keep their own palette and render unchanged.
