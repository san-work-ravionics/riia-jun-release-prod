import { api } from './api.js';
import { DS_C, mkTbl } from './utils.js';

export async function loadExport() {
  try {
    const h=await api('/health');
    document.getElementById('deploy-manifest').innerHTML=[
      ['Version',h.version||'1.0.0'],['Environment',h.environment||'development'],
      ['Model File',h.model_file||'—'],['Data Rows',h.data_rows||'—'],
      ['Latest Date',h.latest_date||'—'],['API Port','8000']
    ].map(([k,v])=>`<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--border);font-size:12px"><span style="color:var(--t3)">${k}</span><span style="font-family:var(--fm);font-weight:500">${v}</span></div>`).join('');
  } catch(e){ document.getElementById('deploy-manifest').innerHTML='<div class="empty" style="padding:16px">API offline.</div>'; }

  document.getElementById('env-tbl').innerHTML=mkTbl([
    {key:'PYTHON_ENV',value:'C:/Users/Sandeep/pyenv-envs/poc'},
    {key:'API_HOST',value:'0.0.0.0:8000'},{key:'DASHBOARD',value:'/dashboard/'},
    {key:'RITA_OUTPUT',value:'rita_output/'},{key:'RITA_INPUT',value:'rita_input/'}
  ],[{key:'key',label:'Variable',mono:true},{key:'value',label:'Value',mono:true}]);
}

export async function pingAPI() {
  const el=document.getElementById('api-health');
  el.innerHTML='<div class="empty" style="padding:10px"><span class="spinner"></span>Pinging…</div>';
  try {
    const t0=performance.now(); const h=await api('/health'); const ms=(performance.now()-t0).toFixed(0);
    el.innerHTML=`<div class="alert-strip">
      <div class="alert-row ok"><span class="alert-icon">✓</span><span class="alert-msg">FastAPI responding — <strong>${ms}ms</strong></span></div>
      <div class="alert-row ok"><span class="alert-icon">◈</span><span class="alert-msg">Version: ${h.version||'—'} · Model: ${h.model_file||'—'}</span></div>
      <div class="alert-row ok"><span class="alert-icon">📊</span><span class="alert-msg">Data rows: ${h.data_rows||'—'} · Latest: ${h.latest_date||'—'}</span></div>
    </div>`;
  } catch(e){
    el.innerHTML=`<div class="alert-strip"><div class="alert-row err"><span class="alert-icon">✗</span><span class="alert-msg">${e.message}</span></div></div>`;
  }
}

export async function dlJSON(path, filename) {
  try {
    const r=await fetch(path); const blob=await r.blob();
    const url=URL.createObjectURL(blob); const a=document.createElement('a');
    a.href=url; a.download=filename; a.click(); URL.revokeObjectURL(url);
  } catch(e){ alert('Download failed: '+e.message); }
}
