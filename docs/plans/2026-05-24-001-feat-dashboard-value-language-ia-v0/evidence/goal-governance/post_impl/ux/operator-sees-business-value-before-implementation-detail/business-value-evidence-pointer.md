# Business-value-before-implementation-detail — evidence pointer

Plan: `2026-05-24-001-feat-dashboard-value-language-ia-v0`
Journey: `operator-sees-business-value-before-implementation-detail`

This journey is substantiated by the same dashboard surfaces captured
under the `non-technical-operator-opens-dashboard-and-understands-what-needs-attention`
directory, plus the exact-substrate disclosure proven under
`agent-and-technical-operator-can-still-recover-exact-substrate`. The
journey's acceptance signals map across captured artifacts as follows:

| Acceptance signal | Captured artifact |
|---|---|
| Warning cards include business/user impact phrasing | `../non-technical-operator-opens-dashboard-and-understands-what-needs-attention/dashboard-needs-attention-snapshot.html` (Layer-1 headlines render `Approval needed`, `Setup needed`, `Setup drift`, `Blocked work`, `System warning`) |
| Command chips still show exact commands | Same snapshot, `wn-card-command` blocks render `<pre><code>dontpanic …</code></pre>` per F002 / D006 |
| Source/provenance is visible without dominating the first read | `../non-technical-operator-opens-dashboard-and-understands-what-needs-attention/dashboard-needs-attention-snapshot.html` provenance footer (`buildWhatNowProvenance`) + `../agent-and-technical-operator-can-still-recover-exact-substrate/dashboard-accessibility-checks.md` §3 "Mobile / desktop non-overlap" |
| Four-band status taxonomy is preserved | `dashboard-needs-attention-snapshot.html` (`wn-status-chip--<color>`) plus `dashboard-health-empty-state-snapshot.html` honesty states; copy-map §3 documents the four bands + the optional relevance chip |

The `dashboard-value-language-copy-map.md` (under `../docs/future-dashboard-work-has-a-copy-and-design-contract/`)
is the contract that requires impact phrasing to lead and technical
substrate to follow.
