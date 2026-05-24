// ── Architecture Page Module ──
// Plan 2026-05-24-002 F003 — interactive swimlane explorer.
//
// The page registers itself with the dashboard router as `architecture`
// and reads `state.architectureViewState` (loaded by core.js from
// `dashboard/state/architecture-view-state.json`). The renderer in
// `lib/architecture-logic.js` produces the swimlane SVG, flow rail,
// step inspector, filter toolbar, legend, and detail panel as a pure
// HTML string. This module owns the DOM-side behavior: flow selection
// (highlight + dim), clear-selection, search filtering, lane/type/edge
// filter checkboxes, click-to-detail panel, hover (handled by native
// `<title>` elements on each node), zoom/pan, and the regen copy
// button.
//
// The page is read-only. Copy buttons write the raw command string to
// the clipboard so the operator runs `dontpanic architecture regen
// --with-html` themselves; the dashboard never auto-regenerates.

import {
  renderArchitectureHTML,
  renderNodeDetailHTML,
  renderStepInspectorHTML,
  resolveArchitectureEnvelope,
  normalizeEnvelope,
  getFlowParticipants,
  layoutArchitectureGraph,
  isMissingSelectedProject,
} from '../../lib/architecture-logic.js';
import { ALL_PROJECTS_VALUE } from '../../lib/project-selector-logic.js';

