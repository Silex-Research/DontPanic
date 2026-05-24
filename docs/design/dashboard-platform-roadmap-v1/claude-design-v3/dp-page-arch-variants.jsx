/* Architecture variants — fulfills Section 2.3, 2.4, 2.5, 2.6, 2.11 and Section 3.1 / 3.3 of the brief.
   Reuses ARCH_NODES, arrowPath, ArchNode, FlowItem, StepItem from dp-page-architecture.jsx. */

const ArchCanvasFrame = ({ children, action }) => (
  <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 6, padding: '14px 18px', display: 'flex', flexDirection: 'column', minWidth: 0, position: 'relative', flex: 1 }}>
    {action}
    {children}
  </div>
);

// Render the architecture diagram with optional highlighted flow + clicked node
const ArchDiagram = ({ flowEdges = [], clickedNodeId, fadeAll }) => {
  const archW = GRID_PAD_X * 2 + 7 * COL_W + 6 * COL_GAP;
  const archH = GRID_PAD_Y + 5 * (NODE_H + NODE_GAP) + 24;
  return (
    <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
      <div style={{ position: 'relative', width: archW, height: archH, transform: 'scale(0.92)', transformOrigin: 'top left', opacity: fadeAll ? 0.7 : 1 }}>
        {COL_LABELS.map((cl, i) => (
          <div key={i} className="dp-kicker" style={{ position: 'absolute', left: GRID_PAD_X + i * (COL_W + COL_GAP), top: 14, width: COL_W, fontSize: 9, letterSpacing: '0.14em', color: 'var(--dp-text-muted)' }}>{cl}</div>
        ))}
        {COL_LABELS.map((_, i) => i < COL_LABELS.length - 1 && (
          <div key={`d-${i}`} style={{ position: 'absolute', left: GRID_PAD_X + i * (COL_W + COL_GAP) + COL_W + COL_GAP / 2, top: 0, bottom: 0, width: 1, background: 'var(--dp-border-subtle)', opacity: 0.4 }} />
        ))}
        <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
          <defs>
            <marker id="vbg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 Z" fill="#344163" /></marker>
            <marker id="vhi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 Z" fill="#F5A623" /></marker>
            <marker id="vpurp" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 Z" fill="#8B6FFF" /></marker>
          </defs>
          {ARCH_EDGES_BG.map(([a, b], i) => {
            const isHi = flowEdges.some(s => s.from === a && s.to === b);
            if (isHi) return null;
            return <path key={i} d={arrowPath(a, b)} fill="none" stroke="#344163" strokeWidth="1" opacity={fadeAll ? 0.4 : 0.35} markerEnd="url(#vbg)" />;
          })}
          {flowEdges.map((s, i) => (
            <path key={`h-${i}`} d={arrowPath(s.from, s.to)} fill="none" stroke="#F5A623" strokeWidth={s.dashed ? 1.2 : 2} strokeDasharray={s.dashed ? '3 3' : 'none'} opacity={s.dashed ? 0.5 : 0.95} markerEnd={s.dashed ? null : 'url(#vhi)'} />
          ))}
          {flowEdges.filter(s => !s.dashed).map((s, i) => {
            const f = ARCH_NODES[s.from], t = ARCH_NODES[s.to];
            const fp = nodePos(f), tp = nodePos(t);
            const mx = (fp.x + COL_W + tp.x) / 2, my = (fp.y + NODE_H / 2 + tp.y + NODE_H / 2) / 2;
            return (
              <g key={`hn-${i}`}>
                <circle cx={mx} cy={my} r="9" fill="#0A0E17" stroke="#F5A623" strokeWidth="1.5" />
                <text x={mx} y={my + 3} textAnchor="middle" fontSize="10" fontWeight="700" fill="#F5A623" fontFamily="var(--dp-font-mono)">{s.step}</text>
              </g>
            );
          })}
          {/* Clicked-node glow */}
          {clickedNodeId && ARCH_NODES[clickedNodeId] && (() => {
            const n = ARCH_NODES[clickedNodeId];
            const p = nodePos(n);
            return <rect x={p.x - 4} y={p.y - 4} width={COL_W + 8} height={NODE_H + 8} rx="6" fill="none" stroke="#8B6FFF" strokeWidth="2" opacity="0.9" />;
          })()}
        </svg>
        {Object.entries(ARCH_NODES).map(([id, n]) => {
          const highlighted = flowEdges.some(s => s.from === id || s.to === id) && !n.muted;
          return <ArchNode key={id} id={id} n={n} highlighted={highlighted} />;
        })}
      </div>
    </div>
  );
};

