/* Documentation artboards: Empty states · Component inventory · Tokens · Implementation notes */

/* ──────────────────────────────────────────────────────────
   EMPTY STATES — for each kind of missing data
   ────────────────────────────────────────────────────────── */
const PageEmpty = () => (
  <div className="dp" style={{ width: 1440, height: 900, padding: '32px 36px', background: 'var(--dp-bg-base)', display: 'flex', flexDirection: 'column' }}>
    <div className="dp-kicker" style={{ marginBottom: 8 }}>DELIVERABLE 07</div>
    <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 6 }}>Empty states for missing data</h1>
    <p style={{ color: 'var(--dp-text-muted)', fontSize: 13, marginBottom: 24, maxWidth: 640 }}>
      Operators distrust pages that lie. Every empty state names the absent data source, says why it might be missing, and offers the exact command to populate it. Never fake numbers; never collapse the panel as if the feature were disabled.
    </p>

    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, flex: 1 }}>
      {/* 1. Never probed */}
      <div>
        <div className="dp-kicker" style={{ marginBottom: 8 }}>01 · NEVER PROBED</div>
        <EmptyState
          icon={IconClock}
          title="No probe data for this capability yet"
          body="DontPanic hasn't checked whether OpenClaw/Hermes is reachable from this machine. Run a probe to populate the row."
          command="dontpanic caps probe hermes"
          source="capabilities/hermes.yaml"
        />
      </div>

      {/* 2. Stale */}
      <div>
        <div className="dp-kicker" style={{ marginBottom: 8 }}>02 · STALE</div>
        <EmptyState
          icon={IconWarn}
          title="Doctor scan hasn't run in 6h"
          body="The last sweep is stale enough that we can't vouch for it. The values below are what we last saw — re-run before relying on them."
          command="dontpanic doctor --force"
          source=".dontpanic/doctor.json (mtime: 14:22 UTC)"
        />
      </div>

      {/* 3. Capability missing */}
      <div>
        <div className="dp-kicker" style={{ marginBottom: 8 }}>03 · CAPABILITY MISSING</div>
        <EmptyState
          icon={IconBlocked}
          title="No cost-provider capability configured"
          body="DontPanic can show daily token spend and per-plan budgets when a cost provider is connected. None is configured — add one to populate."
          command="dontpanic caps add cost-provider"
          source="capabilities/cost-provider.yaml (does not exist)"
        />
      </div>

      {/* 4. No items yet */}
      <div>
        <div className="dp-kicker" style={{ marginBottom: 8 }}>04 · NO ITEMS YET</div>
        <EmptyState
          icon={IconDoc}
          title="No plans in this project"
          body="DontPanic looks for plan files in plans/. None were found. Create your first plan to unlock the Work view."
          command="dontpanic plan new add-auth"
          source="plans/ (0 files)"
        />
      </div>

      {/* 5. Permission denied */}
      <div>
        <div className="dp-kicker" style={{ marginBottom: 8 }}>05 · PERMISSION DENIED</div>
        <EmptyState
          icon={IconKey}
          title="DontPanic cannot read security scan results"
          body=".dontpanic/security/ exists but is not readable by the current user. Either fix the permissions or re-run as the owning user."
          command="ls -la .dontpanic/security/"
          source=".dontpanic/security/ (mode 0600 root:root)"
        />
      </div>

      {/* 6. Deferred / future */}
      <div>
        <div className="dp-kicker" style={{ marginBottom: 8 }}>06 · DEFERRED</div>
        <div className="dp-empty" style={{ borderStyle: 'dashed', borderColor: 'var(--dp-border-subtle)' }}>
          <div className="dp-empty__title">
            <IconLink size={14} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} />
            Integrations are coming, not here yet
          </div>
          <div className="dp-empty__body">
            Linear, Discord, and Firebase integrations are deferred to a later milestone. They're listed in the sidebar so you know what's planned, but not surfaced in v0 navigation as first-class tabs.
          </div>
          <div className="dp-empty__prov">
            <IconDoc size={11} sw={1.8} />
            <span>tracked in <span style={{ color: 'var(--dp-text-soft)' }}>docs/roadmap.md#integrations</span></span>
          </div>
        </div>
      </div>
    </div>
  </div>
);


