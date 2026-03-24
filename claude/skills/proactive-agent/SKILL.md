# Proactive Agent Skill

## Overview

Enables agents to act autonomously without explicit user prompts. The agent monitors systems, detects opportunities/threats, and takes initiative within defined boundaries.

## When to Use

- Monitoring trading positions for stop-loss triggers
- Scanning markets for setup opportunities
- Checking competitor activity
- Alerting on system anomalies
- Maintaining heartbeat without user presence

## Core Behaviors

### 1. Sensing
```javascript
// Continuous monitoring patterns
- Market data streams (price, volume, volatility)
- Social media trends (X, TikTok, news)
- System health metrics (API status, data freshness)
- Time-based triggers (market open, earnings dates)
```

### 2. Threshold Detection
```javascript
// Decision triggers
if (vix > 30) => Alert: "Volatility spike detected"
if (position.pnl < -50) => Action: "Stop loss triggered"
if (trending_topic.matches(our_content)) => Action: "Create response content"
```

### 3. Bounded Action
```javascript
// Pre-approved autonomous actions
ALLOWED:
- Send status updates
- Close losing positions (circuit breakers)
- Queue content for approval
- Log research findings

REQUIRES_APPROVAL:
- Open new positions
- Publish content
- Modify strategy parameters
- Spend money
```

## Implementation

### Configuration
```json
{
  "proactive_agent": {
    "enabled": true,
    "check_interval_ms": 15000,
    "domains": ["trading", "content", "research"],
    "autonomy_level": "bounded",
    "alert_channels": ["telegram", "log"],
    "circuit_breakers": {
      "max_daily_actions": 50,
      "cooldown_after_alert_ms": 300000
    }
  }
}
```

### Example: Trading Monitor
```javascript
// Runs every 15 seconds via cron
function proactiveTradingCheck() {
  // Sense
  const positions = getOpenPositions();
  const marketData = fetchLatestPrices();
  
  // Detect
  for (const pos of positions) {
    const currentPrice = marketData[pos.symbol];
    const pnl = calculatePnL(pos, currentPrice);
    
    // Threshold
    if (pnl <= -50) {
      // Bounded action
      closePosition(pos.id, "circuit_breaker");
      alertUser(`Stopped out: ${pos.symbol} at $${pnl} loss`);
    }
  }
}
```

### Example: Content Opportunity Scanner
```javascript
function proactiveContentScan() {
  // Sense trending topics
  const trends = fetchXTrends(["fashion", "AI", "dating"]);
  
  // Match against our apps
  for (const trend of trends) {
    if (matchesStylnBrand(trend)) {
      // Bounded action
      const script = generateScript(trend);
      queueForApproval(script);
      log(`Queued content for trend: ${trend.topic}`);
    }
  }
}
```

## Safety Mechanisms

### 1. Circuit Breakers
- Max actions per hour
- Cooldown periods after significant actions
- Daily/weekly limits

### 2. Escalation Paths
```
Level 1: Log only (informational)
Level 2: Queue for review (minor decisions)
Level 3: Alert user (moderate impact)
Level 4: Require approval (high impact)
Level 5: Emergency stop (critical)
```

### 3. Audit Trail
Every proactive action logged with:
- Timestamp
- Trigger condition
- Decision rationale
- Action taken
- Outcome

## Integration with Current System

### Where to Add
- `AUTOMATED.md` — Define proactive checks
- `HEARTBEAT.md` — Trigger proactive scans
- `BLOCKED.md` — Escalation when blocked

### Current Capabilities
✅ Content bot generates scripts automatically
✅ Bayesian tracker updates after each trade
⏳ Need: Real-time position monitoring
⏳ Need: Trend scanning without user prompt

## Tools Required

- Cron/scheduler for periodic checks
- WebSocket or polling for real-time data
- State management for ongoing monitoring
- Notification system for alerts

## Success Metrics

- Response time to opportunities (< 5 minutes)
- False positive rate (< 20%)
- User approval rate of queued actions (> 70%)
- Incidents requiring rollback (< 1/month)

---

**Status:** Framework defined, implementation queued for trading monitor and content scanner
