/*
 * Domain regroup — the three-domain IA (plan 2026-06-06-004 F006, spec §1). Collapses the 8
 * implementation tabs into operator intent: COCKPIT (act) · WORK (understand) · SYSTEM (operate
 * the environment). Repair dissolves into the cockpit queue (a broken thing IS an ActionItem,
 * §1.3); Architecture moves under Work. Pure data + a renderer + the old→new resolver.
 */

export const DOMAINS = Object.freeze([
  { id: 'cockpit', label: 'Cockpit', subnav: ['overview', 'needs_decision', 'needs_auth', 'agent_runnable', 'history'] },
  { id: 'work', label: 'Work', subnav: ['plans', 'runs', 'architecture'] },
  { id: 'system', label: 'System', subnav: ['health', 'capabilities', 'projects', 'preferences'] },
]);

/* Old page module → new home (the §1.3 mapping). `dissolved` marks tabs that stop being a
   destination and reappear as something else (Repair → an item in the cockpit queue). */
export const OLD_TO_NEW = Object.freeze({
  'operator-console': { domain: 'cockpit', view: 'overview', disposition: 'merged' },
  'what-now': { domain: 'cockpit', view: 'needs', disposition: 'merged' },
  'repair': { domain: 'cockpit', view: 'overview', disposition: 'dissolved' },
  'mission-control': { domain: 'work', view: 'plans', disposition: 'kept' },
  'architecture': { domain: 'work', view: 'architecture', disposition: 'moved' },
  'health': { domain: 'system', view: 'health', disposition: 'kept' },
  'capabilities': { domain: 'system', view: 'capabilities', disposition: 'kept' },
  'settings': { domain: 'system', view: 'preferences', disposition: 'kept' },
});

export const SUBNAV_LABELS = Object.freeze({
  overview: 'Overview', needs_decision: 'Needs Decision', needs_auth: 'Needs Auth',
  agent_runnable: 'Agent-Runnable', history: 'History',
  plans: 'Plans', runs: 'Runs', architecture: 'Architecture',
  health: 'Health', capabilities: 'Capabilities', projects: 'Projects', preferences: 'Preferences',
});

/** Resolve where an old tab now lives (so existing deep-links/routes keep working). */
export function resolveDomain(oldModule) {
  return OLD_TO_NEW[oldModule] || null;
}

export function domainOf(id) {
  return DOMAINS.find((d) => d.id === id) || null;
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

/** Top nav: three domains; the active domain renders its sub-nav beneath. */
export function renderNav(activeDomain = 'cockpit', activeView = null) {
  const nav = el('nav', 'dp-nav');
  const top = el('div', 'dp-nav-domains');
  for (const d of DOMAINS) {
    const btn = el('button', `dp-nav-domain${d.id === activeDomain ? ' dp-nav-domain--active' : ''}`, d.label);
    btn.type = 'button';
    btn.dataset.domain = d.id;
    top.appendChild(btn);
  }
  nav.appendChild(top);

  const dom = domainOf(activeDomain);
  if (dom) {
    const sub = el('div', 'dp-nav-subnav');
    for (const v of dom.subnav) {
      const item = el('button', `dp-nav-sub${v === activeView ? ' dp-nav-sub--active' : ''}`, SUBNAV_LABELS[v] || v);
      item.type = 'button';
      item.dataset.view = v;
      sub.appendChild(item);
    }
    nav.appendChild(sub);
  }
  return nav;
}
