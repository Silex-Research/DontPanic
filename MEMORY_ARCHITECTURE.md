# AXIOM Agent Memory Architecture

Multi-agent memory system with cross-domain knowledge sharing, inspired by the
Bell Labs organizational model. Any agent can accumulate knowledge in its domain,
and any other agent can discover that knowledge when the *method* is relevant.

---

## Setup Guide

### Prerequisites

- Firebase project with Firestore enabled
- Node.js 20+ (for Cloud Functions)
- Python 3.10+ with `firebase-admin` and `google-cloud-firestore` packages
- Firebase CLI (`npm install -g firebase-tools`)
- `gcloud` CLI authenticated with your project

### Step 1: Deploy Cloud Functions

```bash
cd functions
npm install
npm run build
firebase deploy --only functions
```

This deploys 6 memory functions:

| Function | Type | Purpose |
|----------|------|---------|
| `memoryWrite` | HTTP | Write single memory item |
| `memoryWriteBatch` | HTTP | Write up to 10 items |
| `memoryRead` | HTTP | Tiered retrieval with prompt injection formatting |
| `memoryNightlyDecay` | Scheduled (3 AM UTC) | Apply score decay, delete expired items |
| `memoryWeeklyRebuild` | Scheduled (Sun 4 AM UTC) | Promote high-value items, sync cross-refs |
| `memoryMaintenanceTrigger` | HTTP | Manual decay/rebuild, overdue detection |

### Step 2: Deploy Firestore Rules

```bash
firebase deploy --only firestore:rules
```

This adds rules for 4 new collections under each tenant:
- `memory_items` — read/write by members
- `memory_working` — read/write by members (rate limit subcollection is Cloud Functions only)
- `memory_sessions` — read/write by members
- `memory_decay_state` — read by members, write by Cloud Functions only

### Step 3: Create Firestore Composite Indexes

The tiered retrieval queries require 3 composite indexes. Create them with:

```bash
# Tier 1: Own-domain retrieval (domains + currentScore)
gcloud firestore indexes composite create \
  --project=YOUR_PROJECT_ID \
  --collection-group=memory_items \
  --field-config field-path=domains,array-config=CONTAINS \
  --field-config field-path=currentScore,order=DESCENDING

# Tier 2: Cross-domain insights (methods + layer + currentScore)
gcloud firestore indexes composite create \
  --project=YOUR_PROJECT_ID \
  --collection-group=memory_items \
  --field-config field-path=methods,array-config=CONTAINS \
  --field-config field-path=layer,order=ASCENDING \
  --field-config field-path=currentScore,order=DESCENDING

# Tier 3: Recent interactions (sourceAgent + layer + createdAt)
gcloud firestore indexes composite create \
  --project=YOUR_PROJECT_ID \
  --collection-group=memory_items \
  --field-config field-path=sourceAgent,order=ASCENDING \
  --field-config field-path=layer,order=ASCENDING \
  --field-config field-path=createdAt,order=DESCENDING
```

Index creation takes 5-10 minutes. Wait for all 3 to complete before testing reads.

### Step 4: Seed Config Registries

Write the domain and method registries to your tenant's Firestore config.
Replace `YOUR_TENANT_ID` with your actual tenant document ID.

