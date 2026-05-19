import { api } from './api.js';
import { DS_C, mkTbl } from './utils.js';
import { mkChart } from '../shared/charts.js';

const C = DS_C;

export async function loadObservability() {
  try {
    const [log, drift] = await Promise.all([
      api('/api/experience/ops/step-log').catch(()=>[]),
      api('/api/v1/drift').catch(()=>({}))
    ]);
    const failed=log.filter(s=>s.status!=='ok'&&s.status!=='success').length;
    const el=id=>document.getElementById(id);
    if(el('ob-total')) el('ob-total').textContent=log.length;
    if(el('ob-failed')){ el('ob-failed').textContent=failed; el('ob-failed').className=`kpi-value ${failed>0?'neg':'pos'}`; }
    const driftOk=!drift.drift_detected;
    if(el('ob-drift')){ el('ob-drift').textContent=driftOk?'No Drift':'Drift Detected'; el('ob-drift').className=`kpi-value ${driftOk?'pos':'neg'}`; }

    if(log.length) {
      mkChart('ch-ob-dur',{type:'bar',data:{
        labels:log.map(s=>s.step_name||s.name||'Step'),
        datasets:[{label:'Duration (s)',data:log.map(s=>parseFloat(s.duration_s??0)),backgroundColor:C.dsBg,borderColor:C.ds,borderWidth:1.5}]
      },options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});
    }

    el('obs-health').innerHTML=[
      {name:'FastAPI',ok:true,msg:'Responding (you are connected)'},
      {name:'Model File',ok:!!drift.model_version,msg:drift.model_version?`v${drift.model_version}`:'Check rita_output/'},
      {name:'Data Drift',ok:driftOk,msg:driftOk?'No drift detected':'Drift detected — consider retraining'},
      {name:'Step Log',ok:failed===0,msg:failed===0?'All steps passing':`${failed} failed step(s)`}
    ].map(c=>`<div class="alert-row ${c.ok?'ok':'warn'}"><span class="alert-icon">${c.ok?'✓':'⚠'}</span><span class="alert-msg"><strong>${c.name}</strong> — ${c.msg}</span></div>`).join('');

    el('obs-run-tbl').innerHTML=mkTbl(log.slice(-20).reverse(),[
      {key:'timestamp',label:'Time',mono:true},{key:'step_name',label:'Step'},
      {key:'status',label:'Status',badge:true},{key:'duration_s',label:'Duration(s)',mono:true,right:true},{key:'notes',label:'Notes'}
    ]);
  } catch(e){ console.warn('Observability:',e); }
}
