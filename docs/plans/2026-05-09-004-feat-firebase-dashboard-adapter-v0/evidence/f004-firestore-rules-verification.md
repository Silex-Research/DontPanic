# F004 Firestore Rules Verification

Plan: `2026-05-09-004-feat-firebase-dashboard-adapter-v0`
Feature: `F004`
Verified at: `2026-05-21T20:15:54Z`

## Local checks

Command:

```sh
npm --prefix dashboard test -- tests/unit/firestore-rules.test.js
```

Result: `3 passed`

Command:

```sh
npm --prefix dashboard test
```

Result: `21 passed / 412 tests passed`

Command:

```sh
npm --prefix dashboard/functions run lint
```

Result: passed

## Live deploy

Command:

```sh
firebase deploy --project <firebase-project-id> --only firestore:rules
```

Result:

```text
=== Deploying to '<firebase-project-id>'...
cloud.firestore: rules file firestore.rules compiled successfully
firestore: released rules firestore.rules to cloud.firestore
Deploy complete
```

## Boundary

`firestore.rules` now allows authenticated browser reads with `request.auth != null` and denies all client-side writes with `allow write: if false`.

Writes remain server-side through Admin SDK paths: the sync daemon and Cloud Functions. F003 Cloud Functions and the full end-to-end MCP smoke remain incomplete.
