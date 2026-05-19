import { api } from './api.js';
import { state } from './state.js';
import { DS_C, mkTbl, fmtPctRaw } from './utils.js';
import { mkChart } from '../shared/charts.js';

const C = DS_C;

function fmt(v, dec=2) {
  if (v==null||v==='') return '—';
  const n = parseFloat(v);
  return isNaN(n) ? String(v) : n.toFixed(dec);
}

export function switchPerfTab(tab, el) {
  document.querySelectorAll('.perf-phase-tab').forEach(t=>t.classList.remove('active'));
  el?.classList.add('active');
  document.querySelectorAll('.perf-phase-panel').forEach(p=>p.classList.add('hidden'));
  const panel=document.getElementById('pp-'+tab);
  if(panel) panel.classList.remove('hidden');
}

export async function loadPerformance() {
  try {
    const [summary, daily, history] = await Promise.all([
      api('/api/v1/performance-summary'),
      api('/api/v1/experience/rita/backtest-daily'),
      api('/api/v1/experience/rita/training-history').catch(()=>[])
    ]);
    const p=summary.performance||summary;
    const set=(id,v,cls)=>{ const e=document.getElementById(id); if(e){e.textContent=v;if(cls)e.className='kpi-value '+cls;} };
    const ret=parseFloat(p.portfolio_total_return_pct??p.total_return_pct??p.total_return??0);
    set('p-return', fmtPctRaw(ret,1), ret>=0?'pos':'neg');
    set('p-cagr',   fmtPctRaw(parseFloat(p.portfolio_cagr_pct??p.cagr_pct??p.cagr??0),1), '');
    set('p-sharpe', fmt(p.sharpe_ratio??p.sharpe,2), 'neu');
    set('p-mdd',    fmtPctRaw(parseFloat(p.max_drawdown_pct??p.max_drawdown??0),1), 'neg');
    set('p-winrate',fmtPctRaw(parseFloat(p.win_rate_pct??p.win_rate??0),1), '');

    const constraints=summary.constraints||[];
    const perfCons=document.getElementById('perf-constraints');
    if(constraints.length) {
      perfCons.style.display='';
      perfCons.innerHTML=constraints.map(c=>{
        const ok=c.passed||c.status==='pass'||c.status==='ok';
        const cls=ok?'ok':(c.status==='warn'?'warn':'err');
        return `<div class="alert-row ${cls}"><span class="alert-icon">${ok?'✓':(cls==='warn'?'⚠':'✗')}</span><span class="alert-msg">${c.name||c.constraint}: <strong>${c.value??''}</strong></span><span class="alert-tag">${c.threshold??''}</span></div>`;
      }).join('');
    } else {
      perfCons.style.display='none';
    }

    if(daily&&daily.length) {
      const labels=daily.map(r=>r.date);
      const strat=daily.map(r=>parseFloat(r.cumulative_strategy??r.portfolio_value??1)*100);
      const bnh  =daily.map(r=>parseFloat(r.benchmark_value??r.cumulative_bnh??r.buy_hold??1)*100);
      const alloc=daily.map(r=>parseFloat(r.allocation??0));
      const pvRaw=daily.map(r=>parseFloat(r.portfolio_value??1));
      const dd = daily.map((r,i)=>{
        if(r.drawdown_pct!=null&&r.drawdown_pct!=='') return parseFloat(r.drawdown_pct)*100;
        let peak=pvRaw[0]; for(let j=1;j<=i;j++) if(pvRaw[j]>peak) peak=pvRaw[j];
        return peak>0?(pvRaw[i]-peak)/peak*100:0;
      });
      const rets=pvRaw.map((v,i)=>i===0?0:(pvRaw[i-1]>0?(v-pvRaw[i-1])/pvRaw[i-1]:0));

      const _instName = state.activeInst?.name || state.activeInst?.id || 'Instrument';
      mkChart('ch-returns',{type:'line',data:{labels,datasets:[
        {label:'DDQN Strategy',data:strat,borderColor:C.build,backgroundColor:C.buildBg,borderWidth:1.5,pointRadius:0,fill:true},
        {label:`${_instName} Buy & Hold`,data:bnh,borderColor:C.run,backgroundColor:'transparent',borderWidth:1.5,pointRadius:0,borderDash:[4,2]}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});

      mkChart('ch-drawdown',{type:'line',data:{labels,datasets:[
        {label:'Drawdown %',data:dd,borderColor:C.danger,backgroundColor:C.dangerBg,borderWidth:1.5,pointRadius:0,fill:true}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});

      const rollSharpe=rets.map((_,i)=>{
        if(i<63) return null;
        const sl=rets.slice(i-63,i);
        const mn=sl.reduce((a,b)=>a+b,0)/63;
        const sd=Math.sqrt(sl.map(x=>(x-mn)**2).reduce((a,b)=>a+b,0)/63);
        return sd>0?(mn/sd)*Math.sqrt(252):null;
      });
      mkChart('ch-sharpe-roll',{type:'line',data:{labels,datasets:[
        {label:'Rolling 63d Sharpe',data:rollSharpe,borderColor:C.ds,backgroundColor:C.dsBg,borderWidth:1.5,pointRadius:0,fill:true,spanGaps:false}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}},annotation:{annotations:{zero:{type:'line',yMin:0,yMax:0,borderColor:'rgba(0,0,0,.3)',borderDash:[3,2]}}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});

      mkChart('ch-alloc',{type:'bar',data:{labels,datasets:[
        {label:'Allocation %',data:alloc.map(v=>v*100),
         backgroundColor:alloc.map(v=>v>0.6?C.buildBg:v>0.3?C.dsBg:C.runBg),
         borderColor:alloc.map(v=>v>0.6?C.build:v>0.3?C.ds:C.run),borderWidth:1}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3},min:0,max:100}}}});
    }

    try {
      const history2 = await api('/api/v1/experience/rita/training-history').catch(()=>[]);
      const hRows = Array.isArray(history2)?history2:(history2.runs||[]);
      const hLabels = hRows.map((r,i)=>`R${i+1}`);

      const cmpScales = {
        x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},
        y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3},title:{display:true,text:'Sharpe / MDD / Return',color:C.t3,font:{size:9}}},
        y1:{position:'right',grid:{drawOnChartArea:false},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3},title:{display:true,text:'Trades',color:C.t3,font:{size:9}}}
      };
      const tblCols = [
        {key:'run',label:'Run'},
        {key:'sharpe',label:'Sharpe',mono:true,right:true},
        {key:'mdd',label:'MDD %',mono:true,right:true},
        {key:'ret',label:'Return %',mono:true,right:true},
        {key:'trades',label:'Trades',mono:true,right:true}
      ];

      if(hRows.length) {
        const trSharpe    = hRows.map(r=>parseFloat(r.backtest_sharpe??0)||null);
        const trMdd       = hRows.map(r=>Math.abs(parseFloat(r.backtest_mdd_pct??0))||null);
        const trRet       = hRows.map(r=>parseFloat(r.backtest_return_pct??0)||null);
        const trTimesteps = hRows.map(r=>parseInt(r.timesteps??0)||null);
        mkChart('ch-pf-train',{type:'line',data:{labels:hLabels,datasets:[
          {label:'Post-Train Sharpe',data:trSharpe,borderColor:C.ds,backgroundColor:'transparent',borderWidth:1.5,pointRadius:3,spanGaps:false,yAxisID:'y'},
          {label:'Post-Train MDD %',data:trMdd,borderColor:C.danger,backgroundColor:'transparent',borderWidth:1.5,pointRadius:3,spanGaps:false,yAxisID:'y',borderDash:[4,2]},
          {label:'Post-Train Return %',data:trRet,borderColor:C.run,backgroundColor:'transparent',borderWidth:1.5,pointRadius:3,spanGaps:false,yAxisID:'y',borderDash:[2,2]},
          {label:'Timesteps (k)',data:trTimesteps.map(v=>v?Math.round(v/1000):null),borderColor:C.mon,backgroundColor:'transparent',borderWidth:1.5,pointRadius:3,spanGaps:false,yAxisID:'y1',borderDash:[6,2]}
        ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3},title:{display:true,text:'Sharpe / MDD / Return',color:C.t3,font:{size:9}}},y1:{position:'right',grid:{drawOnChartArea:false},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3},title:{display:true,text:'Timesteps (k)',color:C.t3,font:{size:9}}}}}});
        const pfTrainTbl = document.getElementById('pf-train-tbl');
        if(pfTrainTbl) pfTrainTbl.innerHTML = mkTbl(
          hRows.map((r,i)=>({
            run:hLabels[i],
            sharpe:fmt(parseFloat(r.backtest_sharpe??0),3),
            mdd:fmtPctRaw(Math.abs(parseFloat(r.backtest_mdd_pct??0)),1),
            ret:fmtPctRaw(parseFloat(r.backtest_return_pct??0),1),
            trades:r.timesteps?`${Math.round(parseInt(r.timesteps)/1000)}k`:'—'
          })),
          [{key:'run',label:'Run'},{key:'sharpe',label:'Sharpe',mono:true,right:true},{key:'mdd',label:'MDD %',mono:true,right:true},{key:'ret',label:'Return %',mono:true,right:true},{key:'trades',label:'Timesteps',mono:true,right:true}]
        );

        const valSharpe = hRows.map(r=>parseFloat(r.val_sharpe??r.backtest_sharpe??0)||null);
        const valMdd    = hRows.map(r=>Math.abs(parseFloat(r.val_mdd_pct??r.backtest_mdd_pct??0))||null);
        const valRet    = hRows.map(r=>parseFloat(r.val_cagr_pct??r.backtest_cagr_pct??r.backtest_return_pct??0)||null);
        const valTrades = hRows.map(r=>parseInt(r.val_trade_count??r.backtest_trade_count??0)||null);
        mkChart('ch-pf-val',{type:'line',data:{labels:hLabels,datasets:[
          {label:'Val Sharpe',data:valSharpe,borderColor:C.ds,backgroundColor:'transparent',borderWidth:1.5,pointRadius:3,spanGaps:false,yAxisID:'y'},
          {label:'Val MDD %',data:valMdd,borderColor:C.danger,backgroundColor:'transparent',borderWidth:1.5,pointRadius:3,spanGaps:false,yAxisID:'y',borderDash:[4,2]},
          {label:'Val CAGR %',data:valRet,borderColor:C.run,backgroundColor:'transparent',borderWidth:1.5,pointRadius:3,spanGaps:false,yAxisID:'y',borderDash:[2,2]},
          {label:'Trades',data:valTrades,borderColor:C.mon,backgroundColor:'transparent',borderWidth:1.5,pointRadius:3,spanGaps:false,yAxisID:'y1',borderDash:[6,2]}
        ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:cmpScales}});
        const pfValTbl = document.getElementById('pf-val-tbl');
        if(pfValTbl) pfValTbl.innerHTML = mkTbl(
          hRows.map((r,i)=>({
            run:hLabels[i],
            sharpe:fmt(parseFloat(r.val_sharpe??r.backtest_sharpe??0),3),
            mdd:fmtPctRaw(Math.abs(parseFloat(r.val_mdd_pct??r.backtest_mdd_pct??0)),1),
            ret:fmtPctRaw(parseFloat(r.val_cagr_pct??r.backtest_cagr_pct??r.backtest_return_pct??0),1),
            trades:r.val_trade_count??r.backtest_trade_count??'—'
          })), tblCols);

        const btSharpe = hRows.map(r=>parseFloat(r.backtest_sharpe??r.sharpe_ratio??r.sharpe??0)||null);
        const btMdd    = hRows.map(r=>Math.abs(parseFloat(r.backtest_mdd_pct??r.max_drawdown_pct??0))||null);
        const btRet    = hRows.map(r=>parseFloat(r.backtest_return_pct??r.total_return_pct??0)||null);
        const btTrades = hRows.map(r=>parseInt(r.backtest_trade_count??r.trade_count??0)||null);
        mkChart('ch-pf-bt',{type:'line',data:{labels:hLabels,datasets:[
          {label:'BT Sharpe',data:btSharpe,borderColor:C.ds,backgroundColor:'transparent',borderWidth:1.5,pointRadius:3,spanGaps:false,yAxisID:'y'},
          {label:'BT MDD %',data:btMdd,borderColor:C.danger,backgroundColor:'transparent',borderWidth:1.5,pointRadius:3,spanGaps:false,yAxisID:'y',borderDash:[4,2]},
          {label:'BT Return %',data:btRet,borderColor:C.run,backgroundColor:'transparent',borderWidth:1.5,pointRadius:3,spanGaps:false,yAxisID:'y',borderDash:[2,2]},
          {label:'Trades',data:btTrades,borderColor:C.mon,backgroundColor:'transparent',borderWidth:1.5,pointRadius:3,spanGaps:false,yAxisID:'y1',borderDash:[6,2]}
        ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:cmpScales}});
        const pfBtTbl = document.getElementById('pf-bt-tbl');
        if(pfBtTbl) pfBtTbl.innerHTML = mkTbl(
          hRows.map((r,i)=>({
            run:hLabels[i],
            sharpe:r.backtest_sharpe!=null?fmt(parseFloat(r.backtest_sharpe??r.sharpe_ratio??r.sharpe??0),3):'—',
            mdd:r.backtest_mdd_pct!=null?fmtPctRaw(Math.abs(parseFloat(r.backtest_mdd_pct??r.max_drawdown_pct??0)),1):'—',
            ret:r.backtest_return_pct!=null?fmtPctRaw(parseFloat(r.backtest_return_pct??r.total_return_pct??0),1):'—',
            trades:r.backtest_trade_count??r.trade_count??'—'
          })), tblCols);
      }
    } catch(e2){ console.warn('perf-round-cmp:',e2); }

  } catch(e){ console.warn('Performance:',e); }
}
