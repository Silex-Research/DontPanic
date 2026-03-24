---
name: token-budget-tracker
description: Track AI model usage, token costs, and optimize spend across agents
---

# Token Budget Tracker

## Overview

Monitor AI model usage, costs, and optimize agent budget allocation. Provides visibility into real spend per agent, per task, and per day.

## Why Track Tokens

| Problem | Impact | Solution |
|---------|--------|----------|
| Blind spend | Budget overrun | Real-time cost visibility |
| Inefficient routing | Paying GPT-4 for simple tasks | Model router optimized per task |
| No accountability | Can't attribute costs to outcomes | Per-agent cost tracking |

## Current Model Costs (as of Feb 2024)

| Model | Provider | Input | Output | Use Case |
|-------|----------|-------|--------|----------|
| **Kimi K2.5** | OpenRouter | $3/M tokens | $3/M tokens | Most tasks, default |
| **Claude Sonnet 4.5** | Anthropic | $15/M tokens | $75/M tokens | Complex reasoning, content |
| **Claude Opus 4.5** | Anthropic | $75/M tokens | $150/M tokens | Deep research only |
| **GPT-4 Turbo** | OpenAI | $30/M tokens | $60/M tokens | Fallback, legacy |
| **Grok 3** | xAI | $10/M tokens | $20/M tokens | X/Twitter research |

## Budget Allocation (Monthly)

```yaml
total_budget: $500/month

allocation:
  axioms_main:    $150  # 30% - Coordinator, main interface
  trader:         $100  # 20% - Trading decisions (fast, frequent)
  creator:        $120  # 24% - Content generation (creative)
  investment:     $80   # 16% - Research (thorough, deep)
  mission_control:  $50  # 10% - Overhead, tracking

cost_optimization:
  # Use cheaper models for routine tasks
  heartbeats:        Kimi K2.5    # $3/M tokens
  content_scripts:   Kimi K2.5    # $3/M tokens  
  trading_signals:   Kimi K2.5    # $3/M tokens
  
  # Use expensive models only when justified
  investment_research: Claude Opus  # $75/M tokens (but 10x/month max)
  content_polish:    Sonnet        # $15/M tokens (when high quality needed)
  ```

## Cost Tracking Schema

```javascript
// /tracking/token-usage.json
{
  "monthly_budget": 500,
  "spent_this_month": 0,
  "projected_spend": 0,
  "by_agent": {
    "axiom": {
      "budget": 150,
      "spent": 0,
      "token_count": 0,
      "primary_model": "kimi-k2.5"
    },
    "trader": {
      "budget": 100,
      "spent": 0,
      "token_count": 0,
      "primary_model": "kimi-k2.5"
    },
    "creator": {
      "budget": 120,
      "spent": 0,
      "token_count": 0,
      "primary_model": "claude-sonnet-4-5"
    },
    "investment": {
      "budget": 80,
      "spent": 0,
      "token_count": 0,
      "primary_model": "claude-opus-4-5"
    }
  },
  "by_day": [
    {
      "date": "2026-02-04",
      "total_tokens": 0,
      "total_cost": 0,
      "breakdown": {
        "axiom": 0,
        "trader": 0,
        "creator": 0,
        "investment": 0
      }
    }
  ],
  "by_task": [
    {
      "task_id": "task-123",
      "agent": "creator",
      "model": "claude-sonnet-4-5",
      "input_tokens": 500,
      "output_tokens": 800,
      "cost": 0.015,  // $0.015
      "duration_ms": 3400
    }
  ],
  "alerts": {
    "daily_threshold": 20,    // Alert if daily > $20
    "agent_threshold": 10,  // Alert if agent > $10/day
    "projected_overrun": 1.2 // Alert if projecting 20%+ over budget
  }
}
```

## Real-Time Cost Tracking

```javascript
// Track every API call
class TokenTracker {
  constructor() {
    this.PRICING = {
      'kimi-k2.5': { input: 3, output: 3 },        // $3/M tokens
      'claude-sonnet-4-5': { input: 15, output: 75 }, // $15/$75 per M
      'claude-opus-4-5': { input: 75, output: 150 },  // $75/$150 per M
      'grok-3': { input: 10, output: 20 }
    };
  }

  trackCall({ agent, model, task, inputTokens, outputTokens, duration }) {
    const pricing = this.PRICING[model];
    if (!pricing) {
      console.warn(`Unknown model pricing: ${model}`);
      return;
    }

    // Calculate cost
    const inputCost = (inputTokens / 1_000_000) * pricing.input;
    const outputCost = (outputTokens / 1_000_000) * pricing.output;
    const totalCost = inputCost + outputCost;

    const record = {
      timestamp: new Date().toISOString(),
      agent,
      model,
      task: task.substring(0, 50), // Truncate
      inputTokens,
      outputTokens,
      cost: totalCost,
      duration
    };

    // Log immediately
    this.logCall(record);
    
    // Check thresholds
    this.checkThresholds(agent, totalCost);
    
    return record;
  }

  checkThresholds(agent, cost) {
    const data = this.loadData();
    const daily = this.getTodaySpending(data);
    const agentDaily = this.getAgentTodaySpending(data, agent);

    if (daily + cost > 20) {
      this.alert(`⚠️ Daily spend approaching $20: ${(daily + cost).toFixed(2)}`);
    }
    
    if (agentDaily + cost > 10) {
      this.alert(`⚠️ ${agent} agent spend approaching $10 today: ${(agentDaily + cost).toFixed(2)}`);
    }
  }

  getDailyReport() {
    const data = this.loadData();
    const today = new Date().toISOString().split('T')[0];
    const todayCalls = data.by_task.filter(t => t.timestamp?.startsWith(today));
    
    const totalCost = todayCalls.reduce((sum, t) => sum + t.cost, 0);
    const byAgent = {};
    
    todayCalls.forEach(t => {
      byAgent[t.agent] = (byAgent[t.agent] || 0) + t.cost;
    });

    return {
      date: today,
      totalCalls: todayCalls.length,
      totalCost: totalCost.toFixed(4),
      byAgent: Object.entries(byAgent).map(([agent, cost]) => ({
        agent,
        cost: cost.toFixed(4),
        pctOfDaily: ((cost / totalCost) * 100).toFixed(1)
      })),
      remainingBudget: (500 / 30 - totalCost).toFixed(4)
    };
  }

  alert(message) {
    // Send via Telegram
    console.log(`[ALERT] ${message}`);
    // TODO: Send to user
  }
}
```