(() => {
  let _el = null;
  let _envelope = null; // normalized envelope (for interactions)
  let _layout = null;
  let _state = {
    flowId: null,
    search: '',
    filters: { type: null, lane: null, edge: null }, // null = all enabled
    zoom: 1,
    pan: { x: 0, y: 0 },
    detailNodeId: null,
  };
  let _delegateBound = false;
  let _drag = null; // active pan-drag: { startX, startY, startPanX, startPanY, vbW, vbH, rectW, rectH, moved }
  let _suppressNextClick = false;
  const PAN_KEY_STEP = 60; // viewBox units per arrow-key press
  const DRAG_THRESHOLD_PX = 3;

  function render(state) {
    if (!_el) return;
    const selected = state && typeof state.selectedProject === 'string'
      ? state.selectedProject
      : ALL_PROJECTS_VALUE;
    const byProject = state ? state.architectureViewStateByProject : null;
    const fleetSummary = state ? state.fleetSummary : null;
    const raw = resolveArchitectureEnvelope({
      selectedProject: selected,
      single: state ? state.architectureViewState : null,
      byProject,
    });
    // F004 finding #1: when a concrete project is selected and the
    // per-project cache is missing that entry, treat the envelope as
    // absent so interactions (flow selection, node-detail, layout) do
    // not fire against another project's data.
    const missingForProject = isMissingSelectedProject({
      selectedProject: selected,
      byProject,
    });
    _envelope = missingForProject ? null : normalizeEnvelope(raw);
    _layout = _envelope ? layoutArchitectureGraph(_envelope) : null;
    _el.innerHTML = renderArchitectureHTML(raw, {
      selectedProject: selected,
      byProject,
      fleetSummary,
    });
    // Reset interaction state — a new view-state envelope means the
    // previous selection/flow IDs are not guaranteed to exist anymore.
    _state = {
      flowId: null,
      search: '',
      filters: { type: null, lane: null, edge: null },
      zoom: 1,
      pan: { x: 0, y: 0 },
      detailNodeId: null,
    };
    // Stash original viewBox for reset.
    const canvas = _el.querySelector('[data-canvas]');
    if (canvas) {
      const vb = canvas.getAttribute('viewBox') || '';
      canvas.setAttribute('data-original-viewbox', vb);
    }
    attachHandlers();
  }

  // ── Selection / dimming ───────────────────────────────────────────

  function applySelection() {
    if (!_el) return;
    const flowId = _state.flowId;
    const canvas = _el.querySelector('[data-canvas]');
    if (!canvas) return;
    // Always reset selection classes first, then layer on the new state.
    canvas.querySelectorAll('.arch-node, .arch-edge').forEach((g) => {
      g.classList.remove('is-selected', 'is-dimmed');
    });
    canvas.querySelectorAll('[data-step-markers] *').forEach((n) => n.remove());

    const flowRail = _el.querySelector('[data-flow-rail]');
    if (flowRail) {
      flowRail.querySelectorAll('[data-arch-flow]').forEach((btn) => {
        btn.setAttribute('aria-pressed', 'false');
        btn.classList.remove('is-selected');
      });
    }
    const clearBtn = _el.querySelector('[data-arch-flow-clear]');
    const inspector = _el.querySelector('[data-step-inspector]');
    const stepList = _el.querySelector('[data-step-list]');
    if (!flowId) {
      if (clearBtn) clearBtn.hidden = true;
      if (inspector) inspector.hidden = true;
      if (stepList) stepList.innerHTML = '';
      return;
    }
    const { nodeIds, edgeIds, stepRefs } = getFlowParticipants(_envelope, flowId);
    const dimAll = nodeIds.size > 0 || edgeIds.size > 0;
    if (dimAll) {
      canvas.querySelectorAll('.arch-node').forEach((g) => {
        const id = g.dataset.nodeId;
        if (nodeIds.has(id)) g.classList.add('is-selected');
        else g.classList.add('is-dimmed');
      });
      canvas.querySelectorAll('.arch-edge').forEach((p) => {
        const id = p.dataset.edgeId;
        if (edgeIds.has(id)) {
          p.classList.add('is-selected');
        } else {
          p.classList.add('is-dimmed');
        }
      });
    }
    const markersGroup = canvas.querySelector('[data-step-markers]');
    if (markersGroup && _layout) {
      // Numbered step markers above each step's node.
      for (const step of stepRefs) {
        const nodeId = step.node_ref;
        const node = _layout.nodesById.get(nodeId);
        if (!node) continue;
        const ns = 'http://www.w3.org/2000/svg';
        const g = document.createElementNS(ns, 'g');
        g.setAttribute('class', 'arch-step-marker');
        g.setAttribute('data-step-id', step.id);
        g.setAttribute('data-step-order', String(step.order));
        const cx = node.x + node.w / 2;
        const cy = node.y - 10;
        const circle = document.createElementNS(ns, 'circle');
        circle.setAttribute('cx', String(cx));
        circle.setAttribute('cy', String(cy));
        circle.setAttribute('r', '11');
        circle.setAttribute('class', 'arch-step-marker-bg');
        g.appendChild(circle);
        const text = document.createElementNS(ns, 'text');
        text.setAttribute('x', String(cx));
        text.setAttribute('y', String(cy + 4));
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('class', 'arch-step-marker-text');
        text.textContent = String(step.order);
        g.appendChild(text);
        markersGroup.appendChild(g);
      }
    }
    if (flowRail) {
      const activeBtn = flowRail.querySelector(`[data-arch-flow="${cssEscape(flowId)}"]`);
      if (activeBtn) {
        activeBtn.setAttribute('aria-pressed', 'true');
        activeBtn.classList.add('is-selected');
      }
    }
    if (clearBtn) clearBtn.hidden = false;
    if (inspector) inspector.hidden = false;
    if (stepList) {
      stepList.innerHTML = renderStepInspectorHTML(_envelope, flowId);
    }
  }

  function setFlow(flowId) {
    _state.flowId = flowId;
    applySelection();
  }

  // ── Filter / search ───────────────────────────────────────────────

  function applyFilters() {
    if (!_el || !_envelope) return;
    const canvas = _el.querySelector('[data-canvas]');
    if (!canvas) return;
    const search = (_state.search || '').trim().toLowerCase();
    const typeFilter = _state.filters.type; // Set or null
    const laneFilter = _state.filters.lane;
    const edgeFilter = _state.filters.edge;
    const visibleNodeIds = new Set();
    canvas.querySelectorAll('.arch-node').forEach((g) => {
      const id = g.dataset.nodeId || '';
      const type = g.dataset.nodeType || '';
      const lane = g.dataset.laneId || '';
      const node = (_envelope.nodes || []).find((n) => n && n.id === id);
      const title = (node && typeof node.title === 'string') ? node.title.toLowerCase() : '';
      const source = (node && typeof node.source_path === 'string') ? node.source_path.toLowerCase() : '';
      const matchesType = typeFilter == null || typeFilter.has(type);
      const matchesLane = laneFilter == null || laneFilter.has(lane);
      const matchesSearch = search.length === 0
        || id.toLowerCase().includes(search)
        || title.includes(search)
        || source.includes(search);
      const visible = matchesType && matchesLane && matchesSearch;
      g.classList.toggle('is-filtered-out', !visible);
      if (visible) visibleNodeIds.add(id);
    });
    canvas.querySelectorAll('.arch-edge').forEach((p) => {
      const from = p.dataset.from || '';
      const to = p.dataset.to || '';
      const type = p.dataset.edgeType || '';
      const matchesType = edgeFilter == null || edgeFilter.has(type);
      const endpointsVisible = visibleNodeIds.has(from) && visibleNodeIds.has(to);
      p.classList.toggle('is-filtered-out', !(matchesType && endpointsVisible));
    });
  }

  function syncFilterStateFromDOM() {
    if (!_el) return;
    const collect = (kind) => {
      const boxes = _el.querySelectorAll(`[data-arch-filter="${kind}"]`);
      if (boxes.length === 0) return null;
      let allChecked = true;
      const enabled = new Set();
      boxes.forEach((b) => {
        if (b.checked) enabled.add(b.value);
        else allChecked = false;
      });
      return allChecked ? null : enabled;
    };
    _state.filters.type = collect('type');
    _state.filters.lane = collect('lane');
    _state.filters.edge = collect('edge');
  }

  // ── Zoom / pan ────────────────────────────────────────────────────

  function applyZoom() {
    if (!_el) return;
    const canvas = _el.querySelector('[data-canvas]');
    if (!canvas) return;
    const orig = canvas.getAttribute('data-original-viewbox') || canvas.getAttribute('viewBox');
    if (!orig) return;
    const parts = orig.split(/\s+/).map(Number);
    if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n))) return;
    const [, , w, h] = parts;
    const z = _state.zoom;
    // Lower viewBox dimensions = zoomed-in. Center the zoom on the
    // current pan position.
    const newW = w / z;
    const newH = h / z;
    const x = _state.pan.x;
    const y = _state.pan.y;
    canvas.setAttribute('viewBox', `${x} ${y} ${newW} ${newH}`);
    canvas.dataset.zoom = String(z);
  }

  function currentViewBoxDims() {
    if (!_el) return null;
    const canvas = _el.querySelector('[data-canvas]');
    if (!canvas) return null;
    const orig = canvas.getAttribute('data-original-viewbox') || canvas.getAttribute('viewBox');
    if (!orig) return null;
    const parts = orig.split(/\s+/).map(Number);
    if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n))) return null;
    const [, , w, h] = parts;
    const z = _state.zoom || 1;
    return { canvas, baseW: w, baseH: h, vbW: w / z, vbH: h / z };
  }

  function panBy(dxViewBox, dyViewBox) {
    const dims = currentViewBoxDims();
    if (!dims) return;
    _state.pan = {
      x: _state.pan.x + dxViewBox,
      y: _state.pan.y + dyViewBox,
    };
    applyZoom();
  }

  function startDrag(ev) {
    const dims = currentViewBoxDims();
    if (!dims) return;
    const rect = dims.canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    _drag = {
      startX: ev.clientX,
      startY: ev.clientY,
      startPanX: _state.pan.x,
      startPanY: _state.pan.y,
      vbW: dims.vbW,
      vbH: dims.vbH,
      rectW: rect.width,
      rectH: rect.height,
      moved: false,
    };
  }

  function continueDrag(ev) {
    if (!_drag) return;
    const dx = ev.clientX - _drag.startX;
    const dy = ev.clientY - _drag.startY;
    if (!_drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
    _drag.moved = true;
    // Drag right → content shifts right → viewBox x decreases.
    const vbDx = -dx * (_drag.vbW / _drag.rectW);
    const vbDy = -dy * (_drag.vbH / _drag.rectH);
    _state.pan = {
      x: _drag.startPanX + vbDx,
      y: _drag.startPanY + vbDy,
    };
    applyZoom();
    if (typeof ev.preventDefault === 'function') ev.preventDefault();
  }

  function endDrag() {
    if (!_drag) return;
    if (_drag.moved) _suppressNextClick = true;
    _drag = null;
  }

  function onWheel(ev) {
    if (!_el) return;
    const canvas = _el.querySelector('[data-canvas]');
    if (!canvas) return;
    const wrap = ev.target && typeof ev.target.closest === 'function'
      ? ev.target.closest('[data-canvas-wrap]')
      : null;
    if (!wrap) return;
    if (typeof ev.preventDefault === 'function') ev.preventDefault();
    const dy = typeof ev.deltaY === 'number' ? ev.deltaY : 0;
    if (dy === 0) return;
    const factor = dy < 0 ? 1.1 : 1 / 1.1;
    const next = _state.zoom * factor;
    _state.zoom = Math.max(0.5, Math.min(4, next));
    applyZoom();
  }

  function resetView() {
    _state.zoom = 1;
    _state.pan = { x: 0, y: 0 };
    _state.flowId = null;
    _state.search = '';
    _state.filters = { type: null, lane: null, edge: null };
    _state.detailNodeId = null;
    _drag = null;
    _suppressNextClick = false;
    if (_el) {
      const searchInput = _el.querySelector('[data-arch-search]');
      if (searchInput) searchInput.value = '';
      _el.querySelectorAll('[data-arch-filter]').forEach((b) => { b.checked = true; });
      const detail = _el.querySelector('[data-detail-panel]');
      if (detail) detail.hidden = true;
    }
    applyZoom();
    applyFilters();
    applySelection();
  }

  // ── Detail panel ──────────────────────────────────────────────────

  function showDetail(nodeId) {
    if (!_el || !_envelope) return;
    const panel = _el.querySelector('[data-detail-panel]');
    const body = _el.querySelector('[data-detail-body]');
    if (!panel || !body) return;
    body.innerHTML = renderNodeDetailHTML(_envelope, nodeId);
    panel.hidden = false;
    panel.dataset.nodeId = nodeId;
    _state.detailNodeId = nodeId;
  }

  function hideDetail() {
    if (!_el) return;
    const panel = _el.querySelector('[data-detail-panel]');
    if (panel) {
      panel.hidden = true;
      panel.removeAttribute('data-node-id');
    }
    _state.detailNodeId = null;
  }

  // ── Event delegation ──────────────────────────────────────────────

  function attachHandlers() {
    if (!_el) return;
    if (_delegateBound) return;
    _el.addEventListener('click', onClick);
    _el.addEventListener('keydown', onKeydown);
    _el.addEventListener('input', onInput);
    _el.addEventListener('change', onChange);
    _el.addEventListener('mousedown', onMouseDown);
    _el.addEventListener('mousemove', onMouseMove);
    _el.addEventListener('mouseup', onMouseUp);
    _el.addEventListener('mouseleave', onMouseUp);
    _el.addEventListener('wheel', onWheel, { passive: false });
    _delegateBound = true;
  }

  function onMouseDown(ev) {
    const t = ev.target;
    if (!t || typeof t.closest !== 'function') return;
    // Only drag-pan from the canvas wrap area. Allow drags that start on
    // empty SVG, lane backgrounds, edges, or nodes — the click-suppress
    // flag protects node click-to-detail from being triggered by a drag.
    if (!t.closest('[data-canvas-wrap]')) return;
    // Skip interactive controls inside the wrap (e.g. detail close).
    if (t.closest('[data-detail-panel]') || t.closest('button')) return;
    if (typeof ev.button === 'number' && ev.button !== 0) return;
    startDrag(ev);
  }

  function onMouseMove(ev) {
    if (!_drag) return;
    continueDrag(ev);
  }

  function onMouseUp() {
    endDrag();
  }

  function onClick(ev) {
    const t = ev.target;
    if (!t || typeof t.closest !== 'function') return;

    // If the user just finished a drag-pan, swallow the synthetic click
    // so it does not also open the detail panel for the node under the
    // cursor.
    if (_suppressNextClick) {
      _suppressNextClick = false;
      if (typeof ev.preventDefault === 'function') ev.preventDefault();
      if (typeof ev.stopPropagation === 'function') ev.stopPropagation();
      return;
    }

    // Copy command (preserve F002 behavior).
    const copyBtn = t.closest('.arch-copy-btn');
    if (copyBtn) {
      const cmd = copyBtn.dataset.command || '';
      const nav = (typeof navigator !== 'undefined') ? navigator : null;
      if (nav && nav.clipboard && typeof nav.clipboard.writeText === 'function') {
        nav.clipboard.writeText(cmd).then(() => {
          copyBtn.dataset.copied = '1';
          copyBtn.textContent = 'copied';
          setTimeout(() => {
            copyBtn.dataset.copied = '';
            copyBtn.textContent = 'copy';
          }, 1500);
        }).catch(() => {
          copyBtn.dataset.copied = 'denied';
        });
      } else {
        copyBtn.dataset.copied = 'unsupported';
      }
      return;
    }

    // Flow selection.
    const flowBtn = t.closest('[data-arch-flow]');
    if (flowBtn) {
      const flowId = flowBtn.dataset.archFlow;
      // Toggle off if clicking the active flow again.
      if (_state.flowId === flowId) setFlow(null);
      else setFlow(flowId);
      return;
    }

    // Clear-selection.
    if (t.closest('[data-arch-flow-clear]')) {
      setFlow(null);
      return;
    }

    // Zoom controls.
    const zoomBtn = t.closest('[data-arch-zoom]');
    if (zoomBtn) {
      const dir = zoomBtn.dataset.archZoom;
      if (dir === 'in') _state.zoom = Math.min(4, _state.zoom * 1.25);
      else if (dir === 'out') _state.zoom = Math.max(0.5, _state.zoom / 1.25);
      applyZoom();
      return;
    }
    if (t.closest('[data-arch-reset]')) {
      resetView();
      return;
    }

    // Detail panel close.
    if (t.closest('[data-arch-detail-close]')) {
      hideDetail();
      return;
    }

    // F004 fleet view → open a project's map. The button updates the
    // project selector via the existing shell helper (history + storage
    // + active-page re-render) so the user lands on that project's
    // architecture without us forcing a navigation.
    const openBtn = t.closest('[data-arch-open-project]');
    if (openBtn) {
      const name = openBtn.dataset.archOpenProject || '';
      if (name.length === 0) return;
      const J = (typeof globalThis !== 'undefined' && globalThis.Jarvis) ? globalThis.Jarvis : null;
      if (J && typeof J.setSelectedProject === 'function') {
        J.setSelectedProject(name);
      } else if (J && J.state) {
        // Fallback: mutate state + re-render without the helper.
        J.state.selectedProject = name;
        render(J.state);
      }
      return;
    }

    // Node click → detail panel.
    const nodeG = t.closest('.arch-node');
    if (nodeG) {
      const nodeId = nodeG.dataset.nodeId;
      if (nodeId) showDetail(nodeId);
      return;
    }
  }

  function onKeydown(ev) {
    const t = ev.target;
    if (!t || typeof t.closest !== 'function') return;

    // Arrow-key pan when the canvas wrap (or anything inside it that is
    // not a focusable control) has focus. Skip if the user is typing in
    // the search box or interacting with checkboxes/buttons.
    if (
      ev.key === 'ArrowUp'
      || ev.key === 'ArrowDown'
      || ev.key === 'ArrowLeft'
      || ev.key === 'ArrowRight'
    ) {
      const wrap = t.closest('[data-canvas-wrap]');
      if (!wrap) return;
      const tag = (t.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'button') return;
      const dims = currentViewBoxDims();
      if (!dims) return;
      const stepX = PAN_KEY_STEP * (dims.vbW / dims.baseW);
      const stepY = PAN_KEY_STEP * (dims.vbH / dims.baseH);
      let dx = 0;
      let dy = 0;
      if (ev.key === 'ArrowLeft') dx = -stepX;
      else if (ev.key === 'ArrowRight') dx = stepX;
      else if (ev.key === 'ArrowUp') dy = -stepY;
      else if (ev.key === 'ArrowDown') dy = stepY;
      ev.preventDefault();
      panBy(dx, dy);
      return;
    }

    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    const nodeG = t.closest('.arch-node');
    if (nodeG) {
      ev.preventDefault();
      const nodeId = nodeG.dataset.nodeId;
      if (nodeId) showDetail(nodeId);
    }
  }

  function onInput(ev) {
    const t = ev.target;
    if (!t) return;
    if (t.hasAttribute && t.hasAttribute('data-arch-search')) {
      _state.search = t.value || '';
      applyFilters();
    }
  }

  function onChange(ev) {
    const t = ev.target;
    if (!t) return;
    if (t.matches && t.matches('[data-arch-filter]')) {
      syncFilterStateFromDOM();
      applyFilters();
    }
  }

  function cssEscape(s) {
    if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') return CSS.escape(s);
    return String(s).replace(/[^a-zA-Z0-9_-]/g, (c) => `\\${c}`);
  }

  Jarvis.registerPage({
    id: 'architecture',
    label: 'Architecture',

    init(state) {
      _el = Jarvis.getPageEl('architecture');
      if (!_el) return;
      _delegateBound = false;
      render(state);
    },

    onActivate(state) {
      _delegateBound = false;
      render(state);
    },
  });
})();
