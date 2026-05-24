/* Fleet variants — Section 1.5 of the brief.
   When "All projects" is selected in the top strip, attention items group by project. */

const FleetProjectHeader = ({ name, summary, health }) => (
  <div style={{ padding: '10px 14px', background: 'var(--dp-bg-row)', borderBottom: '1px solid var(--dp-border-subtle)', display: 'flex', alignItems: 'center', gap: 10 }}>
    <IconFolder size={13} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} />
    <span style={{ fontWeight: 600, fontSize: 13 }}>{name}</span>
    <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>{summary}</span>
    <span style={{ marginLeft: 'auto' }} />
    <Badge band={health.band}>{health.label}</Badge>
  </div>
);

/* ──────────────────────────────────────────────────────────
   HOME — fleet view
   ────────────────────────────────────────────────────────── */
const PageHomeFleet = () => (
  <Shell active="home" height={1240} topStripProps={{ project: 'All projects (6)', updated: '14s ago', warnings: 9, reviews: 4, health: 'action' }}>
    <PageHead
      kicker="HOME · ALL PROJECTS"
      title="What now — across your fleet"
      sub="9 things need your attention across 6 projects · 4 AI reviews in flight"
      actions={
        <>
          <button className="dp-cmd dp-cmd--inline" style={{ background: 'transparent' }}>
            <IconRefresh size={12} />
            <span style={{ fontFamily: 'var(--dp-font-sans)' }}>Refresh</span>
          </button>
          <Provenance source="~/.dontpanic/projects.json" updated="14s ago" />
        </>
      }
    />

    <div className="dp-page__body" style={{ padding: '16px 24px', display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 380px', gap: 16, alignContent: 'start' }}>
      {/* LEFT — attention grouped by project */}
      <div className="dp-stack">
        <Panel kicker="STUCK" title="Needs you to unblock — across projects" action={<Chip variant="required">3 stuck</Chip>} noPad>
          <FleetProjectHeader name="silex-research/dontpanic" summary="2 items" health={{ band: 'blocked', label: 'Blocked' }} />
          <HomeAttentionRow
            band="blocked"
            title="Tests don't cover enough of the new code yet"
            meta={<><Badge band="blocked">Blocked</Badge><span>coverage 64% · project min 80%</span></>}
            source="dontpanic / plans/add-auth.md"
            action="dontpanic resume vol-4f1a --re-verify"
          />
          <HomeAttentionRow
            band="blocked"
            title="Approval window expired during independent review"
            meta={<><Badge band="blocked">Blocked</Badge></>}
            source="dontpanic / plans/api-rewrite.md"
            action="dontpanic plan extend vol-9c33"
          />

          <FleetProjectHeader name="silex/billing-svc" summary="1 item" health={{ band: 'blocked', label: 'Blocked' }} />
          <HomeAttentionRow
            band="blocked"
            title="Refactor introduced a regression in invoice totals"
            meta={<><Badge band="blocked">Blocked</Badge><span>quality check failed</span></>}
            source="billing-svc / plans/invoice-rounding.md"
            action="dontpanic review vol-c7d1 --open"
          />
        </Panel>

        <Panel kicker="APPROVALS" title="Approvals awaiting you" action={<Chip variant="required">2 waiting</Chip>} noPad>
          <FleetProjectHeader name="silex-research/dontpanic" summary="1 item" health={{ band: 'action', label: 'Needs action' }} />
          <HomeAttentionRow
            band="action"
            title="Review the billing change before it ships"
            meta={<><Badge band="action">Needs action</Badge><span>step 4 of 5</span></>}
            source="dontpanic / vol-2b7e"
            action="dontpanic review vol-2b7e --open"
          />
          <FleetProjectHeader name="silex/web-dashboard" summary="1 item" health={{ band: 'action', label: 'Needs action' }} />
          <HomeAttentionRow
            band="action"
            title="Approve OAuth scope additions"
            meta={<><Badge band="action">Needs action</Badge></>}
            source="web-dashboard / vol-d3a9"
            action="dontpanic review vol-d3a9 --open"
          />
        </Panel>

        <Panel kicker="SETUP" title="Setup needed for tools" action={<Chip variant="required">4 across projects</Chip>} noPad>
          <FleetProjectHeader name="silex-research/dontpanic" summary="2 items" health={{ band: 'action', label: 'Needs setup' }} />
          <HomeAttentionRow
            band="action"
            title="OpenAI isn't connected — one of three reviewers is offline"
            meta={<><Badge band="action">Needs action</Badge></>}
            source="dontpanic / capabilities/openai.yaml"
            action="dontpanic caps setup openai"
          />
          <HomeAttentionRow
            band="pending"
            title="GitHub needs one extra permission for ready-to-deploy"
            meta={<><Badge band="pending">Pending</Badge></>}
            source="dontpanic / capabilities/github.yaml"
            action="dontpanic caps probe github"
          />
          <FleetProjectHeader name="silex/api-gateway" summary="2 items" health={{ band: 'action', label: 'Needs setup' }} />
          <HomeAttentionRow
            band="action"
            title="Anthropic key over 90 days — rotate when convenient"
            meta={<><Badge band="action">Needs action</Badge></>}
            source="api-gateway / capabilities/anthropic.yaml"
            action="dontpanic caps rotate anthropic"
          />
          <HomeAttentionRow
            band="pending"
            title="OpenClaw/Hermes has been unreachable for 1h"
            meta={<><Badge band="pending">Pending</Badge></>}
            source="api-gateway / capabilities/hermes.yaml"
            action="dontpanic caps probe hermes"
          />
        </Panel>
      </div>

      {/* RIGHT */}
      <div className="dp-stack">
        <Panel kicker="ACROSS PROJECTS" title="AI reviews in flight" action={<span className="dp-mono dp-muted" style={{ fontSize: 11 }}>4 / 12 slots</span>}>
          <VolleyRow name="Add auth feature" file="dontpanic / vol-4f1a" model="sonnet-4.5" agent="Code reviewer" step="independent review" gate={{ band: 'pending', label: 'Reviewing' }} elapsed="3m" />
          <VolleyRow name="Refactor billing module" file="dontpanic / vol-2b7e" model="gpt-5-codex" agent="Quality check" step="your turn" gate={{ band: 'action', label: 'Awaiting you' }} elapsed="14m" />
          <VolleyRow name="Invoice rounding bug fix" file="billing-svc / vol-c7d1" model="opus-4" agent="Quality check" step="blocked" gate={{ band: 'blocked', label: 'Failed' }} elapsed="22m" />
          <VolleyRow name="OAuth scope review" file="web-dashboard / vol-d3a9" model="sonnet-4.5" agent="Code reviewer" step="your turn" gate={{ band: 'action', label: 'Awaiting you' }} elapsed="6m" />
        </Panel>

        <Panel kicker="PROJECT HEALTH" title="At a glance">
          {[
            { name: 'silex-research/dontpanic', band: 'action', items: '3 needs · 2 reviews' },
            { name: 'silex/api-gateway', band: 'action', items: '2 setup · 0 reviews' },
            { name: 'silex/web-dashboard', band: 'action', items: '1 review awaiting' },
            { name: 'silex/billing-svc', band: 'blocked', items: '1 stuck · needs eye' },
            { name: 'silex/internal-tools', band: 'pending', items: 'no setup yet' },
            { name: 'silex/marketing-site', band: 'healthy', items: 'all good' },
          ].map((p, i) => (
            <div key={i} className="dp-row" style={{ gridTemplateColumns: '8px 1fr auto', padding: '9px 14px' }}>
              <Pip band={p.band} />
              <span style={{ fontSize: 12 }}>{p.name}</span>
              <span style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>{p.items}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>

    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="~/.dontpanic/projects.json + per-project state.yaml" updated="14s ago" scope="6 projects" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only · click any row to open its project</span>
    </footer>
  </Shell>
);


/* ──────────────────────────────────────────────────────────
   WORK — fleet view
   ────────────────────────────────────────────────────────── */
const PageWorkFleet = () => (
  <Shell active="work" height={1100} topStripProps={{ project: 'All projects (6)', updated: '14s ago', warnings: 9, reviews: 4, health: 'action' }}>
    <PageHead
      kicker="WORK · ALL PROJECTS"
      title="Plans"
      sub="12 active plans across 6 projects · grouped by project · read-only"
      actions={
        <div className="dp-row-flex" style={{ gap: 8 }}>
          <div className="dp-row-flex" style={{ gap: 4, padding: 2, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 4 }}>
            <button style={{ padding: '4px 10px', color: 'var(--dp-text-muted)', borderRadius: 3, fontSize: 12 }}>Board</button>
            <button style={{ padding: '4px 10px', background: 'var(--dp-bg-elevated)', color: 'var(--dp-text)', borderRadius: 3, fontSize: 12, fontWeight: 600 }}>List</button>
          </div>
          <button className="dp-cmd dp-cmd--inline" style={{ background: 'var(--dp-bg-panel)' }}>
            <IconFilter size={12} />
            <span style={{ fontFamily: 'var(--dp-font-sans)' }}>Group: project</span>
            <IconChevD size={11} />
          </button>
        </div>
      }
    />

    <div className="dp-page__body" style={{ padding: '14px 24px' }}>
      <div className="dp-panel" style={{ overflow: 'hidden' }}>
        <table className="dp-table">
          <thead>
            <tr>
              <th style={{ width: 28 }}></th>
              <th>Plan</th>
              <th>Project</th>
              <th>Stage</th>
              <th>Reviewer / Model</th>
              <th>Owner</th>
              <th style={{ textAlign: 'right' }}>Updated</th>
            </tr>
          </thead>
          <tbody>
            <tr style={{ background: 'var(--dp-bg-row)' }}>
              <td colSpan={7} style={{ padding: '6px 16px', borderBottom: '1px solid var(--dp-border-subtle)' }}>
                <span className="dp-row-flex" style={{ gap: 8 }}>
                  <IconFolder size={11} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} />
                  <span className="dp-kicker" style={{ color: 'var(--dp-text)' }}>silex-research/dontpanic</span>
                  <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>4 plans · 2 stuck · 1 awaiting you</span>
                </span>
              </td>
            </tr>
            <tr>
              <td><Pip band="blocked" /></td>
              <td><span style={{ fontWeight: 600 }}>Add auth feature</span><div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>plans/add-auth.md</div></td>
              <td><span style={{ fontSize: 11, padding: '2px 7px', borderRadius: 3, background: 'rgba(139,111,255,0.10)', color: 'var(--dp-brand)', fontFamily: 'var(--dp-font-mono)' }}>dontpanic</span></td>
              <td><Badge band="blocked">Audit · 3/5</Badge></td>
              <td><span style={{ fontSize: 12 }}>Code reviewer · sonnet-4.5</span></td>
              <td><span style={{ fontSize: 12 }}>you</span></td>
              <td className="num" style={{ textAlign: 'right' }}>3m</td>
            </tr>
            <tr>
              <td><Pip band="action" /></td>
              <td><span style={{ fontWeight: 600 }}>Refactor billing module</span><div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>plans/billing-refactor.md</div></td>
              <td><span style={{ fontSize: 11, padding: '2px 7px', borderRadius: 3, background: 'rgba(139,111,255,0.10)', color: 'var(--dp-brand)', fontFamily: 'var(--dp-font-mono)' }}>dontpanic</span></td>
              <td><Badge band="action">Your turn · 4/5</Badge></td>
              <td><span style={{ fontSize: 12 }}>Quality check · gpt-5</span></td>
              <td><span style={{ fontSize: 12 }}>you</span></td>
              <td className="num" style={{ textAlign: 'right' }}>14m</td>
            </tr>

            <tr style={{ background: 'var(--dp-bg-row)' }}>
              <td colSpan={7} style={{ padding: '6px 16px', borderBottom: '1px solid var(--dp-border-subtle)' }}>
                <span className="dp-row-flex" style={{ gap: 8 }}>
                  <IconFolder size={11} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} />
                  <span className="dp-kicker" style={{ color: 'var(--dp-text)' }}>silex/billing-svc</span>
                  <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>2 plans · 1 stuck</span>
                </span>
              </td>
            </tr>
            <tr>
              <td><Pip band="blocked" /></td>
              <td><span style={{ fontWeight: 600 }}>Invoice rounding bug fix</span><div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>plans/invoice-rounding.md</div></td>
              <td><span style={{ fontSize: 11, padding: '2px 7px', borderRadius: 3, background: 'rgba(245,166,35,0.10)', color: 'var(--dp-action)', fontFamily: 'var(--dp-font-mono)' }}>billing-svc</span></td>
              <td><Badge band="blocked">Audit · 3/5</Badge></td>
              <td><span style={{ fontSize: 12 }}>Quality check · opus-4</span></td>
              <td><span style={{ fontSize: 12 }}>you</span></td>
              <td className="num" style={{ textAlign: 'right' }}>22m</td>
            </tr>

            <tr style={{ background: 'var(--dp-bg-row)' }}>
              <td colSpan={7} style={{ padding: '6px 16px', borderBottom: '1px solid var(--dp-border-subtle)' }}>
                <span className="dp-row-flex" style={{ gap: 8 }}>
                  <IconFolder size={11} sw={1.8} style={{ color: 'var(--dp-text-muted)' }} />
                  <span className="dp-kicker" style={{ color: 'var(--dp-text)' }}>silex/web-dashboard</span>
                  <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>3 plans · 1 awaiting you</span>
                </span>
              </td>
            </tr>
            <tr>
              <td><Pip band="action" /></td>
              <td><span style={{ fontWeight: 600 }}>Approve OAuth scope additions</span><div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>plans/oauth-scopes.md</div></td>
              <td><span style={{ fontSize: 11, padding: '2px 7px', borderRadius: 3, background: 'rgba(108,168,255,0.10)', color: 'var(--dp-relevance)', fontFamily: 'var(--dp-font-mono)' }}>web-dashboard</span></td>
              <td><Badge band="action">Your turn · 4/5</Badge></td>
              <td><span style={{ fontSize: 12 }}>Code reviewer · sonnet-4.5</span></td>
              <td><span style={{ fontSize: 12 }}>you</span></td>
              <td className="num" style={{ textAlign: 'right' }}>6m</td>
            </tr>
            <tr>
              <td><Pip band="healthy" /></td>
              <td><span style={{ fontWeight: 600 }}>Migrate to Tailwind 4</span><div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>plans/tailwind-4.md</div></td>
              <td><span style={{ fontSize: 11, padding: '2px 7px', borderRadius: 3, background: 'rgba(108,168,255,0.10)', color: 'var(--dp-relevance)', fontFamily: 'var(--dp-font-mono)' }}>web-dashboard</span></td>
              <td><Badge band="healthy">Executing · 2/5</Badge></td>
              <td><span style={{ fontSize: 12 }}>Builder · grok-4</span></td>
              <td><span style={{ fontSize: 12 }}>you</span></td>
              <td className="num" style={{ textAlign: 'right' }}>just now</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="per-project plans/*.md frontmatter" updated="14s ago" scope="6 projects · 12 plans" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only · click a project chip to filter</span>
    </footer>
  </Shell>
);


/* ──────────────────────────────────────────────────────────
   TOOLS & SETUP — fleet view (capabilities install-global, readiness per-project)
   ────────────────────────────────────────────────────────── */
const PageCapsFleet = () => (
  <Shell active="caps" height={1000} topStripProps={{ project: 'All projects (6)', updated: '14s ago', warnings: 9, reviews: 4, health: 'action' }}>
    <PageHead
      kicker="TOOLS & SETUP · ALL PROJECTS"
      title="Connections — per project"
      sub="Tools are installed globally on your machine, but each project decides which tools it needs. This shows readiness per project."
    />
    <div className="dp-page__body" style={{ padding: '14px 24px' }}>
      <div className="dp-panel" style={{ overflow: 'hidden' }}>
        <table className="dp-table">
          <thead>
            <tr>
              <th style={{ width: 260 }}>Tool</th>
              <th>silex-research/dontpanic</th>
              <th>silex/api-gateway</th>
              <th>silex/web-dashboard</th>
              <th>silex/billing-svc</th>
              <th>silex/internal-tools</th>
              <th>silex/marketing-site</th>
            </tr>
          </thead>
          <tbody>
            {[
              { tool: 'Anthropic', sub: 'sonnet-4.5 · code reviewer', cells: ['healthy', 'action', 'healthy', 'healthy', 'pending', 'na'] },
              { tool: 'OpenAI', sub: 'gpt-5 · verifier', cells: ['action', 'healthy', 'healthy', 'action', 'pending', 'na'] },
              { tool: 'Google Gemini', sub: 'devil\'s advocate', cells: ['healthy', 'healthy', 'healthy', 'na', 'pending', 'na'] },
              { tool: 'xAI Grok', sub: 'builder', cells: ['healthy', 'na', 'healthy', 'na', 'na', 'na'] },
              { tool: 'GitHub', sub: 'PR · ready-to-deploy', cells: ['action', 'healthy', 'healthy', 'healthy', 'pending', 'healthy'] },
              { tool: 'OpenClaw/Hermes', sub: 'cross-model audit', cells: ['blocked', 'pending', 'na', 'na', 'na', 'na'] },
              { tool: 'MCP — Filesystem', sub: 'connected tool', cells: ['healthy', 'healthy', 'healthy', 'healthy', 'healthy', 'healthy'] },
              { tool: 'MCP — Linear', sub: 'connected tool', cells: ['pending', 'na', 'pending', 'na', 'na', 'na'] },
              { tool: 'Local Ollama', sub: 'fallback verifier', cells: ['healthy', 'na', 'na', 'na', 'healthy', 'na'] },
            ].map((row, i) => (
              <tr key={i}>
                <td>
                  <div style={{ fontWeight: 600 }}>{row.tool}</div>
                  <div style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>{row.sub}</div>
                </td>
                {row.cells.map((c, j) => (
                  <td key={j} style={{ textAlign: 'center' }}>
                    {c === 'na'
                      ? <span style={{ color: 'var(--dp-text-dim)', fontSize: 11 }}>—</span>
                      : <Pip band={c} />
                    }
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 18, padding: 14, background: 'var(--dp-bg-panel)', border: '1px solid var(--dp-border-subtle)', borderRadius: 5, display: 'grid', gridTemplateColumns: 'repeat(5, auto) 1fr', gap: 16, alignItems: 'center' }}>
        <span className="dp-kicker">LEGEND</span>
        <span className="dp-row-flex" style={{ gap: 6, fontSize: 12 }}><Pip band="healthy" /> Ready</span>
        <span className="dp-row-flex" style={{ gap: 6, fontSize: 12 }}><Pip band="action" /> Needs action</span>
        <span className="dp-row-flex" style={{ gap: 6, fontSize: 12 }}><Pip band="blocked" /> Blocked</span>
        <span className="dp-row-flex" style={{ gap: 6, fontSize: 12 }}><Pip band="pending" /> Not checked</span>
        <span style={{ fontSize: 12, color: 'var(--dp-text-muted)', textAlign: 'right' }}><span className="dp-mono" style={{ marginRight: 4 }}>—</span>Not required by this project</span>
      </div>
    </div>
    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="per-project capabilities/*.yaml + global tool install" updated="6m ago" scope="6 projects · 9 tools" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only · click a cell for that project's tool detail</span>
    </footer>
  </Shell>
);

Object.assign(window, { PageHomeFleet, PageWorkFleet, PageCapsFleet });
