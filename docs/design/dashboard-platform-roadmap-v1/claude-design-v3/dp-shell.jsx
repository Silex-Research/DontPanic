/* DontPanic shared UI primitives */

// Brand mark (shield + check) using the poster gradient
const DPMark = ({ size = 22 }) => (
  <span className="dp-mark" style={{ width: size, height: size, borderRadius: size * 0.22 }}>
    <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3l8 4v6c0 4.5-3.5 7-8 8-4.5-1-8-3.5-8-8V7l8-4z" fill="rgba(255,255,255,0.08)" />
      <path d="m9 12 2.2 2.2L15.5 10" />
    </svg>
  </span>
);

// Status pip (dot only) — bands: healthy / action / blocked / pending
const Pip = ({ band = 'pending' }) => <span className={`dp-pip dp-pip--${band}`} />;

// Status badge with label
const Badge = ({ band = 'pending', children }) => (
  <span className={`dp-badge dp-badge--${band}`}>{children}</span>
);

// Relevance chip — NOT a status band
const Chip = ({ variant = 'optional', children }) => (
  <span className={`dp-chip dp-chip--${variant}`}>{children}</span>
);

// Command chip with copy button. inline = small, block = full width
const Cmd = ({ children, inline, block, prompt = '$' }) => (
  <span className={`dp-cmd ${inline ? 'dp-cmd--inline' : ''} ${block ? 'dp-cmd--block' : ''}`}>
    <span className="dp-cmd__prompt">{prompt}</span>
    <span className="dp-cmd__text dp-grow">{children}</span>
    <button className="dp-cmd__copy" aria-label="Copy"><IconCopy size={12} sw={1.8} /></button>
  </span>
);

// Provenance footer / inline
const Provenance = ({ source, updated, scope, extra, compact }) => (
  <div className="dp-provenance" style={compact ? { fontSize: 11 } : null}>
    {source && (
      <span className="dp-provenance__item">
        <IconDoc size={11} sw={1.8} />
        <span className="dp-provenance__label">source</span>
        <span className="dp-provenance__value">{source}</span>
      </span>
    )}
    {scope && (
      <>
        <span className="dot" />
        <span className="dp-provenance__item">
          <span className="dp-provenance__label">scope</span>
          <span className="dp-provenance__value">{scope}</span>
        </span>
      </>
    )}
    {updated && (
      <>
        <span className="dot" />
        <span className="dp-provenance__item">
          <IconClock size={11} sw={1.8} />
          <span className="dp-provenance__label">updated</span>
          <span className="dp-provenance__value">{updated}</span>
        </span>
      </>
    )}
    {extra}
  </div>
);

// Panel wrapper with optional head + foot
const Panel = ({ title, kicker, action, foot, children, className = '', noPad }) => (
  <section className={`dp-panel ${className}`}>
    {(title || action) && (
      <header className="dp-panel__head">
        <div className="dp-panel__title">
          {kicker && <span className="dp-panel__kicker">{kicker}</span>}
          {title && <span>{title}</span>}
        </div>
        {action}
      </header>
    )}
    <div className="dp-panel__body" style={noPad ? null : { padding: '4px 0' }}>
      {children}
    </div>
    {foot && <footer className="dp-panel__foot">{foot}</footer>}
  </section>
);

// Top strip — brand + project selector + last updated + warning + active reviews + system health
const TopStrip = ({ project = 'silex-research/dontpanic', updated = '14s ago', warnings = 3, reviews = 2, health = 'action' }) => {
  const healthLabels = { healthy: 'Healthy', action: 'Needs action', blocked: 'Blocked', pending: 'Pending' };
  return (
    <div className="dp-topstrip">
      <div className="dp-topstrip__brand">
        <DPMark size={22} />
        <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
          <span className="dp-topstrip__brand-name">DontPanic</span>
          <span className="dp-topstrip__brand-meta">operator console · v0.4.2</span>
        </div>
      </div>

      <button className="dp-topstrip__cell" style={{ minWidth: 0, gap: 10 }}>
        <span className="dp-topstrip__cell-label">project</span>
        <span className="dp-topstrip__cell-value dp-mono dp-truncate" style={{ maxWidth: 240 }}>{project}</span>
        <IconChevD size={12} style={{ color: 'var(--dp-text-muted)' }} />
      </button>

      <div className="dp-topstrip__cell">
        <IconClock size={12} sw={1.6} style={{ color: 'var(--dp-text-muted)' }} />
        <span className="dp-topstrip__cell-label">updated</span>
        <span className="dp-topstrip__cell-value dp-mono">{updated}</span>
      </div>

      <div className="dp-topstrip__cell">
        <IconWarn size={12} style={{ color: warnings ? 'var(--dp-action)' : 'var(--dp-text-muted)' }} />
        <span className="dp-topstrip__cell-label">warnings</span>
        <span className="dp-topstrip__cell-value dp-mono" style={{ color: warnings ? 'var(--dp-action)' : null }}>{warnings}</span>
      </div>

      <div className="dp-topstrip__cell">
        <IconBranch size={12} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} />
        <span className="dp-topstrip__cell-label">active reviews</span>
        <span className="dp-topstrip__cell-value dp-mono">{reviews}</span>
      </div>

      <div className="dp-topstrip__cell dp-grow" />

      <div className="dp-topstrip__health">
        <Badge band={health}>{healthLabels[health]}</Badge>
        <button style={{ color: 'var(--dp-text-muted)', display: 'flex' }} aria-label="Refresh">
          <IconRefresh size={14} />
        </button>
      </div>
    </div>
  );
};

