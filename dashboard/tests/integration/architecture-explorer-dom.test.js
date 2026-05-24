// F003 DOM-side integration tests for the Architecture explorer.
//
// Covers acceptance items: flow selection highlights nodes/edges,
// non-selected dims (does not hide), numbered step markers appear on
// the canvas, clear-selection works, search/filters apply visibility
// classes, click-to-detail opens the side panel, reset returns to
// neutral. Runs the real `pages/architecture/architecture.js` module
// against the F002 fixture via the same jsdom shell the F002 tests
// already use.

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

function bootWithFixture() {
  page.init({ architectureViewState: fixture, selectedProject: 'all' });
  return jarvisShim.getPageEl('architecture');
}

describe('explorer render', () => {
  it('renders the SVG canvas with one <g.arch-node> per fixture node', () => {
    const el = bootWithFixture();
    const nodes = el.querySelectorAll('.arch-node');
    expect(nodes.length).toBe(fixture.nodes.length);
    const edges = el.querySelectorAll('.arch-edge');
    expect(edges.length).toBe(fixture.edges.length);
    expect(el.querySelector('[data-canvas]')).not.toBeNull();
    expect(el.querySelector('[data-flow-rail]')).not.toBeNull();
  });

  it('exposes the persistent legend on every render (acceptance #5)', () => {
    const el = bootWithFixture();
    expect(el.querySelector('[data-legend]')).not.toBeNull();
    expect(el.querySelector('[data-legend-type="module"]')).not.toBeNull();
    expect(el.querySelector('[data-legend-edge="import"]')).not.toBeNull();
  });

  it('renders a flow row per flow with clear-selection initially hidden', () => {
    const el = bootWithFixture();
    expect(el.querySelectorAll('[data-arch-flow]').length).toBe(fixture.flows.length);
    expect(el.querySelector('[data-arch-flow-clear]').hidden).toBe(true);
  });
});

describe('flow selection — highlight + dim (acceptance #2, #3)', () => {
  it('selecting a flow marks participating nodes selected and dims the rest', () => {
    const el = bootWithFixture();
    const flowBtn = el.querySelector('[data-arch-flow="flow:architecture-regen"]');
    expect(flowBtn).not.toBeNull();
    flowBtn.click();

    const selectedNodes = el.querySelectorAll('.arch-node.is-selected');
    const dimmedNodes = el.querySelectorAll('.arch-node.is-dimmed');
    expect(selectedNodes.length).toBeGreaterThan(0);
    expect(dimmedNodes.length).toBeGreaterThan(0);
    // Non-selected nodes dim but stay in the DOM — acceptance #3 says
    // they must not be hidden when a flow is selected.
    expect(dimmedNodes[0].style.display).not.toBe('none');
    expect(dimmedNodes[0].classList.contains('is-filtered-out')).toBe(false);
  });

  it('renders numbered step markers above the flow path nodes', () => {
    const el = bootWithFixture();
    el.querySelector('[data-arch-flow="flow:architecture-regen"]').click();
    const markers = el.querySelectorAll('[data-step-markers] .arch-step-marker');
    expect(markers.length).toBe(2); // two steps in the regen flow fixture
    const orders = [...markers].map((m) => m.dataset.stepOrder).sort();
    expect(orders).toEqual(['1', '2']);
  });

  it('renders the step inspector with rows ordered by step.order', () => {
    const el = bootWithFixture();
    el.querySelector('[data-arch-flow="flow:architecture-regen"]').click();
    const inspector = el.querySelector('[data-step-inspector]');
    expect(inspector.hidden).toBe(false);
    const rows = el.querySelectorAll('[data-step-list] .arch-step-row');
    expect(rows.length).toBe(2);
    expect(rows[0].dataset.stepOrder).toBe('1');
    expect(rows[1].dataset.stepOrder).toBe('2');
  });

  it('clear-selection returns to neutral state (acceptance #4)', () => {
    const el = bootWithFixture();
    el.querySelector('[data-arch-flow="flow:architecture-regen"]').click();
    expect(el.querySelectorAll('.arch-node.is-selected').length).toBeGreaterThan(0);

    el.querySelector('[data-arch-flow-clear]').click();
    expect(el.querySelectorAll('.arch-node.is-selected').length).toBe(0);
    expect(el.querySelectorAll('.arch-node.is-dimmed').length).toBe(0);
    expect(el.querySelector('[data-arch-flow-clear]').hidden).toBe(true);
    expect(el.querySelector('[data-step-inspector]').hidden).toBe(true);
  });

  it('clicking the active flow toggles selection off', () => {
    const el = bootWithFixture();
    const btn = el.querySelector('[data-arch-flow="flow:architecture-regen"]');
    btn.click();
    expect(btn.getAttribute('aria-pressed')).toBe('true');
    btn.click();
    expect(btn.getAttribute('aria-pressed')).toBe('false');
    expect(el.querySelectorAll('.arch-node.is-selected').length).toBe(0);
  });

  it('selecting a flow whose references are broken does not crash (acceptance #5)', () => {
    const el = bootWithFixture();
    expect(() => {
      el.querySelector('[data-arch-flow="flow:authored-broken"]').click();
    }).not.toThrow();
    // The selected flow row should still be marked, the step inspector
    // visible, and the validation warnings panel still rendered.
    expect(el.querySelector('[data-arch-flow="flow:authored-broken"]').classList.contains('is-selected')).toBe(true);
    expect(el.querySelector('[data-warnings="1"]')).not.toBeNull();
  });
});

