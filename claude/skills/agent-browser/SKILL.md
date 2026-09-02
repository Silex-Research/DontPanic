---
name: agent-browser
description: Design proposal for agent-oriented browser automation (structured extraction, multi-step workflows, error recovery, persistent sessions). Reference when designing such a pipeline; the `agentBrowser.*` API shown here is not implemented and cannot be imported.
disable-model-invocation: true
applies_to:
  surfaces: [web, ux]
  goal_types: [new_feature, parity]
---

# Agent Browser Skill

## Overview

Specialized browser automation designed specifically for agent workflows. Unlike general browser use, this skill optimizes for:
- Structured data extraction
- Multi-step workflows
- Error recovery
- State persistence across sessions
- Integration with agent memory systems

## Key Differentiator: Browser Use vs. Agent Browser

| Feature | Browser Use | Agent Browser |
|---------|-------------|---------------|
| **Primary use** | One-off tasks | Recurring workflows |
| **State** | Ephemeral | Persistent across sessions |
| **Error handling** | Basic retry | Sophisticated recovery |
| **Data extraction** | Raw scraping | Structured to QMD |
| **Integration** | Manual | Automatic agent memory |

## Core Capabilities

### 1. Persistent Sessions
```javascript
// Save browser state (cookies, localStorage)
await agentBrowser.saveSession('instagram-auth', {
  cookies: await page.cookies(),
  localStorage: await page.evaluate(() => localStorage),
  timestamp: Date.now()
});

// Resume later
await agentBrowser.loadSession('instagram-auth');
```

### 2. Structured Data Pipeline
```javascript
// Extract → Transform → Load to QMD
const workflow = {
  source: 'https://apps.apple.com/charts',
  extract: async (page) => {
    return await page.evaluate(() => {
      return Array.from(document.querySelectorAll('.app')).map(app => ({
        name: app.querySelector('.name').textContent,
        rank: app.querySelector('.rank').textContent,
        category: app.querySelector('.category').textContent
      }));
    });
  },
  transform: (data) => {
    return data.map(d => ({
      ...d,
      scrapedAt: new Date().toISOString(),
      source: 'app_store'
    }));
  },
  load: async (data) => {
    await indexToQMD('app-store-rankings', data);
  }
};

await agentBrowser.runWorkflow(workflow);
```

### 3. Workflow Templates

#### Template A: Content Discovery Pipeline
```javascript
const contentDiscovery = {
  name: 'viral-content-scanner',
  schedule: 'every_4_hours',
  steps: [
    {
      name: 'scan-tiktok',
      url: 'https://tiktok.com/discover',
      action: async (page) => {
        const videos = await page.queryAll('[data-e2e="card-video"]');
        return videos.map(v => ({
          views: await v.text('[data-e2e="video-views"]'),
          topic: await v.text('[data-e2e="video-desc"]')
        }));
      }
    },
    {
      name: 'filter-by-views',
      filter: (items) => items.filter(i => parseViews(i.views) > 1000000)
    },
    {
      name: 'match-to-apps',
      match: (items) => items.filter(i => 
        matchesStyln(i.topic) || matchesSpinDine(i.topic)
      )
    },
    {
      name: 'queue-for-content',
      action: async (matched) => {
        for (const item of matched) {
          await contentBot.generateFromTrend(item);
        }
      }
    }
  ]
};
```

#### Template B: Lead Generation Pipeline
```javascript
const influencerLeadGen = {
  name: 'micro-influencer-finder',
  schedule: 'daily',
  steps: [
    {
      name: 'search-hashtag',
      url: 'https://instagram.com/explore/tags/fashionblogger',
      extract: 'posts'
    },
    {
      name: 'profile-deep-dive',
      forEach: 'posts',
      action: async (post) => {
        const profile = await navigate(post.authorUrl);
        return {
          username: await profile.text('h1'),
          followers: await profile.text('[role="button"] span'),
          engagement: calculateEngagement(profile)
        };
      }
    },
    {
      name: 'qualify-leads',
      filter: (profiles) => profiles.filter(p => 
        p.followers > 10000 && 
        p.followers < 100000 &&
        p.engagement > 0.03
      )
    },
    {
      name: 'save-to-crm',
      action: async (qualified) => {
        await saveToQMD('influencer-leads', qualified);
      }
    }
  ]
};
```