/* ──────────────────────────────────────────────────────────
   COMPONENT INVENTORY
   ────────────────────────────────────────────────────────── */
const InvItem = ({ name, hint, children, span = 1, h }) => (
  <div style={{ gridColumn: `span ${span}`, padding: 18, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, display: 'flex', flexDirection: 'column' }}>
    <div className="dp-kicker">{name}</div>
    <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', marginTop: 4, marginBottom: 16 }}>{hint}</div>
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'flex-start', flexWrap: 'wrap', gap: 10, minHeight: h || 'auto' }}>
      {children}
    </div>
  </div>
);

const PageInventory = () => (
  <div className="dp" style={{ width: 1440, padding: '32px 36px', background: 'var(--dp-bg-base)' }}>
    <div className="dp-kicker" style={{ marginBottom: 8 }}>DELIVERABLE 08</div>
    <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 6 }}>Component inventory</h1>
    <p style={{ color: 'var(--dp-text-muted)', fontSize: 13, marginBottom: 24, maxWidth: 640 }}>
      Every component used in the v0 IA cleanup. Reuse these by name in implementation; do not invent new visual variants outside this set.
    </p>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
      <InvItem name="STATUS BADGE" hint="Use exactly these four bands. No others.">
        <Badge band="healthy">Healthy</Badge>
        <Badge band="action">Needs action</Badge>
        <Badge band="blocked">Blocked</Badge>
        <Badge band="pending">Pending</Badge>
      </InvItem>

      <InvItem name="STATUS PIP" hint="Dot-only variant for dense rows.">
        <span className="dp-row-flex" style={{ gap: 12 }}>
          <Pip band="healthy" /><Pip band="action" /><Pip band="blocked" /><Pip band="pending" />
        </span>
      </InvItem>

      <InvItem name="RELEVANCE CHIP" hint="‘Optional’ is a chip, NEVER a status band.">
        <Chip variant="optional">Optional</Chip>
        <Chip variant="recommended">Recommended</Chip>
        <Chip variant="required">Required</Chip>
      </InvItem>

      <InvItem name="COMMAND CHIP — INLINE" hint="Embed in tables and rows. Read-only with copy.">
        <Cmd inline>dontpanic doctor</Cmd>
        <Cmd inline>dontpanic review vol-2b7e</Cmd>
      </InvItem>

      <InvItem name="COMMAND CHIP — BLOCK" hint="Use in action cards and drawer.">
        <Cmd block>dontpanic caps setup openai --interactive</Cmd>
      </InvItem>

      <InvItem name="PROVENANCE FOOTER" hint="Source + last-updated + scope. On every page.">
        <Provenance source=".dontpanic/state.yaml" updated="14s ago" scope="silex-research/dontpanic@main" />
      </InvItem>

      <InvItem name="WARNING ROW" hint="Row variant used in Home attention feed." span={2}>
        <div style={{ width: '100%', background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4 }}>
          <HomeAttentionRow
            band="action"
            title="Human gate: review evidence packet for billing changes"
            meta={<><Badge band="action">Needs action</Badge><span className="dp-mono">vol-2b7e · gate 4/5</span></>}
            source="evidence/vol-2b7e/packet.md"
            action="dontpanic review vol-2b7e"
          />
        </div>
      </InvItem>

      <InvItem name="ACTIVE VOLLEY ROW" hint="Right-rail volley list.">
        <div style={{ width: '100%', background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4 }}>
          <VolleyRow
            name="add-auth.md"
            model="sonnet-4.5"
            agent="Reviewer"
            step="audit"
            gate={{ band: 'pending', label: 'Auditing' }}
            elapsed="3m 12s"
          />
        </div>
      </InvItem>

      <InvItem name="CAPABILITY SETUP ROW" hint="Wide row with steps + command. Truncated here." span={3}>
        <div style={{ width: '100%', background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4 }}>
          <CapRow
            band="action"
            name="OpenAI"
            vendor="api.openai.com"
            provides="Verifier agent · gpt-5-codex"
            owner="You"
            probe={{ label: 'last 6m · 401', color: 'var(--dp-action)' }}
          />
        </div>
      </InvItem>

      <InvItem name="TOP STATUS STRIP" hint="Persistent. Project + freshness + warnings + volleys + system health." span={3}>
        <div style={{ width: '100%', borderRadius: 4, overflow: 'hidden', border: '1px solid var(--dp-border-subtle)' }}>
          <TopStrip warnings={3} volleys={2} health="action" />
        </div>
      </InvItem>

      <InvItem name="PROJECT SELECTOR" hint="Top-strip cell. Dropdown opens a project list." span={1}>
        <button className="dp-topstrip__cell" style={{ background: 'var(--dp-bg-sunken)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4, height: 32 }}>
          <span className="dp-topstrip__cell-label">project</span>
          <span className="dp-topstrip__cell-value dp-mono">silex-research/dontpanic</span>
          <IconChevD size={11} style={{ color: 'var(--dp-text-muted)' }} />
        </button>
      </InvItem>

      <InvItem name="EMPTY STATE" hint="Diagonal-hatch background distinguishes from real data." span={2}>
        <EmptyState
          icon={IconClock}
          title="No probe data for this capability yet"
          body="DontPanic hasn't checked this capability from this machine. Run a probe to populate the row."
          command="dontpanic caps probe hermes"
          source="capabilities/hermes.yaml"
        />
      </InvItem>
    </div>
  </div>
);


/* ──────────────────────────────────────────────────────────
   DESIGN TOKENS
   ────────────────────────────────────────────────────────── */
const Swatch = ({ name, varName, value, sub, text = '#000' }) => (
  <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, overflow: 'hidden' }}>
    <div style={{ height: 56, background: value, borderBottom: '1px solid var(--dp-border-subtle)' }} />
    <div style={{ padding: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 600 }}>{name}</div>
      <div className="dp-mono" style={{ fontSize: 10, color: 'var(--dp-text-muted)' }}>{varName}</div>
      <div className="dp-mono" style={{ fontSize: 10, color: 'var(--dp-text-dim)' }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 4 }}>{sub}</div>}
    </div>
  </div>
);

