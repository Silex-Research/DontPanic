// ── DontPanic — Health Page Module ──
// Honesty surface for install/setup/build health. Per copy-map.md §2.5
// every card must have a credible data source or a named missing-data
// state; never render an empty card as "OK".
//
// V0 (F002) ships a minimal missing-data scaffold so the nav contract
// (Home/Needs Attention, Work, Tools & Setup, Health, Preferences)
// is honored at the shell level. F003 will compose this surface from
// the existing readiness/security/build-warning substrate.

(() => {
  let _el = null;

  function buildHTML() {
    return `
      <div class="hlth-layout">
        <section class="panel hlth-empty-state">
          <h2>Health</h2>
          <p class="hlth-empty-body">
            No health snapshot yet. Health composes install reconcile, build
            warnings, security findings, and budget guardrails into one
            honest readout. Run the local CLI to produce the source data,
            then reload this page.
          </p>
          <pre class="hlth-empty-cmd">dontpanic dashboard build</pre>
          <div class="hlth-empty-hint">
            Sources: <code>dashboard/state/capabilities-status.json</code>,
            <code>dashboard/state/what-now.json</code>,
            <code>dashboard/state/quota_state.json</code>.
            Composition lands with plan 2026-05-24-001 F003.
          </div>
        </section>
      </div>
    `;
  }

  function render() {
    if (!_el) return;
    _el.innerHTML = buildHTML();
  }

  Jarvis.registerPage({
    id: 'health',
    label: 'Health',

    init() {
      _el = Jarvis.getPageEl('health');
      render();
    },

    onActivate() {
      render();
    },
  });
})();