describe('search + filters (acceptance #6, #7)', () => {
  it('search input filters visible nodes by id, title, or source path', () => {
    const el = bootWithFixture();
    const input = el.querySelector('[data-arch-search]');
    expect(input).not.toBeNull();
    input.value = 'supervisor';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    const visible = [...el.querySelectorAll('.arch-node')].filter((n) => !n.classList.contains('is-filtered-out'));
    const filteredOut = [...el.querySelectorAll('.arch-node')].filter((n) => n.classList.contains('is-filtered-out'));
    expect(visible.length).toBeGreaterThan(0);
    expect(filteredOut.length).toBeGreaterThan(0);
    expect(visible.every((n) => n.dataset.nodeId.toLowerCase().includes('supervisor'))).toBe(true);
  });

  it('type filter hides nodes whose type checkbox is unchecked (acceptance #7 — filter #1)', () => {
    const el = bootWithFixture();
    const moduleBox = el.querySelector('[data-arch-filter="type"][value="module"]');
    moduleBox.checked = false;
    moduleBox.dispatchEvent(new Event('change', { bubbles: true }));
    const modules = [...el.querySelectorAll('.arch-node[data-node-type="module"]')];
    expect(modules.length).toBeGreaterThan(0);
    expect(modules.every((n) => n.classList.contains('is-filtered-out'))).toBe(true);
    // Commands remain visible.
    const cmds = [...el.querySelectorAll('.arch-node[data-node-type="command"]')];
    expect(cmds.every((n) => !n.classList.contains('is-filtered-out'))).toBe(true);
  });

  it('lane filter hides nodes by lane id (acceptance #7 — filter #2)', () => {
    const el = bootWithFixture();
    const laneBox = el.querySelector('[data-arch-filter="lane"][value="lane:orchestrator-runtime"]');
    laneBox.checked = false;
    laneBox.dispatchEvent(new Event('change', { bubbles: true }));
    const inLane = [...el.querySelectorAll('.arch-node[data-lane-id="lane:orchestrator-runtime"]')];
    expect(inLane.length).toBeGreaterThan(0);
    expect(inLane.every((n) => n.classList.contains('is-filtered-out'))).toBe(true);
  });

  it('edge filter hides edges by type (acceptance #7 — filter #3)', () => {
    const el = bootWithFixture();
    const edgeBox = el.querySelector('[data-arch-filter="edge"][value="import"]');
    edgeBox.checked = false;
    edgeBox.dispatchEvent(new Event('change', { bubbles: true }));
    const imports = [...el.querySelectorAll('.arch-edge[data-edge-type="import"]')];
    expect(imports.length).toBeGreaterThan(0);
    expect(imports.every((e) => e.classList.contains('is-filtered-out'))).toBe(true);
  });
});