```bash
# Using the Firestore REST API (or seed via the Firebase console)
ACCESS_TOKEN=$(gcloud auth print-access-token)
PROJECT="YOUR_PROJECT_ID"
TENANT="YOUR_TENANT_ID"

# Seed memory_domains
curl -X PATCH \
  "https://firestore.googleapis.com/v1/projects/$PROJECT/databases/(default)/documents/tenants/$TENANT/config/memory_domains" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "domains": {
        "mapValue": {
          "fields": {
            "markets-trading": { "mapValue": { "fields": { "label": {"stringValue": "Markets & Trading"} }}},
            "fundamental-research": { "mapValue": { "fields": { "label": {"stringValue": "Fundamental Research"} }}},
            "content-creative": { "mapValue": { "fields": { "label": {"stringValue": "Content & Creative"} }}},
            "portfolio-strategy": { "mapValue": { "fields": { "label": {"stringValue": "Portfolio Strategy"} }}},
            "engineering": { "mapValue": { "fields": { "label": {"stringValue": "Engineering & Infra"} }}},
            "meta-cognition": { "mapValue": { "fields": { "label": {"stringValue": "Meta & Process"} }}}
          }
        }
      }
    }
  }'

# Seed memory_methods
curl -X PATCH \
  "https://firestore.googleapis.com/v1/projects/$PROJECT/databases/(default)/documents/tenants/$TENANT/config/memory_methods" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "methods": {
        "mapValue": {
          "fields": {
            "bayesian-inference": { "mapValue": { "fields": { "label": {"stringValue": "Bayesian Inference"} }}},
            "risk-modeling": { "mapValue": { "fields": { "label": {"stringValue": "Risk Modeling"} }}},
            "pattern-recognition": { "mapValue": { "fields": { "label": {"stringValue": "Pattern Recognition"} }}},
            "first-principles": { "mapValue": { "fields": { "label": {"stringValue": "First Principles"} }}},
            "valuation": { "mapValue": { "fields": { "label": {"stringValue": "Valuation"} }}},
            "narrative-craft": { "mapValue": { "fields": { "label": {"stringValue": "Narrative Craft"} }}},
            "temporal-analysis": { "mapValue": { "fields": { "label": {"stringValue": "Temporal Analysis"} }}}
          }
        }
      }
    }
  }'
```

If config is not seeded, the write gate falls back to hardcoded defaults — but seeding
is required for the system to validate against your custom domains/methods.

### Step 5: Verify the System

**Write a test item:**

```bash
curl -X POST "https://us-central1-YOUR_PROJECT.cloudfunctions.net/memoryWrite" \
  -H "Content-Type: application/json" \
  -d '{
  "tenantId": "YOUR_TENANT_ID",
  "item": {
    "content": "Test memory item — delete after verification",
    "layer": "interaction",
    "domains": ["engineering"],
    "methods": ["first-principles"],
    "category": "fact",
    "sourceAgent": "test-agent",
    "sourceSession": "setup-verification",
    "confidence": 0.5
  }
}'
```

Expected: `{ "action": "created", "id": "...", "baseScore": 0.325 }`

**Write the same item again (dedup test):**

Run the same curl command. Expected: `{ "action": "dedup_bumped", "id": "...", ... }`

**Read it back:**

```bash
curl -X POST "https://us-central1-YOUR_PROJECT.cloudfunctions.net/memoryRead" \
  -H "Content-Type: application/json" \
  -d '{
  "tenantId": "YOUR_TENANT_ID",
  "agentId": "test-agent",
  "primaryDomain": "engineering",
  "taskMethods": ["first-principles"],
  "format": "injection"
}'
```

Expected: Response with `## Active Memory` section containing your test item.

**Check decay status:**

```bash
curl -X POST "https://us-central1-YOUR_PROJECT.cloudfunctions.net/memoryMaintenanceTrigger" \
  -H "Content-Type: application/json" \
  -d '{ "tenantId": "YOUR_TENANT_ID", "action": "check" }'
```

Expected: `{ "status": "up_to_date", ... }` or `{ "status": "ran_first_decay", ... }`

### Step 6: Add Extraction Protocol to Your Agents

Add this block to each agent's SKILL.md (see `skills/trader-agent/SKILL.md` for example):

```
## Memory Extraction Protocol

After completing work, extract 0-5 items worth remembering:

<memory_extract>
content: [concise statement, max 100 words]
layer: [insight|domain|interaction]
domains: [comma-separated domain IDs]
methods: [comma-separated method IDs]
category: [fact|preference|procedure|episode|belief|goal]
confidence: [0.0-1.0]
</memory_extract>
```

### Step 7: Set Up Session Flush

At the end of each agent session, run the flush script to parse extractions and
write them to Firestore:

```bash
# From session output file
python scripts/memory_flush.py \
  --agent trader-agent \
  --tenant YOUR_TENANT_ID \
  --session-file /path/to/session_output.txt

# Or pipe directly
agent_command | python scripts/memory_flush.py \
  --agent trader-agent \
  --tenant YOUR_TENANT_ID

# Or write items directly without parsing
python scripts/memory_flush.py \
  --agent trader-agent \
  --tenant YOUR_TENANT_ID \
  --direct \
  --content "0DTE put credit spreads work best 10-11:30 ET when VIX 14-18" \
  --layer domain \
  --domains markets-trading \
  --methods temporal-analysis,pattern-recognition \
  --category fact \
  --confidence 0.85
```