const TypeRow = ({ name, sample, size, weight = 400, family = 'sans' }) => (
  <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr 180px', gap: 16, padding: '12px 0', borderTop: '1px solid var(--dp-border-subtle)', alignItems: 'baseline' }}>
    <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{name}</div>
    <div style={{ fontFamily: family === 'mono' ? 'var(--dp-font-mono)' : 'var(--dp-font-sans)', fontSize: size, fontWeight: weight }}>{sample}</div>
    <div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>{size}px · {weight} · {family}</div>
  </div>
);

const SpaceBar = ({ name, px }) => (
  <div className="dp-row-flex" style={{ gap: 12, padding: '6px 0' }}>
    <span style={{ width: 60, fontSize: 12, color: 'var(--dp-text-muted)' }} className="dp-mono">{name}</span>
    <span style={{ height: 14, width: px, background: 'var(--dp-brand)', opacity: 0.6, borderRadius: 2 }} />
    <span style={{ fontSize: 12, color: 'var(--dp-text-muted)' }} className="dp-mono">{px}px</span>
  </div>
);

const PageTokens = () => (
  <div className="dp" style={{ width: 1440, padding: '32px 36px', background: 'var(--dp-bg-base)' }}>
    <div className="dp-kicker" style={{ marginBottom: 8 }}>DELIVERABLE 09</div>
    <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 6 }}>Design tokens</h1>
    <p style={{ color: 'var(--dp-text-muted)', fontSize: 13, marginBottom: 24, maxWidth: 640 }}>
      The full token set powering this design. Implementation should map these to CSS custom properties on <span className="dp-mono">:root</span> in <span className="dp-mono">core.css</span>.
    </p>

    {/* SURFACES */}
    <div className="dp-kicker" style={{ marginBottom: 10 }}>SURFACES</div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12, marginBottom: 24 }}>
      <Swatch name="Base" varName="--dp-bg-base" value="#0A0E17" sub="page background" />
      <Swatch name="Sunken" varName="--dp-bg-sunken" value="#070A11" sub="sidebar, top strip" />
      <Swatch name="Panel" varName="--dp-bg-panel" value="#0F1521" sub="primary panel" />
      <Swatch name="Elevated" varName="--dp-bg-elevated" value="#131A2A" sub="row hover, drawer" />
      <Swatch name="Row inset" varName="--dp-bg-row" value="#0C111B" sub="zebra, table head" />
      <Swatch name="Border" varName="--dp-border" value="#25304A" sub="default border" />
    </div>

    {/* STATUS */}
    <div className="dp-kicker" style={{ marginBottom: 10 }}>STATUS BANDS — these four, nothing else</div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
      <Swatch name="Healthy" varName="--dp-healthy" value="#3DD68C" sub="green · safe-to-ship spectrum" />
      <Swatch name="Needs action" varName="--dp-action" value="#F5A623" sub="amber · human gate, setup" />
      <Swatch name="Blocked" varName="--dp-blocked" value="#F25555" sub="red · plan locked / probe failed" />
      <Swatch name="Pending" varName="--dp-pending" value="#7E8BA6" sub="slate · waiting / not-started" />
    </div>

    {/* BRAND */}
    <div className="dp-kicker" style={{ marginBottom: 10 }}>BRAND</div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
      <Swatch name="DontPanic violet" varName="--dp-brand" value="#8B6FFF" sub="primary accent" />
      <Swatch name="Brand deep" varName="--dp-brand-deep" value="#5B3FE0" sub="mark gradient base" />
      <Swatch name="Relevance blue" varName="--dp-relevance" value="#6CA8FF" sub="recommended chip" />
      <Swatch name="Text primary" varName="--dp-text" value="#E6EAF3" sub="body, headlines" />
    </div>

    {/* TYPE */}
    <div className="dp-kicker" style={{ marginBottom: 10 }}>TYPOGRAPHY</div>
    <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, padding: '4px 18px', marginBottom: 24 }}>
      <TypeRow name="Display" sample="What now" size={20} weight={600} />
      <TypeRow name="H2" sample="External readiness" size={15} weight={600} />
      <TypeRow name="Body" sample="Plan lock expired during cross-model audit" size={13} weight={400} />
      <TypeRow name="Meta" sample="last 6m · 401" size={12} weight={400} family="mono" />
      <TypeRow name="Micro" sample="Needs action" size={11} weight={600} />
      <TypeRow name="Nano (kicker)" sample="CAPABILITIES" size={10} weight={600} />
      <TypeRow name="Mono command" sample="$ dontpanic doctor --force" size={13} weight={500} family="mono" />
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      {/* SPACING */}
      <div>
        <div className="dp-kicker" style={{ marginBottom: 10 }}>SPACING — 4px base</div>
        <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, padding: 14 }}>
          <SpaceBar name="sp-1" px={4} />
          <SpaceBar name="sp-2" px={8} />
          <SpaceBar name="sp-3" px={12} />
          <SpaceBar name="sp-4" px={16} />
          <SpaceBar name="sp-5" px={20} />
          <SpaceBar name="sp-6" px={24} />
          <SpaceBar name="sp-8" px={32} />
          <SpaceBar name="sp-10" px={40} />
        </div>
      </div>

      {/* RADII */}
      <div>
        <div className="dp-kicker" style={{ marginBottom: 10 }}>RADIUS</div>
        <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, padding: 14, display: 'flex', alignItems: 'center', gap: 18 }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ width: 60, height: 60, background: 'var(--dp-bg-elevated)', border: '1px solid var(--dp-border)', borderRadius: 3 }} />
            <div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 6 }}>r-1 · 3px</div>
            <div style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>rows · inputs · chips</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ width: 60, height: 60, background: 'var(--dp-bg-elevated)', border: '1px solid var(--dp-border)', borderRadius: 5 }} />
            <div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 6 }}>r-2 · 5px</div>
            <div style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>panels · cards</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ width: 60, height: 60, background: 'var(--dp-bg-elevated)', border: '1px solid var(--dp-border)', borderRadius: 8 }} />
            <div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 6 }}>r-3 · 8px</div>
            <div style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>large surfaces</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ width: 60, height: 24, background: 'var(--dp-bg-elevated)', border: '1px solid var(--dp-border)', borderRadius: 999, marginTop: 18 }} />
            <div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 6 }}>r-pill</div>
            <div style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>badges · chips</div>
          </div>
        </div>

        <div className="dp-kicker" style={{ margin: '18px 0 10px' }}>BORDER & DIVIDER RULES</div>
        <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, padding: 14, fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.7 }}>
          <div>• Outer panel border: <span className="dp-mono" style={{ color: 'var(--dp-text-soft)' }}>1px var(--dp-border-subtle)</span></div>
          <div>• Row dividers within a panel: same subtle border</div>
          <div>• No nested cards. A panel is the deepest level.</div>
          <div>• No drop shadows on panels. Reserve shadow for the drawer hover state only.</div>
          <div>• No gradients except the brand mark.</div>
        </div>
      </div>
    </div>
  </div>
);


