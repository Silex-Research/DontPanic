/* Work — board view. Plain-language stages, read-only by default,
   with an optional drag-to-command pattern that respects the read-only invariant.

   Lifecycle columns map to the DontPanic 5-stage flow from the brand poster:
     Plan Lock  →  Execute  →  Cross-Model Audit  →  Human Gate  →  Safe to Ship
   Translated to plain language for the operator:
     Draft      →  Working  →  Reviewing          →  Your turn   →  Shipped
*/

const PLAN_TYPES = {
  FEAT: { bg: 'rgba(139,111,255,0.13)', fg: '#B69CFF' },
  FIX:  { bg: 'rgba(245,166,35,0.13)',  fg: '#F5A623' },
  INFRA:{ bg: 'rgba(108,168,255,0.13)', fg: '#6CA8FF' },
  PERF: { bg: 'rgba(61,214,140,0.13)',  fg: '#3DD68C' },
};

const Avatar = ({ label, color = '#8B6FFF' }) => (
  <span style={{ width: 18, height: 18, borderRadius: 4, background: color, color: '#fff', fontSize: 9, fontWeight: 700, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', letterSpacing: 0.02, flexShrink: 0 }}>{label}</span>
);

const StageBar = ({ stage = 3, total = 5 }) => (
  <div style={{ display: 'flex', gap: 3, marginTop: 2 }}>
    {Array.from({ length: total }, (_, i) => (
      <div key={i} style={{
        flex: 1, height: 3, borderRadius: 1,
        background: i < stage ? 'var(--dp-brand)' : 'var(--dp-border-subtle)',
        opacity: i === stage - 1 ? 1 : i < stage ? 0.55 : 1,
      }} />
    ))}
  </div>
);

const PlanCard = ({ type, title, why, agents, elapsed, stage, total = 5, statusBand, statusLabel, dragging, ghost }) => (
  <div style={{
    background: ghost ? 'transparent' : 'var(--dp-bg-panel)',
    border: dragging ? '1px solid var(--dp-brand-edge)' : ghost ? '1px dashed var(--dp-border)' : '1px solid var(--dp-border-subtle)',
    boxShadow: dragging ? '0 12px 32px -10px rgba(91,63,224,0.55), 0 0 0 3px rgba(139,111,255,0.18)' : 'none',
    borderRadius: 5,
    padding: '10px 12px',
    opacity: ghost ? 0.45 : 1,
    transform: dragging ? 'rotate(-1.5deg)' : 'none',
    position: 'relative',
  }}>
    <div className="dp-row-flex" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
      <span style={{ padding: '1px 6px', borderRadius: 3, fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', background: PLAN_TYPES[type].bg, color: PLAN_TYPES[type].fg }}>{type}</span>
      <Pip band={statusBand} />
    </div>
    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--dp-text)', lineHeight: 1.35, marginBottom: 4 }}>{title}</div>
    {why && <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', lineHeight: 1.45, marginBottom: 8 }}>{why}</div>}
    <StageBar stage={stage} total={total} />
    <div className="dp-row-flex" style={{ justifyContent: 'space-between', marginTop: 8 }}>
      <span className="dp-row-flex" style={{ gap: 4 }}>
        {agents.map((a, i) => <Avatar key={i} label={a.short} color={a.color} />)}
        <span style={{ fontSize: 10, color: 'var(--dp-text-muted)', marginLeft: 4 }}>{agents.map(a => a.name).join(' · ')}</span>
      </span>
      <span className="dp-mono" style={{ fontSize: 10, color: 'var(--dp-text-dim)' }}>{elapsed}</span>
    </div>
    {statusLabel && (
      <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid var(--dp-border-subtle)' }}>
        <Badge band={statusBand}>{statusLabel}</Badge>
      </div>
    )}
  </div>
);

const BoardColumn = ({ name, kicker, count, band, hint, children, drop, dropLabel }) => (
  <div style={{
    background: 'var(--dp-bg-sunken)',
    border: drop ? '1px dashed var(--dp-brand-edge)' : '1px solid var(--dp-border-subtle)',
    borderRadius: 5,
    display: 'flex', flexDirection: 'column',
    minWidth: 0,
  }}>
    <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--dp-border-subtle)' }}>
      <div className="dp-row-flex" style={{ justifyContent: 'space-between' }}>
        <span className="dp-row-flex" style={{ gap: 6 }}>
          <Pip band={band} />
          <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--dp-text)' }}>{name}</span>
        </span>
        <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>{count}</span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 4 }}>{hint}</div>
    </div>
    <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minHeight: 0 }}>
      {drop && (
        <div style={{
          border: '1px dashed var(--dp-brand)', borderRadius: 4, padding: '14px 12px',
          background: 'rgba(139,111,255,0.06)', textAlign: 'center',
          fontSize: 11, color: 'var(--dp-brand)',
          display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center'
        }}>
          <IconArrowR size={14} sw={2} />
          <span>Drop to move to <strong>{dropLabel}</strong></span>
          <span style={{ color: 'var(--dp-text-muted)' }}>You'll get the exact command — nothing changes yet</span>
        </div>
      )}
      {children}
    </div>
  </div>
);

