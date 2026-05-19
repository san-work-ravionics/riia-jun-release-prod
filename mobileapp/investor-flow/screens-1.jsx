// Onboarding + Step 1 (Investor type) + Step 2 (Goal) wireframes.
// Each screen is a self-contained component receiving { plan, set, onNext, onBack, onJump }.

// ─────────────────────────────────────────────────────────────
// Onboarding intro — the front door before Step 1
// ─────────────────────────────────────────────────────────────
function OnboardingA({ onNext }) {
  return (
    <Phone>
      <StatusBar />
      <div className="body" style={{ display: 'flex', flexDirection: 'column', gap: 22, paddingTop: 28 }}>
        <div className="hand" style={{ fontSize: 14, color: 'var(--ink-2)' }}>welcome to</div>
        <div>
          <div className="h1" style={{ fontSize: 32, lineHeight: 1.05 }}>
            Know what you<br />
            <span style={{ borderBottom: '3px solid var(--accent)' }}>actually keep.</span>
          </div>
          <div className="body-text" style={{ marginTop: 12 }}>
            Plan an investment in 4 quick steps. We'll show you the real return — after inflation, tax, and costs.
          </div>
        </div>
        <div className="scribble">
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', height: 110 }}>
            <div style={{ width: 18, height: 30, background: 'var(--ink-4)', borderRadius: 2 }} />
            <div style={{ width: 18, height: 50, background: 'var(--ink-4)', borderRadius: 2 }} />
            <div style={{ width: 18, height: 75, background: 'var(--ink-4)', borderRadius: 2 }} />
            <div style={{ width: 18, height: 95, background: 'var(--ink-3)', borderRadius: 2 }} />
            <div className="hand" style={{ fontSize: 11, marginLeft: 4, marginBottom: 2 }}>= gross</div>
          </div>
          <div className="hand" style={{ position: 'absolute', bottom: 12, right: 14, color: 'var(--accent)', fontSize: 13 }}>
            ↓ what you keep
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            ['1.', 'Tell us your goal'],
            ['2.', 'Tell us your timeline'],
            ['3.', 'Tell us your numbers'],
            ['4.', 'See reality'],
          ].map(([n, t]) => (
            <div key={n} style={{ display: 'flex', gap: 12, alignItems: 'baseline' }}>
              <span className="hand" style={{ fontSize: 18, color: 'var(--accent)', minWidth: 18 }}>{n}</span>
              <span style={{ fontSize: 14, fontWeight: 500 }}>{t}</span>
            </div>
          ))}
        </div>
      </div>
      <BottomNav onNext={onNext} nextLabel="Get started" />
    </Phone>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP 1 — Investor type
// Variant A: List with metadata (risk preset visible)
// ─────────────────────────────────────────────────────────────
function Step1A({ plan, set, onNext, onBack }) {
  const opts = [
    { id: 'short', t: 'Short-term', m: '≤ 1 year · low risk preset', glyph: '1y' },
    { id: 'goal',  t: 'Goal-based', m: '5–10 years · balanced preset', glyph: '5y' },
    { id: 'long',  t: 'Long-term',  m: '20+ years · growth preset', glyph: '20+' },
  ];
  return (
    <Phone>
      <StatusBar />
      <AppBar title="Set up your plan" step={1} onBack={onBack} />
      <StepStrip current={1} />
      <div className="body">
        <div className="label" style={{ marginTop: 14 }}>Step 1 of 6</div>
        <div className="h1" style={{ marginTop: 6 }}>What type of investor are you?</div>
        <div className="body-text" style={{ marginTop: 8 }}>This sets your default risk level. You can change it later.</div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 22 }}>
          {opts.map((o) => (
            <button key={o.id}
              className={'choice' + (plan.investorType === o.id ? ' selected' : '')}
              onClick={() => set('investorType', o.id)}>
              <div className="glyph">{o.glyph}</div>
              <div style={{ flex: 1 }}>
                <div className="choice-title">{o.t}</div>
                <div className="choice-meta">{o.m}</div>
              </div>
              {plan.investorType === o.id && Ico.check}
            </button>
          ))}
        </div>

        <div className="hint" style={{ marginTop: 22 }}>
          <div className="hint-icon">i</div>
          <div>Your timeline drives risk. Longer = more time to ride out dips.</div>
        </div>
      </div>
      <BottomNav onBack={onBack} onNext={onNext} nextDisabled={!plan.investorType} />
    </Phone>
  );
}

