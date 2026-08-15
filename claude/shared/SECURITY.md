# Security Policy

## Reporting a Vulnerability

Please do not open a public issue for a security problem in `agent-conventions`.
Report it privately through GitHub's private vulnerability reporting flow for
this repository, or contact the maintainer through the address associated with
the latest signed commit.

Include:

- the affected schema, validator, or generated model;
- the tag or commit SHA where you observed the issue;
- a minimal reproduction;
- whether downstream consumers such as DontPanic are affected.

Good-faith security reports are welcome.

## Supported Versions

`agent-conventions` is consumed by downstream projects through tag-pinned
subtree pulls. Security fixes land on `master` and are released as new tags.

| Version | Supported |
| --- | --- |
| Latest tag | Yes |
| Older tags | No, unless a downstream consumer needs a coordinated migration |

## Scope

In scope:

- schema correctness that can cause downstream validators to accept unsafe or
  malformed artifacts;
- validator behavior in `resolver/` and `schemas/v1.0/validate.py`;
- generated Pydantic mirrors under `schemas/v1.0/models/`;
- supply-chain posture of this repo's release and validation workflow.

Out of scope:

- vulnerabilities in downstream projects that merely consume these schemas;
- disagreements about product semantics without a concrete security impact.