### Step 8: Edit Behavioral Lessons

Edit `memory/lessons.md` with patterns from user corrections and agent mistakes.
This file is loaded at every agent session start — it's the single highest-ROI
memory piece (zero LLM overhead, immediate behavioral improvement).

---

## How It Works

### Two-Axis Domain Model

Every memory item is tagged with both **domains** (what problem space) and
**methods** (what reasoning technique). This is the cross-pollination mechanism:
when the Trader queries for `pattern-recognition` insights, it discovers the
Investment agent's RSI mean-reversion finding — even though it was stored in a
different domain.

**Axis 1 — Problem Domains** (the "what"):

| ID | Domain | Primary Owner |
|----|--------|--------------|
| `markets-trading` | Markets & Trading | Trader Agent |
| `fundamental-research` | Fundamental Research | Investment Agent |
| `content-creative` | Content & Creative | Creator Agent |
| `portfolio-strategy` | Portfolio Strategy | Coordinator |
| `engineering` | Engineering & Infra | Any |
| `meta-cognition` | Meta & Process | Any |

**Axis 2 — Method Capabilities** (the "how", cross-cutting):

| ID | Method |
|----|--------|
| `bayesian-inference` | Probability updating, prior/posterior reasoning |
| `risk-modeling` | Position sizing, VaR, drawdown, circuit breakers |
| `pattern-recognition` | Technical patterns, trend detection, anomalies |
| `first-principles` | Reductive reasoning from fundamentals |
| `valuation` | DCF, comps, multiples |
| `narrative-craft` | Hooks, storytelling, persuasion structure |
| `temporal-analysis` | Time-series, seasonality, decay curves |

### G-Memory Hierarchy

```
INSIGHT LAYER  (durable, abstract, cross-domain)
  Decay: 0.005/day (~140-day half-life) | TTL: none
      ↕ promotes / informs
DOMAIN LAYER   (medium-term, contextual, domain-specific)
  Decay: 0.015/day (~46-day half-life) | TTL: 180 days
      ↕ generates / informs
INTERACTION LAYER (short-term, tactical, execution-level)
  Decay: 0.05/day (~14-day half-life) | TTL: 30 days
```

### Retrieval Tiers

**Tier 1 — Own domain** (insights + domain layer, primary domain):
- `WHERE domains CONTAINS primary_domain AND currentScore >= 0.3`
- Limit: 10 items

**Tier 2 — Cross-domain insights** (Bell Labs serendipity, method-based):
- `WHERE methods CONTAINS_ANY task_methods AND layer == 'insight' AND currentScore >= 0.5`
- Limit: 5 items

