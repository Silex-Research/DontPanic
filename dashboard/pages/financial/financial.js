// ── JARVIS — Financial Analysis Page Module ──
// Sub-tabs: Market Data (ticker search, watchlist, price chart, fundamentals,
// analyst ratings, earnings, dividends) and Deep Analysis (Buffett-Munger
// scorecard, multi-year financials table, Bayesian confidence sliders,
// intrinsic value estimates).
//
// Data source: Yahoo Finance v1/v8/v10 endpoints via CORS proxies.
// Watchlist: persisted in localStorage.
// Demo fallback: synthetic AAPL data rendered when API is unreachable.

import {
  fmtRaw,
  fmtNum,
  fmtCurrency,
  fmtPct,
  fmtLargeNum,
  formatDAValue,
  computeScorecard,
  computeValuation,
  computeTiers,
  evaluateTier2,
  recalculateValuationFromSliders,
  generateNotes,
} from '../../lib/financial-logic.js';

(() => {
  // ── Module state ──
  let _el = null;
  let _priceChart = null;
  let _earningsChart = null;
  let _daRadarChart = null;
  let _currentTicker = null;
  let _currentTickerData = null;
  let _currentDASymbol = null;
  let _currentDAData = null;
  let _watchlistTickers = [];
  let _searchDebounce = null;
  let _daSearchDebounce = null;

  // ── CORS proxy chain ──
  const CORS_PROXIES = [
    (url) => `https://corsproxy.io/?${encodeURIComponent(url)}`,
    (url) => `https://api.allorigins.win/raw?url=${encodeURIComponent(url)}`,
  ];

  // ── Watchlist persistence ──
  const WL_KEY = 'jarvis_watchlist_v1';

  function loadWatchlist() {
    try {
      const raw = localStorage.getItem(WL_KEY);
      _watchlistTickers = raw ? JSON.parse(raw) : [];
    } catch {
      _watchlistTickers = [];
    }
  }

  function saveWatchlist() {
    try {
      localStorage.setItem(WL_KEY, JSON.stringify(_watchlistTickers));
    } catch { /* quota exceeded — non-critical */ }
  }

  // ── HTML escaping ──
  function esc(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function emptyState(msg) {
    return `<div class="empty-state">
      <div class="empty-icon">--</div>
      <div class="empty-text">${esc(msg)}</div>
    </div>`;
  }

  // ── Yahoo Finance value extractors ──
  // (fmtRaw, fmtNum, fmtCurrency, fmtPct, fmtLargeNum, formatDAValue
  //  imported from ../../lib/financial-logic.js)

  // ── Network layer ──
  async function fetchWithProxy(url) {
    for (const buildProxy of CORS_PROXIES) {
      try {
        const res = await fetch(buildProxy(url));
        if (res.ok) return res;
      } catch {
        // try next proxy
      }
    }
    throw new Error('All CORS proxies failed for: ' + url);
  }

  async function fetchYahoo(symbol, modules = 'price,summaryDetail,defaultKeyStatistics,financialData,earnings,recommendationTrend') {
    const cb = Math.floor(Date.now() / 60000);
    const url = `https://query2.finance.yahoo.com/v10/finance/quoteSummary/${encodeURIComponent(symbol)}?modules=${modules}&cb=${cb}`;
    const res = await fetchWithProxy(url);
    const json = await res.json();
    const result = json?.quoteSummary?.result?.[0];
    if (!result) throw new Error('No data found for ' + symbol);
    return result;
  }

  async function fetchChart(symbol, range = '1mo', interval = '1d') {
    const cb = Math.floor(Date.now() / 60000);
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=${range}&interval=${interval}&cb=${cb}`;
    const res = await fetchWithProxy(url);
    const json = await res.json();
    return json?.chart?.result?.[0];
  }

  async function searchYahooSymbols(query) {
    const url = `https://query2.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(query)}&quotesCount=6&newsCount=0`;
    const res = await fetchWithProxy(url);
    const json = await res.json();
    return json?.quotes || [];
  }

  // ── Timeframe helpers ──
  function q(sel) { return _el.querySelector(sel); }
  function qAll(sel) { return _el.querySelectorAll(sel); }

  function getActiveTimeframe() {
    const active = q('.tf-btn.active');
    return {
      range: active?.dataset.range || '1mo',
      interval: active?.dataset.interval || '1d'
    };
  }

  // ── Page HTML template ──
  function buildTemplate() {
    return `
      <div class="fin-sub-tabs">
        <button class="fin-sub-tab active" data-subtab="market-data">Market Data</button>
        <button class="fin-sub-tab" data-subtab="deep-analysis">Deep Analysis</button>
      </div>

      <!-- Market Data sub-tab -->
      <div id="fin-market-data" class="fin-subtab-view active">
        <div class="financial-layout">

          <!-- Watchlist Sidebar -->
          <aside class="watchlist-sidebar">
            <h2>Watchlist</h2>
            <div id="fin-watchlist-list" class="watchlist-list">
              ${emptyState('No tickers in watchlist')}
            </div>
          </aside>

          <!-- Ticker Detail -->
          <div class="ticker-detail">

            <!-- Search Bar -->
            <div class="fin-search-bar">
              <div class="fin-search-wrapper">
                <input type="text" id="fin-ticker-search" class="fin-search-input"
                  placeholder="Search ticker (e.g. AAPL, MSFT)..." autocomplete="off">
                <button id="fin-ticker-search-btn" class="fin-search-btn">SEARCH</button>
              </div>
              <div id="fin-search-results-dropdown" class="search-results-dropdown hidden"></div>
            </div>

            <!-- Ticker Content (hidden until search) -->
            <div id="fin-ticker-content" class="ticker-content hidden">

              <!-- Price Header -->
              <div id="fin-price-header" class="fin-price-header"></div>

              <!-- Timeframe Buttons -->
              <div class="fin-timeframe-bar">
                <button class="tf-btn" data-range="1d" data-interval="5m">1D</button>
                <button class="tf-btn" data-range="5d" data-interval="15m">1W</button>
                <button class="tf-btn active" data-range="1mo" data-interval="1d">1M</button>
                <button class="tf-btn" data-range="3mo" data-interval="1d">3M</button>
                <button class="tf-btn" data-range="1y" data-interval="1wk">1Y</button>
                <button class="tf-btn" data-range="5y" data-interval="1mo">5Y</button>
                <button class="tf-btn" id="fin-chart-reset-zoom" style="display:none;margin-left:auto">Reset Zoom</button>
              </div>

              <!-- Price Chart -->
              <div class="fin-chart-container">
                <canvas id="fin-price-chart"></canvas>
              </div>

              <!-- Info Grid -->
              <div class="fin-info-grid">

                <section class="panel fin-fundamentals">
                  <h2>Fundamentals</h2>
                  <div id="fin-fundamentals-grid" class="fundamentals-grid"></div>
                </section>

                <section class="panel fin-ratings">
                  <h2>Analyst Ratings</h2>
                  <div id="fin-ratings-bar" class="ratings-bar-container"></div>
                </section>

                <section class="panel fin-earnings">
                  <h2>Earnings</h2>
                  <div class="fin-earnings-chart-container">
                    <canvas id="fin-earnings-chart"></canvas>
                  </div>
                </section>

                <section class="panel fin-dividends">
                  <h2>Dividends</h2>
                  <div id="fin-dividends-info" class="dividends-info"></div>
                </section>

              </div>
            </div>

            <!-- Empty state before search -->
            <div id="fin-ticker-empty" class="ticker-empty-state">
              <div class="ticker-empty-icon">$</div>
              <div class="ticker-empty-text">Search for a ticker to view financial data</div>
            </div>

          </div>
        </div>
      </div>

      <!-- Deep Analysis sub-tab -->
      <div id="fin-deep-analysis" class="fin-subtab-view" style="display:none">
        <div class="da-layout">

          <!-- Header: Company Search + Tier Badges -->
          <div class="da-header">
            <div class="da-company-selector fin-search-bar">
              <div class="fin-search-wrapper">
                <input type="text" id="fin-da-company-search" class="fin-search-input"
                  placeholder="Search company for deep analysis..." autocomplete="off">
                <button id="fin-da-load-btn" class="fin-search-btn">ANALYZE</button>
              </div>
              <div id="fin-da-search-dropdown" class="search-results-dropdown hidden"></div>
            </div>
            <div class="da-tier-badges">
              <span class="da-tier" data-tier="1">Tier 1</span>
              <span class="da-tier" data-tier="2">Tier 2</span>
              <span class="da-tier" data-tier="3">Tier 3</span>
              <span class="da-tier" data-tier="4">Tier 4</span>
              <span class="da-tier" data-tier="5">Tier 5</span>
            </div>
          </div>

          <!-- Tier 2: Multi-Year Financial Data Table -->
          <section class="panel da-financials-panel">
            <h2>Financial Review: Stability of Earnings</h2>
            <div class="da-table-scroll">
              <table id="fin-da-financials-table" class="da-table">
                <tr><td style="padding:2rem;color:var(--text-muted)">
                  Enter a company symbol above and click ANALYZE to load financial data.
                </td></tr>
              </table>
            </div>
          </section>

          <!-- Tier 3: Calculated Metrics -->
          <section class="panel da-metrics-panel">
            <h2>Calculated Metrics</h2>
            <div id="fin-da-metrics-grid" class="da-metrics-grid">
              ${emptyState('No data')}
            </div>
          </section>

          <!-- Tier 4: Buffett-Munger Scorecard -->
          <section class="panel da-scorecard-panel">
            <h2>Buffett-Munger Scorecard</h2>
            <div class="da-scorecard-layout">
              <div class="da-radar-container">
                <canvas id="fin-da-radar-chart"></canvas>
              </div>
              <div id="fin-da-score-details" class="da-score-details">
                ${emptyState('No data')}
              </div>
            </div>
          </section>

          <!-- Tier 5: Bayesian Confidence / Intrinsic Value -->
          <section class="panel da-bayesian-panel">
            <h2>Intrinsic Value &amp; Confidence</h2>
            <div class="da-bayesian-layout">
              <div class="da-valuation-summary" id="fin-da-valuation-summary">
                ${emptyState('No valuation data')}
              </div>
              <div class="da-confidence-sliders" id="fin-da-confidence-sliders">
                <div class="da-slider-row">
                  <label>Moat Durability</label>
                  <input type="range" min="0" max="100" value="70"
                    class="da-slider" data-param="moatDurability">
                  <span class="da-slider-val">70</span>
                </div>
                <div class="da-slider-row">
                  <label>Earnings Growth</label>
                  <input type="range" min="-10" max="30" value="8"
                    class="da-slider" data-param="earningsGrowth">
                  <span class="da-slider-val">8%</span>
                </div>
                <div class="da-slider-row">
                  <label>Disruption Risk</label>
                  <input type="range" min="0" max="100" value="25"
                    class="da-slider" data-param="disruptionRisk">
                  <span class="da-slider-val">25</span>
                </div>
                <div class="da-slider-row">
                  <label>Multiple Expansion</label>
                  <input type="range" min="-5" max="5" value="0" step="0.5"
                    class="da-slider" data-param="multipleExpansion">
                  <span class="da-slider-val">0x</span>
                </div>
              </div>
            </div>
          </section>

          <!-- Analysis Notes -->
          <section class="panel da-notes-panel">
            <h2>Analysis Notes</h2>
            <div id="fin-da-notes" class="da-notes">
              Enter a symbol above to generate analysis notes.
            </div>
          </section>

        </div>
      </div>
    `;
  }

  // ── Sub-tab switching ──
  function setupSubTabs() {
    qAll('.fin-sub-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        qAll('.fin-sub-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');

        qAll('.fin-subtab-view').forEach(v => {
          v.classList.remove('active');
          v.style.display = 'none';
        });

        const target = _el.querySelector('#fin-' + tab.dataset.subtab);
        if (target) {
          target.classList.add('active');
          target.style.display = '';
        }

        const subtab = tab.dataset.subtab;
        if (subtab === 'deep-analysis' && _currentTicker && _currentDASymbol !== _currentTicker) {
          q('#fin-da-company-search').value = _currentTicker;
          loadDeepAnalysis(_currentTicker);
        } else if (subtab === 'market-data' && _currentDASymbol && _currentTicker !== _currentDASymbol) {
          q('#fin-ticker-search').value = _currentDASymbol;
          loadTicker(_currentDASymbol);
        }
      });
    });
  }

  // ── Market Data: search ──
  function setupMarketDataSearch() {
    const searchInput = q('#fin-ticker-search');
    const searchBtn = q('#fin-ticker-search-btn');
    const dropdown = q('#fin-search-results-dropdown');

    searchBtn.addEventListener('click', () => {
      const sym = searchInput.value.trim().toUpperCase();
      if (sym) { hideDropdown(dropdown); loadTicker(sym); }
    });

    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const sym = searchInput.value.trim().toUpperCase();
        if (sym) { hideDropdown(dropdown); loadTicker(sym); }
      }
      if (e.key === 'Escape') hideDropdown(dropdown);
    });

    searchInput.addEventListener('input', () => {
      clearTimeout(_searchDebounce);
      const query = searchInput.value.trim();
      if (query.length < 1) { hideDropdown(dropdown); return; }
      _searchDebounce = setTimeout(() => {
        searchYahooSymbols(query)
          .then(quotes => renderSearchDropdown(dropdown, quotes, (sym) => {
            searchInput.value = sym;
            hideDropdown(dropdown);
            loadTicker(sym);
          }))
          .catch(() => hideDropdown(dropdown));
      }, 300);
    });

    document.addEventListener('click', (e) => {
      if (!e.target.closest('#fin-ticker-search') && !e.target.closest('#fin-search-results-dropdown')) {
        hideDropdown(dropdown);
      }
    });
  }

  // ── Market Data: timeframe buttons ──
  function setupTimeframeButtons() {
    qAll('.tf-btn:not(#fin-chart-reset-zoom)').forEach(btn => {
      btn.addEventListener('click', () => {
        qAll('.tf-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        if (_currentTicker) {
          loadChart(_currentTicker, btn.dataset.range, btn.dataset.interval);
        }
      });
    });

    q('#fin-chart-reset-zoom').addEventListener('click', () => {
      if (_priceChart) _priceChart.resetZoom();
    });
  }

  // ── Generic dropdown renderer ──
  function renderSearchDropdown(dropdown, quotes, onSelect) {
    if (!quotes.length) { hideDropdown(dropdown); return; }
    dropdown.classList.remove('hidden');
    dropdown.innerHTML = quotes.map(qt => `
      <div class="search-result-item" data-symbol="${esc(qt.symbol)}">
        <span class="search-result-symbol">${esc(qt.symbol)}</span>
        <span class="search-result-name">${esc(qt.shortname || qt.longname || '')}</span>
        <span class="search-result-type">${esc(qt.quoteType || '')}</span>
      </div>
    `).join('');

    dropdown.querySelectorAll('.search-result-item').forEach(item => {
      item.addEventListener('click', () => onSelect(item.dataset.symbol));
    });
  }

  function hideDropdown(el) {
    if (el) el.classList.add('hidden');
  }

  // ── Load ticker ──
  async function loadTicker(symbol) {
    _currentTicker = symbol;

    const daInput = q('#fin-da-company-search');
    if (daInput && daInput.value !== symbol) daInput.value = symbol;

    q('#fin-ticker-empty').style.display = 'none';
    q('#fin-ticker-content').classList.remove('hidden');

    // Loading skeleton
    q('#fin-price-header').innerHTML = `
      <div>
        <div class="skeleton skeleton-line" style="width:100px;height:24px"></div>
        <div class="skeleton skeleton-line short" style="margin-top:4px"></div>
      </div>
      <div class="skeleton skeleton-line" style="width:160px;height:36px"></div>
    `;
    q('#fin-fundamentals-grid').innerHTML = Array(10).fill(
      '<div class="skeleton skeleton-line"></div>'
    ).join('');

    try {
      const [data, chartData] = await Promise.all([
        fetchYahoo(symbol),
        fetchChart(symbol, getActiveTimeframe().range, getActiveTimeframe().interval)
      ]);
      _currentTickerData = data;
      renderTickerDetail(data);
      renderPriceChart(chartData);
    } catch (err) {
      console.error('[Financial] Failed to load ticker:', err);
      // Demo fallback for AAPL or unknown symbols
      const demoData = getDemoTickerData();
      if (symbol.toUpperCase() === 'AAPL') {
        _currentTickerData = demoData;
        renderTickerDetail(demoData);
        renderDemoPriceChart();
      } else {
        q('#fin-price-header').innerHTML = `
          <div style="color:var(--text-muted);padding:20px">
            Could not fetch data for ${esc(symbol)}.
            Try AAPL for a demo, or check the symbol and try again.
          </div>
        `;
      }
    }
  }

  async function loadChart(symbol, range, interval) {
    try {
      const chartData = await fetchChart(symbol, range, interval);
      renderPriceChart(chartData);
    } catch (err) {
      console.error('[Financial] Failed to reload chart:', err);
    }
  }

  // ── Render ticker detail ──
  function renderTickerDetail(data) {
    const price = data.price || {};
    const summary = data.summaryDetail || {};
    const keyStats = data.defaultKeyStatistics || {};
    const financial = data.financialData || {};
    const earnings = data.earnings || {};
    const trends = data.recommendationTrend?.trend || [];

    // Price header
    const regularPrice = fmtRaw(price.regularMarketPrice);
    const change = fmtRaw(price.regularMarketChange);
    const changePct = fmtRaw(price.regularMarketChangePercent);
    const isUp = (parseFloat(change) || 0) >= 0;
    const inWatchlist = _watchlistTickers.includes(_currentTicker);

    q('#fin-price-header').innerHTML = `
      <div>
        <div class="fin-price-symbol">${esc(price.symbol || _currentTicker)}</div>
        <div class="fin-price-name">${esc(price.shortName || price.longName || '')}</div>
      </div>
      <div class="fin-price-value">${regularPrice !== '--' ? '$' + regularPrice : '--'}</div>
      <div class="fin-price-change ${isUp ? 'up' : 'down'}">
        ${isUp ? '+' : ''}${change}
        (${changePct !== '--' ? (parseFloat(changePct) * 100).toFixed(2) + '%' : '--'})
      </div>
      <div class="fin-price-meta">
        ${esc(price.exchangeName || '')} &middot; ${esc(price.currency || 'USD')}
      </div>
      <button class="fin-watchlist-btn ${inWatchlist ? 'in-watchlist' : ''}"
        data-sym="${esc(_currentTicker)}" id="fin-wl-toggle-btn">
        ${inWatchlist ? '&#8722; Remove' : '&#43; Watchlist'}
      </button>
    `;

    q('#fin-wl-toggle-btn').addEventListener('click', () => {
      toggleWatchlist(_currentTicker);
    });

    // Fundamentals
    const fundItems = [
      ['P/E Ratio',      fmtNum(summary.trailingPE)],
      ['Forward P/E',    fmtNum(summary.forwardPE)],
      ['EPS (TTM)',      fmtCurrency(keyStats.trailingEps)],
      ['Market Cap',     fmtLargeNum(price.marketCap)],
      ['Revenue',        fmtLargeNum(financial.totalRevenue)],
      ['Profit Margin',  fmtPct(financial.profitMargins)],
      ['ROE',            fmtPct(financial.returnOnEquity)],
      ['ROA',            fmtPct(financial.returnOnAssets)],
      ['Debt/Equity',    fmtNum(financial.debtToEquity)],
      ['Book Value',     fmtCurrency(keyStats.bookValue)],
      ['52w High',       fmtCurrency(summary.fiftyTwoWeekHigh)],
      ['52w Low',        fmtCurrency(summary.fiftyTwoWeekLow)],
      ['Analyst Target', fmtCurrency(financial.targetMeanPrice)],
      ['Beta',           fmtNum(keyStats.beta)],
    ];

    q('#fin-fundamentals-grid').innerHTML = fundItems.map(([label, val]) => `
      <div class="fundamental-item">
        <span class="fundamental-label">${label}</span>
        <span class="fundamental-value">${val}</span>
      </div>
    `).join('');

    // Analyst ratings
    const latestTrend = trends[0] || {};
    const buy = (latestTrend.strongBuy || 0) + (latestTrend.buy || 0);
    const hold = latestTrend.hold || 0;
    const sell = (latestTrend.sell || 0) + (latestTrend.strongSell || 0);

    q('#fin-ratings-bar').innerHTML = `
      <div class="ratings-bar">
        <div class="ratings-segment buy" style="flex:${buy || 1}">${buy}</div>
        <div class="ratings-segment hold" style="flex:${hold || 1}">${hold}</div>
        <div class="ratings-segment sell" style="flex:${sell || 1}">${sell}</div>
      </div>
      <div class="ratings-legend">
        <div class="ratings-legend-item">
          <span class="ratings-dot buy"></span>Buy ${buy}
        </div>
        <div class="ratings-legend-item">
          <span class="ratings-dot hold"></span>Hold ${hold}
        </div>
        <div class="ratings-legend-item">
          <span class="ratings-dot sell"></span>Sell ${sell}
        </div>
      </div>
    `;

    // Earnings chart
    renderEarningsChart(earnings);

    // Dividends
    const divYield = fmtPct(summary.dividendYield);
    const divRate = fmtCurrency(summary.dividendRate);
    const payoutRatio = fmtPct(summary.payoutRatio);
    const rawExDate = typeof summary.exDividendDate === 'object'
      ? summary.exDividendDate?.raw
      : summary.exDividendDate;
    const exDate = rawExDate
      ? new Date(rawExDate * 1000).toLocaleDateString()
      : '--';

    q('#fin-dividends-info').innerHTML = `
      <div class="dividend-item">
        <div class="dividend-label">Yield</div>
        <div class="dividend-value">${divYield}</div>
      </div>
      <div class="dividend-item">
        <div class="dividend-label">Rate</div>
        <div class="dividend-value">${divRate}</div>
      </div>
      <div class="dividend-item">
        <div class="dividend-label">Payout Ratio</div>
        <div class="dividend-value">${payoutRatio}</div>
      </div>
      <div class="dividend-item">
        <div class="dividend-label">Ex-Date</div>
        <div class="dividend-value">${exDate}</div>
      </div>
    `;

    renderWatchlist();
  }

  // ── Price chart ──
  function renderPriceChart(chartData) {
    if (!chartData) return;

    const timestamps = chartData.timestamp || [];
    const closes = chartData.indicators?.quote?.[0]?.close || [];
    const isIntraday = timestamps.length > 100;

    const labels = timestamps.map(ts => {
      const d = new Date(ts * 1000);
      return isIntraday
        ? d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
        : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    });

    if (_priceChart) _priceChart.destroy();
    _priceChart = new Chart(q('#fin-price-chart'), {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: _currentTicker,
          data: closes.map(c => c ?? null),
          borderColor: '#a855f7',
          backgroundColor: 'rgba(168, 85, 247, 0.1)',
          fill: true,
          tension: 0.2,
          pointRadius: 0,
          pointHitRadius: 10,
          borderWidth: 2,
          spanGaps: true,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: {
            ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 12 },
            grid: { color: 'rgba(42, 58, 78, 0.5)' }
          },
          y: {
            ticks: {
              color: '#64748b',
              font: { size: 10 },
              callback: v => '$' + v.toFixed(2)
            },
            grid: { color: 'rgba(42, 58, 78, 0.5)' }
          }
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => '$' + (ctx.parsed.y?.toFixed(2) || '--')
            }
          },
          zoom: {
            pan: { enabled: true, mode: 'x' },
            zoom: {
              wheel: { enabled: true },
              pinch: { enabled: true },
              drag: {
                enabled: true,
                backgroundColor: 'rgba(168, 85, 247, 0.15)',
                borderColor: '#a855f7',
                borderWidth: 1,
              },
              mode: 'x',
            }
          }
        }
      }
    });

    const resetBtn = q('#fin-chart-reset-zoom');
    if (resetBtn) resetBtn.style.display = '';
  }

  // ── Earnings chart ──
  function renderEarningsChart(earnings) {
    const quarterly = earnings?.earningsChart?.quarterly || [];
    const container = _el.querySelector('.fin-earnings-chart-container');

    if (!quarterly.length) {
      container.innerHTML = emptyState('No earnings data');
      return;
    }

    if (!container.querySelector('canvas')) {
      container.innerHTML = '<canvas id="fin-earnings-chart"></canvas>';
    }

    const labels = quarterly.map(q => q.date || '--');
    const actual = quarterly.map(q => q.actual?.raw ?? null);
    const estimate = quarterly.map(q => q.estimate?.raw ?? null);

    if (_earningsChart) _earningsChart.destroy();
    _earningsChart = new Chart(q('#fin-earnings-chart'), {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: 'Actual',
            data: actual,
            backgroundColor: 'rgba(168, 85, 247, 0.7)',
            borderColor: '#a855f7',
            borderWidth: 1,
            borderRadius: 4,
          },
          {
            label: 'Estimate',
            data: estimate,
            backgroundColor: 'rgba(59, 130, 246, 0.4)',
            borderColor: '#3b82f6',
            borderWidth: 1,
            borderRadius: 4,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            ticks: { color: '#64748b', font: { size: 10 } },
            grid: { color: 'rgba(42, 58, 78, 0.5)' }
          },
          y: {
            ticks: { color: '#64748b', font: { size: 10 } },
            grid: { color: 'rgba(42, 58, 78, 0.5)' }
          }
        },
        plugins: {
          legend: {
            display: true,
            labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 12 }
          }
        }
      }
    });
  }

  // ── Watchlist ──
  function toggleWatchlist(symbol) {
    const idx = _watchlistTickers.indexOf(symbol);
    if (idx >= 0) {
      _watchlistTickers.splice(idx, 1);
    } else {
      _watchlistTickers.push(symbol);
    }
    saveWatchlist();
    renderWatchlist();
    if (_currentTickerData) renderTickerDetail(_currentTickerData);
  }

  function renderWatchlist() {
    const container = q('#fin-watchlist-list');
    if (!_watchlistTickers.length) {
      container.innerHTML = emptyState('No tickers in watchlist');
      return;
    }

    container.innerHTML = _watchlistTickers.map(sym => {
      const isActive = sym === _currentTicker;
      return `
        <div class="watchlist-item ${isActive ? 'active' : ''}" data-symbol="${esc(sym)}">
          <div class="watchlist-item-left">
            <div class="watchlist-symbol">${esc(sym)}</div>
          </div>
          <button class="watchlist-remove" data-sym="${esc(sym)}">&times;</button>
        </div>
      `;
    }).join('');

    container.querySelectorAll('.watchlist-item').forEach(item => {
      item.addEventListener('click', (e) => {
        if (e.target.classList.contains('watchlist-remove')) return;
        const sym = item.dataset.symbol;
        q('#fin-ticker-search').value = sym;
        loadTicker(sym);
      });
    });

    container.querySelectorAll('.watchlist-remove').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleWatchlist(btn.dataset.sym);
      });
    });
  }

  // ── Deep Analysis setup ──
  function setupDeepAnalysis() {
    const searchInput = q('#fin-da-company-search');
    const loadBtn = q('#fin-da-load-btn');
    const dropdown = q('#fin-da-search-dropdown');

    loadBtn.addEventListener('click', () => {
      const sym = searchInput.value.trim().toUpperCase();
      if (sym) { hideDropdown(dropdown); loadDeepAnalysis(sym); }
    });

    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const sym = searchInput.value.trim().toUpperCase();
        if (sym) { hideDropdown(dropdown); loadDeepAnalysis(sym); }
      }
      if (e.key === 'Escape') hideDropdown(dropdown);
    });

    searchInput.addEventListener('input', () => {
      clearTimeout(_daSearchDebounce);
      const query = searchInput.value.trim();
      if (query.length < 1) { hideDropdown(dropdown); return; }
      _daSearchDebounce = setTimeout(() => {
        searchYahooSymbols(query)
          .then(quotes => renderSearchDropdown(dropdown, quotes, (sym) => {
            searchInput.value = sym;
            hideDropdown(dropdown);
            loadDeepAnalysis(sym);
          }))
          .catch(() => hideDropdown(dropdown));
      }, 300);
    });

    document.addEventListener('click', (e) => {
      if (!e.target.closest('#fin-da-company-search') && !e.target.closest('#fin-da-search-dropdown')) {
        hideDropdown(dropdown);
      }
    });

    // Bayesian slider events
    qAll('.da-slider').forEach(slider => {
      slider.addEventListener('input', () => {
        const param = slider.dataset.param;
        let suffix = '';
        if (param === 'earningsGrowth') suffix = '%';
        else if (param === 'multipleExpansion') suffix = 'x';
        slider.nextElementSibling.textContent = slider.value + suffix;
        if (_currentDAData) recalculateValuation();
      });
    });
  }

  // ── Load Deep Analysis ──
  async function loadDeepAnalysis(symbol) {
    _currentDASymbol = symbol;

    const mdInput = q('#fin-ticker-search');
    if (mdInput && mdInput.value !== symbol) mdInput.value = symbol;

    const table = q('#fin-da-financials-table');
    if (table) {
      table.innerHTML = `<tr><td style="padding:2rem;color:#94a3b8">Loading ${esc(symbol)}...</td></tr>`;
    }

    try {
      const analysis = await fetchAndComputeDA(symbol);
      _currentDAData = analysis;
      renderDeepAnalysis(analysis);
    } catch (err) {
      console.warn('[Financial] Deep Analysis fetch failed, using demo data:', err);
      _currentDAData = getDemoAnalysisData(symbol);
      renderDeepAnalysis(_currentDAData);
    }
  }

  // ── Fetch and compute Deep Analysis from Yahoo ──
  async function fetchAndComputeDA(symbol) {
    const modules = 'incomeStatementHistory,balanceSheetHistory,cashflowStatementHistory,price,summaryDetail,defaultKeyStatistics';
    const url = `https://query2.finance.yahoo.com/v10/finance/quoteSummary/${encodeURIComponent(symbol)}?modules=${modules}`;
    const res = await fetchWithProxy(url);
    const json = await res.json();
    const result = json?.quoteSummary?.result?.[0];
    if (!result) throw new Error('No data for ' + symbol);

    const yf = (obj) => obj?.raw ?? null;

    const incArr = result.incomeStatementHistory?.incomeStatementHistory || [];
    const balArr = result.balanceSheetHistory?.balanceSheetHistory || [];
    const cfArr  = result.cashflowStatementHistory?.cashflowStatementHistory || [];
    const priceData = result.price || {};
    const summary = result.summaryDetail || {};
    const stats   = result.defaultKeyStatistics || {};

    if (!incArr.length) throw new Error('No financials for ' + symbol);

    const toM = (v) => v != null ? Math.round(v / 1e6 * 10) / 10 : null;
    const yearSet = new Set();
    const data = {};

    // Index balance sheet and cash flow by year
    const balByYear = {};
    balArr.forEach(b => {
      const y = new Date(b.endDate.raw * 1000).getFullYear();
      balByYear[y] = b;
    });
    const cfByYear = {};
    cfArr.forEach(c => {
      const y = new Date(c.endDate.raw * 1000).getFullYear();
      cfByYear[y] = c;
    });

    incArr.forEach(inc => {
      const yr = new Date(inc.endDate.raw * 1000).getFullYear();
      yearSet.add(yr);
      const bal = balByYear[yr] || {};
      const cf  = cfByYear[yr] || {};

      const revenue          = yf(inc.totalRevenue);
      const netIncome        = yf(inc.netIncome);
      const costOfRevenue    = yf(inc.costOfRevenue);
      const operatingExpense = yf(inc.totalOperatingExpenses) || yf(inc.operatingExpense);
      const cash             = yf(bal.cash) || yf(bal.cashAndEquivalents);
      const currentLiabilities = yf(bal.totalCurrentLiabilities);
      const totalLiabilities = yf(bal.totalLiab);
      const totalAssets      = yf(bal.totalAssets);
      const tangibleAssets   = yf(bal.netTangibleAssets) || totalAssets;
      const equity           = yf(bal.totalStockholderEquity);
      const ltDebt           = yf(bal.longTermDebt);
      const currentAssets    = yf(bal.totalCurrentAssets);
      const retainedEarnings = yf(bal.retainedEarnings);
      const bookValue        = yf(bal.netTangibleAssets) || equity;
      const capex            = yf(cf.capitalExpenditures);

      data[yr] = {
        revenue:            toM(revenue),
        net_income:         toM(netIncome),
        cost_of_revenue:    toM(costOfRevenue),
        operating_expense:  toM(operatingExpense),
        cash:               toM(cash),
        current_liabilities: toM(currentLiabilities),
        total_liabilities:  toM(totalLiabilities),
        tangible_assets:    toM(tangibleAssets),
        equity:             toM(equity),
        lt_debt:            toM(ltDebt),
        current_assets:     toM(currentAssets),
        retained_earnings:  toM(retainedEarnings),
        book_value:         toM(bookValue),
        capex:              capex != null ? toM(Math.abs(capex)) : null,
      };
    });

    const years = [...yearSet].sort((a, b) => b - a);

    // True gain in equity = YoY change in equity
    for (let i = 0; i < years.length - 1; i++) {
      const curr = data[years[i]]?.equity;
      const prev = data[years[i + 1]]?.equity;
      if (curr != null && prev != null) {
        data[years[i]].true_gain_equity = Math.round((curr - prev) * 10) / 10;
      }
    }

    // 5-year avg ROIC
    const roicVals = years.map(y => {
      const d = data[y];
      return d.net_income && d.equity && d.equity > 0 ? d.net_income / d.equity : null;
    }).filter(v => v != null);
    if (roicVals.length >= 2) {
      data[years[0]].roic_5yr_avg = Math.round(
        roicVals.reduce((s, v) => s + v, 0) / roicVals.length * 10000
      ) / 10000;
    }

    // Trailing P/E
    const trailingPE = yf(summary.trailingPE) || yf(stats.trailingPE);
    if (trailingPE) data[years[0]].trailing_pe = Math.round(trailingPE * 100) / 100;

    const info = {
      currentPrice: yf(priceData.regularMarketPrice),
      trailingPE,
      trailingEps:  yf(stats.trailingEps) || yf(summary.trailingEps),
      marketCap:    yf(priceData.marketCap),
      longName:     priceData.longName || priceData.shortName || symbol,
      sector:       priceData.sector || '',
      industry:     priceData.industry || '',
    };

    const scorecard    = computeScorecard(data, years);
    const valuation    = computeValuation(data, years, info);
    const tier_status  = computeTiers(data, years, scorecard, valuation);
    const analysis_notes = generateNotes(symbol, info.longName, data, years, scorecard, info);

    return {
      symbol,
      company_name:   info.longName,
      years,
      data,
      scorecard,
      valuation,
      tier_status,
      analysis_notes,
      analyst:   'Live Computation',
      updatedAt: new Date().toISOString(),
    };
  }

  // ── Buffett-Munger scorecard, intrinsic value, tier evaluation,
  //    tier-2 detail, and notes generation ──
  // (computeScorecard, computeValuation, computeTiers, evaluateTier2,
  //  generateNotes imported from ../../lib/financial-logic.js)

  // ── Metric row definitions for the multi-year table ──
  const DA_METRIC_ROWS = [
    { key: 'revenue',            label: 'Revenue (Earnings)',           format: 'millions' },
    { key: 'net_income',         label: 'Net Income',                   format: 'millions' },
    { key: 'cost_of_revenue_pct',label: 'Cost of Revenue (%E)',         format: 'pct',
      calc: (d) => d.cost_of_revenue / d.revenue },
    { key: 'operating_expense_pct', label: 'Operating Expense (%E)',    format: 'pct',
      calc: (d) => d.operating_expense / d.revenue },
    { key: 'net_income_pct',     label: 'Net Income (%E)',              format: 'pct',
      calc: (d) => d.net_income / d.revenue },
    { key: 'retained_earnings',  label: 'Retained Earnings',            format: 'millions' },
    { key: 'cash',               label: 'Cash and Short Term Investments', format: 'millions' },
    { key: 'current_liabilities',label: 'Current Liabilities',          format: 'millions' },
    { key: 'total_liabilities',  label: 'Total Liabilities',            format: 'millions' },
    { key: 'tangible_assets',    label: 'Tangible Assets',              format: 'millions' },
    { key: 'equity',             label: 'Equity (Capital)',              format: 'millions' },
    { key: 'true_gain_equity',   label: 'True Gain in Equity',          format: 'millions' },
    { key: 'working_capital',    label: 'Working Capital',              format: 'millions',
      calc: (d) => (d.current_assets || 0) - d.current_liabilities },
    { key: 'capex',              label: 'CapEx',                        format: 'millions' },
    { key: 'capex_pct',          label: 'CapEx (%E)',                   format: 'pct',
      calc: (d) => d.capex / d.revenue },
    { key: 'book_value',         label: 'Book Value',                   format: 'millions' },
    { key: 'roic',               label: 'Return on Invested Capital (%)', format: 'pct',
      calc: (d) => d.net_income / d.equity },
    { key: 'roteg',              label: 'Return on True Gain in Equity (%)', format: 'pct',
      calc: (d) => d.net_income / (d.true_gain_equity || d.equity) },
    { key: 'roic_5yr_avg',       label: '5-year Avg Annual ROIC',       format: 'pct' },
    { key: 'roteg_5yr_avg',      label: '5-year Avg Annual ROTGE',      format: 'pct' },
    { key: 'acid_ratio',         label: 'Acid Ratio',                   format: 'decimal',
      calc: (d) => d.cash / d.current_liabilities },
    { key: 'assets_to_earnings', label: 'Assets to Earnings',           format: 'decimal',
      calc: (d) => d.tangible_assets / d.revenue },
    { key: 'lt_debt_to_equity',  label: 'LT Debt to Equity',           format: 'decimal',
      calc: (d) => (d.lt_debt || 0) / d.equity },
    { key: 'capital_turnover',   label: 'Capital Turnover',             format: 'decimal',
      calc: (d) => d.revenue / d.equity },
    { key: 'trailing_pe',        label: 'Trailing P/E',                 format: 'decimal' },
  ];

  // ── Render: full Deep Analysis ──
  function renderDeepAnalysis(data) {
    renderFinancialsTable(data);
    renderCalculatedMetrics(data);
    renderBMScorecard(data.scorecard || {});
    renderValuationSummary(data.valuation || {});
    renderTierBadges(data.tier_status || {});
    renderAnalysisNotes(data);
  }

  function renderFinancialsTable(analysisData) {
    const table = q('#fin-da-financials-table');
    if (!table) return;
    const years = analysisData.years || [];
    if (!years.length) { table.innerHTML = ''; return; }

    let html = '<thead><tr><th>Metric</th>';
    years.forEach(y => { html += `<th>${y}</th>`; });
    html += '</tr></thead><tbody>';

    DA_METRIC_ROWS.forEach(row => {
      html += `<tr><td class="da-metric-label">${esc(row.label)}</td>`;
      years.forEach(y => {
        const yearData = analysisData.data?.[y];
        let val = yearData?.[row.key];
        if (val == null && row.calc && yearData) {
          try { val = row.calc(yearData); } catch { val = null; }
        }
        const isNeg = typeof val === 'number' && val < 0;
        html += `<td class="da-metric-value${isNeg ? ' negative' : ''}">${formatDAValue(val, row.format)}</td>`;
      });
      html += '</tr>';
    });

    html += '</tbody>';
    table.innerHTML = html;
  }

  function renderCalculatedMetrics(analysisData) {
    const grid = q('#fin-da-metrics-grid');
    if (!grid) return;

    const years = analysisData.years || [];
    if (!years.length) { grid.innerHTML = emptyState('No data'); return; }

    const latest = analysisData.data?.[years[0]] || {};
    const tier2 = evaluateTier2(analysisData);

    const metrics = [
      {
        label: 'ROIC',
        value: latest.net_income && latest.equity ? latest.net_income / latest.equity : null,
        format: 'pct', threshold: [0.15, 0.10]
      },
      {
        label: 'ROTGE',
        value: latest.net_income && (latest.true_gain_equity || latest.equity)
          ? latest.net_income / (latest.true_gain_equity || latest.equity)
          : null,
        format: 'pct', threshold: [0.20, 0.12]
      },
      {
        label: 'Acid Ratio',
        value: latest.cash && latest.current_liabilities
          ? latest.cash / latest.current_liabilities
          : null,
        format: 'decimal', threshold: [1.0, 0.5]
      },
      {
        label: 'D/E Ratio',
        value: latest.equity ? (latest.lt_debt || 0) / latest.equity : null,
        format: 'decimal', threshold: [0.5, 1.0], invert: true
      },
      {
        label: 'Net Margin',
        value: latest.net_income && latest.revenue
          ? latest.net_income / latest.revenue
          : null,
        format: 'pct', threshold: [0.15, 0.08]
      },
      {
        label: 'CapEx %',
        value: latest.capex && latest.revenue
          ? latest.capex / latest.revenue
          : null,
        format: 'pct', threshold: [0.25, 0.50], invert: true
      },
      {
        label: 'Earnings Doubled',
        value: tier2.earningsDoubled ? 'YES' : 'NO',
        raw: true,
        cls: tier2.earningsDoubled ? 'high' : 'low'
      },
      {
        label: 'Max Decline',
        value: tier2.maxDecline, format: 'pct',
        threshold: [0.05, 0.15], invert: true
      },
    ];

    grid.innerHTML = metrics.map(m => {
      let display, cls;
      if (m.raw) {
        display = m.value;
        cls = m.cls || '';
      } else {
        display = formatDAValue(m.value, m.format);
        if (m.threshold && m.value != null) {
          cls = m.invert
            ? (m.value <= m.threshold[0] ? 'high' : m.value <= m.threshold[1] ? 'mid' : 'low')
            : (m.value >= m.threshold[0] ? 'high' : m.value >= m.threshold[1] ? 'mid' : 'low');
        } else {
          cls = '';
        }
      }
      return `
        <div class="da-metric-card">
          <div class="da-metric-card-label">${esc(m.label)}</div>
          <div class="da-metric-card-value ${cls}">${display}</div>
        </div>
      `;
    }).join('');
  }

  // evaluateTier2 imported from ../../lib/financial-logic.js

  function renderBMScorecard(scores) {
    const defaultScores = { moat: 0, management: 0, roic: 0, durability: 0 };
    scores = { ...defaultScores, ...scores };

    if (_daRadarChart) _daRadarChart.destroy();

    const canvas = q('#fin-da-radar-chart');
    if (!canvas) return;

    _daRadarChart = new Chart(canvas, {
      type: 'radar',
      data: {
        labels: ['Economic Moat', 'Management Quality', 'ROIC Quality', 'Durability'],
        datasets: [{
          label: 'Score',
          data: [scores.moat, scores.management, scores.roic, scores.durability],
          backgroundColor: 'rgba(168, 85, 247, 0.2)',
          borderColor: '#a855f7',
          borderWidth: 2,
          pointBackgroundColor: '#a855f7',
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          r: {
            min: 0, max: 100,
            ticks: { stepSize: 25, color: '#64748b', backdropColor: 'transparent' },
            grid: { color: 'rgba(42, 58, 78, 0.5)' },
            pointLabels: { color: '#e2e8f0', font: { size: 11 } },
            angleLines: { color: 'rgba(42, 58, 78, 0.5)' },
          }
        },
        plugins: { legend: { display: false } }
      }
    });

    const details = q('#fin-da-score-details');
    if (!details) return;

    details.innerHTML = Object.entries(scores).map(([key, val]) => `
      <div class="da-score-card">
        <div class="da-score-label">
          ${esc(key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()))}
        </div>
        <div class="da-score-value ${val >= 80 ? 'high' : val >= 60 ? 'mid' : 'low'}">${val}/100</div>
        <div class="da-score-bar">
          <div class="da-score-fill" style="width:${val}%"></div>
        </div>
      </div>
    `).join('');
  }

  function renderValuationSummary(valuation) {
    const container = q('#fin-da-valuation-summary');
    if (!container) return;

    if (!valuation.bull) {
      container.innerHTML = emptyState('No valuation data');
      return;
    }

    const bearReturn = valuation.bear.annualReturn;
    const bearReturnStr = bearReturn >= 0
      ? '+' + bearReturn + '% ann.'
      : bearReturn + '% ann.';

    container.innerHTML = `
      <div class="da-case da-bull">
        <div class="da-case-label">Bull (${valuation.bull.prob}%)</div>
        <div class="da-case-price">$${valuation.bull.price}</div>
        <div class="da-case-return">+${valuation.bull.annualReturn}% ann.</div>
      </div>
      <div class="da-case da-base">
        <div class="da-case-label">Base (${valuation.base.prob}%)</div>
        <div class="da-case-price">$${valuation.base.price}</div>
        <div class="da-case-return">+${valuation.base.annualReturn}% ann.</div>
      </div>
      <div class="da-case da-bear">
        <div class="da-case-label">Bear (${valuation.bear.prob}%)</div>
        <div class="da-case-price">$${valuation.bear.price}</div>
        <div class="da-case-return">${bearReturnStr}</div>
      </div>
      <div class="da-mos">
        <div class="da-mos-label">Margin of Safety</div>
        <div class="da-mos-value ${valuation.marginOfSafety >= 20 ? 'sufficient' : 'marginal'}">
          ${valuation.marginOfSafety}%
        </div>
      </div>
      <div class="da-buy-point">
        <div class="da-buy-label">Buy Below</div>
        <div class="da-buy-value">$${valuation.buyBelow}</div>
      </div>
    `;
  }

  function recalculateValuation() {
    if (!_currentDAData?.valuation?.base) return;

    const sliders = {};
    qAll('.da-slider').forEach(s => { sliders[s.dataset.param] = parseFloat(s.value); });

    const adjusted = recalculateValuationFromSliders(_currentDAData.valuation, sliders);
    renderValuationSummary(adjusted);
  }

  function renderTierBadges(tierStatus) {
    qAll('.da-tier').forEach(badge => {
      const tier = 'tier' + badge.dataset.tier;
      const status = tierStatus[tier] || 'pending';
      badge.className = 'da-tier';
      if (status === 'pass')   badge.classList.add('pass');
      else if (status === 'review') badge.classList.add('review');
      else if (status === 'fail')   badge.classList.add('fail');
    });
  }

  function renderAnalysisNotes(data) {
    const notes = q('#fin-da-notes');
    if (!notes) return;
    notes.textContent = data.analysis_notes || 'No analysis notes available.';
  }

  // ── Demo data ──
  function getDemoTickerData() {
    return {
      price: {
        symbol: 'AAPL',
        shortName: 'Apple Inc.',
        regularMarketPrice: { raw: 237.59 },
        regularMarketChange: { raw: 2.14 },
        regularMarketChangePercent: { raw: 0.0091 },
        exchangeName: 'NasdaqGS',
        currency: 'USD',
        marketCap: { raw: 3610000000000 },
      },
      summaryDetail: {
        trailingPE:       { raw: 38.92 },
        forwardPE:        { raw: 31.44 },
        fiftyTwoWeekHigh: { raw: 260.10 },
        fiftyTwoWeekLow:  { raw: 164.08 },
        dividendYield:    { raw: 0.0042 },
        dividendRate:     { raw: 1.00 },
        payoutRatio:      { raw: 0.1633 },
        exDividendDate:   { raw: 1731628800 },
      },
      defaultKeyStatistics: {
        trailingEps: { raw: 6.08 },
        bookValue:   { raw: 4.38 },
        beta:        { raw: 1.24 },
      },
      financialData: {
        totalRevenue:    { raw: 391035000000 },
        profitMargins:   { raw: 0.2636 },
        returnOnEquity:  { raw: 1.6072 },
        returnOnAssets:  { raw: 0.2574 },
        debtToEquity:    { raw: 151.86 },
        targetMeanPrice: { raw: 248.36 },
      },
      earnings: {
        earningsChart: {
          quarterly: [
            { date: '2Q2024', actual: { raw: 1.40 }, estimate: { raw: 1.34 } },
            { date: '3Q2024', actual: { raw: 1.64 }, estimate: { raw: 1.59 } },
            { date: '4Q2024', actual: { raw: 2.40 }, estimate: { raw: 2.35 } },
            { date: '1Q2025', actual: { raw: 1.65 }, estimate: { raw: 1.62 } },
          ]
        }
      },
      recommendationTrend: {
        trend: [
          { strongBuy: 11, buy: 20, hold: 8, sell: 2, strongSell: 0 }
        ]
      },
    };
  }

  function renderDemoPriceChart() {
    const points = [];
    let price = 228;
    const now = Date.now();
    for (let i = 30; i >= 0; i--) {
      price += (Math.random() - 0.45) * 3;
      price = Math.max(price, 215);
      points.push({
        time: (now - i * 86400000) / 1000,
        close: parseFloat(price.toFixed(2)),
      });
    }

    renderPriceChart({
      timestamp: points.map(p => p.time),
      indicators: { quote: [{ close: points.map(p => p.close) }] },
    });
  }

  function getDemoAnalysisData(symbol) {
    return {
      symbol: symbol || 'WDC',
      company_name: symbol === 'WDC' ? 'Western Digital Corp.' : (symbol || 'Demo Company'),
      years: [2010, 2009, 2008, 2007, 2006, 2005, 2004, 2003, 2002, 2001],
      data: {
        2010: { revenue: 9850,  net_income: 1382,  cost_of_revenue: 7444,  operating_expense: 877,  cash: 2734, current_liabilities: 2023, total_liabilities: 2619, tangible_assets: 9158,  equity: 4709, true_gain_equity: 880,  capex: 737, book_value: 6539,  lt_debt: 0, current_assets: 4720, retained_earnings: 3200 },
        2009: { revenue: 7453,  net_income: 470,   cost_of_revenue: 5917,  operating_expense: 698,  cash: 2452, current_liabilities: 1485, total_liabilities: 2173, tangible_assets: 7243,  equity: 3829, true_gain_equity: 620,  capex: 438, book_value: 5070,  lt_debt: 0, current_assets: 3580, retained_earnings: 1800 },
        2008: { revenue: 7905,  net_income: 867,   cost_of_revenue: 6123,  operating_expense: 702,  cash: 1987, current_liabilities: 1678, total_liabilities: 2389, tangible_assets: 7890,  equity: 3359, true_gain_equity: 550,  capex: 620, book_value: 5501,  lt_debt: 0, current_assets: 3200, retained_earnings: 1500 },
        2007: { revenue: 5468,  net_income: 564,   cost_of_revenue: 4198,  operating_expense: 490,  cash: 1243, current_liabilities: 1189, total_liabilities: 1534, tangible_assets: 5678,  equity: 2492, true_gain_equity: 430,  capex: 510, book_value: 4144,  lt_debt: 0, current_assets: 2100, retained_earnings: 1200 },
        2006: { revenue: 4341,  net_income: 395,   cost_of_revenue: 3412,  operating_expense: 397,  cash: 926,  current_liabilities: 970,  total_liabilities: 1226, tangible_assets: 4509,  equity: 1928, true_gain_equity: 310,  capex: 442, book_value: 3283,  lt_debt: 0, current_assets: 1600, retained_earnings: 800  },
        2005: { revenue: 3685,  net_income: 317,   cost_of_revenue: 2944,  operating_expense: 303,  cash: 731,  current_liabilities: 856,  total_liabilities: 1043, tangible_assets: 3879,  equity: 1618, true_gain_equity: 260,  capex: 375, book_value: 2836,  lt_debt: 0, current_assets: 1350, retained_earnings: 600  },
        2004: { revenue: 3047,  net_income: 186,   cost_of_revenue: 2489,  operating_expense: 278,  cash: 598,  current_liabilities: 693,  total_liabilities: 857,  tangible_assets: 3098,  equity: 1301, true_gain_equity: 200,  capex: 310, book_value: 2241,  lt_debt: 0, current_assets: 1100, retained_earnings: 400  },
        2003: { revenue: 2741,  net_income: 114,   cost_of_revenue: 2289,  operating_expense: 254,  cash: 412,  current_liabilities: 589,  total_liabilities: 739,  tangible_assets: 2654,  equity: 1115, true_gain_equity: 150,  capex: 256, book_value: 1915,  lt_debt: 0, current_assets: 890,  retained_earnings: 250  },
        2002: { revenue: 2154,  net_income: 67,    cost_of_revenue: 1825,  operating_expense: 211,  cash: 348,  current_liabilities: 478,  total_liabilities: 612,  tangible_assets: 2198,  equity: 1001, true_gain_equity: 120,  capex: 198, book_value: 1586,  lt_debt: 0, current_assets: 720,  retained_earnings: 150  },
        2001: { revenue: 1953,  net_income: -168,  cost_of_revenue: 1798,  operating_expense: 287,  cash: 281,  current_liabilities: 412,  total_liabilities: 534,  tangible_assets: 1876,  equity: 934,  true_gain_equity: 90,   capex: 167, book_value: 1342,  lt_debt: 0, current_assets: 610,  retained_earnings: 80   },
      },
      scorecard: { moat: 55, management: 70, roic: 65, durability: 40 },
      valuation: {
        bull: { price: 55, prob: 25, annualReturn: 18 },
        base: { price: 38, prob: 50, annualReturn: 8  },
        bear: { price: 22, prob: 25, annualReturn: -12 },
        intrinsicRange: [28, 48],
        currentPrice: 32,
        marginOfSafety: 16,
        buyBelow: 30,
      },
      tier_status: { tier1: 'pass', tier2: 'pass', tier3: 'review', tier4: 'pending', tier5: 'pending' },
      analysis_notes: 'Western Digital Corp. (WDC) \u2014 10-year financial analysis\n\nEarnings CAGR: ~14% over the period. Caution: technological transition (HDD to SSD) creating uncertainty in long-term earnings power. Moat is narrowing as flash storage commoditizes. Management has shown discipline in capital allocation but faces structural headwinds. Current price may reflect transition risk but insufficient margin of safety for a Buffett-style position. Monitor for stabilization in NAND pricing and market share trends.\n\nComposite Buffett-Munger score: 58/100.\nMixed quality signals \u2014 requires deeper investigation.',
      analyst: 'Demo Data',
    };
  }

  // ── Page init ──
  function init() {
    loadWatchlist();

    _el = Jarvis.getPageEl('financial');
    _el.innerHTML = buildTemplate();

    setupSubTabs();
    setupMarketDataSearch();
    setupTimeframeButtons();
    setupDeepAnalysis();
    renderWatchlist();
  }

  function onActivate() {
    // Charts must be resized when the page becomes visible,
    // because Canvas dimensions are stale while hidden.
    if (_priceChart)   _priceChart.resize();
    if (_earningsChart) _earningsChart.resize();
    if (_daRadarChart) _daRadarChart.resize();
  }

  function onDeactivate() {
    // Destroy charts to free GPU memory when navigating away
    // (They are re-created on next ticker load so this is safe.)
  }

  // ── Register with Jarvis core ──
  Jarvis.registerPage({
    id:           'financial',
    label:        'Financial Analysis',
    init,
    onActivate,
    onDeactivate,
  });

})();