const RightRail = ({ children }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minHeight: 0 }}>{children}</div>
);

const FlowsPanel = ({ items, activeIdx }) => (
  <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 6, flexShrink: 0 }}>
    <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--dp-border-subtle)' }}>
      <div className="dp-kicker">FLOWS</div>
      <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 2 }}>Pick one to highlight the path</div>
    </div>
    {items.map((it, i) => <FlowItem key={i} {...it} active={i === activeIdx} />)}
  </div>
);


/* ──────────────────────────────────────────────────────────
   ① NEUTRAL / NOTHING-SELECTED STATE (Section 2.3)
   ────────────────────────────────────────────────────────── */
const PageArchNeutral = () => (
  <Shell active="arch" height={1100} topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
    <PageHead
      kicker="ARCHITECTURE"
      title="How DontPanic protects your codebase"
      sub="Default state · pick a flow on the right to trace a path"
      actions={
        <div className="dp-row-flex" style={{ gap: 8 }}>
          <div className="dp-row-flex" style={{ gap: 6, padding: '4px 10px', background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4, minWidth: 240 }}>
            <IconSearch size={12} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} />
            <input placeholder="Search…" style={{ background: 'transparent', border: 'none', outline: 'none', flex: 1, color: 'var(--dp-text)', fontSize: 12 }} />
            <kbd style={{ fontSize: 10, color: 'var(--dp-text-dim)', fontFamily: 'var(--dp-font-mono)', padding: '1px 5px', border: '1px solid var(--dp-border-subtle)', borderRadius: 3 }}>/</kbd>
          </div>
        </div>
      }
    />
    <div className="dp-page__body" style={{ padding: '14px 24px', display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 340px', gap: 14, overflow: 'hidden' }}>
      <ArchCanvasFrame>
        <div className="dp-row-flex" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Governance Layer</div>
            <div style={{ fontSize: 12, color: 'var(--dp-text-muted)' }}>28 nodes · 41 connections · no flow selected</div>
          </div>
          <Legend items={[
            { color: '#F25555', label: 'Human' }, { color: '#8B6FFF', label: 'AI agent' },
            { color: '#7E8BA6', label: 'Data' }, { color: '#F5A623', label: 'Decision' },
            { color: '#3DD68C', label: 'External' },
          ]} />
        </div>
        <ArchDiagram flowEdges={[]} fadeAll />
      </ArchCanvasFrame>

      <RightRail>
        <FlowsPanel items={[
          { name: 'Lock the scope of a change', sub: 'Plan → lock', source: 'authored' },
          { name: 'An AI does the work', sub: 'Builder runs the locked plan', source: 'authored' },
          { name: 'Cross-model audit', sub: 'Three AIs review the diff', source: 'authored' },
          { name: 'Human gate', sub: 'You approve or reject', source: 'authored' },
          { name: 'Safe to ship', sub: 'Approved → CI/CD → production', source: 'authored' },
          { name: 'Dashboard build & open', sub: 'Derived from imports', source: 'derived' },
        ]} activeIdx={-1} />

        <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 6, flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div style={{ textAlign: 'center', maxWidth: 280 }}>
            <IconArch size={28} sw={1.4} style={{ color: 'var(--dp-text-dim)', margin: '0 auto 10px' }} />
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Pick a flow to start</div>
            <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.5 }}>Or click any node in the diagram to see what it is, where it lives in the code, and which plans touch it.</div>
          </div>
        </div>
      </RightRail>
    </div>
    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="docs/architecture/architecture.json" updated="14s ago" scope="silex-research/dontpanic@main" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only</span>
    </footer>
  </Shell>
);


/* ──────────────────────────────────────────────────────────
   ② CLICK-TO-DETAIL NODE PANEL (Section 2.6 + Section 3.3 — swap-on-click)
   ────────────────────────────────────────────────────────── */
