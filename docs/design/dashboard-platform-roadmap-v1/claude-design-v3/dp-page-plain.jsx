/* Plain-language pass — rewrites jargon, leads with value */

/* ──────────────────────────────────────────────────────────
   VALUE STRIP — three variants. Pick one for the top of Home.
   ────────────────────────────────────────────────────────── */
const ValueStat = ({ value, label, color = 'var(--dp-healthy)' }) => (
  <div style={{ minWidth: 0 }}>
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
      <span style={{ fontSize: 22, fontWeight: 600, color, fontFamily: 'var(--dp-font-mono)' }}>{value}</span>
    </div>
    <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 2 }}>{label}</div>
  </div>
);

const ValueStripA = () => (
  <div style={{ background: 'linear-gradient(180deg, rgba(139,111,255,0.07) 0%, transparent 100%)', border: '1px solid rgba(139,111,255,0.22)', borderRadius: 5, padding: '14px 18px', display: 'flex', alignItems: 'center', gap: 22, rowGap: 14, flexWrap: 'wrap' }}>
    <div className="dp-mark" style={{ width: 30, height: 30, flexShrink: 0 }}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l8 4v6c0 4.5-3.5 7-8 8-4.5-1-8-3.5-8-8V7l8-4z" /><path d="m9 12 2.2 2.2L15.5 10" /></svg>
    </div>
    <div style={{ flex: '1 1 320px', minWidth: 280 }}>
      <div style={{ fontSize: 13, color: 'var(--dp-text-soft)', lineHeight: 1.45 }}>
        <span style={{ color: 'var(--dp-text)', fontWeight: 600 }}>Today DontPanic protected your codebase.</span>
        {' '}Reviewed 14 AI changes · caught <span style={{ color: 'var(--dp-action)' }}>2 issues</span> · held <span style={{ color: 'var(--dp-blocked)' }}>1 risky change</span> for you to look at.
      </div>
    </div>
    <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexShrink: 0 }}>
      <ValueStat value="14" label="reviewed" color="var(--dp-text)" />
      <div style={{ width: 1, height: 28, background: 'var(--dp-border-subtle)' }} />
      <ValueStat value="2" label="caught" color="var(--dp-action)" />
      <div style={{ width: 1, height: 28, background: 'var(--dp-border-subtle)' }} />
      <ValueStat value="1" label="held for you" color="var(--dp-blocked)" />
      <div style={{ width: 1, height: 28, background: 'var(--dp-border-subtle)' }} />
      <ValueStat value="$8.40" label="tokens today" color="var(--dp-healthy)" />
    </div>
  </div>
);

const ValueStripB = () => (
  <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, padding: '12px 18px', display: 'flex', alignItems: 'center', gap: 14 }}>
    <IconShield size={16} sw={1.8} style={{ color: 'var(--dp-brand)' }} />
    <div style={{ fontSize: 13, color: 'var(--dp-text-soft)' }}>
      <strong style={{ color: 'var(--dp-text)' }}>Nothing has shipped without your approval.</strong>
      {' '}Your AI is working on 2 things. 1 is ready for you to look at — the other is being double-checked.
    </div>
  </div>
);

const ValueStripC = () => (
  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
    <div style={{ padding: '12px 14px', background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderLeft: '3px solid var(--dp-healthy)', borderRadius: 4 }}>
      <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 600 }}>Protected</div>
      <div style={{ fontSize: 13, color: 'var(--dp-text)', marginTop: 4 }}>Nothing has reached production today without going through review.</div>
    </div>
    <div style={{ padding: '12px 14px', background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderLeft: '3px solid var(--dp-action)', borderRadius: 4 }}>
      <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 600 }}>Caught</div>
      <div style={{ fontSize: 13, color: 'var(--dp-text)', marginTop: 4 }}>2 issues spotted in the last hour. Both were fixable.</div>
    </div>
    <div style={{ padding: '12px 14px', background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderLeft: '3px solid var(--dp-brand)', borderRadius: 4 }}>
      <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 600 }}>Saved</div>
      <div style={{ fontSize: 13, color: 'var(--dp-text)', marginTop: 4 }}>~42 minutes of review work, this week.</div>
    </div>
  </div>
);