// Variant B: Visual horizon scale (timeline-as-spectrum)
function Step1B({ plan, set, onNext, onBack }) {
  const opts = [
    { id: 'short', t: 'Short', sub: '≤ 1y', risk: 'Low' },
    { id: 'goal',  t: 'Goal',  sub: '5–10y', risk: 'Med' },
    { id: 'long',  t: 'Long',  sub: '20y+', risk: 'High' },
  ];
  return (
    <Phone>
      <StatusBar />
      <AppBar title="Plan setup" step={1} onBack={onBack} />
      <StepStrip current={1} />
      <div className="body">
        <div className="label" style={{ marginTop: 14 }}>About you</div>
        <div className="h1" style={{ marginTop: 6 }}>How far out are you<br/>thinking?</div>

        {/* Horizon spectrum */}
        <div style={{ marginTop: 28, position: 'relative' }}>
          <div style={{ height: 2, background: 'var(--ink)', position: 'absolute', left: 28, right: 28, top: 28 }} />
          <div className="grid-3" style={{ gap: 0 }}>
            {opts.map((o) => (
              <button key={o.id}
                onClick={() => set('investorType', o.id)}
                style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
                  border: 'none', background: 'transparent', cursor: 'pointer', padding: '0 4px', fontFamily: 'inherit',
                }}>
                <div style={{
                  width: 56, height: 56,
                  borderRadius: '50%',
                  border: '2px solid var(--ink)',
                  background: plan.investorType === o.id ? 'var(--ink)' : '#fff',
                  color: plan.investorType === o.id ? 'var(--paper)' : 'var(--ink)',
                  display: 'grid', placeItems: 'center',
                  fontSize: 11, fontWeight: 700,
                  position: 'relative', zIndex: 1,
                }}>
                  {o.sub}
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, marginTop: 4 }}>{o.t}</div>
                <div className="tiny">{o.risk} risk</div>
              </button>
            ))}
          </div>
        </div>

        {plan.investorType && (
          <div className="sketch fill" style={{ marginTop: 28, padding: 14 }}>
            <div className="label">Preset locked in</div>
            <div className="h2" style={{ marginTop: 4 }}>
              {plan.investorType === 'short' && 'Stable instruments · Low volatility'}
              {plan.investorType === 'goal'  && 'Mixed portfolio · Moderate growth'}
              {plan.investorType === 'long'  && 'Equity-heavy · High growth + compounding'}
            </div>
            <div className="hand" style={{ fontSize: 13, color: 'var(--accent)', marginTop: 8 }}>
              ✓ we'll tune the calculator for this
            </div>
          </div>
        )}
      </div>
      <BottomNav onBack={onBack} onNext={onNext} nextDisabled={!plan.investorType} />
    </Phone>
  );
}

// ─────────────────────────────────────────────────────────────
// STEP 2 — Goal
// Variant A: List with dynamic hint per goal
// ─────────────────────────────────────────────────────────────
const GOALS = [
  { id: 'edu',    t: 'Education',     hint: 'Typically 5–15 years out · stable growth', icon: Ico.edu },
  { id: 'retire', t: 'Retirement',    hint: '20+ years · long compounding window',      icon: Ico.ret },
  { id: 'buy',    t: 'Major purchase',hint: '3–7 years · capital preservation matters', icon: Ico.buy },
  { id: 'travel', t: 'Travel',        hint: '1–3 years · short, low risk',              icon: Ico.travel },
  { id: 'wealth', t: 'Wealth creation',hint: 'Open-ended · growth + diversification',    icon: Ico.wealth },
];

