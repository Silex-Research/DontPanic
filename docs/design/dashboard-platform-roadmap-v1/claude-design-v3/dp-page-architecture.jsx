/* Architecture & Flows — explicitly deferred from v0; designed for the next milestone.
   Layout follows the ToDesktop reference: column-based swim lanes of nodes,
   numbered yellow arrows tracing the selected flow, flows + steps panel on the right.

   For DontPanic, the swim lanes are the trust boundaries:
     YOU · AI AGENTS · PLAN · EXECUTION · AUDIT · GATE · EXTERNAL SERVICES
*/

const ARCH_NODES = {
  // Column 1 — YOU
  operator:   { col: 0, row: 0, label: 'You',                  sub: 'operator',                          type: 'actor' },
  team:       { col: 0, row: 1, label: 'Your team',            sub: 'reviewers · stakeholders',          type: 'actor', muted: true },

  // Column 2 — AGENTS
  claudecode: { col: 1, row: 0, label: 'Claude Code',          sub: 'CLI in your terminal',              type: 'agent' },
  codex:      { col: 1, row: 1, label: 'Codex / Aider',        sub: 'alt builder CLI',                   type: 'agent', muted: true },
  gemini:     { col: 1, row: 2, label: 'Gemini CLI',           sub: 'alt builder',                       type: 'agent', muted: true },

  // Column 3 — PLAN
  plan:       { col: 2, row: 0, label: 'plans/*.md',           sub: 'scope · acceptance · budget',       type: 'data' },
  lock:       { col: 2, row: 1, label: 'Plan lock',            sub: '.dontpanic/locks/',                 type: 'data' },

  // Column 4 — EXECUTION
  builder:    { col: 3, row: 0, label: 'Builder agent',        sub: 'writes code in your repo',          type: 'agent-core' },
  workspace:  { col: 3, row: 1, label: 'Working tree',         sub: 'branch · uncommitted changes',      type: 'data' },

  // Column 5 — AUDIT
  reviewer:   { col: 4, row: 0, label: 'Code reviewer',        sub: 'AI #1 · reads diff',                type: 'agent-review' },
  devil:      { col: 4, row: 1, label: 'Devil\'s advocate',    sub: 'AI #2 · argues against',            type: 'agent-review' },
  verifier:   { col: 4, row: 2, label: 'Quality check',        sub: 'AI #3 · runs tests',                type: 'agent-review' },
  consensus:  { col: 4, row: 3, label: 'Consensus',            sub: '3 independent verdicts',            type: 'data', subtle: true },

  // Column 6 — GATE
  evidence:   { col: 5, row: 0, label: 'Review summary',       sub: 'evidence/* · what changed & why',   type: 'data' },
  decision:   { col: 5, row: 1, label: 'Your decision',        sub: 'approve · changes · reject',        type: 'gate' },

  // Column 7 — EXTERNAL
  github:     { col: 6, row: 0, label: 'GitHub',               sub: 'PR · checks · merge',               type: 'external' },
  openai:     { col: 6, row: 1, label: 'OpenAI',               sub: 'Verifier model',                    type: 'external' },
  anthropic:  { col: 6, row: 2, label: 'Anthropic',            sub: 'Reviewer model',                    type: 'external' },
  google:     { col: 6, row: 3, label: 'Google',               sub: 'Devil\'s advocate model',           type: 'external' },
  mcp:        { col: 6, row: 4, label: 'MCP servers',          sub: 'connected tools',                   type: 'external', muted: true },
};

const NODE_TYPES = {
  actor:         { color: '#F25555', bg: 'rgba(242,85,85,0.05)', edge: 'rgba(242,85,85,0.45)' },
  agent:         { color: '#6CA8FF', bg: 'rgba(108,168,255,0.05)', edge: 'rgba(108,168,255,0.45)' },
  'agent-core':  { color: '#8B6FFF', bg: 'rgba(139,111,255,0.07)', edge: 'rgba(139,111,255,0.55)' },
  'agent-review':{ color: '#8B6FFF', bg: 'rgba(139,111,255,0.04)', edge: 'rgba(139,111,255,0.30)' },
  data:          { color: '#7E8BA6', bg: 'rgba(126,139,166,0.05)', edge: 'rgba(126,139,166,0.40)' },
  gate:          { color: '#F5A623', bg: 'rgba(245,166,35,0.05)', edge: 'rgba(245,166,35,0.45)' },
  external:      { color: '#3DD68C', bg: 'rgba(61,214,140,0.05)', edge: 'rgba(61,214,140,0.40)' },
};

