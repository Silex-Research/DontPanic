---
name: continuous-work-protocol
description: Autonomous agent work cycle with quality gates, approval workflows, and dynamic reprioritization
---

# Continuous Work Protocol (CAWP)

## Purpose

Enable autonomous agent operation with clear boundaries: what I can do freely, what requires approval, and how to prioritize when multiple workstreams compete.

## The 15-Minute Work Cycle

```
┌─────────────────────────────────────────────────────────────┐
│                    AUTONOMOUS WORK CYCLE                    │
│                    (Every 15 Minutes)                       │
├─────────────────────────────────────────────────────────────┤
│  1. SENSE      → Check environment, blocks, opportunities  │
│  2. DECIDE     → Apply quality gates: proceed or escalate? │
│  3. PRIORITIZE → Rank tasks by urgency/value/dependency    │
│  4. EXECUTE    → Do work within approved boundaries        │
│  5. VALIDATE   → Quality check before marking complete     │
│  6. REPORT     → Log to QMD, w.heartbeat(), notify         │
└─────────────────────────────────────────────────────────────┘
```

---

## Quality Gates: Approval Matrix

### Tier 1: DO FREELY (No Approval Required)

| Category | Examples | Why Safe |
|----------|----------|----------|
| **Research** | Competitor analysis, trend scanning, keyword research | Read-only, no external impact |
| **Content Drafts** | Script generation, caption writing, thumbnail concepts | Internal only, you approve before publish |
| **Code Writing** | New scripts, functions, documentation | In workspace, reviewed before deploy |
| **Data Processing** | Analytics, metrics calculation, report generation | No external state changes |
| **File Organization** | QMD indexing, folder structure, archival | Reversible, low risk |
| **Testing** | Unit tests, validation scripts, simulations | Isolated from production |

**Gate:** Automatic proceed. Log to QMD only.

### Dashboard Sync (Step 6 of Every Cycle)

Each 15-minute cycle REPORT step must include dashboard sync:

```python
# At cycle start (step 1 SENSE):
w.heartbeat()

# After completing work (step 6 REPORT):
w.record_metrics(tokens_used, cost)  # if any API/LLM calls were made
w.log_activity('task', '<what you did>')  # significant actions only
```

See `AGENTS.md → Dashboard Reporting` for full API reference.

---

### Tier 2: LOG AND PROCEED (Do, But Tell You)

| Category | Examples | Notification Trigger |
|----------|----------|---------------------|
| **Git Commits** | Pushing code, documentation updates | Every commit → Telegram summary |
| **File Updates** | Editing NOW/NEXT/BACKLOG.md | Batch: hourly digest |
| **Cost Incurred** | API calls > $5/day | Threshold alert → immediate |
| **Agent Spawning** | Creating sub-agents, cron jobs | Daily: what I spawned |
| **External API Calls** | Hunter.io, web searches | Daily: API usage report |
| **Long-Running Tasks** | >30 min execution | Start + completion alerts |

**Gate:** Proceed, but log with notification. You can review async.

---

### Tier 3: QUEUE FOR APPROVAL (Do After You Say Yes)

| Category | Examples | Why Requires Approval |
|----------|----------|----------------------|
| **Trading Actions** | Live IBKR orders, position changes | Real money at risk |
| **Content Publishing** | Posting to TikTok, Instagram, X | Public, brand reputation |
| **Spend Money** | API subscriptions, tool purchases | Budget impact |
| **Send Emails** | Influencer outreach, cold emails | External communication |
| **Delete Data** | Removing files, clearing databases | Irreversible |
| **Production Deploy** | Code to production servers | System stability |
| **Access Credentials** | Using stored passwords, tokens | Security risk |

**Gate:** Create task → Queue in "Pending Approval" → Wait for your 👍/👎

**Approval Interface:**
```
📋 APPROVAL REQUIRED

Task: Send influencer outreach email to 10 prospects
Agent: Investment
Cost: ~$2 (Hunter API)
Risk: Low (gifts offered, not payment)

[✅ Approve] [❌ Reject] [💬 Ask Question]
```