function Step2A({ plan, set, onNext, onBack }) {
  const sel = GOALS.find((g) => g.id === plan.goal);
  return (
    <Phone>
      <StatusBar />
      <AppBar title="Plan setup" step={2} onBack={onBack} />
      <StepStrip current={2} />
      <div className="body">
        <div className="label" style={{ marginTop: 14 }}>Step 2 of 6</div>
        <div className="h1" style={{ marginTop: 6 }}>What are you investing for?</div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 20 }}>
          {GOALS.map((g) => (
            <button key={g.id}
              className={'choice' + (plan.goal === g.id ? ' selected' : '')}
              onClick={() => set('goal', g.id)}>
              <div className="glyph" style={{ border: 'none', background: 'transparent' }}>{g.icon}</div>
              <div style={{ flex: 1 }}>
                <div className="choice-title">{g.t}</div>
              </div>
              {plan.goal === g.id && Ico.check}
            </button>
          ))}
        </div>

        {sel && (
          <div className="hint" style={{ marginTop: 18, borderLeftColor: 'var(--accent)' }}>
            <div className="hint-icon" style={{ borderColor: 'var(--accent)', color: 'var(--accent)' }}>↗</div>
            <div><b>{sel.t}:</b> {sel.hint}</div>
          </div>
        )}
      </div>
      <BottomNav onBack={onBack} onNext={onNext} nextDisabled={!plan.goal} />
    </Phone>
  );
}

// Variant B: 2x3 tile grid
function Step2B({ plan, set, onNext, onBack }) {
  return (
    <Phone>
      <StatusBar />
      <AppBar title="Goal" step={2} onBack={onBack} />
      <StepStrip current={2} />
      <div className="body">
        <div className="label" style={{ marginTop: 14 }}>Pick one</div>
        <div className="h1" style={{ marginTop: 6 }}>What's the money for?</div>

        <div className="grid-2" style={{ marginTop: 20, gap: 12 }}>
          {GOALS.map((g) => (
            <button key={g.id}
              className={'tile' + (plan.goal === g.id ? ' selected' : '')}
              onClick={() => set('goal', g.id)}
              style={{ minHeight: 110 }}>
              <div className="tile-icon">{g.icon}</div>
              <div className="tile-label">{g.t}</div>
            </button>
          ))}
          <div className="tile dashed" style={{ background: 'transparent', borderStyle: 'dashed', cursor: 'default', minHeight: 110 }}>
            <div style={{ fontSize: 22, color: 'var(--ink-3)' }}>+</div>
            <div className="tile-label" style={{ color: 'var(--ink-3)' }}>Custom</div>
          </div>
        </div>

        {plan.goal && (
          <div className="sketch" style={{ marginTop: 18, padding: 12, display: 'flex', gap: 10, alignItems: 'center' }}>
            <div style={{ flex: 1 }}>
              <div className="label">Typical horizon</div>
              <div className="h2" style={{ marginTop: 2 }}>
                {plan.goal === 'edu' && '8–15 years'}
                {plan.goal === 'retire' && '20–35 years'}
                {plan.goal === 'buy' && '3–7 years'}
                {plan.goal === 'travel' && '1–3 years'}
                {plan.goal === 'wealth' && 'Open-ended'}
              </div>
            </div>
            <div className="hand" style={{ fontSize: 12, color: 'var(--accent)' }}>we'll<br/>pre-fill →</div>
          </div>
        )}
      </div>
      <BottomNav onBack={onBack} onNext={onNext} nextDisabled={!plan.goal} />
    </Phone>
  );
}

Object.assign(window, { OnboardingA, Step1A, Step1B, Step2A, Step2B, GOALS });
