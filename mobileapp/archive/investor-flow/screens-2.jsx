// Steps 3-4 (timeline + plan, grouped) and Step 5 (advanced).

// ─────────────────────────────────────────────────────────────
// STEP 3+4 — Timeline + Plan grouped
// Variant A: Stacked (slider on top, money below)
// ─────────────────────────────────────────────────────────────
function Step34A({ plan, set, onNext, onBack }) {
  const { proj } = { proj: computeProjection(plan) };
  return (
    <Phone>
      <StatusBar />
      <AppBar title="Timeline & plan" step={3} totalSteps={6} onBack={onBack} />
      <StepStrip current={3} />
      <div className="body">
        <div className="label" style={{ marginTop: 12 }}>Steps 3 & 4 of 6</div>
        <div className="h1" style={{ marginTop: 6 }}>Your timeline & numbers</div>

        {/* Timeline */}
        <div className="sketch" style={{ marginTop: 18, padding: 14 }}>
          <div className="label">When do you need it?</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 4 }}>
            <span className="big-number" style={{ fontSize: 38 }}>{plan.horizon}</span>
            <span className="unit" style={{ fontSize: 16, color: 'var(--ink-3)' }}>years</span>
          </div>
          <input type="range" min="1" max="40" value={plan.horizon}
            onChange={(e) => set('horizon', +e.target.value)} className="slider" />
          <div className="slider-ticks">
            <span>1</span><span>10</span><span>20</span><span>30</span><span>40</span>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <span className={'badge ' + (plan.horizon < 5 ? 'bad' : plan.horizon < 15 ? 'warn' : 'good')}>
              {plan.horizon < 5 ? 'Aggressive' : plan.horizon < 15 ? 'Balanced' : 'Growth + compound'}
            </span>
            <span className="tiny" style={{ alignSelf: 'center' }}>
              · {plan.horizon < 5 ? 'Low risk' : plan.horizon < 15 ? 'Medium' : 'Higher tolerance'}
            </span>
          </div>
        </div>

        {/* Money */}
        <div className="sketch" style={{ marginTop: 14, padding: 14 }}>
          <div className="label">Monthly investment</div>
          <div className="input-row" style={{ marginTop: 4 }}>
            <span className="currency">€</span>
            <input type="number" value={plan.monthly}
              onChange={(e) => set('monthly', Math.max(0, +e.target.value || 0))} />
            <span className="tiny">/mo</span>
          </div>

          <div className="label" style={{ marginTop: 16 }}>Target goal</div>
          <div className="input-row" style={{ marginTop: 4 }}>
            <span className="currency">€</span>
            <input type="number" value={plan.target}
              onChange={(e) => set('target', Math.max(0, +e.target.value || 0))} />
          </div>
        </div>

        <div className="hint" style={{ marginTop: 14 }}>
          <div className="hint-icon">∑</div>
          <div>
            Over {plan.horizon}y you'll contribute <b>{fmtEur(proj.totalContrib)}</b> · target {fmtEur(plan.target)}
          </div>
        </div>
      </div>
      <BottomNav onBack={onBack} onNext={onNext} />
    </Phone>
  );
}

