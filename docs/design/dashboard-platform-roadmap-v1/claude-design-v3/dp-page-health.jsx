/* Health — doctor / security / reconcile status, honest empty states */

const HealthMetric = ({ label, value, sub, band, mono }) => (
  <div style={{ padding: '14px 16px', borderRight: '1px solid var(--dp-border-subtle)', flex: 1, minWidth: 0 }}>
    <div className="dp-kicker" style={{ marginBottom: 6 }}>{label}</div>
    <div className="dp-row-flex" style={{ gap: 8 }}>
      <Pip band={band} />
      <span style={{ fontSize: 18, fontWeight: 600, fontFamily: mono ? 'var(--dp-font-mono)' : null, color: 'var(--dp-text)' }}>{value}</span>
    </div>
    {sub && <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 4, fontFamily: 'var(--dp-font-mono)' }}>{sub}</div>}
  </div>
);

const HealthCheck = ({ band, name, detail, source, last }) => (
  <div className="dp-row" style={{ gridTemplateColumns: '8px 1fr 180px 130px', padding: '10px 16px' }}>
    <Pip band={band} />
    <div className="dp-stack-sm" style={{ minWidth: 0 }}>
      <div style={{ fontWeight: 500 }}>{name}</div>
      <div style={{ fontSize: 12, color: 'var(--dp-text-muted)' }}>{detail}</div>
    </div>
    <div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>{source}</div>
    <div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)', textAlign: 'right' }}>{last}</div>
  </div>
);

const EmptyState = ({ icon: Ico = IconClock, title, body, command, source }) => (
  <div className="dp-empty">
    <div className="dp-empty__title"><Ico size={14} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} /> {title}</div>
    <div className="dp-empty__body">{body}</div>
    {command && <Cmd>{command}</Cmd>}
    {source && (
      <div className="dp-empty__prov">
        <IconDoc size={11} sw={1.8} />
        <span>expected at <span style={{ color: 'var(--dp-text-soft)' }}>{source}</span></span>
      </div>
    )}
  </div>
);

const PageHealth = () => (
  <Shell active="health" topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
    <PageHead
      kicker="HEALTH"
      title="System health"
      sub="Doctor · Security · Reconcile — last full sweep 6h ago"
      actions={
        <>
          <button className="dp-cmd dp-cmd--inline" style={{ background: 'var(--dp-bg-panel)' }}>
            <IconRefresh size={12} />
            <span style={{ fontFamily: 'var(--dp-font-sans)' }}>Run doctor</span>
          </button>
          <Provenance source=".dontpanic/doctor.json" updated="6h ago" />
        </>
      }
    />

    <div className="dp-page__body" style={{ padding: '16px 24px' }}>
      {/* Summary strip */}
      <Panel kicker="OVERALL" title="System summary" action={<Badge band="action">Needs action</Badge>}>
        <div style={{ display: 'flex' }}>
          <HealthMetric label="Doctor checks" value="14 / 16 pass" sub="2 warnings · 0 errors" band="action" />
          <HealthMetric label="Security scan" value="0 high · 2 medium" sub="last 6h ago" band="action" />
          <HealthMetric label="Reconcile" value="In sync" sub="state ↔ disk · 14s" band="healthy" />
          <HealthMetric label="Plan lock" value="3 active" sub="0 expired" band="healthy" mono />
          <HealthMetric label="Agents reachable" value="6 / 7" sub="hermes 503" band="action" mono />
        </div>
      </Panel>

      <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 16 }}>
        <Panel kicker="DOCTOR" title="Environment checks" action={<span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>16 checks</span>}>
          <HealthCheck band="healthy" name="git available" detail="git 2.45.1 · in PATH" source="$(which git)" last="6h ago" />
          <HealthCheck band="healthy" name="node available" detail="node v22.4.1 · npm 10" source="$(which node)" last="6h ago" />
          <HealthCheck band="healthy" name=".dontpanic/ writable" detail="ok · 14 entries · 312KB" source=".dontpanic/" last="6h ago" />
          <HealthCheck band="action"  name="Plan budget warning" detail="add-auth.md at 71% of token budget" source="plans/add-auth.md" last="6h ago" />
          <HealthCheck band="action"  name="Doctor scan stale" detail="hasn't run in over 4h — re-run recommended" source=".dontpanic/doctor.json" last="6h ago" />
          <HealthCheck band="healthy" name="filesystem mcp reachable" detail="responded in 4ms" source="capabilities/mcp-fs.yaml" last="14s ago" />
        </Panel>

        <Panel kicker="SECURITY" title="Security & secrets" action={<span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>scan via gitleaks</span>}>
          <HealthCheck band="healthy" name="No high-severity findings" detail="last scan covered 1,847 files" source=".dontpanic/security/last.json" last="6h ago" />
          <HealthCheck band="action"  name="2 medium: hardcoded URLs in tests" detail="tests/fixtures/auth.spec.ts:42" source="gitleaks/medium" last="6h ago" />
          <HealthCheck band="action"  name="One vendor key over 90 days" detail="Anthropic — rotate when convenient" source="capabilities/anthropic.yaml" last="6h ago" />
          <HealthCheck band="healthy" name="Plan lock signatures valid" detail="3 active plans · all signed" source=".dontpanic/state.yaml" last="14s ago" />
        </Panel>

        <Panel kicker="RECONCILE" title="State ↔ disk drift" action={<Badge band="healthy">In sync</Badge>}>
          <HealthCheck band="healthy" name="Plans on disk match state" detail="12 files indexed · no orphans" source="plans/" last="14s ago" />
          <HealthCheck band="healthy" name="Volley records consistent" detail="9 records · 9 backing dirs" source=".dontpanic/volleys/" last="14s ago" />
          <HealthCheck band="healthy" name="Evidence packets intact" detail="all referenced files exist" source="evidence/" last="14s ago" />
        </Panel>

        <Panel kicker="MISSING DATA" title="Surfaces with no signal yet">
          <div style={{ padding: '14px 16px' }}>
            <EmptyState
              icon={IconClock}
              title="No cost telemetry"
              body="Token spend history isn't being recorded yet. Enable the cost provider to see daily and per-plan spend over time."
              command="dontpanic caps probe cost-provider"
              source=".dontpanic/cost-history.jsonl"
            />
          </div>
          <div style={{ padding: '0 16px 14px' }}>
            <EmptyState
              icon={IconShield}
              title="No production telemetry source configured"
              body="DontPanic can show runtime guardrail trips if a production telemetry source (OTel, Sentry) is connected. None is configured."
              command="dontpanic caps add runtime-telemetry"
              source="capabilities/runtime-telemetry.yaml"
            />
          </div>
        </Panel>
      </div>
    </div>

    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source=".dontpanic/doctor.json · .dontpanic/security/last.json" updated="6h ago" scope="silex-research/dontpanic@main" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only · no telemetry pushed</span>
    </footer>
  </Shell>
);

window.PageHealth = PageHealth;
window.EmptyState = EmptyState;
