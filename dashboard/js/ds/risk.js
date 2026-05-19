import { api } from './api.js';
import { DS_C, mkTbl, fmtPctRaw } from './utils.js';
import { mkChart } from '../shared/charts.js';

const C = DS_C;

export async function loadRisk() {
  try {
    const [risk, events] = await Promise.all([
      api('/api/v1/experience/rita/risk-timeline').catch(()=>[]),
      api('/api/v1/trade-events').catch(()=>[])
    ]);
    if(!risk||!risk.length) return;

    const labels=risk.map(r=>r.date);
    const vol   =risk.map(r=>parseFloat(r.rolling_vol_20d??r.volatility??0));
    const var95 =risk.map(r=>parseFloat(r.portfolio_var_95??r.var_95??0));
    const budget=risk.map(r=>parseFloat(r.drawdown_budget_pct??r.dd_budget_used??r.budget_pct??0));
    const trend =risk.map(r=>parseFloat(r.trend_score??r.regime??0));
    const alloc =risk.map(r=>parseFloat(r.allocation??0));
    const evtMap={}; events.forEach(e=>{ if(e.date) evtMap[e.date]=(parseFloat(e.delta_var??e.delta_allocation??0)); });
    const delta=labels.map(d=>evtMap[d]??0);

    const invested=risk.filter(r=>parseFloat(r.allocation??0)>0.3);
    const avgVar=invested.length?invested.reduce((s,r)=>s+parseFloat(r.portfolio_var_95??r.var_95??0),0)/invested.length:0;
    const peakVar=Math.max(...var95); const maxBudget=Math.max(...budget);
    const riTrades=events.filter(e=>e.risk_action==='Increased'||e.event_type==='entry'||e.trade_type==='entry').length;

    const e=id=>document.getElementById(id);
    if(e('r-avg-var'))  e('r-avg-var').textContent=fmtPctRaw(avgVar,2);
    if(e('r-peak-var')) e('r-peak-var').textContent=fmtPctRaw(peakVar,2);
    if(e('r-max-budget')) e('r-max-budget').textContent=fmtPctRaw(maxBudget,1);
    if(e('r-ri-trades')) e('r-ri-trades').textContent=riTrades;

    mkChart('ch-var',{type:'line',data:{labels,datasets:[
      {label:'Rolling Vol 20d %',data:vol,borderColor:C.warn,backgroundColor:'transparent',borderWidth:1.5,pointRadius:0},
      {label:'Portfolio VaR 95% %',data:var95,borderColor:C.danger,backgroundColor:C.dangerBg,borderWidth:1.5,pointRadius:0,fill:true}
    ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});

    mkChart('ch-budget',{type:'line',data:{labels,datasets:[
      {label:'DD Budget Used % (100% = 10% MDD limit hit)',data:budget,borderColor:C.run,backgroundColor:C.runBg,borderWidth:1.5,pointRadius:0,fill:true}
    ]},options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{
        legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}},
        annotation:{annotations:{limit:{type:'line',yMin:100,yMax:100,borderColor:C.danger,borderDash:[4,2],label:{display:true,content:'MDD Limit',position:'end',color:C.danger,font:{size:9,family:"'IBM Plex Mono'"}}}}}
      },
      scales:{
        x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},
        y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,callback:v=>v+'%'},min:0}
      }
    }});

    mkChart('ch-trade-risk',{type:'bar',data:{labels,datasets:[
      {label:'ΔVaR %',data:delta,backgroundColor:delta.map(v=>v>0?C.dangerBg:C.buildBg),borderColor:delta.map(v=>v>0?C.danger:C.build),borderWidth:1}
    ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});

    mkChart('ch-regime',{type:'line',data:{labels,datasets:[
      {label:'Trend Score (−1=bearish, 0=neutral, +1=bullish)',data:trend,borderColor:C.ds,backgroundColor:C.dsBg,borderWidth:1.5,pointRadius:0,fill:true,yAxisID:'y'},
      {label:'Allocation %',data:alloc.map(v=>v*100),borderColor:C.build,backgroundColor:'transparent',borderWidth:1,borderDash:[3,2],pointRadius:0,yAxisID:'y2'}
    ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{
      x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},
      y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,callback:v=>v===1?'+1 Bull':v===0?'Neutral':v===-1?'−1 Bear':v},min:-1,max:1},
      y2:{position:'right',grid:{display:false},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,callback:v=>v+'%'},min:0,max:100}
    }}});

    const phases={};
    risk.forEach(r=>{ const p=r.phase||'All'; if(!phases[p]) phases[p]={phase:p,cnt:0,varSum:0,budMax:0};
      phases[p].cnt++; phases[p].varSum+=parseFloat(r.portfolio_var_95??r.var_95??0);
      phases[p].budMax=Math.max(phases[p].budMax,parseFloat(r.drawdown_budget_pct??r.dd_budget_used??r.budget_pct??0)); });
    const phRows=Object.values(phases).map(p=>({phase:p.phase,days:p.cnt,avg_var:fmtPctRaw(p.varSum/p.cnt,2),max_budget:fmtPctRaw(p.budMax,1)}));
    document.getElementById('risk-phase-tbl').innerHTML=mkTbl(phRows,[
      {key:'phase',label:'Phase'},{key:'days',label:'Days',mono:true,right:true},
      {key:'avg_var',label:'Avg VaR%',mono:true,right:true},{key:'max_budget',label:'Max Budget%',mono:true,right:true}
    ]);
  } catch(e){ console.warn('Risk:',e); }
}