// Numbered flow path — Cross-model audit
const FLOW_AUDIT = [
  { from: 'workspace', to: 'reviewer',  step: 1 },
  { from: 'workspace', to: 'devil',     step: 2 },
  { from: 'workspace', to: 'verifier',  step: 3 },
  { from: 'reviewer',  to: 'consensus', step: 4 },
  { from: 'devil',     to: 'consensus', step: 5 },
  { from: 'verifier',  to: 'consensus', step: 6 },
  { from: 'consensus', to: 'evidence',  step: 7 },
  { from: 'reviewer',  to: 'anthropic', step: 4, dashed: true },
  { from: 'devil',     to: 'google',    step: 5, dashed: true },
  { from: 'verifier',  to: 'openai',    step: 6, dashed: true },
];

// Background subtle connections (the whole product DAG, not highlighted)
const ARCH_EDGES_BG = [
  ['operator', 'plan'],
  ['operator', 'claudecode'],
  ['operator', 'decision'],
  ['claudecode', 'plan'],
  ['plan', 'lock'],
  ['lock', 'builder'],
  ['claudecode', 'builder'],
  ['builder', 'workspace'],
  ['workspace', 'reviewer'],
  ['workspace', 'devil'],
  ['workspace', 'verifier'],
  ['reviewer', 'consensus'],
  ['devil', 'consensus'],
  ['verifier', 'consensus'],
  ['consensus', 'evidence'],
  ['evidence', 'decision'],
  ['decision', 'github'],
  ['reviewer', 'anthropic'],
  ['devil', 'google'],
  ['verifier', 'openai'],
  ['builder', 'mcp'],
];

const COL_W = 178;
const COL_GAP = 22;
const NODE_H = 56;
const NODE_GAP = 18;
const GRID_PAD_X = 32;
const GRID_PAD_Y = 56;

// Compute pixel position of a node given its (col, row)
const nodePos = (n) => ({
  x: GRID_PAD_X + n.col * (COL_W + COL_GAP),
  y: GRID_PAD_Y + n.row * (NODE_H + NODE_GAP),
});

const COL_LABELS = ['ACTORS', 'AI AGENTS', 'PLAN', 'EXECUTION', 'CROSS-MODEL AUDIT', 'HUMAN GATE', 'EXTERNAL SERVICES'];

const ArchNode = ({ id, n, highlighted }) => {
  const t = NODE_TYPES[n.type];
  const pos = nodePos(n);
  const isMuted = n.muted && !highlighted;
  return (
    <div style={{
      position: 'absolute', left: pos.x, top: pos.y, width: COL_W, height: NODE_H,
      background: highlighted ? 'rgba(245,166,35,0.10)' : (n.subtle ? 'transparent' : t.bg),
      border: `1px ${n.subtle ? 'dashed' : 'solid'} ${highlighted ? '#F5A623' : t.edge}`,
      borderRadius: 4,
      padding: '7px 10px',
      display: 'flex', flexDirection: 'column', justifyContent: 'center',
      opacity: isMuted ? 0.42 : 1,
      boxShadow: highlighted ? '0 0 0 3px rgba(245,166,35,0.18)' : 'none',
    }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: highlighted ? '#F5A623' : t.color, lineHeight: 1.25, fontFamily: n.type === 'data' ? 'var(--dp-font-mono)' : 'var(--dp-font-sans)' }}>
        {n.label}
      </div>
      <div style={{ fontSize: 10, color: 'var(--dp-text-muted)', marginTop: 2, lineHeight: 1.3 }}>{n.sub}</div>
    </div>
  );
};

// Arrow path — curved cubic bezier from right edge of from-node to left edge of to-node
const arrowPath = (fromId, toId) => {
  const f = ARCH_NODES[fromId], t = ARCH_NODES[toId];
  if (!f || !t) return null;
  const fp = nodePos(f), tp = nodePos(t);
  const x1 = fp.x + COL_W;
  const y1 = fp.y + NODE_H / 2;
  const x2 = tp.x;
  const y2 = tp.y + NODE_H / 2;
  const dx = Math.max(40, (x2 - x1) * 0.45);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
};