/* ──────────────────────────────────────────────────────────
   PAGE A — Read-only board, no drag affordance
   ────────────────────────────────────────────────────────── */
const PageWorkBoard = () => (
  <Shell active="work" height={1100} topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
    <PageHead
      kicker="WORK"
      title="Plans"
      sub="Board view · read-only · stage reflects the plan's frontmatter on disk"
      actions={
        <div className="dp-row-flex" style={{ gap: 8 }}>
          <div className="dp-row-flex" style={{ gap: 4, padding: 2, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4 }}>
            <button style={{ padding: '4px 10px', background: 'var(--dp-bg-elevated)', color: 'var(--dp-text)', borderRadius: 3, fontSize: 12, fontWeight: 600 }}>Board</button>
            <button style={{ padding: '4px 10px', color: 'var(--dp-text-muted)', borderRadius: 3, fontSize: 12 }}>List</button>
          </div>
          <button className="dp-cmd dp-cmd--inline" style={{ background: 'var(--dp-bg-panel)' }}>
            <IconFilter size={12} />
            <span style={{ fontFamily: 'var(--dp-font-sans)' }}>All types</span>
            <IconChevD size={11} />
          </button>
        </div>
      }
    />

    <div className="dp-page__body" style={{ padding: '16px 24px', overflow: 'auto' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 12, alignItems: 'stretch', height: '100%' }}>
        <BoardColumn name="DRAFT" count="3" band="pending" hint="Scope not yet approved">
          <PlanCard type="FEAT" title="reduce-token-spend.md" why="Cut Claude usage on the long-tail audits to save ~$40/wk."
            agents={[{ short: 'YOU', name: 'you', color: '#7E8BA6' }]} elapsed="2h" stage={0} total={5} statusBand="pending" />
          <PlanCard type="INFRA" title="migrate-vector-db.md" why="Move embeddings store from sqlite to Qdrant."
            agents={[{ short: 'YOU', name: 'you', color: '#7E8BA6' }]} elapsed="1d" stage={0} total={5} statusBand="pending" />
          <PlanCard type="FEAT" title="add-otel-traces.md" why="Trace cross-AI handoffs end-to-end."
            agents={[{ short: 'YOU', name: 'you', color: '#7E8BA6' }]} elapsed="3d" stage={0} total={5} statusBand="pending" />
        </BoardColumn>

        <BoardColumn name="WORKING" count="2" band="healthy" hint="An AI is doing the work">
          <PlanCard type="FEAT" title="rate-limiter.md" why="Add per-route rate limiting to prevent abuse."
            agents={[{ short: 'CL', name: 'Builder · Claude', color: '#D97757' }]} elapsed="14m" stage={2} total={5} statusBand="healthy" statusLabel="Executing" />
          <PlanCard type="FIX" title="prune-stale-tokens.md" why="Worker still references rotated keys — fix and redeploy."
            agents={[{ short: 'GR', name: 'Builder · Grok', color: '#5E6168' }]} elapsed="3m" stage={2} total={5} statusBand="healthy" statusLabel="Executing" />
        </BoardColumn>

        <BoardColumn name="REVIEWING" count="2" band="pending" hint="A second AI is double-checking">
          <PlanCard type="FEAT" title="add-auth.md" why="Magic-link auth for the public dashboard."
            agents={[
              { short: 'CL', name: 'Reviewer · Claude', color: '#D97757' },
              { short: 'GE', name: 'Devil\'s adv · Gemini', color: '#4E8CFF' },
            ]} elapsed="3m" stage={3} total={5} statusBand="blocked" statusLabel="Coverage 64%" />
          <PlanCard type="INFRA" title="api-rewrite.md" why="Move from Express to Hono. Big surface area."
            agents={[
              { short: 'CL', name: 'Reviewer · Claude', color: '#D97757' },
              { short: 'OA', name: 'Verifier · GPT-5', color: '#10A37F' },
            ]} elapsed="42m" stage={3} total={5} statusBand="blocked" statusLabel="Past approved scope" />
        </BoardColumn>

        <BoardColumn name="YOUR TURN" count="1" band="action" hint="Waiting on your approval">
          <PlanCard type="FEAT" title="billing-refactor.md" why="All checks passed. Summary is ready for your eye."
            agents={[
              { short: 'CL', name: 'Claude', color: '#D97757' },
              { short: 'OA', name: 'GPT-5', color: '#10A37F' },
              { short: 'GE', name: 'Gemini', color: '#4E8CFF' },
            ]} elapsed="14m" stage={4} total={5} statusBand="action" statusLabel="Review summary ready" />
        </BoardColumn>

        <BoardColumn name="SHIPPED" count="5 · 7d" band="healthy" hint="Approved and deployed">
          <PlanCard type="FEAT" title="cli-quickstart-banner.md" why=""
            agents={[{ short: 'CL', name: 'Claude', color: '#D97757' }]} elapsed="4h" stage={5} total={5} statusBand="healthy" />
          <PlanCard type="FIX" title="harden-cors-policy.md" why=""
            agents={[{ short: 'OA', name: 'GPT-5', color: '#10A37F' }]} elapsed="1d" stage={5} total={5} statusBand="healthy" />
          <PlanCard type="FIX" title="fix-error-redaction.md" why=""
            agents={[{ short: 'CL', name: 'Claude', color: '#D97757' }]} elapsed="2d" stage={5} total={5} statusBand="healthy" />
          <PlanCard type="PERF" title="add-rate-limit-tests.md" why=""
            agents={[{ short: 'GE', name: 'Gemini', color: '#4E8CFF' }]} elapsed="6d" stage={5} total={5} statusBand="healthy" />
        </BoardColumn>
      </div>
    </div>

    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="plans/*.md frontmatter" updated="14s ago" scope="silex-research/dontpanic@main" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only · stage updates when the underlying plan file changes</span>
    </footer>
  </Shell>
);

