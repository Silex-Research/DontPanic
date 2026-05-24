/* Work — read-only lifecycle list (renamed from Mission Control) */

const WorkRow = ({ status, indicator, name, gate, agent, model, volley, owner, updated, selected }) => {
  const statusToBand = { draft: 'pending', active: 'healthy', completed: 'healthy' };
  const indicatorBand = indicator?.kind; // 'action' | 'blocked' | null
  return (
    <tr style={selected ? { background: 'var(--dp-bg-elevated)' } : null}>
      <td style={{ width: 28 }}>
        {indicatorBand ? <Pip band={indicatorBand} /> : <Pip band={statusToBand[status]} />}
      </td>
      <td style={{ width: 120 }}>
        <span className="dp-kicker" style={{ color: status === 'active' ? 'var(--dp-text-soft)' : 'var(--dp-text-muted)' }}>{status.toUpperCase()}</span>
      </td>
      <td>
        <div className="dp-stack-sm">
          <div className="dp-row-flex" style={{ gap: 8 }}>
            <span style={{ fontWeight: 600 }}>{name}</span>
            {indicator && <Badge band={indicator.kind}>{indicator.label}</Badge>}
          </div>
        </div>
      </td>
      <td className="dim" style={{ width: 130 }}>
        <span className="dp-mono" style={{ fontSize: 12 }}>{volley || '—'}</span>
      </td>
      <td style={{ width: 160 }}>
        {gate ? <Badge band={gate.band}>{gate.label}</Badge> : <span className="dim">—</span>}
      </td>
      <td className="dim" style={{ width: 160 }}>
        {agent ? (
          <span className="dp-row-flex" style={{ gap: 6 }}>
            <IconRobot size={11} sw={1.6} style={{ color: 'var(--dp-text-muted)' }} />
            <span style={{ fontSize: 12 }}>{agent}</span>
            <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>{model}</span>
          </span>
        ) : <span className="dim">—</span>}
      </td>
      <td className="dim" style={{ width: 110 }}>
        <span className="dp-row-flex" style={{ gap: 6 }}>
          <IconUser size={11} sw={1.6} />
          <span style={{ fontSize: 12 }}>{owner}</span>
        </span>
      </td>
      <td className="dim num" style={{ width: 100, textAlign: 'right' }}>{updated}</td>
    </tr>
  );
};

const WorkGroupHeader = ({ label, count, band }) => (
  <tr style={{ background: 'var(--dp-bg-row)' }}>
    <td colSpan={8} style={{ padding: '6px 16px', borderBottom: '1px solid var(--dp-border-subtle)' }}>
      <div className="dp-row-flex" style={{ gap: 8 }}>
        <Pip band={band} />
        <span className="dp-kicker" style={{ color: 'var(--dp-text)' }}>{label}</span>
        <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>{count}</span>
      </div>
    </td>
  </tr>
);