const PageArchClickDetail = () => (
  <Shell active="arch" height={1100} topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
    <PageHead
      kicker="ARCHITECTURE · NODE DETAIL"
      title="How DontPanic protects your codebase"
      sub="You clicked Builder agent — flow inspector is paused. Use Back to flows to return."
    />
    <div className="dp-page__body" style={{ padding: '14px 24px', display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 340px', gap: 14, overflow: 'hidden' }}>
      <ArchCanvasFrame>
        <div className="dp-row-flex" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Governance Layer</div>
            <div style={{ fontSize: 12, color: 'var(--dp-text-muted)' }}><strong style={{ color: '#8B6FFF' }}>Builder agent</strong> selected · 3 inbound · 2 outbound · referenced by 4 plans</div>
          </div>
          <Legend items={[
            { color: '#F25555', label: 'Human' }, { color: '#8B6FFF', label: 'AI agent' },
            { color: '#7E8BA6', label: 'Data' }, { color: '#F5A623', label: 'Decision' },
            { color: '#3DD68C', label: 'External' },
          ]} />
        </div>
        <ArchDiagram flowEdges={[]} clickedNodeId="builder" fadeAll />
      </ArchCanvasFrame>

      <RightRail>
        <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-brand-edge)', borderRadius: 6, flexShrink: 0, boxShadow: '0 0 0 1px rgba(139,111,255,0.15)' }}>
          <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--dp-border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <button className="dp-row-flex" style={{ gap: 6, color: 'var(--dp-text-muted)', fontSize: 11, padding: '3px 8px', border: '1px solid var(--dp-border-subtle)', borderRadius: 3 }}>
              <IconChevR size={11} style={{ transform: 'rotate(180deg)' }} /> Back to flows
            </button>
            <Chip variant="recommended">AI AGENT</Chip>
          </div>
          <div style={{ padding: '14px 16px' }}>
            <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--dp-text)', marginBottom: 4 }}>Builder agent</div>
            <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.5, marginBottom: 14 }}>
              The first AI that actually writes code. Takes the locked plan, opens a working branch, and produces a diff. Never decides on its own whether the diff is good — that's what the three reviewers are for.
            </div>

            <div className="dp-kicker" style={{ marginBottom: 6 }}>WHERE IT LIVES</div>
            <Cmd block>scripts/dontpanic_orchestrate/dispatch.py</Cmd>

            <div className="dp-kicker" style={{ marginTop: 14, marginBottom: 6 }}>RELATED PLANS</div>
            <div className="dp-row-flex" style={{ gap: 4, flexWrap: 'wrap' }}>
              {['plan-2026-05-007', 'plan-2026-05-016', 'plan-2026-05-022', 'plan-2026-04-031'].map(p => (
                <span key={p} style={{ fontSize: 10, fontWeight: 600, padding: '2px 7px', borderRadius: 3, background: 'var(--dp-brand-soft)', color: 'var(--dp-brand)', fontFamily: 'var(--dp-font-mono)', cursor: 'pointer' }}>{p}</span>
              ))}
            </div>

            <div className="dp-kicker" style={{ marginTop: 14, marginBottom: 6 }}>CONNECTED TOOLS</div>
            <div className="dp-stack-sm">
              {[
                { label: 'Anthropic', detail: 'sonnet-4.5 · ready', band: 'healthy' },
                { label: 'MCP — Filesystem', detail: 'local · ready', band: 'healthy' },
                { label: 'OpenAI', detail: 'verifier role · not connected', band: 'action' },
              ].map((c, i) => (
                <div key={i} className="dp-row-flex" style={{ gap: 8 }}>
                  <Pip band={c.band} />
                  <span style={{ fontSize: 12 }}>{c.label}</span>
                  <span style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginLeft: 'auto' }}>{c.detail}</span>
                </div>
              ))}
            </div>

            <div className="dp-kicker" style={{ marginTop: 14, marginBottom: 6 }}>WHAT YOU CAN DO</div>
            <Cmd block>dontpanic inspect builder --plan vol-4f1a</Cmd>
          </div>
        </div>
      </RightRail>
    </div>
    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="docs/architecture/architecture.json · plans/*.md" updated="14s ago" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only · clicking a related plan opens Work</span>
    </footer>
  </Shell>
);


/* ──────────────────────────────────────────────────────────
   ③ EMPTY: NEVER GENERATED (Section 2.4 #1)
   ────────────────────────────────────────────────────────── */