### 4. Error Recovery

```javascript
// Sophisticated error handling
const robustWorkflow = {
  steps: [...],
  
  onError: async (error, context, retryCount) => {
    // Log error
    logError({ error, context, retryCount });
    
    // Recovery strategies
    if (error.type === 'timeout') {
      // Strategy 1: Wait and retry
      await sleep(5000);
      return 'retry';
    }
    
    if (error.type === 'selector_not_found') {
      // Strategy 2: Page structure changed
      await alertUser(`Selector failed: ${error.selector}. Update needed.`);
      return 'abort';
    }
    
    if (error.type === 'rate_limited') {
      // Strategy 3: Backoff
      const backoff = Math.pow(2, retryCount) * 60000;
      await scheduleRetry(context, backoff);
      return 'reschedule';
    }
    
    // Default: Abort with notification
    await alertUser(`Workflow failed: ${error.message}`);
    return 'abort';
  }
};
```

## Use Cases for Silex Holdings

### 1. Daily ASO Monitoring
```javascript
// Check App Store rankings daily
agentBrowser.schedule({
  name: 'aso-monitor',
  frequency: 'daily_9am',
  workflow: {
    check: ['Spin & Dine', 'Styln', '3 competitors'],
    keywords: ['restaurant app', 'AI fashion', 'virtual try on'],
    alertOn: ['ranking_drop > 5', 'new_competitor_review']
  }
});
```

### 2. Trading Market Scan
```javascript
// Pre-market scan across multiple sources
agentBrowser.schedule({
  name: 'pre-market-scan',
  frequency: 'daily_9am_et',
  sources: [
    { name: 'marketwatch', url: 'https://marketwatch.com/markets' },
    { name: 'bloomberg', url: 'https://bloomberg.com/markets' },
    { name: 'finviz', url: 'https://finviz.com/news.ashx' }
  ],
  extract: 'headlines',
  analyze: 'sentiment',
  alertOn: ['high_volatility_expected', 'earnings_today']
});
```

### 3. Competitive Intelligence
```javascript
// Weekly competitor feature tracking
agentBrowser.schedule({
  name: 'competitor-intel',
  frequency: 'weekly_monday',
  competitors: ['lensa', 'dawn-ai', 'geodine'],
  check: ['app_store_changelog', 'website_updates', 'social_posts'],
  report: 'weekly_competitive_brief'
});
```

## Implementation

### Architecture
```
Agent Browser
├── Session Manager (cookies, auth state)
├── Workflow Engine (multi-step pipelines)
├── Data Extractor (structured scraping)
├── Error Handler (recovery strategies)
├── Scheduler (cron integration)
└── QMD Connector (automatic indexing)
```

### Dependencies
```json
{
  "playwright": "^1.40",
  "puppeteer-extra": "^3.3",
  "puppeteer-extra-plugin-stealth": "^2.11",
  "cheerio": "^1.0" // For HTML parsing
}
```

### Configuration
```json
{
  "agent_browser": {
    "default_timeout": 30000,
    "max_retries": 3,
    "user_agent": "Mozilla/5.0 (compatible; SilexBot/1.0)",
    "stealth": true,
    "proxy": {
      "enabled": false,
      "url": "http://proxy:8080"
    }
  }
}
```

## Integration with Skills

- **Proactive Agent:** Triggers browser workflows on schedule or event
- **Self-Improving Agent:** Analyzes workflow success rates, proposes optimizations
- **Content Bot:** Uses browser to research trending topics
- **Trading Bot:** Scrapes alternative data sources

## Success Metrics

- Workflow completion rate: >95%
- Data extraction accuracy: >98%
- False positive rate (alerts): <10%
- Recovery success rate: >80%

---

**Status:** Design proposal. `agentBrowser.*`, `indexToQMD`, and `saveToQMD` do not exist yet; write real automation against Playwright's API and treat the snippets above as the shape to aim for.