// Variant B: Toggle "what to solve for" + dial-style timeline
function Step34B({ plan, set, onNext, onBack }) {
  const [mode, setMode] = useState('amount'); // 'amount' | 'reach'
  return (
    <Phone>
      <StatusBar />
      <AppBar title="Plan" step={3} totalSteps={6} onBack={onBack} />
      <StepStrip current={3} />
      <div className="body">
        <div className="label" style={{ marginTop: 12 }}>Tell us your numbers</div>
        <div className="h1" style={{ marginTop: 6 }}>Two numbers, that's it.</div>

        {/* Solve-for toggle */}
        <div className="tabs" style={{ marginTop: 18 }}>
          <button className={'tab' + (mode === 'amount' ? ' active' : '')} onClick={() => setMode('amount')}>I'll invest €X</button>
          <button className={'tab' + (mode === 'reach' ? ' active' : '')} onClick={() => setMode('reach')}>Reach this goal</button>
        </div>

        {/* Horizon as chip row */}
        <div className="sketch fill" style={{ marginTop: 16, padding: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="label">Time horizon</span>
            <span className="hand" style={{ fontSize: 14 }}>{plan.horizon} years</span>
          </div>
          <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
            {[1, 3, 5, 10, 15, 20, 30].map((y) => (
              <button key={y}
                onClick={() => set('horizon', y)}
                style={{
                  padding: '6px 12px',
                  border: '1.5px solid var(--ink)',
                  borderRadius: 999,
                  background: plan.horizon === y ? 'var(--ink)' : '#fff',
                  color: plan.horizon === y ? 'var(--paper)' : 'var(--ink)',
                  fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
                }}>{y}y</button>
            ))}
          </div>
          <input type="range" min="1" max="40" value={plan.horizon}
            onChange={(e) => set('horizon', +e.target.value)} className="slider" style={{ marginTop: 12 }} />
        </div>

        {/* Amount(s) */}
        <div className="sketch" style={{ marginTop: 14, padding: 14 }}>
          {mode === 'amount' ? (
            <>
              <div className="label">Monthly amount</div>
              <div className="input-row"><span className="currency">€</span>
                <input type="number" value={plan.monthly}
                  onChange={(e) => set('monthly', Math.max(0, +e.target.value || 0))} />
                <span className="tiny">/mo</span>
              </div>
              <div className="hand" style={{ fontSize: 13, marginTop: 10, color: 'var(--accent)' }}>
                ↓ we'll show what this grows into
              </div>
            </>
          ) : (
            <>
              <div className="label">Goal amount</div>
              <div className="input-row"><span className="currency">€</span>
                <input type="number" value={plan.target}
                  onChange={(e) => set('target', Math.max(0, +e.target.value || 0))} />
              </div>
              <div className="hand" style={{ fontSize: 13, marginTop: 10, color: 'var(--accent)' }}>
                ↓ we'll calculate monthly needed
              </div>
            </>
          )}
        </div>
      </div>
      <BottomNav onBack={onBack} onNext={onNext} />
    </Phone>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP 5 — Advanced settings (collapsed by default)
// ─────────────────────────────────────────────────────────────
function Step5({ plan, set, onNext, onBack }) {
  const [open, setOpen] = useState(true);
  const Stepper = ({ value, on, step = 0.1, suffix = '%' }) => (
    <div className="stepper">
      <button onClick={() => on(Math.max(0, +(value - step).toFixed(1)))}>−</button>
      <div className="num">{value.toFixed(1)}{suffix}</div>
      <button onClick={() => on(+(value + step).toFixed(1))}>+</button>
    </div>
  );
  return (
    <Phone>
      <StatusBar />
      <AppBar title="Plan" step={5} totalSteps={6} onBack={onBack} />
      <StepStrip current={5} />
      <div className="body">
        <div className="label" style={{ marginTop: 12 }}>Step 5 of 6 — optional</div>
        <div className="h1" style={{ marginTop: 6 }}>Fine-tune assumptions</div>
        <div className="body-text" style={{ marginTop: 8 }}>
          We pre-filled sensible defaults. Adjust if you have specific numbers.
        </div>

        <div className={'accordion-head' + (open ? ' open' : '')} onClick={() => setOpen((o) => !o)} style={{ marginTop: 22 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="h3">Reality factors</span>
            <span className="badge good" style={{ padding: '2px 8px', fontSize: 10 }}>3 set</span>
          </div>
          <span className="chev">{Ico.chev}</span>
        </div>

        {open && (
          <div style={{ padding: '4px 2px' }}>
            <div className="row-input">
              <div>
                <div className="row-label">Inflation rate</div>
                <div className="tiny">EU avg ≈ 2–3%</div>
              </div>
              <Stepper value={plan.inflation} on={(v) => set('inflation', v)} />
            </div>
            <div className="row-input">
              <div>
                <div className="row-label">Tax on gains</div>
                <div className="tiny">NL box-3 ≈ 25–36%</div>
              </div>
              <Stepper value={plan.tax} on={(v) => set('tax', v)} step={1} />
            </div>
            <div className="row-input">
              <div>
                <div className="row-label">Investment costs</div>
                <div className="tiny">ETF: 0.2–1.5% TER</div>
              </div>
              <Stepper value={plan.costs} on={(v) => set('costs', v)} />
            </div>
            <div className="row-input">
              <div>
                <div className="row-label">Expected gross return</div>
                <div className="tiny">Stocks long-run ≈ 7–9%</div>
              </div>
              <Stepper value={plan.grossReturn} on={(v) => set('grossReturn', v)} step={0.5} />
            </div>
          </div>
        )}

        <div className="hint" style={{ marginTop: 18 }}>
          <div className="hint-icon">!</div>
          <div>Costs &amp; tax compound the wrong way. A 1% fee can eat 20%+ of your final pot over 30 years.</div>
        </div>
      </div>
      <BottomNav onBack={onBack} onNext={onNext} nextLabel="See results" />
    </Phone>
  );
}

Object.assign(window, { Step34A, Step34B, Step5 });
