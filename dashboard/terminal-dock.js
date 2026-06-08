// Embedded terminal dock (plan 2026-06-06-002). An always-visible bottom dock
// that hosts a real shell via xterm.js ↔ the serve's guarded /pty WebSocket.
// Classic script (xterm ships UMD globals). Degrades to an honest hint when the
// serve was started WITHOUT --enable-terminal (the common, safe default).
(function () {
  'use strict';

  var dock, host, bar, statusEl, warnEl, scopeEl, term, fit, ws, opened = false, session = null;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function buildDock() {
    dock = el('div', 'term-dock term-dock--collapsed');
    bar = el('div', 'term-dock-bar');
    var title = el('span', 'term-dock-title', '▸ Terminal');
    warnEl = el('span', 'term-dock-warn', '');     // visible when a real shell is armed
    scopeEl = el('span', 'term-dock-scope', '');   // "Shell: <repo> · session active"
    statusEl = el('span', 'term-dock-status', '');
    bar.appendChild(title);
    bar.appendChild(warnEl);
    bar.appendChild(scopeEl);
    bar.appendChild(statusEl);
    host = el('div', 'term-dock-host');
    dock.appendChild(bar);
    dock.appendChild(host);
    document.body.appendChild(dock);
    bar.addEventListener('click', function () {
      var collapsed = dock.classList.toggle('term-dock--collapsed');
      title.textContent = (collapsed ? '▸' : '▾') + ' Terminal';
      if (!collapsed) openTerminal();
      if (!collapsed && fit) { setTimeout(function () { try { fit.fit(); sendResize(); } catch (e) {} }, 50); }
    });
  }

  function setStatus(msg) { if (statusEl) statusEl.textContent = msg; }

  function openTerminal() {
    if (opened) return;
    if (!session || !session.enabled) {
      host.appendChild(el('div', 'term-dock-off',
        'Terminal is off. Relaunch with:  dontpanic dashboard serve --enable-terminal'));
      opened = true;
      return;
    }
    if (!window.Terminal) { setStatus('xterm not loaded'); return; }
    opened = true;
    term = new window.Terminal({
      cursorBlink: true, fontSize: 13, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      theme: { background: '#0b0e14' },
    });
    try {
      var FitAddon = window.FitAddon && (window.FitAddon.FitAddon || window.FitAddon);
      if (FitAddon) { fit = new FitAddon(); term.loadAddon(fit); }
    } catch (e) { /* fit optional */ }
    term.open(host);
    if (fit) { try { fit.fit(); } catch (e) {} }

    var proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(proto + '://' + location.host + '/pty?token=' + encodeURIComponent(session.token));
    ws.binaryType = 'arraybuffer';
    setStatus('connecting…');
    ws.onopen = function () {
      setStatus('connected');
      if (scopeEl) scopeEl.textContent = 'Shell: ' + scopeName() + ' · session active';
      sendResize();
      term.focus();
    };
    ws.onclose = function () { setStatus('closed'); term.write('\r\n\x1b[2m[session ended]\x1b[0m\r\n'); };
    ws.onerror = function () { setStatus('error'); };
    ws.onmessage = function (ev) {
      if (typeof ev.data === 'string') { term.write(ev.data); }
      else { term.write(new Uint8Array(ev.data)); }
    };
    term.onData(function (d) { if (ws && ws.readyState === 1) ws.send(d); });
    term.onResize(sendResize);
    window.addEventListener('resize', function () { if (fit && !dock.classList.contains('term-dock--collapsed')) { try { fit.fit(); } catch (e) {} } });
  }

  function sendResize() {
    if (!ws || ws.readyState !== 1 || !term) return;
    try { ws.send(JSON.stringify({ resize: { rows: term.rows, cols: term.cols } })); } catch (e) {}
  }

  function scopeName() {
    return (session && (session.cwd_label || session.cwd)) || 'repo root';
  }

  // The visible governance contract (plan 2026-06-06-002): when a real shell is
  // armed, the dock SAYS SO — scope + unrestricted, never silent.
  function applySessionChrome() {
    if (session && session.enabled) {
      warnEl.textContent = '⚠ Terminal enabled · local shell · ' + scopeName() + ' · unrestricted commands';
      warnEl.classList.add('is-armed');
      // Armed = an unrestricted local shell. Assistive tech must ANNOUNCE it the
      // moment it arms (audit 2026-06-08 B2#1: the safety contract from plan 008
      // lived only in an unused component; the REAL dock had no alert semantics).
      warnEl.setAttribute('role', 'alert');
      warnEl.setAttribute('aria-live', 'assertive');
      warnEl.setAttribute('aria-atomic', 'true');
      scopeEl.textContent = 'Shell: ' + scopeName() + ' · ready';
      setStatus('click to open');
    } else {
      warnEl.textContent = '';
      warnEl.classList.remove('is-armed');
      warnEl.removeAttribute('role');
      warnEl.removeAttribute('aria-live');
      warnEl.removeAttribute('aria-atomic');
      scopeEl.textContent = '';
      setStatus('off — relaunch with --enable-terminal');
    }
  }

  function init() {
    buildDock();
    fetch('/terminal/session', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : { enabled: false }; })
      .then(function (s) { session = s; applySessionChrome(); })
      .catch(function () { session = { enabled: false }; applySessionChrome(); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
