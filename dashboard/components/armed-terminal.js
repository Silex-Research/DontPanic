/*
 * Armed-terminal dock — the trust boundary (plan 2026-06-06-004 F005, spec §5.5).
 * The dock is a REAL, unrestricted local shell, OFF by default. When armed the UI must SHOUT:
 * a persistent red hazard frame (the one place saturated --hazard is reserved), the scope
 * shown, never dismissible while armed — disarm is the only exit. Never cute, never pretty.
 */

export function isArmed(state) {
  return !!(state && state.armed);
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

/**
 * Render the dock for `state = { armed, scope, sessionActive }`.
 * OFF  → a quiet bar + an explicit [Arm terminal] (arming requires confirm + shows scope).
 * ARMED → the hazard frame: warning, scope, "no sandbox", session, [Disarm]. No close control.
 */
export function renderTerminalDock(state = {}) {
  const armed = isArmed(state);
  const scope = state.scope || 'repo root';
  const root = el('div', `dp-dock${armed ? ' dp-dock--armed dp-hazard' : ''}`);
  root.dataset.armed = String(armed);
  root.dataset.scope = scope;

  if (!armed) {
    const bar = el('div', 'dp-dock-bar');
    bar.appendChild(el('span', 'dp-dock-status', 'Terminal dock · OFF'));
    const arm = el('button', 'dp-dock-arm', 'Arm terminal');
    arm.type = 'button';
    arm.dataset.action = 'arm';
    bar.appendChild(arm);
    root.appendChild(bar);
    return root;
  }

  // ARMED — the hazard frame. Persistent; does not collapse while armed.
  const frame = el('div', 'dp-hazard-frame');
  frame.setAttribute('role', 'alert');
  frame.appendChild(el('div', 'dp-hazard-title', '⚠  UNRESTRICTED LOCAL SHELL'));
  frame.appendChild(el('div', 'dp-hazard-scope', `Scope · ${scope}`));
  frame.appendChild(el('div', 'dp-hazard-warn', 'Commands execute on YOUR machine. No sandbox.'));

  const foot = el('div', 'dp-hazard-foot');
  foot.appendChild(el('span', 'dp-hazard-session', state.sessionActive ? '● session active' : '● armed'));
  const disarm = el('button', 'dp-dock-disarm', 'Disarm');
  disarm.type = 'button';
  disarm.dataset.action = 'disarm';
  foot.appendChild(disarm);
  frame.appendChild(foot);

  root.appendChild(frame);
  return root;
}