/* ──────────────────────────────────────────────────────────
   HOME — plain language rewrite
   ────────────────────────────────────────────────────────── */
const PlainAttentionRow = ({ band, title, why, source, action, tail }) => (
  <div className="dp-row" style={{ gridTemplateColumns: '8px 1fr auto', padding: '13px 16px' }}>
    <Pip band={band} />
    <div className="dp-stack-sm" style={{ minWidth: 0 }}>
      <div style={{ color: 'var(--dp-text)', fontWeight: 500 }}>{title}</div>
      {why && <div style={{ fontSize: 12, color: 'var(--dp-text-muted)' }}>{why}</div>}
      {source && <div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>in {source}</div>}
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

const PlainTaskRow = ({ name, who, what, gate, elapsed }) => (
  <div className="dp-row" style={{ gridTemplateColumns: '1fr auto', padding: '11px 14px', alignItems: 'flex-start' }}>
    <div className="dp-stack-sm" style={{ minWidth: 0 }}>
      <div className="dp-row-flex" style={{ gap: 8 }}>
        <span style={{ fontWeight: 600 }}>{name}</span>
      </div>
      <div style={{ fontSize: 12, color: 'var(--dp-text-muted)' }}>{what}</div>
      <div style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>{who}</div>
    </div>
    <div style={{ textAlign: 'right' }} className="dp-stack-sm">
      <Badge band={gate.band}>{gate.label}</Badge>
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>{elapsed}</span>
    </div>
  </div>
);

const PlainNextStep = ({ rank, title, why, command }) => (
  <div style={{ padding: '13px 14px', borderTop: '1px solid var(--dp-border-subtle)' }}>
    <div className="dp-row-flex" style={{ gap: 8, marginBottom: 4 }}>
      <span className="dp-mono" style={{ width: 18, height: 18, borderRadius: 4, background: 'var(--dp-brand-soft)', color: 'var(--dp-brand)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700 }}>{rank}</span>
      <span style={{ fontWeight: 600 }}>{title}</span>
    </div>
    <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', marginBottom: 8 }}>{why}</div>
    <Cmd block>{command}</Cmd>
  </div>
);

const PageHomePlain = () => (
  <Shell active="home" height={1180} topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
    <PageHead
      kicker="HOME"
      title="Hi — here's what to look at"
      sub="3 things need your eye. Your AI is working on 2 more in the background."
      actions={
        <button className="dp-cmd dp-cmd--inline" style={{ background: 'transparent' }}>
          <IconRefresh size={12} />
          <span style={{ fontFamily: 'var(--dp-font-sans)' }}>Refresh</span>
        </button>
      }
    />

    <div className="dp-page__body" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 380px', gap: 16, padding: '16px 24px', alignContent: 'start' }}>
      {/* LEFT */}
      <div className="dp-stack" style={{ gap: 14 }}>
        <ValueStripA />

        <Panel
          kicker="01"
          title="Stuck — you need to unblock these"
          action={<Chip variant="required">2 stuck</Chip>}
        >
          <PlainAttentionRow
            band="blocked"
            title="Tests don't cover enough of the new code yet"
            why="The quality check found 64% coverage on this change — your project requires 80% before shipping."
            source="plans/add-auth.md"
            action="dontpanic resume vol-4f1a --re-verify"
          />
          <PlainAttentionRow
            band="blocked"
            title="This plan ran past its approved scope"
            why="The work crossed the line of what you originally approved. Either extend the plan, or trim the changes."
            source="plans/api-rewrite.md"
            action="dontpanic plan extend vol-9c33"
          />
        </Panel>

        <Panel
          kicker="02"
          title="Waiting on your decision"
          action={<Chip variant="required">1 waiting</Chip>}
        >
          <PlainAttentionRow
            band="action"
            title="A change to billing is ready for you to approve"
            why="The AI thinks it's done. We've prepared a summary of what changed and why. Open it to approve, reject, or request changes."
            source="plans/billing-refactor.md"
            action="dontpanic review vol-2b7e"
            tail={<span className="dp-mono" style={{ color: 'var(--dp-text-muted)', fontSize: 11 }}>↑ 14m</span>}
          />
        </Panel>

        <Panel
          kicker="03"
          title="Connections that need setting up"
          action={<Chip variant="required">2 missing</Chip>}
        >
          <PlainAttentionRow
            band="action"
            title="OpenAI is missing — your code reviewer can't run without it"
            why="DontPanic uses OpenAI to double-check work from other AIs. Without it, you lose one of three independent reviewers."
            source="OpenAI account · you set this up once"
            action="dontpanic caps setup openai"
          />
          <PlainAttentionRow
            band="pending"
            title="GitHub needs one extra permission"
            why="With it, DontPanic can confirm a change is safe to merge. Without it, the final check is degraded but everything else works."
            source="GitHub personal access token"
            action="dontpanic caps probe github"
          />
        </Panel>

        <Panel
          kicker="04"
          title="Data is a bit stale"
          action={<Chip variant="optional">just FYI</Chip>}
        >
          <PlainAttentionRow
            band="pending"
            title="The system check hasn't run in 6 hours"
            why="Numbers on the Health page may be out of date. Re-run it when you have a moment."
            source="system check"
            action="dontpanic doctor"
          />
        </Panel>
      </div>

      {/* RIGHT */}
      <div className="dp-stack" style={{ gap: 14 }}>
        <Panel
          kicker="WORKING ON"
          title="Your AI's current tasks"
          action={<span className="dp-mono dp-muted" style={{ fontSize: 11 }}>2 of 4 slots used</span>}
        >
          <PlainTaskRow
            name="add-auth.md"
            who="Reviewer: Claude · Devil's advocate: Gemini"
            what="Step 3 of 5 — a second AI is reviewing the first AI's work."
            gate={{ band: 'pending', label: 'Reviewing' }}
            elapsed="3m 12s"
          />
          <PlainTaskRow
            name="billing-refactor.md"
            who="All checks complete · waiting on you"
            what="Step 4 of 5 — your turn to look at the summary and decide."
            gate={{ band: 'action', label: 'Your turn' }}
            elapsed="14m 03s"
          />
        </Panel>

        <Panel
          kicker="WHAT TO DO NEXT"
          title="Top 3, ranked by impact"
        >
          <PlainNextStep
            rank="1"
            title="Re-run quality checks on add-auth"
            why="The coverage was close to the threshold. A re-run with the fix often passes — safe to try, nothing gets deployed."
            command="dontpanic resume vol-4f1a --re-verify"
          />
          <PlainNextStep
            rank="2"
            title="Connect OpenAI so reviewers are complete"
            why="One of three independent reviewers is offline. You'll get more confident approvals when all three are online."
            command="dontpanic caps setup openai --interactive"
          />
          <PlainNextStep
            rank="3"
            title="Approve or reject the billing change"
            why="It's been waiting 14 minutes. A quick look unblocks shipping."
            command="dontpanic review vol-2b7e --open"
          />
        </Panel>
      </div>
    </div>

    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="your project files" updated="May 23 17:42:18" scope="silex-research/dontpanic@main" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>DontPanic only suggests · nothing changes without you</span>
    </footer>
  </Shell>
);

/* ──────────────────────────────────────────────────────────
   VALUE STRIP VARIANTS — design choices for the user
   ────────────────────────────────────────────────────────── */
const PageValueStrips = () => (
  <div className="dp" style={{ width: 1440, padding: '32px 36px', background: 'var(--dp-bg-base)' }}>
    <div className="dp-kicker" style={{ marginBottom: 8 }}>PLAIN-LANGUAGE PASS · A</div>
    <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 6 }}>Value strip — three flavors for the top of Home</h1>
    <p style={{ color: 'var(--dp-text-muted)', fontSize: 13, marginBottom: 22, maxWidth: 760 }}>
      A non-technical operator needs to feel — within 1 second of landing — that DontPanic is <em>protecting</em> them, not just monitoring stuff. Pick whichever tone fits the brand voice.
    </p>

    <div className="dp-stack" style={{ gap: 22 }}>
      <div>
        <div className="dp-kicker" style={{ marginBottom: 8 }}>VARIANT A · OUTCOMES + STATS — "Today DontPanic protected your codebase."</div>
        <ValueStripA />
        <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', marginTop: 8, maxWidth: 760, lineHeight: 1.55 }}>
          Best when you have real numbers to show. The sentence does the value-prop work; the stats give it teeth. Recommended default.
        </div>
      </div>

      <div>
        <div className="dp-kicker" style={{ marginBottom: 8 }}>VARIANT B · ONE-LINE REASSURANCE — minimal, calmer</div>
        <ValueStripB />
        <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', marginTop: 8, maxWidth: 760, lineHeight: 1.55 }}>
          For users who don't want a "stats bar" — a single sentence that says <em>nothing-has-shipped-without-you</em>. The single most important promise DontPanic makes.
        </div>
      </div>

      <div>
        <div className="dp-kicker" style={{ marginBottom: 8 }}>VARIANT C · THREE CARDS — Protected / Caught / Saved</div>
        <ValueStripC />
        <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', marginTop: 8, maxWidth: 760, lineHeight: 1.55 }}>
          For users who scan rather than read. Each card maps to a business outcome. Useful if leadership ever looks over the operator's shoulder.
        </div>
      </div>
    </div>

    <div style={{ marginTop: 30, padding: 18, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5 }}>
      <div className="dp-kicker" style={{ marginBottom: 8 }}>WRITING RULES — apply across every page</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Lead with the outcome</div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>"Tests don't cover enough of the new code yet" — not "Verifier failed: coverage below threshold." The system's internals are a footnote, not the headline.</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Name the user benefit on every panel</div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>"Waiting on your decision" — not "Active gates." The panel title should answer "why am I looking at this?"</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Explain <em>why</em> in one short sentence</div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>Under every attention row, a single sentence saying why this matters and what happens if you ignore it.</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Keep the command, hide the jargon</div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>Power users still see the exact CLI. But the row title and the description never mention "volley" or "audit" or "probe" — those terms only appear inside the command itself.</div>
        </div>
      </div>
    </div>
  </div>
);

/* ──────────────────────────────────────────────────────────
   GLOSSARY — the jargon → plain mappings
   ────────────────────────────────────────────────────────── */
const GlossRow = ({ tech, plain, when, color }) => (
  <tr>
    <td style={{ padding: '12px 16px', borderTop: '1px solid var(--dp-border-subtle)', verticalAlign: 'top', fontFamily: 'var(--dp-font-mono)', fontSize: 13, color: color || 'var(--dp-text-soft)' }}>{tech}</td>
    <td style={{ padding: '12px 16px', borderTop: '1px solid var(--dp-border-subtle)', verticalAlign: 'top', fontSize: 13, color: 'var(--dp-text)' }}>{plain}</td>
    <td style={{ padding: '12px 16px', borderTop: '1px solid var(--dp-border-subtle)', verticalAlign: 'top', fontSize: 12, color: 'var(--dp-text-muted)' }}>{when}</td>
  </tr>
);

const PageGlossary = () => (
  <div className="dp" style={{ width: 1440, padding: '32px 36px', background: 'var(--dp-bg-base)' }}>
    <div className="dp-kicker" style={{ marginBottom: 8 }}>PLAIN-LANGUAGE PASS · B</div>
    <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 6 }}>Vocabulary translation</h1>
    <p style={{ color: 'var(--dp-text-muted)', fontSize: 13, marginBottom: 22, maxWidth: 760 }}>
      Every jargon term that should disappear from the UI surface, paired with the plain-language phrase that replaces it. The technical terms can still live in the CLI, in config files, and in expanded tooltips — they should not be in panel titles, row headlines, or empty-state copy.
    </p>

    <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, overflow: 'hidden' }}>
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--dp-border-subtle)', display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>The translations</span>
        <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>17 nouns · 6 verbs</span>
      </div>
      <table className="dp-table">
        <thead>
          <tr>
            <th style={{ width: '24%' }}>Technical term</th>
            <th style={{ width: '34%' }}>Plain language</th>
            <th>Where it appears now → where it goes</th>
          </tr>
        </thead>
        <tbody>
          <GlossRow tech="Volley" plain="Task / Run" when="Was: 'volleys in flight'. Becomes: 'tasks in progress.' The token vol-2b7e stays in URLs and CLI but never headlines a panel." />
          <GlossRow tech="Gate" plain="Step / Check" when="Was: 'active gates.' Becomes: 'steps' (the 5-stage flow) or 'check' (one of several reviewers)." />
          <GlossRow tech="Plan lock" plain="Approved scope" when="Was: 'plan lock expired.' Becomes: 'the work ran past your approved scope.' Reflects what the user actually cares about: was this in or out of bounds?" />
          <GlossRow tech="Cross-model audit" plain="Independent review" when="Was: 'cross-model audit · 3 agents.' Becomes: 'a second AI reviews the first AI's work.' The 'cross-model' detail goes into hover/tooltip." />
          <GlossRow tech="Verifier agent" plain="Quality check" when="Was: 'verifier agent failed.' Becomes: 'the quality check found 64% coverage.' Same data, named for what it does." />
          <GlossRow tech="Reviewer agent" plain="Code reviewer" when="Same pattern — describe the role to the user, not the implementation." />
          <GlossRow tech="Challenger agent" plain="Devil's advocate" when="Plays best with non-technical operators. Tooltip: 'an AI explicitly asked to argue against the first AI's choices.'" />
          <GlossRow tech="Capability" plain="Connection" when="Was: 'capability readiness.' Becomes: 'connections that need setting up.' The word 'capability' is engineer-speak." />
          <GlossRow tech="Probe" plain="Connection check" when="Was: 'never probed.' Becomes: 'we haven't checked this yet.' Verb form: 'check the connection.'" />
          <GlossRow tech="Safe to ship" plain="Ready to deploy" when="Slightly more familiar in the broader software world. Keep 'safe-to-ship' as a section heading where space is tight." />
          <GlossRow tech="Evidence packet" plain="Review summary" when="Was: 'evidence packet for billing changes.' Becomes: 'summary of what changed and why' — the actual contents." />
          <GlossRow tech="Doctor" plain="System check" when="Doctor is fine in the CLI ('dontpanic doctor'). Not in the UI: 'system check' is universally understood." />
          <GlossRow tech="Reconcile" plain="Sync check" when="Was: 'reconcile state ↔ disk.' Becomes: 'sync check — does what's in memory match what's on disk?'" />
          <GlossRow tech="MCP" plain="Connected tool" when="Almost no operator knows what MCP stands for. Use 'connected tool' or just name the tool (Filesystem, Linear, etc.)." />
          <GlossRow tech="Frontmatter" plain="Plan details" when="The yaml block at the top of a plan file. Just call it 'plan details' in the UI." />
          <GlossRow tech="Owner boundary" plain="Who handles this" when="Was: 'owner boundary: you / DontPanic / vendor.' Becomes: 'who handles this: you' / 'we do it for you' / 'your vendor's responsibility.'" />
          <GlossRow tech="Provenance" plain="Source · last updated" when="The word 'provenance' only appears in design docs and museum catalogs. Two plain labels do the same job." />
          <GlossRow tech="Probe failure" plain="We couldn't reach it" when="Verb: 'probe failed' → 'we tried to reach it and couldn't.' Calmer, more actionable." />
          <GlossRow tech="Stale data" plain="Last updated N ago" when="Don't editorialize — just show how long since the data refreshed. The user decides if that's stale enough to worry about." />
          <GlossRow tech="Plan budget" plain="Approved token cap" when="Was: 'budget_tokens: 1.2M.' Becomes: 'cap: 1.2M tokens · 71% used.'" />
        </tbody>
      </table>
    </div>

    <div style={{ marginTop: 22, padding: 18, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderLeft: '3px solid var(--dp-brand)', borderRadius: 5 }}>
      <div className="dp-kicker" style={{ marginBottom: 6, color: 'var(--dp-brand)' }}>RULE OF THUMB</div>
      <div style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--dp-text-soft)' }}>
        If a non-developer can't read a section heading out loud and explain what it's for in one sentence, the heading is wrong. The CLI is a power-user surface; the dashboard is a calm-down surface.
      </div>
    </div>
  </div>
);

Object.assign(window, { PageHomePlain, PageValueStrips, PageGlossary, ValueStripA, ValueStripB, ValueStripC });