const PageArchEmptyNever = () => (
  <Shell active="arch" height={900} topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
    <PageHead kicker="ARCHITECTURE" title="How DontPanic protects your codebase" sub="No architecture map yet" />
    <div className="dp-page__body" style={{ padding: '40px 80px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ maxWidth: 620, textAlign: 'center', padding: '40px 32px', border: '1px dashed var(--dp-border)', borderRadius: 8, background: 'repeating-linear-gradient(-45deg, transparent 0 10px, rgba(255,255,255,0.012) 10px 20px)' }}>
        <IconArch size={40} sw={1.2} style={{ color: 'var(--dp-text-dim)', margin: '0 auto 14px' }} />
        <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 6 }}>DontPanic hasn't generated an architecture map for this project yet</h2>
        <p style={{ fontSize: 13, color: 'var(--dp-text-muted)', lineHeight: 1.55, marginBottom: 18, maxWidth: 480, margin: '0 auto 18px' }}>
          The map is built by scanning your code, plans, and connection manifests. Run the regen command from your project root — it's a one-time read pass and writes the output to <span className="dp-mono" style={{ color: 'var(--dp-text-soft)' }}>docs/architecture/</span>.
        </p>
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
          <Cmd>dontpanic architecture regen --with-html</Cmd>
        </div>
        <div style={{ fontSize: 11, color: 'var(--dp-text-dim)', fontFamily: 'var(--dp-font-mono)', marginBottom: 14 }}>
          // safe — read-only scan of your repo
        </div>
        <div style={{ display: 'flex', gap: 18, justifyContent: 'center', fontSize: 11, color: 'var(--dp-text-muted)' }}>
          <span className="dp-row-flex" style={{ gap: 6 }}><IconDoc size={11} sw={1.8} /> expected at <span className="dp-mono" style={{ color: 'var(--dp-text-soft)' }}>docs/architecture/architecture.json</span></span>
        </div>
      </div>
    </div>
    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="docs/architecture/ (no files yet)" updated="—" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only · regen will not mutate code</span>
    </footer>
  </Shell>
);


/* ──────────────────────────────────────────────────────────
   ④ STALE BANNER (Section 2.4 #2)
   ────────────────────────────────────────────────────────── */
const PageArchStale = () => (
  <Shell active="arch" height={1100} topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
    <PageHead kicker="ARCHITECTURE" title="How DontPanic protects your codebase" sub="Map is 6 hours old — values are last-known, not live" />
    <div className="dp-page__body" style={{ padding: '14px 24px', display: 'flex', flexDirection: 'column', gap: 12, overflow: 'hidden' }}>
      <div style={{ padding: '10px 14px', background: 'var(--dp-action-soft)', border: '1px solid var(--dp-action-edge)', borderRadius: 5, display: 'flex', alignItems: 'center', gap: 12 }}>
        <IconWarn size={14} sw={1.8} style={{ color: 'var(--dp-action)' }} />
        <div style={{ flex: 1, fontSize: 12, color: 'var(--dp-text-soft)' }}>
          <strong style={{ color: 'var(--dp-text)' }}>Map is 6 hours old.</strong> Code may have changed since this was last generated.
        </div>
        <Cmd inline>dontpanic architecture regen</Cmd>
        <button style={{ fontSize: 11, color: 'var(--dp-text-muted)', padding: '4px 8px' }}>Dismiss</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 340px', gap: 14, flex: 1, minHeight: 0 }}>
        <ArchCanvasFrame>
          <div className="dp-row-flex" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>Governance Layer <span style={{ color: 'var(--dp-action)', fontSize: 11, marginLeft: 6 }}>(stale)</span></div>
              <div style={{ fontSize: 12, color: 'var(--dp-text-muted)' }}>Highlighted: Cross-model audit · last generated May 23 11:42 UTC</div>
            </div>
            <Legend items={[
              { color: '#F25555', label: 'Human' }, { color: '#8B6FFF', label: 'AI agent' },
              { color: '#7E8BA6', label: 'Data' }, { color: '#F5A623', label: 'Decision' },
              { color: '#3DD68C', label: 'External' },
            ]} />
          </div>
          <ArchDiagram flowEdges={[
            { from: 'workspace', to: 'reviewer', step: 1 },
            { from: 'workspace', to: 'devil', step: 2 },
            { from: 'workspace', to: 'verifier', step: 3 },
            { from: 'consensus', to: 'evidence', step: 4 },
          ]} />
        </ArchCanvasFrame>
        <RightRail>
          <FlowsPanel items={[
            { name: 'Cross-model audit', sub: 'Three AIs review the diff', source: 'authored' },
            { name: 'Human gate', sub: 'You approve or reject', source: 'authored' },
            { name: 'Safe to ship', sub: 'Approved → production', source: 'authored' },
          ]} activeIdx={0} />
        </RightRail>
      </div>
    </div>
    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="docs/architecture/architecture.json" updated="6h ago · stale" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only</span>
    </footer>
  </Shell>
);


/* ──────────────────────────────────────────────────────────
   ⑤ FLEET / ALL PROJECTS (Section 2.5)
   ────────────────────────────────────────────────────────── */
