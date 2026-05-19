import { api } from './api.js';
import { DS_C, mkTbl } from './utils.js';

const C = DS_C;

export async function loadChangelog() {
  try {
    const history=await api('/api/v1/experience/rita/training-history').catch(()=>[]);
    const rows=Array.isArray(history)?history:(history.runs||[]);
    const histEl=document.getElementById('build-hist-tbl');
    const badge=document.getElementById('build-badge');
    if(rows.length) {
      if(badge) badge.textContent=`${rows.length} runs`;
      if(histEl) histEl.innerHTML=mkTbl(rows.slice().reverse(),[
        {key:'timestamp',label:'Date',mono:true},{key:'instrument',label:'Instrument'},
        {key:'timesteps',label:'Timesteps',mono:true,right:true},
        {key:'backtest_sharpe',label:'BT Sharpe',mono:true,right:true},
        {key:'val_sharpe',label:'Val Sharpe',mono:true,right:true},
        {key:'backtest_return_pct',label:'BT Return%',mono:true,right:true},
        {key:'backtest_mdd_pct',label:'BT Max DD%',mono:true,right:true},{key:'notes',label:'Notes'}
      ]);
    } else if(histEl) {
      histEl.innerHTML='<div class="empty">No build history recorded yet.</div>';
    }
  } catch(e){ /* silently skip if API unavailable */ }

  const clTbl=document.getElementById('cl-tbl');
  if(clTbl) clTbl.innerHTML='<div class="empty">No changelog entries yet. Add one below.</div>';
  const clDate=document.getElementById('cl-date');
  if(clDate) clDate.value=new Date().toISOString().slice(0,10);
}

export async function saveChangelog() {
  const g=id=>document.getElementById(id).value;
  const msg=document.getElementById('cl-msg');
  try {
    await api('/api/v1/changelog','POST',{date:g('cl-date'),version:g('cl-version'),category:g('cl-cat'),change:g('cl-change'),notes:g('cl-notes')});
    msg.style.color=C.build; msg.textContent='✓ Saved';
    ['cl-change','cl-notes','cl-version'].forEach(id=>document.getElementById(id).value='');
    await loadChangelog();
  } catch(e){ msg.style.color=C.danger; msg.textContent='✗ '+e.message; }
  setTimeout(()=>msg.textContent='',3000);
}