// Sidebar — grouped nav by job
const navData = [
  {
    label: 'Operate',
    items: [
      { id: 'home', name: 'Home', icon: IconHome },
      { id: 'work', name: 'Work', icon: IconWork, count: { label: 12, kind: 'default' } },
      { id: 'arch', name: 'Architecture', icon: IconArch, hint: 'flows & map' },
      { id: 'caps', name: 'Tools & Setup', icon: IconCaps, count: { label: 3, kind: 'action' } },
    ],
  },
  {
    label: 'Observe',
    items: [
      { id: 'health', name: 'Health', icon: IconHealth, count: { label: 1, kind: 'action' } },
    ],
  },
  {
    label: 'Settings',
    items: [
      { id: 'prefs', name: 'Preferences', icon: IconPrefs },
    ],
  },
];

const Sidebar = ({ active = 'home' }) => (
  <aside className="dp-sidebar">
    {navData.map((group, gi) => (
      <div className="dp-sidebar__group" key={gi}>
        <div className="dp-sidebar__label">{group.label}</div>
        {group.items.map(item => {
          const Ico = item.icon;
          const isActive = item.id === active;
          return (
            <div key={item.id} className={`dp-nav-item ${isActive ? 'is-active' : ''}`} style={item.muted ? { opacity: 0.55 } : null}>
              <span className="dp-nav-item__icon"><Ico size={15} sw={1.7} /></span>
              <span>{item.name}</span>
              {item.hint && <span className="dp-nav-item__count" style={{ background: 'transparent', color: 'var(--dp-text-dim)' }}>{item.hint}</span>}
              {item.count && (
                <span className={`dp-nav-item__count ${item.count.kind === 'action' ? 'dp-nav-item__count--action' : ''} ${item.count.kind === 'blocked' ? 'dp-nav-item__count--blocked' : ''}`}>
                  {item.count.label}
                </span>
              )}
            </div>
          );
        })}
      </div>
    ))}
    <div className="dp-sidebar__footer">
      <span>silex-research/dontpanic</span>
      <span>main@a3f1b29</span>
    </div>
  </aside>
);

// Page header
const PageHead = ({ title, sub, actions, kicker }) => (
  <header className="dp-page__head">
    <div>
      {kicker && <div className="dp-kicker" style={{ marginBottom: 4 }}>{kicker}</div>}
      <h1 className="dp-page__title">{title}</h1>
      {sub && <div className="dp-page__sub">{sub}</div>}
    </div>
    {actions && <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>{actions}</div>}
  </header>
);

// Shell wrapper — fixed-size frame (default 1440x900) holding sidebar+topstrip+page
const Shell = ({ active, topStripProps, children, width = 1440, height = 900 }) => (
  <div className="dp" style={{ width, height, display: 'flex', flexDirection: 'column', overflow: 'hidden', borderRadius: 6, border: '1px solid var(--dp-border-subtle)' }}>
    <TopStrip {...topStripProps} />
    <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
      <Sidebar active={active} />
      <main className="dp-page" style={{ display: 'flex', flexDirection: 'column' }}>
        {children}
      </main>
    </div>
  </div>
);

Object.assign(window, {
  DPMark, Pip, Badge, Chip, Cmd, Provenance, Panel,
  TopStrip, Sidebar, PageHead, Shell, navData
});