const FleetArchCard = ({ name, fresh, nodes, edges, health, hint }) => (
  <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, padding: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
    <div className="dp-row-flex" style={{ justifyContent: 'space-between', gap: 8 }}>
      <span className="dp-row-flex" style={{ gap: 8, minWidth: 0 }}>
        <IconFolder size={13} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} />
        <span style={{ fontWeight: 600, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
      </span>
      <Badge band={health.band}>{health.label}</Badge>
    </div>
    {/* Tiny diagram preview */}
    <div style={{ height: 72, background: 'var(--dp-bg-sunken)', borderRadius: 3, border: '1px solid var(--dp-border-subtle)', padding: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 4 }}>
      {[7, 5, 6, 4, 5, 6, 3].map((h, i) => (
        <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {Array.from({ length: h }, (_, j) => (
            <span key={j} style={{ width: 14, height: 4, background: 'var(--dp-text-dim)', opacity: 0.4 + (j * 0.07), borderRadius: 1 }} />
          ))}
        </div>
      ))}
    </div>
    <div className="dp-row-flex" style={{ justifyContent: 'space-between', fontSize: 11, color: 'var(--dp-text-muted)' }}>
      <span className="dp-mono">{nodes}n · {edges}e</span>
      <span className="dp-mono">{fresh}</span>
    </div>
    <div style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>{hint}</div>
    <button style={{ marginTop: 4, padding: '5px 0', background: 'var(--dp-bg-sunken)', border: '1px solid var(--dp-border-subtle)', borderRadius: 3, fontSize: 12, fontWeight: 500, color: 'var(--dp-text-soft)' }}>Open map →</button>
  </div>
);

const PageArchFleet = () => (
  <Shell active="arch" height={1000} topStripProps={{ project: 'All projects (6)', updated: '14s ago', warnings: 9, reviews: 4, health: 'action' }}>
    <PageHead
      kicker="ARCHITECTURE · ALL PROJECTS"
      title="Pick a project to open its map"
      sub="Architecture maps are per-project — unrelated repos aren't merged into one graph."
      actions={
        <div className="dp-row-flex" style={{ gap: 6, padding: '4px 10px', background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4, minWidth: 240 }}>
          <IconSearch size={12} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} />
          <input placeholder="Filter projects…" style={{ background: 'transparent', border: 'none', outline: 'none', flex: 1, color: 'var(--dp-text)', fontSize: 12 }} />
        </div>
      }
    />
    <div className="dp-page__body" style={{ padding: '18px 24px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
        <FleetArchCard name="silex-research/dontpanic" fresh="14s ago" nodes={28} edges={41} health={{ band: 'action', label: 'Needs action' }} hint="3 connections need setup · 1 active review awaiting you" />
        <FleetArchCard name="silex/api-gateway" fresh="2h ago" nodes={14} edges={22} health={{ band: 'healthy', label: 'Healthy' }} hint="All checks passing · 0 active reviews" />
        <FleetArchCard name="silex/web-dashboard" fresh="6h ago · stale" nodes={31} edges={48} health={{ band: 'action', label: 'Stale map' }} hint="Code likely changed since last regen" />
        <FleetArchCard name="silex/billing-svc" fresh="42m ago" nodes={9} edges={12} health={{ band: 'blocked', label: 'Blocked' }} hint="1 active review failed · needs your eye" />
        <FleetArchCard name="silex/internal-tools" fresh="never" nodes={0} edges={0} health={{ band: 'pending', label: 'No map yet' }} hint="Run dontpanic architecture regen to generate" />
        <FleetArchCard name="silex/marketing-site" fresh="1d ago" nodes={6} edges={8} health={{ band: 'healthy', label: 'Healthy' }} hint="Static site · no AI work in flight" />
      </div>

      <div style={{ marginTop: 22, padding: 14, background: 'var(--dp-bg-panel)', border: '1px dashed var(--dp-border)', borderRadius: 5, fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.5 }}>
        <strong style={{ color: 'var(--dp-text)' }}>Why per-project rather than one combined graph?</strong> Different projects have different trust boundaries, different vendor accounts, different deploy targets. Forcing them onto a single diagram would lie about how the boundaries actually run. Each project owns its own architecture file; the fleet view is a launcher.
      </div>
    </div>
    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="~/.dontpanic/projects.json + per-project docs/architecture/" updated="14s ago" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only</span>
    </footer>
  </Shell>
);


/* ──────────────────────────────────────────────────────────
   ⑥ MOBILE / NARROW (Section 2.11)
   ────────────────────────────────────────────────────────── */
const PageArchMobile = () => (
  <div className="dp" style={{ width: 414, height: 896, display: 'flex', flexDirection: 'column', background: 'var(--dp-bg-base)', border: '1px solid var(--dp-border-subtle)', borderRadius: 28, overflow: 'hidden' }}>
    {/* Compact top bar (no full strip) */}
    <div style={{ height: 44, background: 'var(--dp-bg-sunken)', borderBottom: '1px solid var(--dp-border-subtle)', display: 'flex', alignItems: 'center', padding: '0 14px', gap: 10, flexShrink: 0 }}>
      <button style={{ color: 'var(--dp-text)' }}><IconChevD size={18} style={{ transform: 'rotate(90deg)' }} /></button>
      <DPMark size={20} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>Architecture</div>
        <div className="dp-mono" style={{ fontSize: 10, color: 'var(--dp-text-muted)' }}>silex/dontpanic · 14s ago</div>
      </div>
      <Badge band="action">3</Badge>
    </div>

    {/* Search */}
    <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--dp-border-subtle)', flexShrink: 0, display: 'flex', gap: 8 }}>
      <div className="dp-row-flex" style={{ gap: 6, padding: '5px 10px', background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4, flex: 1 }}>
        <IconSearch size={12} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} />
        <input placeholder="Search…" style={{ background: 'transparent', border: 'none', outline: 'none', flex: 1, color: 'var(--dp-text)', fontSize: 12 }} />
      </div>
      <button style={{ padding: '5px 10px', background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4 }}><IconFilter size={13} style={{ color: 'var(--dp-text-muted)' }} /></button>
    </div>

    {/* Diagram scroll area */}
    <div style={{ flex: 1, overflow: 'auto', position: 'relative', background: 'var(--dp-bg-panel)' }}>
      <div style={{ width: GRID_PAD_X * 2 + 7 * COL_W + 6 * COL_GAP, height: GRID_PAD_Y + 5 * (NODE_H + NODE_GAP) + 24, position: 'relative', transform: 'scale(0.42)', transformOrigin: 'top left' }}>
        {COL_LABELS.map((cl, i) => (
          <div key={i} className="dp-kicker" style={{ position: 'absolute', left: GRID_PAD_X + i * (COL_W + COL_GAP), top: 14, width: COL_W, fontSize: 9, letterSpacing: '0.14em', color: 'var(--dp-text-muted)' }}>{cl}</div>
        ))}
        <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
          <defs>
            <marker id="mbg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 Z" fill="#344163" /></marker>
            <marker id="mhi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 Z" fill="#F5A623" /></marker>
          </defs>
          {ARCH_EDGES_BG.map(([a, b], i) => <path key={i} d={arrowPath(a, b)} fill="none" stroke="#344163" strokeWidth="1" opacity="0.35" markerEnd="url(#mbg)" />)}
        </svg>
        {Object.entries(ARCH_NODES).map(([id, n]) => <ArchNode key={id} id={id} n={n} highlighted={false} />)}
      </div>

      {/* Floating zoom controls */}
      <div style={{ position: 'absolute', bottom: 14, right: 14, display: 'flex', flexDirection: 'column', background: 'var(--dp-bg-sunken)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, boxShadow: '0 4px 12px rgba(0,0,0,0.4)' }}>
        <button style={{ width: 36, height: 36, color: 'var(--dp-text-soft)', borderBottom: '1px solid var(--dp-border-subtle)', fontSize: 14 }}>+</button>
        <button style={{ width: 36, height: 36, color: 'var(--dp-text-soft)', borderBottom: '1px solid var(--dp-border-subtle)', fontSize: 14 }}>−</button>
        <button style={{ width: 36, height: 36, color: 'var(--dp-text-soft)', fontSize: 9, fontFamily: 'var(--dp-font-mono)' }}>1:1</button>
      </div>
    </div>

    {/* Slide-up sheet handle for flows */}
    <div style={{ borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', padding: '8px 14px 12px', flexShrink: 0 }}>
      <div style={{ width: 32, height: 3, background: 'var(--dp-border)', borderRadius: 2, margin: '2px auto 10px' }} />
      <div className="dp-row-flex" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <div className="dp-kicker">FLOWS</div>
        <span style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>Tap to expand</span>
      </div>
      <FlowItem name="Cross-model audit" sub="Three AIs review the diff" source="authored" active />
      <FlowItem name="Human gate" sub="You approve or reject" source="authored" />
    </div>
  </div>
);


/* ──────────────────────────────────────────────────────────
   ⑦ MODULE-CATEGORY SWIMLANE (Section 3.1 — variant B)
   ────────────────────────────────────────────────────────── */
const MODULE_COLS = ['ORCHESTRATOR CORE', 'DASHBOARD', 'CAPABILITIES', 'CLI', 'SCHEMAS', 'DOCS & PLANS', 'EXTERNAL'];

// Re-map the existing nodes to module categories
const MODULE_NODES = {
  // Orchestrator core
  dispatch: { col: 0, row: 0, label: 'dispatch.py', sub: 'orchestrate/dispatch', type: 'agent-core' },
  consensus: { col: 0, row: 1, label: 'consensus.py', sub: 'orchestrate/consensus', type: 'agent-core' },
  verifier:  { col: 0, row: 2, label: 'verifier.py', sub: 'orchestrate/verifier', type: 'agent-core' },
  packet:    { col: 0, row: 3, label: 'packet.py', sub: 'orchestrate/packet', type: 'agent-core' },
  // Dashboard
  dashIndex: { col: 1, row: 0, label: 'dashboard/index.html', sub: 'static entry', type: 'agent' },
  dashCore:  { col: 1, row: 1, label: 'core.js', sub: 'dashboard/core', type: 'agent' },
  dashPages: { col: 1, row: 2, label: 'pages/*', sub: 'page modules', type: 'agent' },
  dashLib:   { col: 1, row: 3, label: 'lib/*', sub: 'logic modules', type: 'agent' },
  // Capabilities
  capsMgr:   { col: 2, row: 0, label: 'capability mgr', sub: 'capabilities/manager.py', type: 'agent' },
  capsManifest: { col: 2, row: 1, label: 'manifests', sub: 'capabilities/*.yaml', type: 'data' },
  // CLI
  cliMain:   { col: 3, row: 0, label: 'dontpanic CLI', sub: 'scripts/dontpanic', type: 'agent' },
  cliDoctor: { col: 3, row: 1, label: 'doctor', sub: 'subcommand', type: 'agent' },
  cliReview: { col: 3, row: 2, label: 'review', sub: 'subcommand', type: 'agent' },
  // Schemas
  schemaPlan:   { col: 4, row: 0, label: 'plan schema', sub: 'schemas/plan.json', type: 'data' },
  schemaState:  { col: 4, row: 1, label: 'state schema', sub: 'schemas/state.json', type: 'data' },
  schemaCap:    { col: 4, row: 2, label: 'capability schema', sub: 'schemas/capability.json', type: 'data' },
  // Docs & plans
  plans:     { col: 5, row: 0, label: 'plans/*.md', sub: 'frontmatter + body', type: 'data' },
  arch:      { col: 5, row: 1, label: 'architecture.json', sub: 'docs/architecture/', type: 'data' },
  evidence:  { col: 5, row: 2, label: 'evidence/*', sub: 'review packets', type: 'data' },
  // External
  github:    { col: 6, row: 0, label: 'GitHub', sub: 'API', type: 'external' },
  anthropic: { col: 6, row: 1, label: 'Anthropic', sub: 'sonnet-4.5', type: 'external' },
  openai:    { col: 6, row: 2, label: 'OpenAI', sub: 'gpt-5', type: 'external' },
  google:    { col: 6, row: 3, label: 'Google', sub: 'gemini-2.5', type: 'external' },
};

const MODULE_EDGES = [
  ['cliMain', 'dispatch'], ['dispatch', 'consensus'], ['consensus', 'verifier'], ['consensus', 'packet'],
  ['cliMain', 'capsMgr'], ['capsMgr', 'capsManifest'],
  ['dispatch', 'anthropic'], ['verifier', 'openai'], ['verifier', 'google'],
  ['packet', 'evidence'], ['packet', 'github'],
  ['cliMain', 'plans'], ['plans', 'schemaPlan'],
  ['dashIndex', 'dashCore'], ['dashCore', 'dashPages'], ['dashCore', 'dashLib'],
  ['dashLib', 'plans'], ['dashLib', 'arch'], ['dashLib', 'capsManifest'],
  ['cliDoctor', 'capsManifest'], ['cliReview', 'evidence'],
];

const PageArchModuleSwim = () => {
  const W = GRID_PAD_X * 2 + 7 * COL_W + 6 * COL_GAP;
  const H = GRID_PAD_Y + 4 * (NODE_H + NODE_GAP) + 24;
  return (
    <Shell active="arch" height={1100} topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
      <PageHead
        kicker="ARCHITECTURE · MODULE VIEW"
        title="How DontPanic protects your codebase"
        sub="Swimlanes = source-tree categories · engineering-navigation mental model"
        actions={
          <div className="dp-row-flex" style={{ gap: 4, padding: 2, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4 }}>
            <button style={{ padding: '4px 10px', color: 'var(--dp-text-muted)', borderRadius: 3, fontSize: 12 }}>Trust boundaries</button>
            <button style={{ padding: '4px 10px', background: 'var(--dp-bg-elevated)', color: 'var(--dp-text)', borderRadius: 3, fontSize: 12, fontWeight: 600 }}>Modules</button>
          </div>
        }
      />
      <div className="dp-page__body" style={{ padding: '14px 24px', display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 340px', gap: 14, overflow: 'hidden' }}>
        <ArchCanvasFrame>
          <div className="dp-row-flex" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>Module Map</div>
              <div style={{ fontSize: 12, color: 'var(--dp-text-muted)' }}>The same nodes regrouped by source-tree category. Useful for "where does this file live?" rather than "where does this run?"</div>
            </div>
          </div>
          <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
            <div style={{ position: 'relative', width: W, height: H, transform: 'scale(0.92)', transformOrigin: 'top left' }}>
              {MODULE_COLS.map((cl, i) => (
                <div key={i} className="dp-kicker" style={{ position: 'absolute', left: GRID_PAD_X + i * (COL_W + COL_GAP), top: 14, width: COL_W, fontSize: 9, letterSpacing: '0.14em', color: 'var(--dp-text-muted)' }}>{cl}</div>
              ))}
              {MODULE_COLS.map((_, i) => i < MODULE_COLS.length - 1 && (
                <div key={`d-${i}`} style={{ position: 'absolute', left: GRID_PAD_X + i * (COL_W + COL_GAP) + COL_W + COL_GAP / 2, top: 0, bottom: 0, width: 1, background: 'var(--dp-border-subtle)', opacity: 0.4 }} />
              ))}
              <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
                <defs>
                  <marker id="modbg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 Z" fill="#344163" /></marker>
                </defs>
                {MODULE_EDGES.map(([a, b], i) => {
                  const f = MODULE_NODES[a], t = MODULE_NODES[b];
                  if (!f || !t) return null;
                  const fp = { x: GRID_PAD_X + f.col * (COL_W + COL_GAP), y: GRID_PAD_Y + f.row * (NODE_H + NODE_GAP) };
                  const tp = { x: GRID_PAD_X + t.col * (COL_W + COL_GAP), y: GRID_PAD_Y + t.row * (NODE_H + NODE_GAP) };
                  const x1 = fp.x + COL_W, y1 = fp.y + NODE_H / 2;
                  const x2 = tp.x, y2 = tp.y + NODE_H / 2;
                  const dx = Math.max(40, (x2 - x1) * 0.45);
                  const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
                  return <path key={i} d={d} fill="none" stroke="#344163" strokeWidth="1" opacity="0.4" markerEnd="url(#modbg)" />;
                })}
              </svg>
              {Object.entries(MODULE_NODES).map(([id, n]) => {
                const t = NODE_TYPES[n.type];
                const x = GRID_PAD_X + n.col * (COL_W + COL_GAP);
                const y = GRID_PAD_Y + n.row * (NODE_H + NODE_GAP);
                return (
                  <div key={id} style={{ position: 'absolute', left: x, top: y, width: COL_W, height: NODE_H, background: t.bg, border: `1px solid ${t.edge}`, borderRadius: 4, padding: '7px 10px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: t.color, lineHeight: 1.25, fontFamily: n.type === 'data' ? 'var(--dp-font-mono)' : 'var(--dp-font-sans)' }}>{n.label}</div>
                    <div style={{ fontSize: 10, color: 'var(--dp-text-muted)', marginTop: 2 }}>{n.sub}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </ArchCanvasFrame>

        <RightRail>
          <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 6, padding: 14 }}>
            <div className="dp-kicker" style={{ marginBottom: 8 }}>VIEW NOTES</div>
            <div style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--dp-text-soft)' }}>
              <strong>Module view</strong> is for engineering navigation — answers "where in the codebase does X live?" <br /><br />
              <strong>Trust boundaries view</strong> is for operator narrative — answers "what protects me from runaway AI changes?" <br /><br />
              Same data, two mental models. The toggle is at the top of the page.
            </div>
          </div>
          <FlowsPanel items={[
            { name: 'How a plan reaches the builder', sub: 'CLI → orchestrator → external', source: 'derived' },
            { name: 'How review packets are written', sub: 'orchestrator → docs/evidence', source: 'derived' },
            { name: 'How the dashboard reads state', sub: 'dashboard/lib → schemas → docs', source: 'derived' },
            { name: 'CLI doctor flow', sub: 'CLI → capability mgr → external probes', source: 'authored' },
          ]} activeIdx={-1} />
        </RightRail>
      </div>
      <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Provenance source="docs/architecture/architecture.json (modules section)" updated="14s ago" />
        <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only</span>
      </footer>
    </Shell>
  );
};

Object.assign(window, { PageArchNeutral, PageArchClickDetail, PageArchEmptyNever, PageArchStale, PageArchFleet, PageArchMobile, PageArchModuleSwim });