const FlowItem = ({ name, sub, active, source = 'authored', warning }) => (
  <div style={{
    padding: '10px 12px',
    background: active ? 'rgba(245,166,35,0.08)' : 'transparent',
    borderLeft: active ? '3px solid #F5A623' : '3px solid transparent',
    cursor: 'pointer',
    borderBottom: '1px solid var(--dp-border-subtle)',
  }}>
    <div className="dp-row-flex" style={{ justifyContent: 'space-between', gap: 8 }}>
      <span style={{ fontSize: 12, fontWeight: active ? 600 : 500, color: active ? 'var(--dp-text)' : 'var(--dp-text-soft)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
      <span className="dp-row-flex" style={{ gap: 4, flexShrink: 0 }}>
        {warning && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, padding: '1px 5px', borderRadius: 3, background: 'var(--dp-action-soft)', color: 'var(--dp-action)', fontSize: 9, fontWeight: 600 }}>
            <IconWarn size={9} sw={2} /> 1 missing
          </span>
        )}
        <span style={{ fontSize: 9, fontWeight: 600, letterSpacing: '0.06em', padding: '1px 5px', borderRadius: 3, textTransform: 'uppercase',
          background: source === 'authored' ? 'rgba(108,168,255,0.12)' : 'rgba(126,139,166,0.10)',
          color: source === 'authored' ? 'var(--dp-relevance)' : 'var(--dp-text-muted)',
        }}>{source === 'authored' ? 'authored' : 'derived'}</span>
      </span>
    </div>
    <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 2 }}>{sub}</div>
  </div>
);

const StepItem = ({ n, title, body, source, planId, command }) => (
  <div style={{ padding: '10px 12px', display: 'flex', gap: 10, borderTop: '1px solid var(--dp-border-subtle)' }}>
    <span style={{ width: 18, height: 18, borderRadius: 4, background: '#F5A623', color: '#0A0E17', fontSize: 10, fontWeight: 700, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 1 }}>{n}</span>
    <div style={{ minWidth: 0, flex: 1 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--dp-text)' }}>{title}</div>
      <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 2, lineHeight: 1.5 }}>{body}</div>
      {(source || planId) && (
        <div className="dp-row-flex" style={{ gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
          {source && <span className="dp-mono" style={{ fontSize: 10, color: 'var(--dp-text-dim)' }}>{source}</span>}
          {planId && <span style={{ fontSize: 9, fontWeight: 600, padding: '1px 5px', borderRadius: 3, background: 'var(--dp-brand-soft)', color: 'var(--dp-brand)', fontFamily: 'var(--dp-font-mono)' }}>{planId}</span>}
        </div>
      )}
      {command && (
        <div style={{ marginTop: 6 }}>
          <Cmd inline>{command}</Cmd>
        </div>
      )}
    </div>
  </div>
);

const Legend = ({ items, active }) => (
  <div className="dp-row-flex" style={{ gap: 4, flexWrap: 'wrap' }}>
    {items.map((it, i) => {
      const isActive = active === it.label;
      const isDim = active && !isActive;
      return (
        <button key={i} className="dp-row-flex" style={{
          gap: 6, fontSize: 11, color: isDim ? 'var(--dp-text-dim)' : 'var(--dp-text-muted)',
          padding: '3px 8px', borderRadius: 999,
          border: isActive ? `1px solid ${it.color}` : '1px solid transparent',
          background: isActive ? `${it.color}1F` : 'transparent',
          opacity: isDim ? 0.5 : 1,
        }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: it.color }} />
          {it.label}
        </button>
      );
    })}
  </div>
);