describe('detail panel (acceptance #8)', () => {
  it('clicking a node opens the side panel without navigation loss', () => {
    const el = bootWithFixture();
    const detail = el.querySelector('[data-detail-panel]');
    expect(detail.hidden).toBe(true);
    const node = el.querySelector('.arch-node');
    node.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(detail.hidden).toBe(false);
    expect(detail.dataset.nodeId).toBe(node.dataset.nodeId);
    // Stays on the architecture page — page-view container is unchanged.
    expect(document.getElementById('page-architecture')).toBe(el);
  });

  it('closes when the close button is clicked', () => {
    const el = bootWithFixture();
    const node = el.querySelector('.arch-node');
    node.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    el.querySelector('[data-arch-detail-close]').click();
    expect(el.querySelector('[data-detail-panel]').hidden).toBe(true);
  });

  it('keyboard activation (Enter) opens detail (acceptance #8 — keyboard)', () => {
    const el = bootWithFixture();
    const node = el.querySelector('.arch-node');
    node.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(el.querySelector('[data-detail-panel]').hidden).toBe(false);
  });
});

describe('zoom + reset (acceptance #9)', () => {
  it('zoom-in shrinks the canvas viewBox', () => {
    const el = bootWithFixture();
    const canvas = el.querySelector('[data-canvas]');
    const original = canvas.getAttribute('viewBox');
    el.querySelector('[data-arch-zoom="in"]').click();
    expect(canvas.getAttribute('viewBox')).not.toBe(original);
    expect(canvas.dataset.zoom).not.toBe('1');
  });

  it('reset returns to original viewBox and clears selection/filter state', () => {
    const el = bootWithFixture();
    // Stir state: select a flow, type into search, uncheck a filter, zoom in.
    el.querySelector('[data-arch-flow="flow:architecture-regen"]').click();
    const search = el.querySelector('[data-arch-search]');
    search.value = 'supervisor';
    search.dispatchEvent(new Event('input', { bubbles: true }));
    const moduleBox = el.querySelector('[data-arch-filter="type"][value="module"]');
    moduleBox.checked = false;
    moduleBox.dispatchEvent(new Event('change', { bubbles: true }));
    el.querySelector('[data-arch-zoom="in"]').click();

    el.querySelector('[data-arch-reset]').click();

    expect(el.querySelectorAll('.arch-node.is-selected').length).toBe(0);
    expect(el.querySelectorAll('.arch-node.is-dimmed').length).toBe(0);
    expect(el.querySelectorAll('.arch-node.is-filtered-out').length).toBe(0);
    expect(el.querySelector('[data-arch-search]').value).toBe('');
    expect(moduleBox.checked).toBe(true);
    // ViewBox is restored to the original via the data-original-viewbox cache.
    const canvas = el.querySelector('[data-canvas]');
    expect(canvas.getAttribute('viewBox')).toBe(canvas.getAttribute('data-original-viewbox'));
  });
});

