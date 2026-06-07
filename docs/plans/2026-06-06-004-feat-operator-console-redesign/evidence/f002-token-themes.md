# F002 — token resolution (dark default + light), generated from tokens.css

| token | dark (`:root`) | light (`[data-theme=light]`) |
|---|---|---|
| `--bucket-needs-auth` | `#F87171` | `#DC2626` |
| `--bucket-needs-decision` | `#FBBF24` | `#D97706` |
| `--bucket-agent-runnable` | `#60A5FA` | `#2563EB` |
| `--bucket-auto-safe` | `#4ADE80` | `#16A34A` |
| `--bucket-uncertain` | `#A78BFA` | `#7C3AED` |
| `--bucket-quiet` | `#94A3B8` | `#64748B` |
| `--freshness-fresh` | `#4ADE80` | `#16A34A` |
| `--freshness-aging` | `#FBBF24` | `#D97706` |
| `--freshness-stale` | `#F87171` | `#DC2626` |
| `--freshness-unproven` | `#64748B` | `#94A3B8` |
| `--scope-fleet` | `#818CF8` | `#4F46E5` |
| `--scope-project` | `#2DD4BF` | `#0D9488` |
| `--scope-global` | `#94A3B8` | `#475569` |
| `--dp-bg` | `#0B0F17` | `#FBFCFD` |
| `--dp-surface-1` | `#121826` | `#FFFFFF` |
| `--dp-surface-2` | `#1A2233` | `#F1F5F9` |
| `--dp-border` | `#283142` | `#E2E8F0` |
| `--dp-text-1` | `#E8EDF4` | `#0F172A` |
| `--dp-text-2` | `#9FB0C3` | `#475569` |
| `--dp-text-3` | `#64748B` | `#94A3B8` |

**Density (comfort default → dense override):**

| token | comfort | dense |
|---|---|---|
| `--dp-card-pad` | `16px` | `8px` |
| `--dp-row-py` | `12px` | `6px` |
| `--dp-stack-gap` | `12px` | `4px` |
| `--dp-group-gap` | `24px` | `12px` |
| `--dp-radius` | `10px` | `6px` |

Fonts: sans=`'Inter'`, mono=`'JetBrains Mono'` (mono = signifier, not default reading face).

Verified by `dashboard/tests/unit/tokens.test.js` (38 assertions): vocabulary completeness, dual-theme coverage, density override, palette-only-in-tokens.css, and the data-theme/data-density controller.