const PageArchitecture = () => {
  const archW = GRID_PAD_X * 2 + 7 * COL_W + 6 * COL_GAP;     // 1452 - too wide; we'll fit
  const archH = GRID_PAD_Y + 5 * (NODE_H + NODE_GAP) + 24;

  // Override: tighten so it fits the 720px-ish board area
  return (
    <Shell active="arch" height={1200} topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
      <PageHead
        kicker="ARCHITECTURE"
        title="How DontPanic protects your codebase"
        sub="Every node, every service, every data flow — pick a flow on the right to trace the path step by step."
        actions={
          <div className="dp-row-flex" style={{ gap: 8 }}>
            <div className="dp-row-flex" style={{ gap: 6, padding: '4px 10px', background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4, minWidth: 260 }}>
              <IconSearch size={12} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} />
              <input placeholder="Search modules, plans, connections…" style={{ background: 'transparent', border: 'none', outline: 'none', flex: 1, color: 'var(--dp-text)', fontSize: 12 }} />
              <kbd style={{ fontSize: 10, color: 'var(--dp-text-dim)', fontFamily: 'var(--dp-font-mono)', padding: '1px 5px', border: '1px solid var(--dp-border-subtle)', borderRadius: 3 }}>/</kbd>
            </div>
            <button className="dp-cmd dp-cmd--inline" style={{ background: 'var(--dp-bg-panel)' }}>
              <IconRefresh size={12} />
              <span style={{ fontFamily: 'var(--dp-font-sans)' }}>Regen</span>
            </button>
          </div>
        }
      />

      <div className="dp-page__body" style={{ padding: '14px 24px', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 340px', gap: 14, overflow: 'hidden' }}>

        {/* DIAGRAM */}
        <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 6, padding: '14px 18px', display: 'flex', flexDirection: 'column', minWidth: 0, position: 'relative' }}>
          <div className="dp-row-flex" style={{ justifyContent: 'space-between', marginBottom: 10, flexShrink: 0, gap: 12, flexWrap: 'wrap' }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>DontPanic — Governance Layer</div>
              <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', maxWidth: 720, marginTop: 3 }}>Highlighted: <strong style={{ color: '#F5A623' }}>Cross-model audit</strong> — how three independent AIs review a builder's work before it ever reaches you.</div>
            </div>
            <Legend items={[
              { color: '#F25555', label: 'Human' },
              { color: '#8B6FFF', label: 'AI agent' },
              { color: '#7E8BA6', label: 'Data' },
              { color: '#F5A623', label: 'Decision' },
              { color: '#3DD68C', label: 'External' },
            ]} active="AI agent" />
          </div>

          {/* Filter chips */}
          <div className="dp-row-flex" style={{ gap: 6, marginBottom: 10, flexWrap: 'wrap', flexShrink: 0 }}>
            <span className="dp-kicker" style={{ marginRight: 4 }}>FILTER</span>
            {[
              { label: 'Modules', count: 28 },
              { label: 'Plans', count: 12 },
              { label: 'Connections', count: 9, active: true },
              { label: 'Changed in 24h', count: 4 },
              { label: 'High coupling', count: 2 },
            ].map((f, i) => (
              <button key={i} className="dp-row-flex" style={{
                gap: 5, fontSize: 11, padding: '3px 9px', borderRadius: 999,
                background: f.active ? 'var(--dp-brand-soft)' : 'rgba(255,255,255,0.03)',
                color: f.active ? 'var(--dp-brand)' : 'var(--dp-text-soft)',
                border: f.active ? '1px solid var(--dp-brand-edge)' : '1px solid var(--dp-border-subtle)',
                fontWeight: f.active ? 600 : 500,
              }}>
                {f.label}
                <span className="dp-mono" style={{ fontSize: 10, color: f.active ? 'var(--dp-brand)' : 'var(--dp-text-muted)', opacity: 0.7 }}>{f.count}</span>
              </button>
            ))}
            <span style={{ flex: 1 }} />
            <button style={{ fontSize: 11, color: 'var(--dp-text-muted)', padding: '3px 6px' }}>Clear selection</button>
          </div>

          {/* The actual diagram — column labels + nodes + arrows */}
          <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
            <div style={{ position: 'relative', width: archW, height: archH, transform: 'scale(0.92)', transformOrigin: 'top left' }}>
              {/* Column labels */}
              {COL_LABELS.map((cl, i) => (
                <div key={i} className="dp-kicker" style={{
                  position: 'absolute',
                  left: GRID_PAD_X + i * (COL_W + COL_GAP),
                  top: 14,
                  width: COL_W,
                  fontSize: 9,
                  letterSpacing: '0.14em',
                  color: 'var(--dp-text-muted)',
                }}>{cl}</div>
              ))}

              {/* Column dividers (faint) */}
              {COL_LABELS.map((_, i) => i < COL_LABELS.length - 1 && (
                <div key={`div-${i}`} style={{
                  position: 'absolute',
                  left: GRID_PAD_X + i * (COL_W + COL_GAP) + COL_W + COL_GAP / 2,
                  top: 0, bottom: 0, width: 1,
                  background: 'var(--dp-border-subtle)', opacity: 0.4,
                }} />
              ))}

              {/* SVG arrows */}
              <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
                <defs>
                  <marker id="arr-bg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                    <path d="M0,0 L10,5 L0,10 Z" fill="#344163" />
                  </marker>
                  <marker id="arr-hi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M0,0 L10,5 L0,10 Z" fill="#F5A623" />
                  </marker>
                </defs>

                {/* Background DAG edges */}
                {ARCH_EDGES_BG.map(([a, b], i) => {
                  const isHi = FLOW_AUDIT.some(s => s.from === a && s.to === b);
                  if (isHi) return null;
                  return <path key={i} d={arrowPath(a, b)} fill="none" stroke="#344163" strokeWidth="1" opacity="0.35" markerEnd="url(#arr-bg)" />;
                })}

                {/* Highlighted flow */}
                {FLOW_AUDIT.map((s, i) => (
                  <path key={i} d={arrowPath(s.from, s.to)} fill="none" stroke="#F5A623" strokeWidth={s.dashed ? 1.2 : 2} strokeDasharray={s.dashed ? '3 3' : 'none'} opacity={s.dashed ? 0.5 : 0.95} markerEnd={s.dashed ? null : 'url(#arr-hi)'} />
                ))}

                {/* Step numbers on highlighted edges */}
                {FLOW_AUDIT.filter(s => !s.dashed).map((s, i) => {
                  const f = ARCH_NODES[s.from], t = ARCH_NODES[s.to];
                  const fp = nodePos(f), tp = nodePos(t);
                  const mx = (fp.x + COL_W + tp.x) / 2;
                  const my = (fp.y + NODE_H / 2 + tp.y + NODE_H / 2) / 2;
                  return (
                    <g key={`n-${i}`}>
                      <circle cx={mx} cy={my} r="9" fill="#0A0E17" stroke="#F5A623" strokeWidth="1.5" />
                      <text x={mx} y={my + 3} textAnchor="middle" fontSize="10" fontWeight="700" fill="#F5A623" fontFamily="var(--dp-font-mono)">{s.step}</text>
                    </g>
                  );
                })}
              </svg>

              {/* Nodes */}
              {Object.entries(ARCH_NODES).map(([id, n]) => {
                const highlighted = FLOW_AUDIT.some(s => s.from === id || s.to === id) && !n.muted;
                return <ArchNode key={id} id={id} n={n} highlighted={highlighted} />;
              })}
            </div>
          </div>
          {/* Zoom + pan + reset controls */}
          <div style={{ position: 'absolute', bottom: 14, right: 14, display: 'flex', flexDirection: 'column', background: 'var(--dp-bg-sunken)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, overflow: 'hidden' }}>
            <button title="Zoom in" style={{ width: 28, height: 28, color: 'var(--dp-text-soft)', borderBottom: '1px solid var(--dp-border-subtle)' }}>+</button>
            <button title="Zoom out" style={{ width: 28, height: 28, color: 'var(--dp-text-soft)', borderBottom: '1px solid var(--dp-border-subtle)' }}>−</button>
            <button title="Reset view" style={{ width: 28, height: 28, color: 'var(--dp-text-soft)', fontSize: 9, fontFamily: 'var(--dp-font-mono)' }}>1:1</button>
          </div>
          <div style={{ position: 'absolute', bottom: 14, right: 50, padding: '3px 7px', background: 'var(--dp-bg-sunken)', border: '1px solid var(--dp-border-subtle)', borderRadius: 999, fontFamily: 'var(--dp-font-mono)', fontSize: 10, color: 'var(--dp-text-muted)' }}>92%</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minHeight: 0 }}>
          <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 6, flexShrink: 0 }}>
            <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--dp-border-subtle)' }}>
              <div className="dp-kicker">FLOWS</div>
              <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 2 }}>Pick one to highlight the path</div>
            </div>
            <FlowItem name="Lock the scope of a change" sub="You write a plan · DontPanic locks the bounds" source="authored" />
            <FlowItem name="An AI does the work" sub="Builder agent executes within the locked scope" source="authored" />
            <FlowItem name="Cross-model audit" sub="Three independent AIs review the diff" source="authored" active />
            <FlowItem name="Human gate" sub="You approve, request changes, or reject" source="authored" />
            <FlowItem name="Safe to ship" sub="Approved change → PR → CI/CD → production" source="authored" />
            <FlowItem name="Setup needed for tools" sub="How a vendor key reaches its AI role" source="authored" />
            <FlowItem name="Dashboard build & open" sub="Derived from imports in scripts/dontpanic_dashboard" source="derived" />
            <FlowItem name="Architecture regen" sub="References missing builder module" source="authored" warning />
          </div>

          <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 6, flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--dp-border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div className="dp-kicker">STEPS · CROSS-MODEL AUDIT</div>
                <div style={{ fontSize: 13, fontWeight: 600, marginTop: 2, color: '#F5A623' }}>7 steps · runs in parallel</div>
              </div>
              <Chip variant="recommended">~45s</Chip>
            </div>
            <div style={{ overflow: 'auto', flex: 1 }}>
              <StepItem n="1" title="Working tree → Code reviewer" body="The Builder agent's branch is handed to Reviewer #1 — an AI explicitly asked to read the diff with skeptical eyes." source="scripts/dontpanic_orchestrate/dispatch.py:142" planId="plan-2026-05-016" />
              <StepItem n="2" title="Working tree → Devil's advocate" body="Same diff, different reviewer model. This AI is prompted to argue against the changes — find the case for rejecting." source="scripts/dontpanic_orchestrate/dispatch.py:168" planId="plan-2026-05-016" />
              <StepItem n="3" title="Working tree → Quality check" body="Third reviewer runs the test suite and checks coverage against your plan's acceptance criteria." source="scripts/dontpanic_orchestrate/verifier.py:142" planId="plan-2026-05-016" command="dontpanic verify vol-4f1a" />
              <StepItem n="4" title="Code reviewer → Consensus" body="Reviewer posts its verdict, written in plain language: what it caught, what it let pass, and why." source="scripts/dontpanic_orchestrate/consensus.py:54" />
              <StepItem n="5" title="Devil's advocate → Consensus" body="Devil's advocate posts its strongest argument against shipping — even if it ultimately approves." source="scripts/dontpanic_orchestrate/consensus.py:78" />
              <StepItem n="6" title="Quality check → Consensus" body="Pass/fail on tests; coverage delta; any regressions vs main. Three numbers, one verdict." source="scripts/dontpanic_orchestrate/consensus.py:102" />
              <StepItem n="7" title="Consensus → Review summary" body="If all three pass, the summary is packaged for you. If any rejects, the plan goes back to Working and the agent gets the feedback." source="scripts/dontpanic_orchestrate/packet.py:88" command="dontpanic review vol-4f1a --open" />
            </div>
          </div>
        </div>
      </div>

      <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Provenance source="static diagram · derived from .dontpanic/config.yaml + capabilities/*.yaml" updated="—" />
        <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only · diagram reflects configured services only</span>
      </footer>
    </Shell>
  );
};

