---
name: browser-use
description: Browser automation for scraping, form submission, screenshots, and web interaction via CDP or Playwright.
disable-model-invocation: true
---

# Browser Use Skill

## Overview

Enables agents to control web browsers for automation, data extraction, form submission, and interaction with web-based tools. Uses headless browser automation via CDP (Chrome DevTools Protocol) or Playwright.

## When to Use

- Scraping competitor pricing or content
- Automating social media posting
- Filling forms (e.g., influencer outreach)
- Taking screenshots for reports
- Monitoring website changes
- Testing web applications

## Core Capabilities

### 1. Page Navigation
```javascript
// Basic navigation
await browser.navigate('https://tiktok.com');
await browser.waitForLoad('networkidle');

// With authentication
await browser.setCookies(authCookies);
await browser.navigate('https://app.interactivebrokers.com');
```

### 2. Element Interaction
```javascript
// Click, type, select
await browser.click('[data-testid="login-button"]');
await browser.type('input[name="username"]', 'user@example.com');
await browser.select('select[name="date-range"]', '30d');

// Extract data
const price = await browser.text('.current-price');
const items = await browser.queryAll('.product-item');
```

### 3. Screenshot & PDF
```javascript
// Full page screenshot
await browser.screenshot({
  path: '/root/clawd/screenshots/report.png',
  fullPage: true
});

// Specific element
await browser.screenshot({
  path: 'chart.png',
  selector: '#price-chart'
});
```

### 4. JavaScript Execution
```javascript
// Execute in page context
const data = await browser.evaluate(() => {
  return window.appData.prices;
});
```

## Use Cases for Silex Holdings

### A. Influencer Research (Styln)
```javascript
// Find fashion micro-influencers
async function findFashionInfluencers() {
  await browser.navigate('https://instagram.com/explore/tags/fashionblogger');
  
  const posts = await browser.queryAll('article a');
  const influencers = [];
  
  for (const post of posts.slice(0, 10)) {
    await post.click();
    await browser.wait(1000);
    
    const username = await browser.text('a[role="link"]');
    const followers = await browser.text('[role="button"] span');
    const bio = await browser.text('.bio-text');
    
    if (parseFollowers(followers) < 100000) {
      influencers.push({
        username,
        followers: parseFollowers(followers),
        bio,
        email: extractEmail(bio)
      });
    }
    
    await browser.keyPress('Escape');
  }
  
  return influencers;
}
```

### B. Competitor Monitoring (Spin & Dine)
```javascript
// Track competitor app store rankings
async function trackCompetitors() {
  const competitors = ['geodine', 'restaurantroulette', 'lunchwheel'];
  const data = {};
  
  for (const comp of competitors) {
    await browser.navigate(`https://apps.apple.com/us/app/${comp}`);
    
    data[comp] = {
      rating: await browser.text('.we-customer-ratings__averages__display'),
      reviews: await browser.text('.we-customer-ratings__count'),
      version: await browser.text('.whats-new__latest__version'),
      updated: await browser.text('.whats-new__latest__date')
    };
  }
  
  // Log to QMD
  await indexToQMD('competitor-tracking', data);
}
```

### C. Trading Data Extraction (IBKR)
```javascript
// Scrape options chain (if API unavailable)
async function scrapeOptionsChain(symbol) {
  await browser.navigate(`https://interactivebrokers.com/options/${symbol}`);
  
  const chain = await browser.evaluate(() => {
    const rows = document.querySelectorAll('.option-row');
    return Array.from(rows).map(row => ({
      strike: row.querySelector('.strike').textContent,
      call: row.querySelector('.call-premium').textContent,
      put: row.querySelector('.put-premium').textContent,
      iv: row.querySelector('.implied-vol').textContent
    }));
  });
  
  return chain;
}
```

## Tools Available

### Option 1: Cloudflare Browser (Current Setup)
- Location: `/skills/cloudflare-browser/SKILL.md`
- Requires: `CDP_SECRET` env var
- Best for: Screenshots, basic scraping within Workers
- Limitation: Limited runtime (30s request timeout)

### Option 2: Playwright (Recommended for complex automation)
```javascript
const { chromium } = require('playwright');

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();

await page.goto('https://example.com');
await page.click('button');
const text = await page.textContent('.result');

await browser.close();
```

### Option 3: Puppeteer (Alternative)
```javascript
const puppeteer = require('puppeteer');

const browser = await puppeteer.launch();
const page = await browser.newPage();
// ... similar API
```

## Implementation

### Installation
```bash
# For Playwright
npm install playwright
npx playwright install chromium

# For Puppeteer
npm install puppeteer
```

### Basic Script
```javascript
// scripts/browser-automation.js
const { chromium } = require('playwright');

async function runBrowserTask(task) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  try {
    const result = await task(page);
    return result;
  } finally {
    await browser.close();
  }
}

module.exports = { runBrowserTask };
```

## Security & Ethics

### Allowed Uses
✅ Scraping publicly available data
✅ Automating your own accounts
✅ Taking screenshots for reports
✅ Testing your own applications

### Prohibited Uses
❌ Bypassing authentication
❌ Scraping private data
❌ Violating Terms of Service
❌ Automated interaction with third-party accounts

### Best Practices
- Respect `robots.txt`
- Add delays between requests (rate limiting)
- Use official APIs when available
- Log all actions for audit trail

## Integration with Proactive Agent

```javascript
// Proactive browser monitoring
async function proactiveCompetitorCheck() {
  const oldData = loadFromQMD('competitor-snapshot');
  const newData = await scrapeCompetitorData();
  
  const changes = detectChanges(oldData, newData);
  
  if (changes.significant) {
    alertUser(`Competitor update detected: ${changes.summary}`);
    queueForReview(changes);
  }
}
```

---

**Status:** Skill defined, requires Playwright/Puppeteer installation for activation