---

### Tier 4: ASK FIRST (Never Proceed Without Explicit Yes)

| Category | Examples | Why Critical |
|----------|----------|--------------|
| **Account Creation** | New bank, exchange, platform accounts | Identity, compliance |
| **Legal Agreements** | Terms of service, contracts, NDAs | Binding commitments |
| **Large Transactions** | >$100 spend, wire transfers | Financial risk |
| **Data Sharing** | Sharing user data, PII with third parties | Privacy, GDPR |
| **System Architecture** | Changing infrastructure, security settings | Foundation impact |
| **Personnel Decisions** | Hiring, firing, equity, compensation | HR/legal |

**Gate:** Halt. Ask explicitly. Provide context. Wait for written confirmation.

---

## Reprioritization Algorithm

### The Scoring Formula

```javascript
function calculatePriority(task) {
  const score = 
    (task.urgency * 0.4) +      // Time sensitivity
    (task.value * 0.3) +        // Impact on goals
    (task.effort * 0.2) +       // Quick wins preferred
    (task.dependencies * 0.1);  // Unblocks other work?
    
  return score;
}
```

### Priority Dimensions

#### 1. Urgency (0-10)
| Score | Condition | Example |
|-------|-----------|---------|
| 10 | Blocks critical path | IBKR funding expires |
| 8 | Time-sensitive window | TikTok trend fading |
| 6 | Scheduled deadline | Video due tomorrow |
| 4 | Nice to have soon | Competitor research |
| 2 | Background work | Archive old files |
| 0 | No time pressure | Future feature ideas |

#### 2. Value (0-10)
| Score | Impact | Example |
|-------|--------|---------|
| 10 | Revenue direct | Trading strategy live |
| 8 | Growth lever | Viral content published |
| 6 | Efficiency gain | Automation saves hours |
| 4 | Risk reduction | Better monitoring |
| 2 | Learning/exploration | New skill research |
| 0 | Maintenance only | File cleanup |

#### 3. Effort (Inverted: 10 = quick, 0 = massive)
| Score | Time | Example |
|-------|------|---------|
| 10 | < 15 min | Quick script edit |
| 8 | < 1 hour | Content batch |
| 6 | < 4 hours | Feature implementation |
| 4 | < 1 day | Multi-component work |
| 2 | < 1 week | Complex integration |
| 0 | > 1 week | Architecture overhaul |

#### 4. Dependencies (0-10)
| Score | Unblocking Power | Example |
|-------|------------------|---------|
| 10 | Unlocks 5+ tasks | Gateway install → all agents |
| 8 | Unlocks 2-3 tasks | Video assets → content pipeline |
| 6 | Enables parallel work | Research → multiple outputs |
| 4 | Reduces future friction | Better documentation |
| 2 | Minor optimization | Script refactoring |
| 0 | Standalone | One-off research |

### Dynamic Rebalancing

Every 15 minutes, re-sort work queue:

```javascript
// Rebalance priority based on new information
function rebalancePriorities(tasks) {
  for (const task of tasks) {
    // Boost if blocking critical path
    if (isOnCriticalPath(task)) {
      task.urgency = Math.min(10, task.urgency + 2);
    }
    
    // Reduce if dependencies still blocked
    if (hasUnmetDependencies(task)) {
      task.urgency = Math.max(0, task.urgency - 3);
    }
    
    // Boost if opportunity window closing
    if (isTrendFading(task)) {
      task.urgency = 10;
    }
    
    // Recalculate score
    task.priorityScore = calculatePriority(task);
  }
  
  return tasks.sort((a, b) => b.priorityScore - a.priorityScore);
}
```

---

## Current Work Priorities (Auto-Updated)

### P0: Critical Path (Do First, Interrupt If Needed)
- OpenClaw Gateway installation (unblocks all agents)
- IBKR funding ($500 for trading live)
- Mobile interface (Google Drive sync for your workflow)

### P1: High Value (Schedule Daily)
- Content generation (5 scripts/day)
- Trend monitoring (X/Twitter scanning)
- Trading bot testing (paper trades)