## Cost Optimization Rules

### 1. Model Router
```javascript
// Automatically select cheapest capable model
function routeToModel(task, agent) {
  const complexity = estimateComplexity(task);
  
  if (complexity === 'simple') {
    // Heartbeats, status checks, simple summaries
    return 'kimi-k2.5';
  }
  
  if (complexity === 'standard') {
    // Content scripts, trading signals, most work
    return 'kimi-k2.5';
  }
  
  if (complexity === 'creative') {
    // Final content polish, brand voice
    return 'claude-sonnet-4-5';
  }
  
  if (complexity === 'research') {
    // Deep analysis, investment research
    return 'claude-opus-4-5';
  }
  
  return 'kimi-k2.5';  // Default
}
```

### 2. Batching
```javascript
// Batch small tasks to reduce overhead
const batch = {
  maxSize: 5,
  maxWait: 30000, // 30 seconds
  
  add(task) {
    this.queue.push(task);
    if (this.queue.length >= this.maxSize) {
      this.flush();
    }
  }
};
```

### 3. Caching
```javascript
// Cache responses to avoid repeat calls
const cache = {
  ttl: 3600000, // 1 hour
  
  get(key) {
    const item = this.store.get(key);
    if (!item) return null;
    if (Date.now() - item.time > this.ttl) {
      this.store.delete(key);
      return null;
    }
    return item.data;
  }
};
```

## Daily Budget Dashboard

```
📊 TOKEN BUDGET — Feb 4, 2026

💰 MONTHLY BUDGET: $500.00
   Spent: $47.23 (9.4%)
   Projected: $520.50 (104% ⚠️)

📅 TODAY (Feb 4)
   Spent: $12.45
   Remaining: $4.22 (of $16.67 daily)
   
┌────────────────────────────────────┐
│ BY AGENT                          │
├────────────────────────────────────┤
│ Axiom        $3.20  ████ (25%)    │
│ Trader       $2.15  ███  (17%)    │
│ Creator      $5.80  ████████ (47%)│
│ Investment   $1.30 ██  (10%)    │
└────────────────────────────────────┘

⚠️ ALERTS
• Creator agent over daily threshold ($5.80 > $5.00)
• Monthly projection 4% over budget

💡 OPTIMIZATION SUGGESTIONS
• Switch Creator from Sonnet to Kimi for scripts ($2.80 saved)
• Batch Trader heartbeats (reduce calls by 60%)
• Cache Investment research queries

🔧 ACTIVE SAVINGS MODES
• [x] Use Kimi for standard tasks
• [x] Batch rapid heartbeats  
• [ ] Defer creative tasks to off-peak

[View Details] [Adjust Budget] [Export Report]
```

## Integration Points

```javascript
// In every agent heartbeat
tracker.trackCall({
  agent: 'trader',
  model: 'kimi-k2.5',
  task: 'Check VIX + scan for signals',
  inputTokens: 120,
  outputTokens: 85,
  duration: 1200
});

// In daily standup generator
const report = tracker.getDailyReport();
standup += `\n📊 Token spend today: $${report.totalCost}`;
```

## Weekly Review Process

1. **Export**: Generate CSV of all calls
2. **Analyze**: Which tasks cost most? Which agents?
3. **Optimize**: Switch expensive models, batch tasks
4. **Adjust**: Reallocate budgets if needed
5. **Report**: To user with recommendations

## Hard Limits

```javascript
// Circuit breakers
if (dailySpend > 100) {
  haltNonCriticalAgents();
  alertUser("Daily token limit hit. Pausing non-essential work.");
}

if (monthlySpend > 550) {
  haltCreativeAgents();
  alertUser("Monthly budget nearly exhausted. Emergency mode.");
}
```

---

## Next Steps

1. **Implement tracker** in all agent calls
2. **Set up daily reports** (Telegram @ 6 PM)
3. **Create optimization rules** (model router)
4. **Build dashboard** (web or Telegram)

**Priority: High — budget visibility critical for sustainable operations.**
