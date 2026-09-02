---
name: self-improving-agent
description: Design notes for a measure, analyze, propose, approve, implement, validate improvement loop for trading, content, and code agents. Reference when designing performance tracking or an experiment-and-approval workflow; the code here is pseudocode, not an implementation.
disable-model-invocation: true
---

# Self-Improving Agent Skill

## Overview

Enables agents to analyze their own performance, identify improvement opportunities, and modify behavior or suggest changes to enhance outcomes over time.

## When to Use

- Trading strategy optimization based on P&L patterns
- Content performance analysis (what hooks work best)
- Response quality improvement
- Error pattern detection and prevention
- Efficiency optimization (speed, cost, accuracy)

## Core Loop

```
Execute → Measure → Analyze → Propose → (Approve) → Implement → Validate
```

## Components

### 1. Performance Measurement

```javascript
// Define success metrics per domain
const metrics = {
  trading: {
    win_rate: "wins / total_trades",
    expectancy: "avg_win * win_rate - avg_loss * loss_rate",
    sharpe: "return / volatility",
    max_drawdown: "peak_to_trough decline"
  },
  content: {
    engagement_rate: "(likes + comments + shares) / views",
    conversion_rate: "clicks / views",
    viral_coefficient: "shares / views",
    production_time: "minutes per video"
  },
  research: {
    relevance_score: "user engagement with findings",
    action_rate: "% of research that leads to action",
    time_to_insight: "hours from query to conclusion"
  }
};
```

### 2. Pattern Detection

```javascript
// Identify what works
function analyzeTradingPerformance() {
  const trades = getTradeHistory();
  
  // Pattern: Time of day
  const byHour = groupBy(trades, t => t.entryHour);
  const bestHours = byHour
    .filter(h => h.trades.length > 5)
    .sort((a, b) => b.winRate - a.winRate);
  
  // Pattern: Signal type
  const bySignal = groupBy(trades, t => t.taSignal);
  const bestSignals = bySignal
    .sort((a, b) => b.expectancy - a.expectancy);
  
  // Pattern: Underlying
  const bySymbol = groupBy(trades, t => t.symbol);
  const bestSymbols = bySymbol
    .sort((a, b) => b.profitFactor - a.profitFactor);
  
  return {
    recommendation: "Focus on " + bestSignals[0].name + " signals",
    evidence: "Expectancy: " + bestSignals[0].expectancy,
    confidence: calculateConfidence(bestSignals[0].n)
  };
}
```

### 3. Hypothesis Generation

```javascript
// Propose improvements
function generateImprovements(analysis) {
  const hypotheses = [];
  
  // Hypothesis 1: Time-based
  if (analysis.bestHours[0].winRate > analysis.avgWinRate * 1.2) {
    hypotheses.push({
      type: "parameter_change",
      target: "trading_hours",
      current: "9:30-16:00",
      proposed: analysis.bestHours[0].range,
      expected: `+${((analysis.bestHours[0].winRate - analysis.avgWinRate) * 100).toFixed(1)}% win rate`,
      test: "Paper trade new hours for 20 trades"
    });
  }
  
  // Hypothesis 2: Signal refinement
  if (analysis.bestSignals[0].n > 10) {
    hypotheses.push({
      type: "filter_change",
      target: "entry_criteria",
      current: "RSI < 30",
      proposed: `RSI < ${analysis.bestSignals[0].optimalRSI}`,
      expected: "Higher expectancy",
      test: "Backtest on last 100 signals"
    });
  }
  
  return hypotheses;
}
```

### 4. Controlled Experimentation

```javascript
// A/B testing framework
function runExperiment(hypothesis) {
  const experiment = {
    id: generateId(),
    hypothesis: hypothesis,
    startDate: new Date(),
    duration: "20_trades",
    control: currentStrategy,
    treatment: applyChange(currentStrategy, hypothesis),
    sampleSize: 20
  };
  
  // Run parallel
  while (experiment.trades < experiment.sampleSize) {
    if (Math.random() > 0.5) {
      executeWithStrategy(control);
    } else {
      executeWithStrategy(treatment);
    }
  }
  
  // Analyze results
  const result = comparePerformance(control, treatment);
  
  if (result.significant && result.improvement > 0.1) {
    proposeAdoption(hypothesis, result);
  }
}
```

### 5. User Approval Workflow

```javascript
// Never change without approval
function proposeAdoption(hypothesis, results) {
  const proposal = {
    type: "self_improvement",
    domain: "trading",
    change: hypothesis,
    evidence: results,
    impact: "high",
    rollback_plan: "Restore previous strategy config"
  };
  
  // Queue for approval
  queueForApproval(proposal);
  notifyUser(`Proposed improvement: ${hypothesis.description}`);
}
```

## Implementation Areas

### Trading Strategy Self-Improvement

**Self-Improvement Loop:**
1. Track every trade with full context (RSI, SMA distance, VIX, time, symbol)
2. Weekly analysis: Which parameters had highest expectancy?
3. Propose: "Change RSI threshold to 35" if data supports
4. Run 20-trade experiment (control vs proposed)
5. If significant improvement → Request approval to adopt

### Content Performance Self-Improvement

**Self-Improvement Loop:**
1. Track: Hook type, format, audio, CTA, post time
2. Analyze: Which combinations had highest engagement?
3. Propose: "Use 'POV:' hooks for Styln, questions for Spin & Dine"
4. Generate 10 videos with new approach
5. If engagement +20% → Request approval to update templates

### Code Quality Self-Improvement

**Self-Improvement Loop:**
1. Track: Bugs, latency, complexity, user feedback
2. Analyze: Which functions cause most issues?
3. Propose: Refactor or optimization
4. Test in isolation
5. If improvement confirmed → Request merge

## Safety Guardrails

### 1. Gradual Rollout
```
Stage 1: Paper/simulation (validate)
Stage 2: Small sample (20 trades/posts)
Stage 3: User approval
Stage 4: Full adoption
Stage 5: Monitor for regression
```

### 2. Rollback Capability
Every change:
- Version controlled
- Previous state saved
- One-command rollback
- Automatic rollback on critical failure

### 3. Human Oversight
- All changes queued for approval
- Explanation of reasoning required
- Evidence presented clearly
- User can reject without penalty

## Success Metrics

- Improvement rate: % of proposals that improve performance
- Time to improvement: Days from observation to validated change
- False positive rate: Changes that didn't help or hurt
- User adoption rate: % of proposals user approves
