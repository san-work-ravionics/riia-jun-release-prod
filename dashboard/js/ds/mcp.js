import { api } from './api.js';
import { DS_C, mkTbl, fmtPctRaw, fmtDT } from './utils.js';
import { mkChart } from '../shared/charts.js';

const C = DS_C;

export async function loadMCP() {
  try {
    const data=await api('/api/v1/mcp-calls');
    const calls=Array.isArray(data)?data:(data.calls||[]);
    const success=calls.filter(c=>c.status==='success'||c.status==='ok').length;
    const tools=[...new Set(calls.map(c=>c.tool_name||c.tool||c.function))].length;
    const lats=calls.map(c=>parseFloat(c.latency_ms??c.duration_ms??0)).filter(v=>v>0);
    const avgLat=lats.length?lats.reduce((a,b)=>a+b,0)/lats.length:0;
    const errors=calls.filter(c=>c.status==='error'||c.status==='fail').length;
    const last=calls.length?(calls[calls.length-1].timestamp||calls[calls.length-1].date||'—'):'—';

    const e=id=>document.getElementById(id);
    if(e('mc-total')) e('mc-total').textContent=calls.length;
    if(e('mc-success')) e('mc-success').textContent=calls.length?fmtPctRaw(success/calls.length*100,0):'—';
    if(e('mc-tools')) e('mc-tools').textContent=tools;
    if(e('mc-latency')) e('mc-latency').textContent=avgLat>0?`${avgLat.toFixed(0)}ms`:'—';
    if(e('mc-errors')){ e('mc-errors').textContent=errors; e('mc-errors').className=`kpi-value ${errors>0?'neg':'pos'}`; }
    if(e('mc-last')) e('mc-last').textContent=String(last).slice(0,10);

    const toolCounts={}, toolLat={};
    calls.forEach(c=>{ const t=c.tool_name||c.tool||c.function||'unknown';
      toolCounts[t]=(toolCounts[t]||0)+1;
      if(!toolLat[t]) toolLat[t]=[];
      const lat=parseFloat(c.latency_ms??c.duration_ms??0); if(lat>0) toolLat[t].push(lat); });
    const names=Object.keys(toolCounts).sort((a,b)=>toolCounts[b]-toolCounts[a]).slice(0,12);

    mkChart('ch-mc-usage',{type:'bar',data:{labels:names,datasets:[
      {label:'Total Calls',data:names.map(t=>toolCounts[t]),backgroundColor:C.monBg,borderColor:C.mon,borderWidth:1.5}
    ]},options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});

    mkChart('ch-mc-latency',{type:'bar',data:{labels:names,datasets:[
      {label:'Avg Latency (ms)',data:names.map(t=>toolLat[t]?.length?toolLat[t].reduce((a,b)=>a+b,0)/toolLat[t].length:0),backgroundColor:C.warnBg,borderColor:C.warn,borderWidth:1.5}
    ]},options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});

    e('mcp-tbl').innerHTML=mkTbl(calls.slice().reverse().slice(0,100),[
      {key:'timestamp',label:'Time',mono:true,fmt:fmtDT},{key:'tool_name',label:'Tool'},
      {key:'status',label:'Status',badge:true},{key:'latency_ms',label:'Latency(ms)',mono:true,right:true},{key:'error',label:'Error'}
    ]);
  } catch(e){ console.warn('MCP:',e); }
}
