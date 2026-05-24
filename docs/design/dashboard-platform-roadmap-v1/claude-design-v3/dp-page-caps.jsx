/* Capabilities — external readiness, setup requirements, owner boundary */

const CapRow = ({ band, name, provides, vendor, owner, probe, expanded, steps, command }) => (
  <div style={{ borderTop: '1px solid var(--dp-border-subtle)' }}>
    <div className="dp-row" style={{ gridTemplateColumns: '8px minmax(0,1.4fr) minmax(0,1.4fr) 110px 130px 130px', padding: '12px 16px' }}>
      <Pip band={band} />
      <div className="dp-stack-sm" style={{ minWidth: 0 }}>
        <div className="dp-row-flex" style={{ gap: 8 }}>
          <span style={{ fontWeight: 600 }}>{name}</span>
          <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>{vendor}</span>
        </div>
        <div className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-muted)' }}>capabilities/{name.toLowerCase().replace(/[^a-z0-9]/g, '-')}.yaml</div>
      </div>
      <div className="dp-stack-sm">
        <span className="dp-row__meta" style={{ color: 'var(--dp-text-soft)' }}>{provides}</span>
      </div>
      <div>
        <Chip variant={owner === 'You' ? 'required' : 'optional'}>{owner}</Chip>
      </div>
      <div>
        <span style={{ fontSize: 12, color: probe.color || 'var(--dp-text-muted)', fontFamily: 'var(--dp-font-mono)' }}>{probe.label}</span>
      </div>
      <div>
        {band === 'healthy' && <Badge band="healthy">Ready</Badge>}
        {band === 'action' && <Badge band="action">Needs action</Badge>}
        {band === 'blocked' && <Badge band="blocked">Blocked</Badge>}
        {band === 'pending' && <Badge band="pending">Pending</Badge>}
      </div>
    </div>
    {expanded && (
      <div style={{ padding: '0 16px 14px 36px', background: 'var(--dp-bg-row)', borderTop: '1px solid var(--dp-border-subtle)' }}>
        <div style={{ paddingTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
          <div>
            <div className="dp-kicker" style={{ marginBottom: 8 }}>SETUP STEPS</div>
            <div className="dp-stack-sm">
              {steps.map((s, i) => (
                <div key={i} className="dp-row-flex" style={{ gap: 8, alignItems: 'flex-start' }}>
                  <span style={{ width: 18, height: 18, borderRadius: 4, background: s.kind === 'human' ? 'var(--dp-action-soft)' : 'var(--dp-brand-soft)', color: s.kind === 'human' ? 'var(--dp-action)' : 'var(--dp-brand)', fontFamily: 'var(--dp-font-mono)', fontSize: 10, fontWeight: 700, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginTop: 1 }}>{i + 1}</span>
                  <div style={{ flex: 1 }}>
                    <div className="dp-row-flex" style={{ gap: 6 }}>
                      <span style={{ fontSize: 12 }}>{s.text}</span>
                      <Chip variant={s.kind === 'human' ? 'required' : 'recommended'}>
                        {s.kind === 'human' ? <><IconUser size={9} sw={2} /> human</> : <><IconRobot size={9} sw={2} /> automatable</>}
                      </Chip>
                    </div>
                    {s.detail && <div style={{ fontSize: 11, color: 'var(--dp-text-muted)', marginTop: 2 }}>{s.detail}</div>}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="dp-kicker" style={{ marginBottom: 8 }}>RUN THIS</div>
            <Cmd block>{command}</Cmd>
            <div style={{ fontSize: 11, color: 'var(--dp-text-dim)', marginTop: 6, fontFamily: 'var(--dp-font-mono)' }}>
              // interactive — will prompt for secrets and never echo them
            </div>
            <div style={{ marginTop: 14 }}>
              <div className="dp-kicker" style={{ marginBottom: 6 }}>OWNER BOUNDARY</div>
              <div style={{ fontSize: 12, color: 'var(--dp-text-muted)', lineHeight: 1.5 }}>
                Vendor accounts and billing live with you. DontPanic only reads probe results — it never creates accounts, mints keys, or changes plan tiers.
              </div>
            </div>
          </div>
        </div>
      </div>
    )}
  </div>
);

const PageCaps = () => (
  <Shell active="caps" topStripProps={{ project: 'silex-research/dontpanic', updated: '14s ago', warnings: 3, reviews: 2, health: 'action' }}>
    <PageHead
      kicker="TOOLS & SETUP"
      title="Connections & setup"
      sub="9 connections · 6 ready · 2 need setup · 1 hasn't been checked yet"
      actions={
        <>
          <button className="dp-cmd dp-cmd--inline" style={{ background: 'var(--dp-bg-panel)' }}>
            <IconRefresh size={12} />
            <span style={{ fontFamily: 'var(--dp-font-sans)' }}>Re-probe all</span>
          </button>
          <Provenance source="capabilities/*.yaml" updated="6m ago" />
        </>
      }
    />

    <div className="dp-page__body" style={{ padding: '14px 24px' }}>
      <Panel>
        <div className="dp-row" style={{ gridTemplateColumns: '8px minmax(0,1.4fr) minmax(0,1.4fr) 110px 130px 130px', padding: '8px 16px', background: 'var(--dp-bg-row)', borderTop: 'none' }}>
          <span />
          <span className="dp-kicker">Capability</span>
          <span className="dp-kicker">Provides</span>
          <span className="dp-kicker">Owner</span>
          <span className="dp-kicker">Probe</span>
          <span className="dp-kicker">State</span>
        </div>

        <CapRow
          band="action"
          name="OpenAI"
          vendor="api.openai.com"
          provides="Verifier agent · gpt-5-codex, o4-mini"
          owner="You"
          probe={{ label: 'last 6m · 401', color: 'var(--dp-action)' }}
          expanded
          steps={[
            { kind: 'human', text: 'Create API key at platform.openai.com', detail: 'You must own the OpenAI account; DontPanic cannot create vendor accounts.' },
            { kind: 'human', text: 'Confirm spend cap is set on the project', detail: 'Recommended: $200/mo soft, $400/mo hard.' },
            { kind: 'auto',  text: 'Store key in OS keychain (dontpanic caps setup)', detail: 'Written via the host OS secret store — never plaintext on disk.' },
            { kind: 'auto',  text: 'Re-probe to confirm capability', detail: 'Runs a 1-token test call; no logs persisted.' },
          ]}
          command="dontpanic caps setup openai --interactive"
        />

        <CapRow
          band="action"
          name="GitHub"
          vendor="api.github.com"
          provides="Plan lock · safe-to-ship gate · PR evidence"
          owner="You"
          probe={{ label: 'last 12m · 200', color: 'var(--dp-healthy)' }}
          expanded
          steps={[
            { kind: 'human', text: 'Grant repo:status scope on PAT', detail: 'Current token has repo but missing repo:status — safe-to-ship gate is degraded.' },
            { kind: 'auto',  text: 'Verify scope expansion via re-probe', detail: 'No mutation; calls /user once.' },
          ]}
          command="dontpanic caps probe github --verbose"
        />

        <CapRow
          band="healthy"
          name="Anthropic"
          vendor="api.anthropic.com"
          provides="Reviewer agent · sonnet-4.5, opus-4"
          owner="You"
          probe={{ label: 'last 2m · 200', color: 'var(--dp-healthy)' }}
        />
        <CapRow
          band="healthy"
          name="Google Gemini"
          vendor="generativelanguage.googleapis.com"
          provides="Challenger agent · gemini-2.5-pro"
          owner="You"
          probe={{ label: 'last 4m · 200', color: 'var(--dp-healthy)' }}
        />
        <CapRow
          band="healthy"
          name="xAI Grok"
          vendor="api.x.ai"
          provides="Challenger agent · grok-4"
          owner="You"
          probe={{ label: 'last 4m · 200', color: 'var(--dp-healthy)' }}
        />
        <CapRow
          band="healthy"
          name="Local Ollama"
          vendor="localhost:11434"
          provides="Local Verifier · llama-3.3-70b"
          owner="You"
          probe={{ label: 'last 1m · 200', color: 'var(--dp-healthy)' }}
        />
        <CapRow
          band="healthy"
          name="MCP — Filesystem"
          vendor="local"
          provides="Read access to plan/evidence paths"
          owner="DontPanic"
          probe={{ label: 'last 14s · 200', color: 'var(--dp-healthy)' }}
        />
        <CapRow
          band="pending"
          name="MCP — Linear"
          vendor="api.linear.app"
          provides="Optional · plan ↔ ticket links"
          owner="You"
          probe={{ label: 'never probed', color: 'var(--dp-text-muted)' }}
        />
        <CapRow
          band="blocked"
          name="OpenClaw / Hermes"
          vendor="hermes.openclaw.dev"
          provides="Cross-model audit · verifier ensemble"
          owner="You"
          probe={{ label: 'last 23m · 503', color: 'var(--dp-blocked)' }}
        />
      </Panel>
    </div>

    <footer style={{ padding: '10px 24px', borderTop: '1px solid var(--dp-border-subtle)', background: 'var(--dp-bg-sunken)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Provenance source="capabilities/*.yaml" updated="6m ago" scope="silex-research/dontpanic@main" />
      <span className="dp-mono" style={{ fontSize: 11, color: 'var(--dp-text-dim)' }}>read-only · setup commands are copy-only · no auto-execute</span>
    </footer>
  </Shell>
);

window.PageCaps = PageCaps;
