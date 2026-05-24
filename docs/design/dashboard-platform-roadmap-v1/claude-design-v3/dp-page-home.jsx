/* Home — "What Now" page */

const HomeAttentionRow = ({ band, title, meta, source, action, tail }) => (
  <div className="dp-row" style={{ gridTemplateColumns: '8px 1fr auto', padding: '11px 16px' }}>
    <Pip band={band} />
    <div className="dp-stack-sm" style={{ minWidth: 0 }}>
      <div className="dp-row__title dp-truncate">{title}</div>
      <div className="dp-row__meta dp-row-flex">
        {meta}
        {source && (
          <>
            <span style={{ color: 'var(--dp-text-dim)' }}>·</span>
            <span className="dp-mono dp-truncate" style={{ color: 'var(--dp-text-dim)' }}>{source}</span>
          </>
        )}
      </div>
    </div>
    <div className="dp-row-flex" style={{ gap: 8 }}>
      {tail}
      {action && (
        <button className="dp-cmd dp-cmd--inline">
          <span className="dp-cmd__prompt">$</span>
          <span className="dp-cmd__text">{action}</span>
          <span className="dp-cmd__copy"><IconCopy size={11} sw={1.8} /></span>
        </button>
      )}
    </div>
  </div>
);

const VolleyRow = ({ name, file, model, agent, step, gate, elapsed }) => (
  <div className="dp-row" style={{ gridTemplateColumns: '1fr auto', padding: '10px 14px', alignItems: 'flex-start' }}>
    <div className="dp-stack-sm" style={{ minWidth: 0 }}>
      <div className="dp-row-flex" style={{ gap: 8 }}>
        <span style={{ fontWeight: 600 }}>{name}</span>
        <Chip variant="optional">{model}</Chip>
      </div>
      <div className="dp-row__meta dp-row-flex" style={{ gap: 6 }}>
        <IconRobot size={11} sw={1.6} />
        <span>{agent}</span>
        <span style={{ color: 'var(--dp-text-dim)' }}>·</span>
        <span className="dp-mono">{step}</span>
      </div>
      {file && <div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>{file}</div>}
    </div>
    <div style={{ textAlign: 'right' }} className="dp-stack-sm">
      <Badge band={gate.band}>{gate.label}</Badge>
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>{elapsed}</span>
    </div>
  </div>
);

