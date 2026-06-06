// Test setup — provides minimal DOM shell, Chart.js mock, and fetch mock
import { vi } from 'vitest';
import { Chart } from './chart-mock.js';

export function setupDOM() {
  // Plan 2026-06-05-002 F002 — match the real index.html shell (DontPanic brand +
  // project-selector container) so tests exercise real header/selector/page chrome
  // instead of a stale fake that drifted on brand + structure.
  document.body.innerHTML = `
    <a href="#main" class="skip-link">Skip to content</a>
    <header>
      <div class="header-left"><h1>DontPanic</h1></div>
      <div class="header-right">
        <span id="sync-status" class="status-badge idle">Checking...</span>
        <span id="clock"></span>
      </div>
    </header>
    <div id="project-selector-container" class="project-selector-bar"></div>
    <nav class="view-nav" id="view-nav"></nav>
    <main id="main"><div id="page-container"></div></main>
    <footer>
      <span>DontPanic v1.0</span>
      <span id="last-sync">Last sync: --</span>
    </footer>
  `;
}

export function setupChartMock() {
  Chart.reset();
  globalThis.Chart = Chart;
  return Chart;
}

export function setupFetchMock(fixtures = {}) {
  const mockFetch = vi.fn(async (url) => {
    const name = url.replace(/.*\//, '').replace('.json', '');
    if (fixtures[name]) {
      return {
        ok: true,
        json: async () => fixtures[name],
      };
    }
    return { ok: false, status: 404 };
  });
  globalThis.fetch = mockFetch;
  return mockFetch;
}

export function setupLocalStorageMock() {
  const store = {};
  const mock = {
    getItem: vi.fn((key) => store[key] ?? null),
    setItem: vi.fn((key, val) => { store[key] = String(val); }),
    removeItem: vi.fn((key) => { delete store[key]; }),
    clear: vi.fn(() => { Object.keys(store).forEach(k => delete store[k]); }),
    get length() { return Object.keys(store).length; },
    key: vi.fn((i) => Object.keys(store)[i] ?? null),
  };
  globalThis.localStorage = mock;
  return mock;
}

export function createMockState(overrides = {}) {
  return {
    agents: overrides.agents || [
      { id: 'claude', name: 'Claude Code', role: 'Primary AI Harness', status: 'online', currentTask: 'Building tests', lastSeen: new Date().toISOString(), tokensUsed: 250000, tokenBudget: 1000000 },
      { id: 'codex', name: 'Codex CLI', role: 'OpenAI Agent', status: 'offline', currentTask: null, lastSeen: null, tokensUsed: 0, tokenBudget: 500000 },
    ],
    tasks: overrides.tasks || [
      { id: 't1', title: 'Build dashboard', project: 'infra', status: 'in_progress', priority: 'high', agent: 'claude', created: '2026-03-22T20:00:00Z' },
      { id: 't2', title: 'Write tests', project: 'infra', status: 'todo', priority: 'medium', agent: null, created: '2026-03-22T21:00:00Z' },
      { id: 't3', title: 'Deploy staging', project: 'styln', status: 'done', priority: 'low', agent: 'claude', created: '2026-03-22T19:00:00Z' },
    ],
    activity: overrides.activity || [
      { type: 'task', text: 'Dashboard created', agent: 'claude', timestamp: '2026-03-22T21:00:00Z' },
      { type: 'deploy', text: 'Deployed to staging', agent: 'claude', timestamp: '2026-03-22T20:00:00Z' },
    ],
    costs: overrides.costs || {
      generated: '2026-03-22T21:00:00Z',
      totals: { 'Styln': 234.56, 'Spin & Dine': 45.67, 'QuantRE/Axiom': 12.34, 'Total': 292.57 },
      breakdown: [
        { app: 'Styln', project: '<glam-firebase-project-id>', service: 'Cloud Functions', cost: 120.00, credits: -10.00, netCost: 110.00 },
        { app: 'Styln', project: '<glam-firebase-project-id>', service: 'Firestore', cost: 80.00, credits: 0, netCost: 80.00 },
      ],
      trend: [
        { month: '2025-10', Styln: 200, 'Spin & Dine': 40, 'QuantRE/Axiom': 10, total: 250 },
        { month: '2025-11', Styln: 220, 'Spin & Dine': 42, 'QuantRE/Axiom': 11, total: 273 },
      ],
    },
    security: overrides.security || [
      { action: 'block', category: 'file_write', agent: 'claude', timestamp: '2026-03-22T21:00:00Z', details: 'Blocked rm -rf /', severity: 'high' },
      { action: 'log', category: 'git_push', agent: 'claude', timestamp: '2026-03-22T20:30:00Z', details: 'Logged git push to main', severity: 'medium' },
      { action: 'require_approval', category: 'api_call', agent: 'codex', timestamp: '2026-03-22T20:00:00Z', details: 'Required approval for external API', severity: 'low' },
    ],
  };
}
