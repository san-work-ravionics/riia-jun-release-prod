import { api } from './api.js';
import { DS_C, mkTbl } from './utils.js';
import { mkChart, destroyChart } from '../shared/charts.js';

const C = DS_C;

function fmt(v, dec=2) {
  if (v==null||v==='') return '—';
  const n = parseFloat(v);
  return isNaN(n) ? String(v) : n.toFixed(dec);
}

// Local CHARTS registry for radar (not covered by mkChart)
const CHARTS = {};

export async function loadExplain() {
  try {
    const data=await api('/api/v1/shap');
    const rawRows=Array.isArray(data)?data:(data.features||[]);
    if(!rawRows.length) return;

    const isLong = rawRows[0].hasOwnProperty('action') || rawRows[0].hasOwnProperty('action_label');
    let features, actions, getVal;
    if(isLong) {
      features=[...new Set(rawRows.map(r=>r.feature))];
      actions=[...new Set(rawRows.map(r=>r.action??r.action_label??'Action'))];
      getVal=(f,a)=>{ const r=rawRows.find(r=>r.feature===f&&(r.action??r.action_label)===a); return r?Math.abs(parseFloat(r.mean_abs_shap??r.importance??0)):0; };
    } else {
      features=rawRows.map(r=>r.feature);
      actions=Object.keys(rawRows[0]).filter(k=>k!=='feature');
      getVal=(f,a)=>{ const r=rawRows.find(r=>r.feature===f); return r?Math.abs(parseFloat(r[a]??0)):0; };
    }

    const colors=[C.build,C.run,C.ds,C.warn];
    mkChart('ch-shap-bar',{type:'bar',data:{labels:features,datasets:actions.map((a,ai)=>({
      label:a,
      data:features.map(f=>getVal(f,a)),
      backgroundColor:colors[ai%4]+'55', borderColor:colors[ai%4], borderWidth:1.5
    }))},options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',
      plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},
      scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},
              y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});

    // Radar — uses direct Chart.js since mkChart wraps single config
    destroyChart('ch-shap-radar');
    const canvas=document.getElementById('ch-shap-radar');
    if(canvas) {
      if(CHARTS['ch-shap-radar']){CHARTS['ch-shap-radar'].destroy();delete CHARTS['ch-shap-radar'];}
      CHARTS['ch-shap-radar']=new Chart(canvas,{type:'radar',
        data:{labels:features,datasets:actions.map((a,ai)=>({
          label:a,
          data:features.map(f=>getVal(f,a)),
          borderColor:colors[ai%4],backgroundColor:colors[ai%4]+'33',borderWidth:1.5,pointRadius:3
        }))},
        options:{responsive:true,maintainAspectRatio:false,
          plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},
          scales:{r:{ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3},grid:{color:C.grid}}}}
      });
    }

    const totals=features.map(f=>({f,v:actions.reduce((s,a)=>s+getVal(f,a),0)})).sort((a,b)=>b.v-a.v);
    if(totals.length) { const t=document.getElementById('sh-top'); if(t) t.textContent=totals[0].f; }
    const cashA=actions.find(a=>a.toLowerCase().includes('0')||a.toLowerCase().includes('cash'));
    const fullA=actions.find(a=>a.toLowerCase().includes('100')||a.toLowerCase().includes('full'));
    [cashA,fullA].forEach((a,i)=>{
      if(!a) return;
      const top=features.map(f=>({f,v:getVal(f,a)})).sort((a,b)=>b.v-a.v)[0];
      const el=document.getElementById(i===0?'sh-cash':'sh-full');
      if(top&&el) el.textContent=top.f;
    });

    const tblRows=features.map(f=>{ const o={feature:f}; actions.forEach(a=>{ o[a]=fmt(getVal(f,a),4); }); return o; });
    document.getElementById('shap-tbl').innerHTML=mkTbl(tblRows,[
      {key:'feature',label:'Feature'},
      ...actions.map(a=>({key:a,label:a,mono:true,right:true}))
    ]);
  } catch(e){ console.warn('Explain:',e); }
}