/* ──────────────────────────────────────────────────────────
   DESIGN NOTES
   ────────────────────────────────────────────────────────── */
const PageArchitectureNotes = () => (
  <div className="dp" style={{ width: 1440, padding: '32px 36px', background: 'var(--dp-bg-base)' }}>
    <div className="dp-kicker" style={{ marginBottom: 8 }}>FUTURE · ARCHITECTURE — DESIGN NOTES</div>
    <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 6 }}>Why this lands after v0, and what it does for you</h1>
    <p style={{ color: 'var(--dp-text-muted)', fontSize: 13, marginBottom: 24, maxWidth: 760 }}>
      The v0 brief deferred Architecture for good reason: it's the kind of surface you build once you have stable telemetry to populate it, and v0 doesn't yet. This sketch is the target — not a v0 deliverable.
    </p>

    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 22 }}>
      <div style={{ padding: 18, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderLeft: '3px solid var(--dp-brand)', borderRadius: 5 }}>
        <div className="dp-kicker" style={{ marginBottom: 8, color: 'var(--dp-brand)' }}>WHAT THE PAGE DOES</div>
        <div style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--dp-text-soft)' }}>
          One glance at the full pipeline: every actor (you, your team), every AI role (Builder, Reviewer, Devil's Advocate, Quality Check), every data file (plans, locks, evidence), every external service (GitHub, OpenAI, Anthropic, Google, MCP servers).
          <br /><br />
          A right-rail list of <em>flows</em> — pick one and the diagram traces its path with numbered yellow arrows. The Steps panel narrates the same flow in plain language.
        </div>
      </div>

      <div style={{ padding: 18, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderLeft: '3px solid var(--dp-action)', borderRadius: 5 }}>
        <div className="dp-kicker" style={{ marginBottom: 8, color: 'var(--dp-action)' }}>WHY IT'S NOT IN v0</div>
        <div style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--dp-text-soft)' }}>
          A diagram that lies is worse than no diagram. To draw the real graph honestly we need three things v0 doesn't have yet:
          <br /><br />
          <strong style={{ color: 'var(--dp-text)' }}>1.</strong> A capability registry that's populated with real connections (not stub probes).
          <br /><strong style={{ color: 'var(--dp-text)' }}>2.</strong> Plan/volley telemetry that names which agent ran which step.
          <br /><strong style={{ color: 'var(--dp-text)' }}>3.</strong> A flow definition format so the same DAG isn't hand-maintained in 4 places.
        </div>
      </div>
    </div>

    <div style={{ padding: 18, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, marginBottom: 22 }}>
      <div className="dp-kicker" style={{ marginBottom: 10 }}>DESIGN PRINCIPLES — should apply when this lands</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 18 }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Render only what's configured</div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>If MCP servers aren't connected, the node grays out. Empty rows collapse. The diagram is a mirror of <span className="dp-mono">.dontpanic/config.yaml</span>, not an idealized architecture poster.</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Flows are first-class</div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>Don't show one static DAG — let the user pick a flow ("how does an AI's work get reviewed?") and trace it. The same diagram supports 6+ stories.</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Numbers, not jargon</div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>Step labels read like sentences: "An AI is asked to argue against the change." Never: "Challenger agent invoked with diff payload."</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Connects to real artifacts</div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>Clicking the <em>Review summary</em> node opens the latest <span className="dp-mono">evidence/*</span> packet. Clicking <em>GitHub</em> opens the most recent PR. Diagram → action, not diagram → diagram.</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Same color system</div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>Five node colors map to: Human / AI agent / Data / Gate / External. No new palette. The 4-band status system still applies to runtime indicators on nodes (e.g. a service is Blocked).</div>
        </div>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Honest about gaps</div>
          <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>If a flow can't be traced because telemetry is missing, the highlighted arrows simply stop — and the Steps panel shows the empty-state component asking the operator to enable that capability.</div>
        </div>
      </div>
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
      <div style={{ padding: 14, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5 }}>
        <div className="dp-kicker" style={{ color: 'var(--dp-healthy)', marginBottom: 6 }}>MILESTONE A · "READ-ONLY DIAGRAM"</div>
        <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>Static node graph driven by config. No flow tracing, no click-through. Lowest cost — ships when the capability registry is real.</div>
      </div>
      <div style={{ padding: 14, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5 }}>
        <div className="dp-kicker" style={{ color: 'var(--dp-action)', marginBottom: 6 }}>MILESTONE B · "FLOWS"</div>
        <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>Right-rail flows list. Highlighted path with numbered arrows. Step descriptions in plain language. Needs a flow-definition format committed to the config.</div>
      </div>
      <div style={{ padding: 14, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5 }}>
        <div className="dp-kicker" style={{ color: 'var(--dp-brand)', marginBottom: 6 }}>MILESTONE C · "LIVE STATE"</div>
        <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.55 }}>Status pips on nodes (healthy/action/blocked/pending). Click a node → see active volleys on it. Click an arrow → see recent traffic. Needs runtime telemetry.</div>
      </div>
    </div>
  </div>
);

Object.assign(window, { PageArchitecture, PageArchitectureNotes, ARCH_NODES, ARCH_EDGES_BG, NODE_TYPES, COL_LABELS, COL_W, COL_GAP, NODE_H, NODE_GAP, GRID_PAD_X, GRID_PAD_Y, nodePos, arrowPath, ArchNode, FlowItem, StepItem, Legend });
