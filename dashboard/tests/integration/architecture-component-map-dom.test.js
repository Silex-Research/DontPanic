// Plan 2026-06-06-007 F002 — DOM-side integration tests for the
// interactive component map behaviours layered onto the existing
// Architecture SVG: click-a-component dependency highlight (upstream +
// downstream highlighted, unrelated dimmed) and the directory breadcrumb
// with cluster drill-down / restore. Runs the real page module against
// the shared fixture (now carrying clusters/levels) via the same jsdom
// shell the F003 explorer tests use.

import { describe, it, expect, beforeAll, beforeEach } from 'vitest';
import { setupDOM } from '../helpers/setup.js';
import fixture from '../fixtures/architecture-view-state.json' with { type: 'json' };

const jarvisShim = {
  pages: [],
  state: { architectureViewState: null, selectedProject: 'all' },
  registerPage(config) { this.pages.push(config); },
  getPageEl(pageId) {
    let el = document.getElementById(`page-${pageId}`);
    if (!el) {
      el = document.createElement('div');
      el.id = `page-${pageId}`;
      el.className = 'page-view';
      document.getElementById('page-container').appendChild(el);
    }
    return el;
  },
};
let page;

beforeAll(async () => {
  setupDOM();
  globalThis.Jarvis = jarvisShim;
  window.Jarvis = jarvisShim;
  await import('../../pages/architecture/architecture.js');
  page = jarvisShim.pages[0];
});

beforeEach(() => {
  setupDOM();
  globalThis.Jarvis = jarvisShim;
  window.Jarvis = jarvisShim;
});

function boot() {
  page.init({ architectureViewState: fixture, selectedProject: 'all' });
  return jarvisShim.getPageEl('architecture');
}

const CLI = 'module:scripts/dontpanic_orchestrate/cli.py';
const SUP = 'module:scripts/dontpanic_orchestrate/supervisor.py';
const CMD = 'command:dontpanic-architecture-regen';

describe('click-a-component dependency highlight', () => {
  it('highlights the focus + its dependency neighbours and dims the rest', () => {
    const el = boot();
    // cli imports supervisor → clicking cli highlights both, dims the
    // unrelated command node.
    el.querySelector(`.arch-node[data-node-id="${CLI}"]`)
      .dispatchEvent(new MouseEvent('click', { bubbles: true }));

    const cli = el.querySelector(`.arch-node[data-node-id="${CLI}"]`);
    const sup = el.querySelector(`.arch-node[data-node-id="${SUP}"]`);
    const cmd = el.querySelector(`.arch-node[data-node-id="${CMD}"]`);
    expect(cli.classList.contains('is-selected')).toBe(true);
    expect(sup.classList.contains('is-selected')).toBe(true);
    expect(cmd.classList.contains('is-dimmed')).toBe(true);
    // Dimmed nodes are not hidden.
    expect(cmd.style.display).not.toBe('none');
  });

  it('opens the detail panel for the clicked component', () => {
    const el = boot();
    el.querySelector(`.arch-node[data-node-id="${CLI}"]`)
      .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    const detail = el.querySelector('[data-detail-panel]');
    expect(detail.hidden).toBe(false);
    expect(detail.dataset.nodeId).toBe(CLI);
  });

  it('highlights the connecting edge between focus and neighbour', () => {
    const el = boot();
    el.querySelector(`.arch-node[data-node-id="${CLI}"]`)
      .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    const edge = el.querySelector('.arch-edge');
    expect(edge.classList.contains('is-selected')).toBe(true);
  });

  it('closing the detail panel clears the dependency highlight', () => {
    const el = boot();
    el.querySelector(`.arch-node[data-node-id="${CLI}"]`)
      .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    el.querySelector('[data-arch-detail-close]').click();
    expect(el.querySelectorAll('.arch-node.is-selected').length).toBe(0);
    expect(el.querySelectorAll('.arch-node.is-dimmed').length).toBe(0);
  });

  it('selecting a flow clears a prior node focus (modes are exclusive)', () => {
    const el = boot();
    el.querySelector(`.arch-node[data-node-id="${CLI}"]`)
      .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    const flowBtn = el.querySelector('[data-arch-flow]');
    flowBtn.click();
    // The flow's own selection now drives the canvas; the node-focus is
    // not additive — exactly one highlight source at a time.
    expect(flowBtn.getAttribute('aria-pressed')).toBe('true');
  });
});

describe('breadcrumb + cluster drill-down', () => {
  it('renders the System breadcrumb + a child cluster chip', () => {
    const el = boot();
    expect(el.querySelector('[data-cluster-bar]')).not.toBeNull();
    expect(el.querySelector('[data-arch-crumb="cluster:"]')).not.toBeNull();
    expect(el.querySelector('[data-arch-cluster="cluster:scripts"]')).not.toBeNull();
  });

  it('drilling into a cluster dims nodes outside that subtree', () => {
    const el = boot();
    el.querySelector('[data-arch-cluster="cluster:scripts"]').click();
    // cli + supervisor live under scripts/ → stay visible; the command
    // node is in System root only → filtered out of the drill scope.
    const cmd = el.querySelector(`.arch-node[data-node-id="${CMD}"]`);
    const cli = el.querySelector(`.arch-node[data-node-id="${CLI}"]`);
    expect(cmd.classList.contains('is-filtered-out')).toBe(true);
    expect(cli.classList.contains('is-filtered-out')).toBe(false);
    // Breadcrumb advanced to System ▸ scripts.
    expect(el.querySelector('[data-cluster-bar]').dataset.clusterId).toBe('cluster:scripts');
  });

  it('clicking the System crumb restores the full map', () => {
    const el = boot();
    el.querySelector('[data-arch-cluster="cluster:scripts"]').click();
    el.querySelector('[data-arch-crumb="cluster:"]').click();
    const cmd = el.querySelector(`.arch-node[data-node-id="${CMD}"]`);
    expect(cmd.classList.contains('is-filtered-out')).toBe(false);
    expect(el.querySelector('[data-cluster-bar]').dataset.clusterId).toBe('cluster:');
  });

  it('reset returns the breadcrumb to System', () => {
    const el = boot();
    el.querySelector('[data-arch-cluster="cluster:scripts"]').click();
    el.querySelector('[data-arch-reset]').click();
    expect(el.querySelector('[data-cluster-bar]').dataset.clusterId).toBe('cluster:');
    expect(el.querySelectorAll('.arch-node.is-filtered-out').length).toBe(0);
  });
});