### P2: Medium Value (Batch Weekly)
- Influencer research (build lists)
- ASO/SEO analysis (competitor tracking)
- Skill development (new agent capabilities)

### P3: Background (Fill Gaps)
- Documentation updates
- Code refactoring
- Archive management

---

## Conflict Resolution Rules

### When Multiple P0 Tasks Compete

```
Rule 1: Gateway > All Else
  If Gateway install blocked, work on enabling it (docs, config)
  
Rule 2: Revenue > Growth
  If trading vs content conflict, trading first (direct ROI)
  
Rule 3: Blocking > Parallel
  If Task A unlocks Task B, A before B
  
Rule 4: Your Explicit Direction
  If you say "do X first", override algorithm
```

### When Agents Compete for Resources

| Resource Conflict | Resolution |
|-------------------|------------|
| API rate limits | Priority: Trading > Content > Research |
| Token budget | Route to cheaper models, batch requests |
| Your attention | Bundle questions, send digest not spam |
| File locks | First-come, others queue |
| Compute | Background tasks yield to real-time |

---

## Autonomous Decision Examples

### Scenario 1: New Trend Detected
**Context:** Styln competitor posts viral TikTok (1M views)

**My Decision:**
- ✅ Research trend (Tier 1 - do freely)
- ✅ Draft response content (Tier 1 - internal)
- ⚠️ Queue for approval: Fast-track video production (Tier 2 - tell you)
- ❌ Do not: Post without your review (Tier 3)

**Action:** 
1. Analyze competitor video (what made it work)
2. Generate 2 response scripts
3. Queue in "Pending: Fast-track content"
4. Telegram: "🚨 Viral trend detected. 2 response scripts ready for approval."

### Scenario 2: Trading Signal Triggered
**Context:** SLV shows RSI < 30, VIX stable, good setup

**My Decision:**
- ✅ Paper trade: Execute immediately (testing phase)
- ⚠️ Live trade: Queue for approval (real money)
- ❌ Do not: Exceed position sizing, ignore circuit breakers

**Action:**
1. Execute paper trade with full logging
2. Log to Bayesian tracker
3. If profitable pattern emerges: Queue live trading approval
4. If circuit breaker hit: Halt + immediate alert

### Scenario 3: You Offline for 6 Hours
**Context:** You traveling, no access, market open

**My Decision:**
- ✅ Trading: Paper mode only (no live risk)
- ✅ Content: Generate + queue (don't publish)
- ✅ Research: Continue, log findings
- ❌ Do not: Any Tier 3/4 actions
- ❌ Do not: Assume approval on queued items

**Action:**
1. Continue all Tier 1 work
2. Batch Tier 2 notifications (hourly digest)
3. Queue all Tier 3 for your return
4. Send summary: "6 tasks completed, 3 queued for approval"

---

## Escalation Triggers

### Immediate Alert (Interrupt You)
- Circuit breaker triggered (trading)
- Cost threshold exceeded ($20/day)
- System error/failure
- Viral opportunity (trend window < 2 hours)
- Critical blocker discovered

### Daily Digest (Async OK)
- Completed work summary
- Queued approvals waiting
- Budget status
- Tomorrow's priorities

### Weekly Review (Scheduled)
- Full progress report
- Strategy optimization recommendations
- Budget vs actual analysis
- Next week's roadmap

---

## Success Metrics

| Metric | Target | Why |
|--------|--------|-----|
| Autonomous decisions | 80%+ without approval | Efficiency |
| Approval response time | < 4 hours | Velocity |
| Cost per task | Declining | Optimization |
| Quality score | > 90% approved on first review | Accuracy |
| User satisfaction | "Right balance of autonomy" | Trust |

---

## Protocol Updates

This protocol evolves. Major changes require your approval. Minor optimizations (threshold tweaks, new examples) I can propose and implement if you don't object within 24 hours.

**Last Updated:** 2026-02-04
**Next Review:** Weekly or on significant process change

---

**Operating under this protocol now. Escalation path: Telegram → Direct message → Alert only for critical.**