describe('pan navigation (acceptance #9 — large graph)', () => {
  function parseViewBox(canvas) {
    return canvas.getAttribute('viewBox').split(/\s+/).map(Number);
  }

  it('exposes the canvas wrap as a focusable pan target', () => {
    const el = bootWithFixture();
    const wrap = el.querySelector('[data-canvas-wrap]');
    expect(wrap).not.toBeNull();
    expect(wrap.getAttribute('tabindex')).toBe('0');
  });

  it('mouse drag pans the viewBox', () => {
    const el = bootWithFixture();
    const wrap = el.querySelector('[data-canvas-wrap]');
    const canvas = el.querySelector('[data-canvas]');
    canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 520, right: 800, bottom: 520, x: 0, y: 0, toJSON: () => '' });
    const before = parseViewBox(canvas);

    wrap.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: 400, clientY: 260, button: 0 }));
    wrap.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: 300, clientY: 200, button: 0 }));
    wrap.dispatchEvent(new MouseEvent('mouseup',   { bubbles: true, clientX: 300, clientY: 200, button: 0 }));

    const after = parseViewBox(canvas);
    // Dragging cursor to the left (clientX decreased) should shift the
    // viewBox X to the right (content scrolls left into view).
    expect(after[0]).not.toBe(before[0]);
    expect(after[0]).toBeGreaterThan(before[0]);
    expect(after[1]).toBeGreaterThan(before[1]);
  });

  it('drag swallows the trailing click so node detail does not open', () => {
    const el = bootWithFixture();
    const wrap = el.querySelector('[data-canvas-wrap]');
    const node = el.querySelector('.arch-node');
    const canvas = el.querySelector('[data-canvas]');
    canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 520, right: 800, bottom: 520, x: 0, y: 0, toJSON: () => '' });
    expect(el.querySelector('[data-detail-panel]').hidden).toBe(true);

    // Drag starts on the node, moves >> threshold, releases.
    node.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: 100, clientY: 100, button: 0 }));
    node.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: 250, clientY: 180, button: 0 }));
    node.dispatchEvent(new MouseEvent('mouseup',   { bubbles: true, clientX: 250, clientY: 180, button: 0 }));
    // The browser fires a click after mouseup — simulate it on the node.
    node.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 250, clientY: 180, button: 0 }));

    expect(el.querySelector('[data-detail-panel]').hidden).toBe(true);
  });

  it('arrow keys pan the viewBox when the canvas wrap has focus', () => {
    const el = bootWithFixture();
    const wrap = el.querySelector('[data-canvas-wrap]');
    const canvas = el.querySelector('[data-canvas]');
    const before = parseViewBox(canvas);
    wrap.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    const right = parseViewBox(canvas);
    expect(right[0]).toBeGreaterThan(before[0]);
    wrap.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    const down = parseViewBox(canvas);
    expect(down[1]).toBeGreaterThan(right[1]);
  });

  it('wheel zooms the viewBox (wheel up = zoom in)', () => {
    const el = bootWithFixture();
    const wrap = el.querySelector('[data-canvas-wrap]');
    const canvas = el.querySelector('[data-canvas]');
    const before = parseViewBox(canvas);
    wrap.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: -120 }));
    const after = parseViewBox(canvas);
    // Zoom in shrinks the viewBox dimensions.
    expect(after[2]).toBeLessThan(before[2]);
    expect(after[3]).toBeLessThan(before[3]);
    expect(Number(canvas.dataset.zoom)).toBeGreaterThan(1);
  });

  it('arrow keys typed inside the search input do NOT pan the map', () => {
    const el = bootWithFixture();
    const search = el.querySelector('[data-arch-search]');
    const canvas = el.querySelector('[data-canvas]');
    const before = parseViewBox(canvas);
    search.focus();
    search.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    const after = parseViewBox(canvas);
    expect(after).toEqual(before);
  });
});

describe('deterministic layout snapshot (acceptance #10)', () => {
  it('produces the same node positions across renders (regression snapshot ready)', () => {
    const el = bootWithFixture();
    const first = [...el.querySelectorAll('.arch-node-bg')].map((r) => ({
      id: r.parentElement.dataset.nodeId,
      x: r.getAttribute('x'),
      y: r.getAttribute('y'),
    }));
    bootWithFixture();
    const second = [...document.getElementById('page-architecture').querySelectorAll('.arch-node-bg')].map((r) => ({
      id: r.parentElement.dataset.nodeId,
      x: r.getAttribute('x'),
      y: r.getAttribute('y'),
    }));
    expect(second).toEqual(first);
  });
});