/* ──────────────────────────────────────────────────────────
   IMPLEMENTATION NOTES — map design → existing files
   ────────────────────────────────────────────────────────── */
const ImplRow = ({ what, files, action }) => (
  <tr>
    <td style={{ padding: '10px 14px', borderTop: '1px solid var(--dp-border-subtle)', verticalAlign: 'top' }}>{what}</td>
    <td style={{ padding: '10px 14px', borderTop: '1px solid var(--dp-border-subtle)', verticalAlign: 'top', fontFamily: 'var(--dp-font-mono)', fontSize: 12, color: 'var(--dp-text-soft)' }}>
      {files.map((f, i) => <div key={i}>{f}</div>)}
    </td>
    <td style={{ padding: '10px 14px', borderTop: '1px solid var(--dp-border-subtle)', verticalAlign: 'top', fontSize: 12, color: 'var(--dp-text-muted)' }}>{action}</td>
  </tr>
);

const PageImpl = () => (
  <div className="dp" style={{ width: 1440, padding: '32px 36px', background: 'var(--dp-bg-base)' }}>
    <div className="dp-kicker" style={{ marginBottom: 8 }}>DELIVERABLE 10</div>
    <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 6 }}>Implementation notes</h1>
    <p style={{ color: 'var(--dp-text-muted)', fontSize: 13, marginBottom: 20, maxWidth: 720 }}>
      Adapt the existing static dashboard files. <strong style={{ color: 'var(--dp-text)' }}>No React rewrite.</strong> Most work is CSS variable swaps, layout re-parenting, and tab renames. No new runtime data sources are introduced.
    </p>

    {/* Plan in 3 phases */}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 22 }}>
      <div style={{ padding: 14, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5 }}>
        <div className="dp-kicker" style={{ color: 'var(--dp-brand)', marginBottom: 6 }}>PHASE 1 · TOKENS</div>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Replace the palette in <span className="dp-mono">core.css</span></div>
        <div style={{ fontSize: 12, color: 'var(--dp-text-muted)' }}>Swap the <span className="dp-mono">:root</span> block 1-for-1 with the dp-* tokens. Every existing class continues to render — just with a calmer palette. Map old to new: <span className="dp-mono">--accent → --dp-brand</span>, <span className="dp-mono">--green → --dp-healthy</span>, <span className="dp-mono">--yellow → --dp-action</span>, <span className="dp-mono">--red → --dp-blocked</span>.</div>
      </div>
      <div style={{ padding: 14, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5 }}>
        <div className="dp-kicker" style={{ color: 'var(--dp-action)', marginBottom: 6 }}>PHASE 2 · IA</div>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Move tabs into a left sidebar</div>
        <div style={{ fontSize: 12, color: 'var(--dp-text-muted)' }}>Replace <span className="dp-mono">.view-nav</span> with a vertical <span className="dp-mono">.dp-sidebar</span>. Lift the project selector out of the page area and into the top strip. Rename Mission Control to Work; update the wordmark and footer to DontPanic; remove Financial and Cloud Costs from nav.</div>
      </div>
      <div style={{ padding: 14, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5 }}>
        <div className="dp-kicker" style={{ color: 'var(--dp-healthy)', marginBottom: 6 }}>PHASE 3 · POLISH</div>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Provenance footer, empty states, command chips</div>
        <div style={{ fontSize: 12, color: 'var(--dp-text-muted)' }}>Add one provenance footer per page. Wrap every "missing data" state in the diagonal-hatch empty-state component. Replace bare CLI snippets with the command-chip component (copy button).</div>
      </div>
    </div>

    <div style={{ background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, overflow: 'hidden' }}>
      <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--dp-border-subtle)', display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>Design element → existing files → action</span>
        <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>18 changes · 0 new runtime sources</span>
      </div>
      <table className="dp-table">
        <thead>
          <tr>
            <th style={{ width: '24%' }}>Design element</th>
            <th style={{ width: '38%' }}>Existing file(s)</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          <ImplRow what="Brand wordmark + title" files={["dashboard/index.html"]} action="Set the page title to 'DontPanic — Operator Console'. Replace the existing <h1> wordmark with the DontPanic name and inline shield SVG mark. Update the footer credit line." />
          <ImplRow what="Token palette swap" files={["dashboard/core.css :root"]} action="Replace :root block with dp-tokens. Keep variable names if useful, but introduce --dp-* aliases. All existing rules adopt the new palette." />
          <ImplRow what="Sidebar nav (replaces .view-nav)" files={["dashboard/index.html", "dashboard/core.css .view-nav", "dashboard/core.js (page registration)"]} action="Convert horizontal tab bar to vertical .dp-sidebar. Keep the existing page-registration callback so each .dp-nav-item triggers the same show/hide as today." />
          <ImplRow what="Persistent top strip" files={["dashboard/index.html", "dashboard/core.css .project-selector-bar"]} action="Replace .project-selector-bar with .dp-topstrip. Move the project selector inside it. Add freshness / warnings / volleys cells, all rendered from existing state already loaded by core.js." />
          <ImplRow what="Rename Mission Control → Work" files={["dashboard/pages/mission-control/*", "dashboard/lib/mission-control-logic.js", "core.js (tab labels)"]} action="Rename folder to dashboard/pages/work/. Update the tab label and file links. Keep the existing JS logic; this is a label-only change. No data shape change." />
          <ImplRow what="Remove drag/drop affordance from Work board" files={["dashboard/pages/mission-control/mission-control.css", "dashboard/pages/mission-control/mission-control.js"]} action="Strip cursor:grab / drag handles / draggable attrs. Keep the rendered cards as static rows in a table layout grouped by status (Draft/Active/Completed)." />
          <ImplRow what="Hide Financial tab" files={["dashboard/index.html (link tag)", "dashboard/pages/financial/*", "core.js (page register)"]} action="Comment out the financial CSS import and unregister from the nav. Leave the files in place — defer, do not delete." />
          <ImplRow what="Hide Cloud Costs tab" files={["dashboard/pages/cloud-costs/*", "dashboard/lib/cloud-costs-logic.js"]} action="Same treatment as Financial. Reachable only via direct URL until cost-provider capability exists." />
          <ImplRow what="Hide Command Center" files={["dashboard/pages/command-center/*"]} action="Defer. The 'agents online/busy/idle' display is a demo holdover and isn't part of v0 IA — agent state surfaces through Work and Capabilities instead." />
          <ImplRow what="Health page" files={["dashboard/pages/security/* (rename to health/)", "dashboard/lib/security-logic.js"]} action="Rename pages/security/ to pages/health/. Re-purpose the existing security-logic.js as the source for the Security panel; add Doctor and Reconcile panels as honest empty states until those scripts exist." />
          <ImplRow what="Settings → Preferences (UI-local only)" files={["dashboard/pages/settings/*", "dashboard/lib/settings-logic.js"]} action="Rename to pages/preferences/. Remove the hardcoded demo project rows. Strip any setting that writes outside localStorage. Add the prominent 'not DontPanic config' note." />
          <ImplRow what="Status badges (4 bands only)" files={["dashboard/core.css .status-badge"]} action="Replace .status-badge.online/busy/offline/idle with .dp-badge--healthy/action/blocked/pending. Provide a one-line alias block so any HTML that still uses the old class names keeps rendering during transition." />
          <ImplRow what="Relevance chip" files={["dashboard/core.css (new selector)"]} action="Add .dp-chip variants. Replace any 'Optional' badge currently rendered with a status-badge to instead use .dp-chip--optional." />
          <ImplRow what="Command chip with copy" files={["dashboard/core.css (new selector)", "dashboard/core.js (one-time clipboard handler)"]} action="Add .dp-cmd component. Bind a single delegated 'click' handler on .dp-cmd__copy to navigator.clipboard.writeText. No new dependencies." />
          <ImplRow what="Provenance footer" files={["dashboard/index.html footer", "dashboard/core.css footer"]} action="Replace the existing footer credit line with .dp-provenance showing source path + last-updated + scope. Each page's render fn supplies its own source string." />
          <ImplRow what="Empty states" files={["dashboard/core.css .empty-state", "all per-page render fns"]} action="Replace the centered empty-state with the left-aligned .dp-empty (diagonal hatch). Every page that today renders 'No data' should render the new variant with a source path and copyable command." />
          <ImplRow what="Project selector relocation" files={["dashboard/lib/project-selector-logic.js", "dashboard/core.css .project-selector*"]} action="Keep the existing logic, swap the host element to the top-strip cell. Render the dropdown menu as a positioned panel below the cell rather than as an inline bar." />
          <ImplRow what="Integrations group (deferred)" files={["dashboard/index.html sidebar", "(no page yet)"]} action="Add a muted 'Future · Integrations' group to the sidebar that doesn't link anywhere yet. Sets the operator expectation for Firebase / Linear / Discord without exposing them in core nav." />
        </tbody>
      </table>
    </div>

    <div style={{ marginTop: 18, padding: 14, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5 }}>
      <div className="dp-kicker" style={{ marginBottom: 8, color: 'var(--dp-blocked)' }}>OUT OF SCOPE FOR v0 — DO NOT BUILD</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, fontSize: 12, color: 'var(--dp-text-muted)' }}>
        <div>· Architecture view</div>
        <div>· Review / Evidence browser</div>
        <div>· Configuration editor</div>
        <div>· Local executor surface</div>
        <div>· Streaming logs panel</div>
        <div>· Embedded browser terminal</div>
        <div>· Session registry</div>
        <div>· Drag/drop kanban mutation</div>
        <div>· Inline state mutation of any kind</div>
      </div>
      <div style={{ fontSize: 12, color: 'var(--dp-text-dim)', marginTop: 10 }}>
        If you find yourself building one of these, stop and confirm scope. The v0 invariant is read-only with copyable commands — anything beyond that is a separate plan.
      </div>
    </div>
  </div>
);

Object.assign(window, { PageEmpty, PageInventory, PageTokens, PageImpl });