const NextCommand = ({ rank, title, why, command, why2 }) => (
  <div style={{ padding: '12px 14px', borderTop: '1px solid var(--dp-border-subtle)' }}>
    <div className="dp-row-flex" style={{ gap: 8, marginBottom: 6 }}>
      <span className="dp-mono" style={{ width: 18, height: 18, borderRadius: 4, background: 'var(--dp-brand-soft)', color: 'var(--dp-brand)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700 }}>{rank}</span>
      <span style={{ fontWeight: 600 }}>{title}</span>
    </div>
    <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', marginBottom: 8 }}>{why}</div>
    <Cmd block>{command}</Cmd>
    {why2 && <div style={{ fontSize: 11, color: 'var(--dp-text-dim)', marginTop: 6, fontFamily: 'var(--dp-font-mono)' }}>{why2}</div>}
  </div>
);

const PageHome = () => (
  <Shell active="home" topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
    <PageHead
      kicker="HOME"
      title="What now"
      sub="3 things need your attention · 2 AI reviews in flight"
      actions={
        <>
          <button className="dp-cmd dp-cmd--inline" style={{ background: 'transparent' }}>
            <IconRefresh size={12} />
            <span style={{ fontFamily: 'var(--dp-font-sans)' }}>Refresh</span>
          </button>
          <Provenance source=".dontpanic/state.yaml" updated="14s ago" />
        </>
      }
    />

    <div className="dp-page__body" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 380px', gap: 16, padding: '16px 24px' }}>
      {/* LEFT — attention feed */}
      <div className="dp-stack">
        <Panel
          kicker="01"
          title="Stuck — needs you to unblock"
          action={<Chip variant="required">2 stuck</Chip>}
        >
          <HomeAttentionRow
            band="blocked"
            title="Tests don't cover enough of the new code yet"
            meta={<><Badge band="blocked">Blocked</Badge><span>An AI reviewer rejected this change because coverage is below the project minimum. Click to ask it to re-check.</span></>}
            source="plans/2026-05-add-auth.md"
            action="dontpanic resume vol-4f1a --re-verify"
          />
          <HomeAttentionRow
            band="blocked"
            title="Approval window expired during independent review"
            meta={<><Badge band="blocked">Blocked</Badge><span className="dp-mono">vol-9c33 · plan needs re-approval</span></>}
            source="plans/api-rewrite.md"
            action="dontpanic plan extend vol-9c33"
          />
        </Panel>

        <Panel
          kicker="02"
          title="Approvals awaiting you"
          action={<Chip variant="required">1 waiting</Chip>}
        >
          <HomeAttentionRow
            band="action"
            title="Review the billing change before it ships"
            meta={<><Badge band="action">Needs action</Badge><span>step 4 of 5 · review summary ready</span></>}
            source="evidence/vol-2b7e/packet.md"
            action="dontpanic review vol-2b7e"
            tail={<span className="dp-mono" style={{ color: 'var(--dp-text-muted)', fontSize: 11 }}>↑ 14m</span>}
          />
        </Panel>

        <Panel
          kicker="03"
          title="Setup needed for tools"
          action={<Chip variant="required">2 missing</Chip>}
        >
          <HomeAttentionRow
            band="action"
            title="OpenAI isn't connected — one of three reviewers is offline"
            meta={<><Badge band="action">Needs action</Badge><span>you set this up once</span></>}
            source="capabilities/openai.yaml"
            action="dontpanic caps setup openai"
          />
          <HomeAttentionRow
            band="pending"
            title="GitHub needs one extra permission for the final ready-to-deploy check"
            meta={<><Badge band="pending">Pending</Badge><span>repo:status scope missing</span></>}
            source="capabilities/github.yaml"
            action="dontpanic caps probe github"
          />
        </Panel>

        <Panel
          kicker="04"
          title="Data hasn't refreshed lately"
          action={<Chip variant="optional">just FYI</Chip>}
        >
          <HomeAttentionRow
            band="pending"
            title="System check hasn't run in 6 hours"
            meta={<><span>numbers on the Health page may be out of date</span><span className="dp-mono">last 14:22 UTC</span></>}
            source=".dontpanic/doctor.json"
            action="dontpanic doctor"
          />
        </Panel>
      </div>

      {/* RIGHT — volleys + next commands */}
      <div className="dp-stack">
        <Panel
          kicker="ACTIVE"
          title="AI reviews in flight"
          action={<span className="dp-mono dp-muted" style={{ fontSize: 11 }}>2 / 4 slots</span>}
        >
          <VolleyRow
            name="Add auth feature"
            file="plans/add-auth.md · vol-4f1a"
            model="claude-sonnet-4.5"
            agent="Code reviewer"
            step="independent review"
            gate={{ band: 'pending', label: 'Reviewing' }}
            elapsed="3m 12s"
          />
          <VolleyRow
            name="Refactor billing module"
            file="plans/billing-refactor.md · vol-2b7e"
            model="gpt-5-codex"
            agent="Quality check"
            step="your turn"
            gate={{ band: 'action', label: 'Awaiting you' }}
            elapsed="14m 03s"
          />
        </Panel>

        <Panel
          kicker="NEXT"
          title="What to do next"
          action={<span className="dp-mono dp-muted" style={{ fontSize: 11 }}>ranked by impact</span>}
        >
          <NextCommand
            rank="1"
            title="Re-run quality checks on Add auth"
            why="Coverage was close to the threshold. Re-running with the fix usually passes — nothing gets deployed."
            command="dontpanic resume vol-4f1a --re-verify"
            why2="// safe — re-verify only, no mutation"
          />
          <NextCommand
            rank="2"
            title="Connect OpenAI so reviewers are complete"
            why="One of three independent reviewers is offline. Approvals are more confident when all three are online."
            command="dontpanic caps setup openai --interactive"
          />
          <NextCommand
            rank="3"
            title="Approve or reject the billing change"
            why="It's been waiting 14 minutes. A quick look unblocks shipping."
            command="dontpanic review vol-2b7e --open"
          />
        </Panel>
      </div>
    </div>

    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source=".dontpanic/state.yaml + capabilities/*.yaml" updated="May 23 17:42:18" scope="silex-research/dontpanic@main" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only · no mutations</span>
    </footer>
  </Shell>
);

window.PageHome = PageHome;