**Tier 3 — Recent interactions** (agent's own tactical memory):
- `WHERE sourceAgent == agent_id AND layer == 'interaction' AND createdAt >= 7_days_ago`
- Limit: 5 items

Re-rank: `currentScore + 0.2*recency_boost + 0.1*log2(accessCount) + 0.15*domain_overlap + 0.1*method_overlap`

### Prompt Injection

`chatProxy.ts` queries the top 15 memory items by `currentScore` and injects them
into the system prompt as an `## Active Memory` section. The `memoryRead` endpoint
formats items with scores, tags, and age for full prompt injection.

### Scoring

Base score at write time:
- Start at 0.5
- +0.3 for insight layer, +0.15 for domain layer
- +0.1 for multi-domain, +0.05 for multi-method
- Scaled by confidence (0.0-1.0)

### Rate Limiting

Each agent is limited to **50 writes per day**. Enforced atomically via a Firestore
transaction counter at `memory_working/{agentId}/rate_limits/{YYYY-MM-DD}`.
Both single and batch endpoints check the limit before writing. Returns HTTP 429
when exceeded.

### Maintenance Schedule

- **Nightly (3 AM UTC)**: Apply layer-specific score decay, delete expired/low-score items, promote eligible domain items to insight layer
- **Weekly (Sunday 4 AM UTC)**: Rebuild cross-references, sync insight summaries
- **Cron fallback**: `memoryMaintenanceTrigger` checks if decay is overdue (>26h) and runs inline

---

## File Map

| File | Purpose |
|------|---------|
| `functions/src/memoryWrite.ts` | Write gate: validate, score, dedup, rate limit, store |
| `functions/src/memoryRead.ts` | Tiered retrieval, scoring, injection formatting |
| `functions/src/memoryMaintenance.ts` | Nightly decay, weekly rebuild, manual trigger |
| `functions/src/chatProxy.ts` | Injects top 15 memory items into system prompt |
| `scripts/memory_retriever.py` | Python retrieval for agent startup |
| `scripts/memory_flush.py` | Session flush: parse `<memory_extract>` blocks, write to Firestore |
| `config/memory-domains.json` | Domain registry (source of truth) |
| `config/memory-methods.json` | Method registry (source of truth) |
| `memory/lessons.md` | Behavioral corrections loaded at session start |
| `memory/insights/{domain}.md` | Per-domain insight summaries (auto-generated by weekly rebuild) |
| `memory/methods/{method}.md` | Per-method knowledge index (auto-generated by weekly rebuild) |
| `memory/agents/{agent}/MEMORY.md` | Per-agent curated memory (auto-generated by weekly rebuild) |
| `firestore.rules` | Security rules for memory collections |
| `MEMORY_ARCHITECTURE.md` | This document |

## Firestore Schema

**`memory_items` document:**

```
{
  content: string,           // max 500 chars
  contentHash: string,       // SHA-256 for dedup
  layer: 'insight'|'domain'|'interaction',
  domains: string[],         // e.g. ["markets-trading"]
  methods: string[],         // e.g. ["bayesian-inference","risk-modeling"]
  category: 'fact'|'preference'|'procedure'|'episode'|'belief'|'goal',
  sourceAgent: string,
  sourceSession: string,
  baseScore: number,         // 0.0-1.0 at creation
  currentScore: number,      // decays over time
  confidence: number,        // 0.0-1.0
  accessCount: number,
  lastAccessed: timestamp|null,
  createdAt: timestamp,
  expiresAt: timestamp|null, // null = no expiry (insights)
  supersededBy: string|null  // conflict resolution
}
```

---

## Adding New Domains or Methods

1. Add entry to `config/memory-domains.json` or `config/memory-methods.json`
2. Seed to Firestore: `tenants/{id}/config/memory_domains` or `memory_methods`
3. Create `memory/insights/{domain}.md` or `memory/methods/{method}.md`
4. Update relevant agent SKILL.md files with the new IDs in their extraction protocol

## Adding a New Agent

1. Create `skills/{agent-name}/SKILL.md` with the memory extraction protocol block
2. Create `memory/agents/{agent-name}/MEMORY.md` and `sessions/` directory
3. Map the agent to its primary domain in `config/memory-domains.json` (`primaryOwner`)
4. List its methods in `config/memory-methods.json` (`usedBy`)
5. Re-seed config to Firestore (Step 4 above)

## Portability

This architecture is stack-agnostic at the concept level:
- Replace Firestore with any document store (Mongo, Postgres JSONB, SQLite)
- Replace Cloud Functions with any serverless platform (Lambda, Vercel, Cloudflare Workers)
- Replace QMD files with any file-based knowledge store
- The two-axis domain model, G-Memory hierarchy, and decay rates are universal

The key constraint: your data store must support `array-contains` and
`array-contains-any` queries (or equivalent) for the domain/method tag filtering.

## Known Limitations

- **No vector search**: Retrieval uses structured tag filtering, not embeddings. Works well at <1K items. If the insight layer grows past ~1K items, consider adding HNSW/FAISS or Pinecone for semantic search.
- **No echo/fizzle tracking**: We don't yet measure which injected memories agents actually reference. This means we can't auto-demote irrelevant items. Planned for Phase 3.
- **No alerting on decay failure**: If the nightly cron fails silently, items accumulate. The 26-hour overdue check mitigates this but doesn't send notifications.
- **Insight layer has no TTL**: Insights live forever. They're rare (only created via promotion after 10+ accesses), but should be monitored.
