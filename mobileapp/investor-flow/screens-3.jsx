// Step 6 (Results — 2 variations) and Step 7 (Actions / Rita handoff).

// Tiny growth-curve SVG (compound)
function GrowthCurve({ months, r, color, dashed, monthly }) {
  const N = 40;
  const pts = [];
  for (let i = 0; i <= N; i++) {
    const m = (months * i) / N;
    const rm = Math.pow(1 + r, 1/12) - 1;
    const fv = Math.abs(rm) < 1e-9 ? monthly * m : monthly * ((Math.pow(1 + rm, m) - 1) / rm);
    pts.push([i / N, fv]);
  }
  const max = pts[N][1] || 1;
  const path = pts.map(([x, y], i) => {
    const px = x * 280;
    const py = 130 - (y / max) * 125;
    return (i === 0 ? 'M' : 'L') + px.toFixed(1) + ',' + py.toFixed(1);
  }).join(' ');
  return <path d={path} fill="none" stroke={color} strokeWidth="2" strokeDasharray={dashed ? '4 3' : 'none'} strokeLinecap="round" strokeLinejoin="round" />;
}

// ─────────────────────────────────────────────────────────────
// STEP 6 — RESULTS — Variant A: Side-by-side big-numbers (gross vs net)
// ─────────────────────────────────────────────────────────────
function Step6A({ plan, onNext, onBack }) {
  const proj = computeProjection(plan);
  const reqStatus = proj.status;
  const [scenario, setScenario] = useState('avg');
  const rByScenario = { best: proj.r_real + 0.025, avg: proj.r_real, worst: Math.max(0, proj.r_real - 0.03) };
  const fvScenario = (() => {
    const rm = Math.pow(1 + rByScenario[scenario], 1/12) - 1;
    return Math.abs(rm) < 1e-9 ? plan.monthly * proj.months : plan.monthly * ((Math.pow(1 + rm, proj.months) - 1) / rm);
  })();

  return (
    <Phone>
      <StatusBar />
      <AppBar title="Reality check" step={6} totalSteps={6} onBack={onBack} />
      <StepStrip current={6} />
      <div className="body" style={{ paddingBottom: 100 }}>
        {/* Required return */}
        <div style={{ marginTop: 12 }}>
          <div className="label">You need to earn</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
            <span className="big-number">{fmtPct(proj.requiredReal)}</span>
            <span className="unit">/yr real</span>
          </div>
          <div style={{ marginTop: 8 }}>
            <span className={'badge ' + reqStatus}>
              {reqStatus === 'good' && <>{Ico.good} Likely achievable</>}
              {reqStatus === 'warn' && <>{Ico.warn} Moderate risk</>}
              {reqStatus === 'bad'  && <>{Ico.bad} Unlikely</>}
            </span>
          </div>
        </div>

        {/* SIDE-BY-SIDE — the hero */}
        <div className="compare" style={{ marginTop: 22 }}>
          <div>
            <div className="compare-label">Gross return</div>
            <div className="compare-num">{fmtEur(proj.fv_gross)}</div>
            <div className="compare-foot">at {fmtPct(proj.r_gross)} /yr</div>
          </div>
          <div className="net">
            <div className="compare-label">What you keep</div>
            <div className="compare-num">{fmtEur(proj.fv_real)}</div>
            <div className="compare-foot">at {fmtPct(proj.r_real)} real</div>
          </div>
        </div>
        <div className="hand" style={{ fontSize: 13, color: 'var(--ink-2)', textAlign: 'center', marginTop: 6 }}>
          ↑ this is the gap most investors miss
        </div>

        {/* Waterfall */}
        <div className="sketch" style={{ marginTop: 22, padding: 14 }}>
          <div className="label">Where it goes</div>
          <div style={{ marginTop: 12 }}>
            <div className="bar-row">
              <span className="bar-label">Market</span>
              <div className="bar-track"><div className="bar-fill" style={{ width: '100%' }} /></div>
              <span className="bar-val">{fmtPct(proj.r_gross)}</span>
            </div>
            <div className="bar-row">
              <span className="bar-label">− Costs</span>
              <div className="bar-track"><div className="bar-fill bad" style={{ width: (plan.costs/plan.grossReturn*100).toFixed(0) + '%' }} /></div>
              <span className="bar-val">−{plan.costs.toFixed(1)}%</span>
            </div>
            <div className="bar-row">
              <span className="bar-label">− Tax</span>
              <div className="bar-track"><div className="bar-fill warn" style={{ width: (plan.tax * (proj.r_gross - plan.costs/100) / proj.r_gross * 60).toFixed(0) + '%' }} /></div>
              <span className="bar-val">−{(plan.tax * (proj.r_gross - plan.costs/100)).toFixed(1)}%</span>
            </div>
            <div className="bar-row">
              <span className="bar-label">− Inflation</span>
              <div className="bar-track"><div className="bar-fill warn" style={{ width: (plan.inflation/plan.grossReturn*100).toFixed(0) + '%' }} /></div>
              <span className="bar-val">−{plan.inflation.toFixed(1)}%</span>
            </div>
            <div className="bar-row" style={{ marginTop: 8, paddingTop: 8, borderTop: '1.5px solid var(--ink)' }}>
              <span className="bar-label" style={{ fontWeight: 700 }}>= You keep</span>
              <div className="bar-track"><div className="bar-fill good" style={{ width: Math.max(0, proj.r_real/proj.r_gross*100).toFixed(0) + '%' }} /></div>
              <span className="bar-val" style={{ color: 'var(--accent)' }}>{fmtPct(proj.r_real)}</span>
            </div>
          </div>
        </div>

        {/* Growth chart */}
        <div className="sketch" style={{ marginTop: 14, padding: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div className="label">Projection</div>
            <div className="tabs" style={{ width: 180 }}>
              {[['worst','Worst'],['avg','Avg'],['best','Best']].map(([id, t]) => (
                <button key={id} className={'tab' + (scenario === id ? ' active' : '')} onClick={() => setScenario(id)}>{t}</button>
              ))}
            </div>
          </div>
          <div className="chart">
            <div className="axis-y"><span>{fmtEur(plan.target * 1.2)}</span><span>0</span></div>
            <div className="axis-x"><span>0y</span><span>{plan.horizon}y</span></div>
            <svg viewBox="0 0 280 130" preserveAspectRatio="none" style={{ width: '100%', height: '100%', overflow: 'visible' }}>
              {/* target line */}
              <line x1="0" x2="280" y1={130 - (plan.target / (plan.target * 1.2)) * 125} y2={130 - (plan.target / (plan.target * 1.2)) * 125} stroke="var(--ink-3)" strokeWidth="1" strokeDasharray="3 3" />
              <text x="276" y={125 - (plan.target / (plan.target * 1.2)) * 125} fontSize="9" textAnchor="end" fill="var(--ink-3)" fontFamily="monospace">target</text>
              <GrowthCurve months={proj.months} r={proj.r_gross} color="var(--ink-3)" dashed monthly={plan.monthly} />
              <GrowthCurve months={proj.months} r={rByScenario[scenario]} color="var(--accent)" monthly={plan.monthly} />
            </svg>
          </div>
          <div style={{ display: 'flex', gap: 14, marginTop: 22, fontSize: 11 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span style={{ width: 14, height: 2, background: 'var(--ink-3)', borderTop: '2px dashed var(--ink-3)' }}/>Gross</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span style={{ width: 14, height: 2, background: 'var(--accent)' }}/>Real ({fmtEur(fvScenario)})</div>
          </div>
        </div>

        {/* Gap insight */}
        {proj.shortfall > 0 && (
          <div className="sketch" style={{ marginTop: 14, padding: 14, background: 'var(--bad-soft)', borderColor: 'var(--bad)' }}>
            <div className="label" style={{ color: 'var(--bad)' }}>Gap insight</div>
            <div className="h2" style={{ marginTop: 4 }}>
              You'll fall short by <span style={{ color: 'var(--bad)' }}>{fmtEur(proj.shortfall)}</span>
            </div>
            <div className="body-text" style={{ marginTop: 4 }}>
              At gross {fmtPct(proj.r_gross)} you'd hit {fmtEur(proj.fv_gross)}. After costs, tax & inflation: {fmtEur(proj.fv_real)}.
            </div>
          </div>
        )}

        {/* Key insight */}
        <div className="sketch fill" style={{ marginTop: 14, padding: 14, borderStyle: 'dashed' }}>
          <div className="label">Insight</div>
          <div className="hand" style={{ fontSize: 16, marginTop: 4, lineHeight: 1.3 }}>
            {plan.horizon >= 20
              ? '"Time reduces risk more than strategy."'
              : plan.costs >= 1
              ? '"Costs matter more than most investors expect."'
              : '"Your plan is achievable — but requires consistency."'}
          </div>
        </div>
      </div>
      <BottomNav onBack={onBack} onNext={onNext} nextLabel="Next steps" />
    </Phone>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP 6 — RESULTS — Variant B: Stacked storytelling (one section at a time)
// ─────────────────────────────────────────────────────────────
function Step6B({ plan, onNext, onBack }) {
  const proj = computeProjection(plan);
  return (
    <Phone>
      <StatusBar />
      <AppBar title="Your reality" step={6} totalSteps={6} onBack={onBack} />
      <StepStrip current={6} />
      <div className="body" style={{ paddingBottom: 100 }}>
        {/* Hero card — gross vs net BIG */}
        <div className="sketch" style={{ marginTop: 14, padding: 18, background: '#fff' }}>
          <div className="label">If you invest €{plan.monthly}/mo for {plan.horizon}y…</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginTop: 14, gap: 8 }}>
            <div style={{ flex: 1 }}>
              <div className="tiny" style={{ textTransform: 'uppercase', letterSpacing: '0.08em' }}>On paper</div>
              <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--ink-3)', lineHeight: 1, marginTop: 4 }}>
                {fmtEur(proj.fv_gross)}
              </div>
              <div className="tiny" style={{ marginTop: 2 }}>{fmtPct(proj.r_gross)} gross</div>
            </div>
            <div style={{ fontSize: 22, color: 'var(--ink-3)' }}>→</div>
            <div style={{ flex: 1, textAlign: 'right' }}>
              <div className="tiny" style={{ textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--accent)', fontWeight: 700 }}>Actually</div>
              <div style={{ fontSize: 32, fontWeight: 800, color: 'var(--accent)', lineHeight: 1, marginTop: 4 }}>
                {fmtEur(proj.fv_real)}
              </div>
              <div className="tiny" style={{ marginTop: 2 }}>{fmtPct(proj.r_real)} real</div>
            </div>
          </div>
          <div style={{ height: 10, marginTop: 14, borderRadius: 5, background: 'var(--ink-4)', position: 'relative', overflow: 'hidden' }}>
            <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: ((proj.fv_real / proj.fv_gross) * 100).toFixed(0) + '%', background: 'var(--accent)' }} />
          </div>
          <div className="tiny" style={{ marginTop: 6, textAlign: 'center' }}>
            You keep <b>{((proj.fv_real / proj.fv_gross) * 100).toFixed(0)}%</b> of the headline number
          </div>
        </div>

        {/* Required return banner */}
        <div className="sketch fill" style={{ marginTop: 12, padding: 14, display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div className="label">Required real return</div>
            <div className="h1" style={{ marginTop: 2 }}>{fmtPct(proj.requiredReal)}/yr</div>
          </div>
          <span className={'badge ' + proj.status}>
            {proj.status === 'good' ? 'Achievable' : proj.status === 'warn' ? 'Tight' : 'Stretch'}
          </span>
        </div>

        {/* Reality check breakdown */}
        <div className="sketch" style={{ marginTop: 12, padding: 14 }}>
          <div className="label">Reality check</div>
          <div style={{ marginTop: 10 }}>
            {[
              ['Market return', `+${plan.grossReturn}%`, 'good'],
              ['Inflation',     `−${plan.inflation}%`, 'warn'],
              ['Tax on gains',  `−${(plan.tax * (plan.grossReturn - plan.costs)/100).toFixed(1)}%`, 'warn'],
              ['Costs',         `−${plan.costs}%`, 'bad'],
            ].map(([k, v, c]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px dashed var(--ink-4)' }}>
                <span style={{ fontSize: 13 }}>{k}</span>
                <span className="mono" style={{ fontSize: 13, fontWeight: 600, color: c === 'good' ? 'var(--accent)' : c === 'warn' ? 'var(--warn)' : 'var(--bad)' }}>{v}</span>
              </div>
            ))}
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '12px 0 4px' }}>
              <span style={{ fontSize: 14, fontWeight: 700 }}>= You keep</span>
              <span className="mono" style={{ fontSize: 16, fontWeight: 800, color: 'var(--accent)' }}>{fmtPct(proj.r_real)}</span>
            </div>
          </div>
        </div>

        {/* Key insight */}
        <div className="sketch" style={{ marginTop: 12, padding: 14, borderStyle: 'dashed' }}>
          <div className="hand" style={{ fontSize: 16, lineHeight: 1.35 }}>
            "{plan.horizon >= 20 ? 'Time reduces risk more than strategy.' : 'Costs matter more than most investors expect.'}"
          </div>
        </div>
      </div>
      <BottomNav onBack={onBack} onNext={onNext} nextLabel="Next steps" />
    </Phone>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP 7 — Actions — handoff to Rita app
// ─────────────────────────────────────────────────────────────
function Step7({ plan, onBack, onAdjust, onRecalc, onStart }) {
  const proj = computeProjection(plan);
  return (
    <Phone>
      <StatusBar />
      <AppBar title="Your plan is ready" onBack={onBack} />
      <div className="body">
        <div className="hand" style={{ fontSize: 14, marginTop: 8 }}>nice work ✓</div>
        <div className="h1" style={{ marginTop: 4 }}>What now?</div>

        {/* Plan summary */}
        <div className="sketch fill" style={{ marginTop: 16, padding: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <div>
              <div className="tiny">Plan</div>
              <div style={{ fontSize: 14, fontWeight: 600, marginTop: 2 }}>
                €{plan.monthly}/mo · {plan.horizon}y
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div className="tiny">You keep</div>
              <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--accent)' }}>{fmtEur(proj.fv_real)}</div>
            </div>
          </div>
        </div>

        {/* Action stack */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 18 }}>
          <button className="choice" onClick={onAdjust}>
            <div className="glyph">{Ico.edit}</div>
            <div style={{ flex: 1 }}>
              <div className="choice-title">Adjust plan</div>
              <div className="choice-meta">Change amount, timeline, or assumptions</div>
            </div>
            {Ico.arrow}
          </button>
          <button className="choice" onClick={onRecalc}>
            <div className="glyph">{Ico.spark}</div>
            <div style={{ flex: 1 }}>
              <div className="choice-title">Recalculate scenarios</div>
              <div className="choice-meta">Try best/worst-case projections</div>
            </div>
            {Ico.arrow}
          </button>
          <button className="choice selected" onClick={onStart} style={{ background: 'var(--accent)', borderColor: 'var(--accent)', color: '#fff' }}>
            <div className="glyph" style={{ borderColor: '#fff' }}>→</div>
            <div style={{ flex: 1 }}>
              <div className="choice-title">Start investing in Rita</div>
              <div style={{ fontSize: 11, opacity: 0.9, marginTop: 2 }}>Hand off to the existing Rita app</div>
            </div>
          </button>
        </div>

        <div className="hint" style={{ marginTop: 18 }}>
          <div className="hint-icon">↗</div>
          <div>Your plan settings carry over to Rita so the portfolio matches.</div>
        </div>
      </div>
      <div className="gesture-bar" />
    </Phone>
  );
}

// ─────────────────────────────────────────────────────────────
// "Rita" placeholder screen — the existing mobile app handoff
// ─────────────────────────────────────────────────────────────
function RitaPlaceholder({ onBack }) {
  return (
    <Phone>
      <StatusBar />
      <AppBar title="Rita · Invest" onBack={onBack} />
      <div className="rita-frame">
        <div className="rita-placeholder">
          <div>
            <div style={{ fontSize: 36, marginBottom: 8 }}>🪴</div>
            <div className="h2">Rita mobile app</div>
            <div className="body-text" style={{ marginTop: 6, maxWidth: 240 }}>
              This is where the existing Rita app continues — portfolio setup, KYC, fund selection, deposit.
            </div>
            <div className="hand" style={{ marginTop: 16, fontSize: 13, color: 'var(--ink-3)' }}>
              swap this with the real Rita HTML
            </div>
          </div>
        </div>
        <div style={{ padding: '0 16px 16px' }}>
          <div className="sketch fill" style={{ padding: 12, fontSize: 12, color: 'var(--ink-2)' }}>
            <b>Carried over:</b> €250/mo · 12y · balanced preset · 2.5% inflation, 25% tax, 1.2% costs
          </div>
        </div>
      </div>
      <div className="gesture-bar" />
    </Phone>
  );
}

Object.assign(window, { Step6A, Step6B, Step7, RitaPlaceholder });