const PageWork = () => (
  <Shell active="work" topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
    <PageHead
      kicker="WORK"
      title="Plans"
      sub="Read-only lifecycle view · sourced from plans/*.md frontmatter"
      actions={
        <>
          <div className="dp-row-flex" style={{ gap: 6, padding: '4px 10px', background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4 }}>
            <IconSearch size={12} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} />
            <input placeholder="Filter plans…" style={{ background: 'transparent', border: 'none', outline: 'none', width: 180, color: 'var(--dp-text)' }} />
          </div>
          <button className="dp-cmd dp-cmd--inline" style={{ background: 'var(--dp-bg-panel)' }}>
            <IconFilter size={12} />
            <span style={{ fontFamily: 'var(--dp-font-sans)' }}>All statuses</span>
            <IconChevD size={11} />
          </button>
        </>
      }
    />

    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 380px', gap: 0, flex: 1, minHeight: 0 }}>
      {/* List */}
      <div style={{ overflow: 'auto', padding: '14px 24px' }}>
        <div className="dp-panel" style={{ overflow: 'hidden' }}>
          <table className="dp-table">
            <thead>
              <tr>
                <th style={{ width: 28 }}></th>
                <th>Status</th>
                <th>Plan</th>
                <th>Volley</th>
                <th>Gate</th>
                <th>Agent / Model</th>
                <th>Owner</th>
                <th style={{ textAlign: 'right' }}>Updated</th>
              </tr>
            </thead>
            <tbody>
              <WorkGroupHeader label="ACTIVE" count="4 plans" band="healthy" />
              <WorkRow
                status="active"
                name="add-auth.md"
                volley="vol-4f1a"
                indicator={{ kind: 'blocked', label: 'Verifier failed' }}
                gate={{ band: 'blocked', label: 'Audit · 3/5' }}
                agent="Reviewer"
                model="sonnet-4.5"
                owner="you"
                updated="3m"
              />
              <WorkRow
                status="active"
                selected
                name="billing-refactor.md"
                volley="vol-2b7e"
                indicator={{ kind: 'action', label: 'Awaiting you' }}
                gate={{ band: 'action', label: 'Human · 4/5' }}
                agent="Verifier"
                model="gpt-5-codex"
                owner="you"
                updated="14m"
              />
              <WorkRow
                status="active"
                name="api-rewrite.md"
                volley="vol-9c33"
                indicator={{ kind: 'blocked', label: 'Plan expired' }}
                gate={{ band: 'blocked', label: 'Audit · 3/5' }}
                agent="Challenger"
                model="gemini-2.5-pro"
                owner="you"
                updated="42m"
              />
              <WorkRow
                status="active"
                name="rate-limiter.md"
                volley="vol-8a01"
                gate={{ band: 'healthy', label: 'Executing · 2/5' }}
                agent="Builder"
                model="grok-4"
                owner="you"
                updated="just now"
              />

              <WorkGroupHeader label="DRAFT" count="3 plans" band="pending" />
              <WorkRow
                status="draft"
                name="reduce-token-spend.md"
                gate={{ band: 'pending', label: 'Not started' }}
                owner="you"
                updated="2h"
              />
              <WorkRow
                status="draft"
                name="migrate-vector-db.md"
                gate={{ band: 'pending', label: 'Not started' }}
                owner="you"
                updated="yesterday"
              />
              <WorkRow
                status="draft"
                name="add-otel-traces.md"
                gate={{ band: 'pending', label: 'Not started' }}
                owner="you"
                updated="3d"
              />

              <WorkGroupHeader label="COMPLETED" count="5 plans · last 7d" band="healthy" />
              <WorkRow
                status="completed"
                name="cli-quickstart-banner.md"
                volley="vol-ff22"
                gate={{ band: 'healthy', label: 'Shipped' }}
                agent="Reviewer"
                model="sonnet-4.5"
                owner="you"
                updated="4h"
              />
              <WorkRow
                status="completed"
                name="harden-cors-policy.md"
                volley="vol-fe19"
                gate={{ band: 'healthy', label: 'Shipped' }}
                agent="Verifier"
                model="gpt-5"
                owner="you"
                updated="1d"
              />
              <WorkRow
                status="completed"
                name="fix-error-redaction.md"
                volley="vol-fb88"
                gate={{ band: 'healthy', label: 'Shipped' }}
                agent="Reviewer"
                model="sonnet-4.5"
                owner="you"
                updated="2d"
              />
              <WorkRow
                status="completed"
                name="prune-stale-tokens.md"
                volley="vol-f7a1"
                gate={{ band: 'healthy', label: 'Shipped' }}
                agent="Verifier"
                model="opus-4"
                owner="you"
                updated="3d"
              />
              <WorkRow
                status="completed"
                name="add-rate-limit-tests.md"
                volley="vol-f111"
                gate={{ band: 'healthy', label: 'Shipped' }}
                agent="Challenger"
                model="gemini-2.5-pro"
                owner="you"
                updated="6d"
              />
            </tbody>
          </table>
        </div>
      </div>

      {/* Detail drawer */}
      <aside className="dp-drawer">
        <div className="dp-drawer__head">
          <div className="dp-row-flex" style={{ gap: 8, marginBottom: 6 }}>
            <span className="dp-kicker">ACTIVE · DETAIL</span>
          </div>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>billing-refactor.md</h2>
          <div className="dp-mono" style={{ fontSize: 12, color: 'var(--dp-text-muted)' }}>plans/billing-refactor.md</div>
          <div className="dp-row-flex" style={{ gap: 6, marginTop: 10 }}>
            <Badge band="action">Awaiting you</Badge>
            <Chip variant="optional">vol-2b7e</Chip>
          </div>
        </div>

        <div className="dp-drawer__body">
          <section className="dp-drawer__section">
            <div className="dp-drawer__section-title">Lifecycle</div>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 8 }}>
              {[
                { name: 'Plan lock', band: 'healthy' },
                { name: 'Execute', band: 'healthy' },
                { name: 'Audit', band: 'healthy' },
                { name: 'Human gate', band: 'action' },
                { name: 'Safe to ship', band: 'pending' },
              ].map((s, i, arr) => (
                <React.Fragment key={i}>
                  <div className="dp-row-flex" style={{ gap: 6 }}>
                    <Pip band={s.band} />
                    <span style={{ fontSize: 11, color: i === 3 ? 'var(--dp-text)' : 'var(--dp-text-muted)' }}>{s.name}</span>
                  </div>
                  {i < arr.length - 1 && <span style={{ color: 'var(--dp-text-dim)' }}>›</span>}
                </React.Fragment>
              ))}
            </div>
          </section>

          <section className="dp-drawer__section">
            <div className="dp-drawer__section-title">Frontmatter</div>
            <div style={{ background: 'var(--dp-bg-sunken)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4, padding: '10px 12px', fontFamily: 'var(--dp-font-mono)', fontSize: 12, color: 'var(--dp-text-soft)' }}>
              <div><span style={{ color: 'var(--dp-text-dim)' }}>status:</span> active</div>
              <div><span style={{ color: 'var(--dp-text-dim)' }}>owner:</span> you</div>
              <div><span style={{ color: 'var(--dp-text-dim)' }}>created:</span> 2026-05-21</div>
              <div><span style={{ color: 'var(--dp-text-dim)' }}>scope:</span> server/billing/*</div>
              <div><span style={{ color: 'var(--dp-text-dim)' }}>budget_tokens:</span> 1.2M</div>
              <div><span style={{ color: 'var(--dp-text-dim)' }}>spend:</span> 847k <span style={{ color: 'var(--dp-action)' }}>(71%)</span></div>
            </div>
          </section>

          <section className="dp-drawer__section">
            <div className="dp-drawer__section-title">Next command</div>
            <Cmd block>dontpanic review vol-2b7e --open</Cmd>
            <div style={{ fontSize: 11, color: 'var(--dp-text-dim)', marginTop: 6, fontFamily: 'var(--dp-font-mono)' }}>
              // opens the evidence packet for human review
            </div>
          </section>

          <section className="dp-drawer__section">
            <div className="dp-drawer__section-title">Provenance</div>
            <div className="dp-stack-sm" style={{ fontFamily: 'var(--dp-font-mono)', fontSize: 11, color: 'var(--dp-text-muted)' }}>
              <div><span style={{ color: 'var(--dp-text-dim)' }}>plan:</span> plans/billing-refactor.md</div>
              <div><span style={{ color: 'var(--dp-text-dim)' }}>state:</span> .dontpanic/volleys/vol-2b7e.yaml</div>
              <div><span style={{ color: 'var(--dp-text-dim)' }}>evidence:</span> evidence/vol-2b7e/</div>
              <div><span style={{ color: 'var(--dp-text-dim)' }}>updated:</span> 14m ago</div>
            </div>
          </section>
        </div>
      </aside>
    </div>

    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="plans/*.md (frontmatter only)" updated="14s ago" scope="silex-research/dontpanic@main" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only · 12 plans · no mutations</span>
    </footer>
  </Shell>
);

window.PageWork = PageWork;
