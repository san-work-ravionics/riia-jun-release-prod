// Shared wireframe primitives — phone shell, status bar, app bar, nav, icons.
// Used by every screen. Pure presentational; no state.

const { useState, useEffect, useRef, useMemo } = React;

// ─── Icons (sketchy SVG, line-based) ─────────────────────────
const Ico = {
  back: <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 2 4 7l5 5"/></svg>,
  close: <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M3 3l8 8M11 3l-8 8"/></svg>,
  arrow: <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7h8M7 3l4 4-4 4"/></svg>,
  check: <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7l3 3 5-6"/></svg>,
  chev:  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 5l3 3 3-3"/></svg>,
  spark: <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M7 2v3M7 9v3M2 7h3M9 7h3M3.5 3.5l2 2M8.5 8.5l2 2M3.5 10.5l2-2M8.5 5.5l2-2"/></svg>,
  warn:  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M7 2 13 12H1z"/><path d="M7 6v3M7 11v.01"/></svg>,
  good:  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="7" cy="7" r="5.5"/><path d="M4.5 7l2 2 3-4"/></svg>,
  bad:   <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><circle cx="7" cy="7" r="5.5"/><path d="M5 5l4 4M9 5l-4 4"/></svg>,
  // Goal icons (Step 2)
  edu:   <svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d="M2 8l9-4 9 4-9 4-9-4z"/><path d="M6 10v4c0 1.5 2.5 3 5 3s5-1.5 5-3v-4M19 9v5"/></svg>,
  ret:   <svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d="M3 18h16M5 18V8l6-4 6 4v10M9 18v-5h4v5"/></svg>,
  buy:   <svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d="M3 18h16M5 18V9h4M9 18v-5h4v5M13 18V9h4"/><path d="M3 9l8-6 8 6"/></svg>,
  travel:<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d="M2 14l18-7-3 12-5-5-3 5-3-3z"/></svg>,
  wealth:<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d="M3 18l5-6 4 3 7-9"/><path d="M14 6h5v5"/></svg>,
  edit:  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9 2l3 3-7 7H2v-3z"/></svg>,
};

// ─── Status bar — Android style ─────────────────────────────
function StatusBar() {
  return (
    <div className="status-bar">
      <span>9:41</span>
      <div className="icons">
        <svg width="14" height="10" viewBox="0 0 14 10" fill="currentColor"><rect x="0" y="6" width="2" height="4"/><rect x="3" y="4" width="2" height="6"/><rect x="6" y="2" width="2" height="8"/><rect x="9" y="0" width="2" height="10"/></svg>
        <svg width="14" height="10" viewBox="0 0 14 10" fill="none" stroke="currentColor" strokeWidth="1"><path d="M1 5a8 8 0 0112 0M3 7a5 5 0 018 0M5.5 9a2 2 0 013 0"/></svg>
        <svg width="20" height="10" viewBox="0 0 20 10" fill="none" stroke="currentColor" strokeWidth="1"><rect x="0.5" y="0.5" width="16" height="9" rx="1.5"/><rect x="2" y="2" width="11" height="6" fill="currentColor"/><rect x="17" y="3" width="2" height="4" fill="currentColor"/></svg>
      </div>
    </div>
  );
}

// ─── App bar with optional back, title, step pill ──────────
function AppBar({ title, step, totalSteps = 6, onBack, onClose }) {
  return (
    <div className="app-bar">
      {onBack && <button className="back" onClick={onBack}>{Ico.back}</button>}
      {onClose && <button className="back" onClick={onClose}>{Ico.close}</button>}
      <div className="title">{title}</div>
      {step != null && <div className="step-pill">Step {step}/{totalSteps}</div>}
    </div>
  );
}

// ─── Step strip (segmented progress under app bar) ─────────
function StepStrip({ current, total = 6 }) {
  return (
    <div className="step-strip">
      {Array.from({ length: total }, (_, i) => (
        <div key={i} className={'seg ' + (i + 1 < current ? 'done' : i + 1 === current ? 'active' : '')} />
      ))}
    </div>
  );
}

// ─── Bottom nav (Next / Back) ──────────────────────────────
function BottomNav({ onBack, onNext, nextLabel = 'Continue', nextDisabled, secondary }) {
  return (
    <>
      <div className="nav-bottom">
        {onBack && <button className="btn ghost icon-only" onClick={onBack}>{Ico.back}</button>}
        {secondary}
        <button className="btn" onClick={onNext} disabled={nextDisabled} style={{ opacity: nextDisabled ? 0.4 : 1 }}>
          {nextLabel} {Ico.arrow}
        </button>
      </div>
      <div className="gesture-bar" />
    </>
  );
}

// ─── Phone wrapper ─────────────────────────────────────────
function Phone({ children }) {
  return <div className="phone">{children}</div>;
}

// ─── Sticky annotation note (off to the side) ──────────────
function DesignerNote({ children, label = 'note', flip, style }) {
  return (
    <div className={'designer-note' + (flip ? ' r' : '')} style={style}>
      <span className="nt">{label}</span>
      {children}
    </div>
  );
}

Object.assign(window, { Ico, StatusBar, AppBar, StepStrip, BottomNav, Phone, DesignerNote });