/* ──────────────────────────────────────────────────────────
   PAGE B — Drag-to-command (intent only; CLI still owns mutation)
   ────────────────────────────────────────────────────────── */
const DragCommandDrawer = () => (
  <div style={{
    position: 'absolute', right: 24, top: 130, width: 380,
    background: 'var(--dp-bg-panel)',
    border: '1px solid var(--dp-brand-edge)',
    borderRadius: 6,
    boxShadow: '0 18px 60px -16px rgba(91,63,224,0.55), 0 0 0 1px rgba(139,111,255,0.18)',
    padding: 16,
    zIndex: 10,
  }}>
    <div className="dp-row-flex" style={{ gap: 8, marginBottom: 10 }}>
      <IconShield size={14} sw={1.8} style={{ color: 'var(--dp-brand)' }} />
      <span className="dp-kicker" style={{ color: 'var(--dp-brand)' }}>INTENT → COMMAND</span>
    </div>
    <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Move <span className="dp-mono" style={{ color: 'var(--dp-text-soft)' }}>billing-refactor.md</span></div>
    <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', marginBottom: 14 }}>
      From <span style={{ color: 'var(--dp-action)', fontWeight: 600 }}>Your turn</span> → <span style={{ color: 'var(--dp-healthy)', fontWeight: 600 }}>Shipped</span> means approving the change. That's a decision only you can make — the dashboard never makes it silently.
    </div>

    <div className="dp-kicker" style={{ marginBottom: 6 }}>RUN ONE OF THESE</div>
    <div className="dp-stack-sm">
      <Cmd block>dontpanic review vol-2b7e --approve</Cmd>
      <div style={{ fontSize: 11, color: 'var(--dp-text-dim)', fontFamily: 'var(--dp-font-mono)' }}>// approves and merges</div>
      <div style={{ height: 4 }} />
      <Cmd block>dontpanic review vol-2b7e --request-changes</Cmd>
      <div style={{ fontSize: 11, color: 'var(--dp-text-dim)', fontFamily: 'var(--dp-font-mono)' }}>// sends back to working with your notes</div>
      <div style={{ height: 4 }} />
      <Cmd block>dontpanic review vol-2b7e --reject</Cmd>
      <div style={{ fontSize: 11, color: 'var(--dp-text-dim)', fontFamily: 'var(--dp-font-mono)' }}>// closes the plan without merging</div>
    </div>

    <div style={{ marginTop: 14, padding: 10, background: 'var(--dp-bg-sunken)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4, fontSize: 11, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>
      <strong style={{ color: 'var(--dp-text)' }}>Why this pattern?</strong> The dashboard is read-only by design. Dragging tells DontPanic what you'd <em>like</em> to do. Copying and running the command in your terminal is the only thing that actually changes state — so there's always an audit trail in your shell history.
    </div>

    <div className="dp-row-flex" style={{ gap: 8, marginTop: 12, justifyContent: 'flex-end' }}>
      <button style={{ padding: '5px 12px', fontSize: 12, color: 'var(--dp-text-muted)' }}>Cancel</button>
      <button style={{ padding: '5px 12px', fontSize: 12, fontWeight: 600, background: 'var(--dp-brand)', color: 'white', borderRadius: 4 }}>Copy first command</button>
    </div>
  </div>
);

const PageWorkBoardDrag = () => (
  <Shell active="work" height={1100} topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
    <PageHead
      kicker="WORK · DRAG-TO-COMMAND"
      title="Plans"
      sub="Dragging a card never mutates state. It reveals the exact command for the transition you want."
      actions={
        <div className="dp-row-flex" style={{ gap: 8 }}>
          <Chip variant="recommended">Drag mode</Chip>
        </div>
      }
    />

    <div className="dp-page__body" style={{ padding: '16px 24px', overflow: 'auto', position: 'relative' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 12, alignItems: 'stretch', height: '100%' }}>
        <BoardColumn name="DRAFT" count="3" band="pending" hint="Scope not yet approved">
          <PlanCard type="FEAT" title="reduce-token-spend.md" agents={[{ short: 'YOU', name: 'you', color: '#7E8BA6' }]} elapsed="2h" stage={0} total={5} statusBand="pending" />
          <PlanCard type="INFRA" title="migrate-vector-db.md" agents={[{ short: 'YOU', name: 'you', color: '#7E8BA6' }]} elapsed="1d" stage={0} total={5} statusBand="pending" />
        </BoardColumn>

        <BoardColumn name="WORKING" count="2" band="healthy" hint="An AI is doing the work">
          <PlanCard type="FEAT" title="rate-limiter.md" agents={[{ short: 'CL', name: 'Builder · Claude', color: '#D97757' }]} elapsed="14m" stage={2} total={5} statusBand="healthy" statusLabel="Executing" />
          <PlanCard type="FIX" title="prune-stale-tokens.md" agents={[{ short: 'GR', name: 'Builder · Grok', color: '#5E6168' }]} elapsed="3m" stage={2} total={5} statusBand="healthy" statusLabel="Executing" />
        </BoardColumn>

        <BoardColumn name="REVIEWING" count="2" band="pending" hint="A second AI is double-checking">
          <PlanCard type="FEAT" title="add-auth.md"
            agents={[{ short: 'CL', name: 'Reviewer · Claude', color: '#D97757' }, { short: 'GE', name: 'Devil\'s adv · Gemini', color: '#4E8CFF' }]}
            elapsed="3m" stage={3} total={5} statusBand="blocked" statusLabel="Coverage 64%" />
          {/* Ghost placeholder where billing-refactor was */}
          <PlanCard type="FEAT" title="billing-refactor.md" why="(being moved)" ghost
            agents={[{ short: 'CL', name: '', color: '#D97757' }]} elapsed="14m" stage={4} total={5} statusBand="pending" />
        </BoardColumn>

        <BoardColumn name="YOUR TURN" count="1" band="action" hint="Waiting on your approval">
          {/* Card mid-drag floating */}
          <div style={{ position: 'relative' }}>
            <PlanCard
              type="FEAT" title="billing-refactor.md"
              why="All checks passed. Summary is ready for your eye."
              agents={[
                { short: 'CL', name: 'Claude', color: '#D97757' },
                { short: 'OA', name: 'GPT-5', color: '#10A37F' },
                { short: 'GE', name: 'Gemini', color: '#4E8CFF' },
              ]}
              elapsed="14m" stage={4} total={5} statusBand="action" statusLabel="Review summary ready"
              dragging
            />
          </div>
        </BoardColumn>

        <BoardColumn name="SHIPPED" count="5 · 7d" band="healthy" hint="Approved and deployed" drop dropLabel="Shipped">
          <PlanCard type="FEAT" title="cli-quickstart-banner.md" agents={[{ short: 'CL', name: 'Claude', color: '#D97757' }]} elapsed="4h" stage={5} total={5} statusBand="healthy" />
          <PlanCard type="FIX" title="harden-cors-policy.md" agents={[{ short: 'OA', name: 'GPT-5', color: '#10A37F' }]} elapsed="1d" stage={5} total={5} statusBand="healthy" />
        </BoardColumn>
      </div>

      <DragCommandDrawer />
    </div>

    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="plans/*.md frontmatter" updated="14s ago" scope="silex-research/dontpanic@main" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>drag = intent · CLI = mutation · always an audit trail in shell history</span>
    </footer>
  </Shell>
);

/* ──────────────────────────────────────────────────────────
   ANNOTATION ARTBOARD — explains the design choice in one place
   ────────────────────────────────────────────────────────── */
const PageWorkBoardNotes = () => (
  <div className="dp" style={{ width: 1440, padding: '32px 36px', background: 'var(--dp-bg-base)' }}>
    <div className="dp-kicker" style={{ marginBottom: 8 }}>WORK · BOARD VIEW · DESIGN NOTES</div>
    <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 6 }}>Bringing back the kanban without breaking the read-only invariant</h1>
    <p style={{ color: 'var(--dp-text-muted)', fontSize: 13, marginBottom: 24, maxWidth: 760 }}>
      The v0 brief said no drag/drop. The reason is sound: dashboards that silently mutate production state are dangerous when the things being moved are autonomous AI changes. But the visual stage-scanning a board gives you is genuinely useful. Here's how to keep both.
    </p>

    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 22 }}>
      <div style={{ padding: 18, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderLeft: '3px solid var(--dp-healthy)', borderRadius: 5 }}>
        <div className="dp-kicker" style={{ marginBottom: 8, color: 'var(--dp-healthy)' }}>OPTION A · READ-ONLY BOARD <em style={{ color: 'var(--dp-text-muted)' }}>(default)</em></div>
        <div style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--dp-text-soft)' }}>
          Five columns mapped to the 5-stage flow from the brand poster. Cards show plan name, why-it-matters one-liner, current step bar, agent avatars, elapsed time, and a status band when something needs attention.
          <br /><br />
          Stage transitions happen because the underlying plan file changed — DontPanic re-reads frontmatter on the auto-refresh interval and re-positions the card. <strong style={{ color: 'var(--dp-text)' }}>No drag affordance.</strong> No mutation surface. Matches the v0 invariant exactly.
        </div>
      </div>

      <div style={{ padding: 18, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderLeft: '3px solid var(--dp-brand)', borderRadius: 5 }}>
        <div className="dp-kicker" style={{ marginBottom: 8, color: 'var(--dp-brand)' }}>OPTION B · DRAG-TO-COMMAND <em style={{ color: 'var(--dp-text-muted)' }}>(opt-in)</em></div>
        <div style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--dp-text-soft)' }}>
          You drag a card to another column. A drawer slides up with the <em>exact CLI commands</em> that would make that transition, with copy buttons.
          <br /><br />
          <strong style={{ color: 'var(--dp-text)' }}>The dashboard never makes the change.</strong> You run the command in your terminal. State only moves when the underlying plan file does. The drag is intent-capture — a fast way to ask "what does it take to move this to Shipped?" without grepping the docs.
        </div>
      </div>
    </div>

    <div style={{ padding: 18, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5 }}>
      <div className="dp-kicker" style={{ marginBottom: 10 }}>WHY THE DRAG-TO-COMMAND PATTERN IS SAFE</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
        <div>
          <div className="dp-row-flex" style={{ gap: 8, marginBottom: 4 }}>
            <IconShield size={13} sw={1.8} style={{ color: 'var(--dp-brand)' }} />
            <strong style={{ fontSize: 13 }}>Mutation lives in the CLI</strong>
          </div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>The dashboard is still read-only at the trust boundary. State changes flow through <span className="dp-mono">dontpanic …</span> commands, which already have auth, dry-run, and confirmation built in.</div>
        </div>
        <div>
          <div className="dp-row-flex" style={{ gap: 8, marginBottom: 4 }}>
            <IconDoc size={13} sw={1.8} style={{ color: 'var(--dp-brand)' }} />
            <strong style={{ fontSize: 13 }}>Audit trail in shell history</strong>
          </div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>Every transition has a paper trail outside DontPanic — in your terminal history, your team's shared bastion, your CI logs. Drag-and-drop in a browser leaves no such trace.</div>
        </div>
        <div>
          <div className="dp-row-flex" style={{ gap: 8, marginBottom: 4 }}>
            <IconUser size={13} sw={1.8} style={{ color: 'var(--dp-brand)' }} />
            <strong style={{ fontSize: 13 }}>Human-in-the-loop, by construction</strong>
          </div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>You can't accidentally approve a billing change by mis-clicking. The drag opens a drawer; the drawer hands you a command; you decide whether to run it.</div>
        </div>
      </div>
    </div>

    <div style={{ marginTop: 22, padding: 14, background: 'var(--dp-bg-sunken)', border: '1px dashed var(--dp-border)', borderRadius: 5, fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>
      <strong style={{ color: 'var(--dp-text)' }}>Implementation note:</strong> the read-only board needs only the existing <span className="dp-mono">.mc-card</span> markup re-grouped into 5 columns by frontmatter <span className="dp-mono">status</span>. The drag-to-command pattern needs a small HTML5 drag handler that opens a positioned drawer — no backend changes, no new state machine, just a lookup of "from column X to column Y → these CLI commands."
    </div>
  </div>
);

Object.assign(window, { PageWorkBoard, PageWorkBoardDrag, PageWorkBoardNotes, PlanCard, BoardColumn });
