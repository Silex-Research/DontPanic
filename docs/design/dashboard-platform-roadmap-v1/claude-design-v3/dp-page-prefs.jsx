/* Preferences — UI-local only. No demo project rows. No legacy labels. */

const PrefRow = ({ label, hint, control }) => (
  <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 24, padding: '14px 18px', borderTop: '1px solid var(--dp-border-subtle)' }}>
    <div>
      <div style={{ fontWeight: 500 }}>{label}</div>
      {hint && <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', marginTop: 3 }}>{hint}</div>}
    </div>
    <div className="dp-row-flex" style={{ gap: 10 }}>{control}</div>
  </div>
);

const Toggle = ({ on }) => (
  <span style={{ width: 32, height: 18, borderRadius: 999, background: on ? 'var(--dp-brand)' : 'var(--dp-border)', position: 'relative', display: 'inline-block', flexShrink: 0 }}>
    <span style={{ position: 'absolute', top: 2, left: on ? 16 : 2, width: 14, height: 14, borderRadius: '50%', background: '#fff', transition: 'left 0.15s' }} />
  </span>
);

const Segmented = ({ options, active }) => (
  <div style={{ display: 'inline-flex', borderRadius: 4, background: 'var(--dp-bg-sunken)', border: '1px solid var(--dp-border-subtle)', padding: 2 }}>
    {options.map(o => (
      <button key={o} style={{
        padding: '4px 10px', borderRadius: 3,
        background: o === active ? 'var(--dp-bg-elevated)' : 'transparent',
        color: o === active ? 'var(--dp-text)' : 'var(--dp-text-muted)',
        fontSize: 12, fontWeight: o === active ? 600 : 500,
        border: o === active ? '1px solid var(--dp-border-subtle)' : '1px solid transparent',
      }}>{o}</button>
    ))}
  </div>
);

const Select = ({ value, hint }) => (
  <button className="dp-row-flex" style={{ gap: 8, padding: '5px 10px', background: 'var(--dp-bg-sunken)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4, fontSize: 12, minWidth: 200, justifyContent: 'space-between' }}>
    <span className="dp-mono">{value}</span>
    <IconChevD size={11} style={{ color: 'var(--dp-text-muted)' }} />
  </button>
);

const PagePrefs = () => (
  <Shell active="prefs" topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
    <PageHead
      kicker="PREFERENCES"
      title="UI preferences"
      sub="Local-only — these settings live in your browser, not in DontPanic state."
      actions={
        <span className="dp-row-flex" style={{ gap: 8, color: 'var(--dp-text-muted)', fontSize: 12 }}>
          <IconKey size={12} />
          <span>For DontPanic config, edit <span className="dp-mono" style={{ color: 'var(--dp-text-soft)' }}>.dontpanic/config.yaml</span> directly.</span>
        </span>
      }
    />

    <div className="dp-page__body" style={{ padding: '18px 24px', maxWidth: 900 }}>
      <Panel kicker="APPEARANCE" title="Appearance">
        <PrefRow label="Theme" hint="Dark theme is calibrated for long sessions. Light theme is preview-only in v0." control={<Segmented options={['Dark', 'Light', 'System']} active="Dark" />} />
        <PrefRow label="Density" hint="Compact tightens rows by 4px and is recommended for laptop screens." control={<Segmented options={['Comfortable', 'Compact']} active="Compact" />} />
        <PrefRow label="Mono font" hint="Used for paths, commands, IDs." control={<Select value="JetBrains Mono" />} />
        <PrefRow label="Show provenance footer" hint="Every page shows source path and last-updated timestamp." control={<><Toggle on /><span style={{ color: 'var(--dp-text-muted)', fontSize: 12 }}>On</span></>} />
      </Panel>

      <div style={{ height: 16 }} />

      <Panel kicker="NOTIFICATIONS" title="Browser notifications" action={<span className="dp-mono dp-muted" style={{ fontSize: 11 }}>local only · no remote push</span>}>
        <PrefRow label="Human gates awaiting you" hint="Browser notification when a volley reaches a human-required gate." control={<><Toggle on /><span style={{ color: 'var(--dp-text-muted)', fontSize: 12 }}>On</span></>} />
        <PrefRow label="Blocked work" hint="Notify when a plan becomes blocked." control={<><Toggle on /><span style={{ color: 'var(--dp-text-muted)', fontSize: 12 }}>On</span></>} />
        <PrefRow label="Capability probe failures" hint="Notify when a previously-healthy capability fails its probe." control={<><Toggle on={false} /><span style={{ color: 'var(--dp-text-muted)', fontSize: 12 }}>Off</span></>} />
        <PrefRow label="Sound" hint="Play a short tone with notifications." control={<><Toggle on={false} /><span style={{ color: 'var(--dp-text-muted)', fontSize: 12 }}>Off</span></>} />
      </Panel>

      <div style={{ height: 16 }} />

      <Panel kicker="DATA" title="Refresh & freshness">
        <PrefRow label="Auto-refresh interval" hint="How often the dashboard re-reads state from disk." control={<Segmented options={['5s', '15s', '60s', 'manual']} active="15s" />} />
        <PrefRow label="Show stale-data warnings" hint="Surface a yellow band when a data source hasn't updated in N×interval." control={<><Toggle on /><span style={{ color: 'var(--dp-text-muted)', fontSize: 12 }}>On</span></>} />
        <PrefRow label="Last-seen project on launch" hint="Open the project you last viewed, or always prompt." control={<Segmented options={['Last seen', 'Always prompt']} active="Last seen" />} />
      </Panel>

      <div style={{ height: 16 }} />

      <Panel kicker="LOCAL STATE" title="Reset">
        <PrefRow
          label="Clear local preferences"
          hint="Resets theme, density, notification toggles, last-seen project. Does NOT touch DontPanic state or plans."
          control={<button style={{ padding: '5px 10px', background: 'var(--dp-blocked-soft)', color: 'var(--dp-blocked)', border: '1px solid var(--dp-blocked-edge)', borderRadius: 4, fontSize: 12, fontWeight: 500 }}>Clear localStorage</button>}
        />
      </Panel>

      <div style={{ marginTop: 18, padding: 14, border: '1px dashed var(--dp-border)', borderRadius: 4, color: 'var(--dp-text-muted)', fontSize: 12, lineHeight: 1.5 }}>
        <div className="dp-row-flex" style={{ gap: 8, marginBottom: 4 }}>
          <IconShield size={12} sw={1.8} style={{ color: 'var(--dp-brand)' }} />
          <span style={{ color: 'var(--dp-text)', fontWeight: 500 }}>This is not DontPanic configuration.</span>
        </div>
        Settings on this page only change how the dashboard renders in your browser. To configure capabilities, agents, gates, plan budgets, or guardrails, edit <span className="dp-mono" style={{ color: 'var(--dp-text-soft)' }}>.dontpanic/config.yaml</span> and re-run <span className="dp-mono" style={{ color: 'var(--dp-text-soft)' }}>dontpanic doctor</span>.
      </div>
    </div>

    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="browser localStorage" updated="—" scope="local · per device" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>UI-local · no remote write</span>
    </footer>
  </Shell>
);

window.PagePrefs = PagePrefs;
