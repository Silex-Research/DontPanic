"""Shared secret-shape regexes used by DontPanic sanitization surfaces."""

from __future__ import annotations

import re

# ── Secret-shape regexes ───────────────────────────────────────────────────
# Distinct from PATTERNS: those guard repo-specific identifiers (literal
# strings); these flag canonical secret shapes from major vendors. Each
# regex carries a `# source:` citation — gitleaks default rules,
# vendor docs, or a tracked issue — so future review can verify the shape
# is current and the false-positive surface is understood.
#
# Anchors are deliberately loose (no \b boundaries) so embedded matches
# inside larger strings still flag — secrets in URLs / JSON / env exports
# don't always sit on word boundaries.

# AWS access key ID. Long-form prefix `AKIA` + 16 base32-uppercase chars.
# Lookaheads reject low-entropy placeholder bodies (e.g. `AKIA0000000000000000`,
# `AKIAAAAAAAAAAAAAAAAA`) by requiring at least one letter AND one digit —
# real AWS keys always mix both, while doc-style placeholders typically don't.
# source: https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml (rule: aws-access-token)
_AWS_ACCESS_KEY_RE = re.compile(r"AKIA(?=[0-9A-Z]*[A-Z])(?=[0-9A-Z]*[0-9])[0-9A-Z]{16}")

# GitHub personal access token (classic). `ghp_` prefix + 36 base62 chars.
# source: https://github.blog/changelog/2021-03-31-authentication-token-format-updates-are-generally-available/
_GH_PAT_RE = re.compile(r"ghp_[A-Za-z0-9]{36}")

# GitHub fine-grained tokens — OAuth (`gho_`), server-to-server (`ghs_`),
# user-to-server (`ghu_`), refresh (`ghr_`). Same 36-char body shape.
# source: https://github.blog/changelog/2021-03-31-authentication-token-format-updates-are-generally-available/
_GH_FINE_GRAINED_RE = re.compile(r"gh[osur]_[A-Za-z0-9]{36}")

# Anthropic API key. `sk-ant-api03-` prefix + 93 url-safe-base64 chars + `AA`.
# source: https://docs.anthropic.com/en/api/getting-started (key format)
_ANTHROPIC_API_KEY_RE = re.compile(r"sk-ant-api03-[A-Za-z0-9_\-]{93}AA")

# OpenAI API key (legacy/standard). Body contains `T3BlbkFJ` infix
# (base64 of "OpenAI"). The 20+/20+ bracket is intentional: OpenAI has
# rotated the surrounding length over time, so we anchor on the infix.
# source: https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml (rule: openai-api-key)
_OPENAI_API_KEY_RE = re.compile(r"sk-[A-Za-z0-9]{20,}T3BlbkFJ[A-Za-z0-9]{20,}")

# Slack tokens. `xox` + role-suffix + body. Covers bot/user/app/refresh/legacy.
# source: https://api.slack.com/authentication/token-types
_SLACK_TOKEN_RE = re.compile(r"xox[baprs]-[0-9a-zA-Z\-]{10,}")

# PEM private-key block opener. Catches RSA / EC / OPENSSH / generic.
# Assembled from parts so this file does not match its own check.
# source: https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml (rule: private-key)
_PEM_PRIVATE_KEY_RE = re.compile(
    "-----" + "BEGIN" + r" (?:RSA |EC |OPENSSH )?" + "PRIVATE KEY" + "-----"
)

# Generic JWT — three base64url segments separated by dots, leading
# `eyJ` (base64 of `{"`) anchors on the JOSE header to keep the false-
# positive surface narrow vs. any 3-segment dotted string.
# source: https://datatracker.ietf.org/doc/html/rfc7519 (JWT spec)
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")

# Discord webhook URL. Both discord.com and discordapp.com hostnames are
# canonical; ID is 17-20 digits, token is base64url-style 60+ chars.
# source: https://discord.com/developers/docs/resources/webhook (webhook URL format)
# Added to ensure live webhooks can never be committed alongside the new
# Discord notification sink.
_DISCORD_WEBHOOK_RE = re.compile(
    r"https?://discord(?:app)?\.com/api/webhooks/\d{17,20}/[A-Za-z0-9_\-]{60,}"
)

# Nostr secret key (bech32 nsec). Must never reach a notify relay body.
# Bech32 alphabet is lowercase only (qpzry9x8gf…);
# allow mixed case for accidental paste variants.
# source: https://github.com/nostr-protocol/nips/blob/master/19.md (bech32 entities)
_NOSTR_NSEC_RE = re.compile(r"nsec1[02-9ac-hj-np-z]{58,}", re.IGNORECASE)

SECRET_REGEXES: tuple[re.Pattern[str], ...] = (
    _AWS_ACCESS_KEY_RE,
    _GH_PAT_RE,
    _GH_FINE_GRAINED_RE,
    _ANTHROPIC_API_KEY_RE,
    _OPENAI_API_KEY_RE,
    _SLACK_TOKEN_RE,
    _PEM_PRIVATE_KEY_RE,
    _JWT_RE,
    _DISCORD_WEBHOOK_RE,
    _NOSTR_NSEC_RE,
)
