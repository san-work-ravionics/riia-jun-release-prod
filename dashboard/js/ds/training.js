import { api } from './api.js';
import { DS_C, mkTbl, fmtPctRaw } from './utils.js';
import { mkChart } from '../shared/charts.js';

const C = DS_C;

function fmt(v, dec=2) {
  if (v==null||v==='') return '—';
  const n = parseFloat(v);
  return isNaN(n) ? String(v) : n.toFixed(dec);
}

export function switchTrainTab(tab, el) {
  document.querySelectorAll('.train-tab').forEach(t=>t.classList.remove('active'));
  el?.classList.add('active');
  document.querySelectorAll('.train-panel').forEach(p=>p.classList.add('hidden'));
  const panel=document.getElementById('tt-'+tab);
  if(panel) panel.classList.remove('hidden');
}

export async function loadTraining() {
  try {
    const [history, progress] = await Promise.all([
      api('/api/v1/experience/rita/training-history').catch(()=>[]),
      api('/api/v1/training-progress').catch(()=>[])
    ]);
    const rows=Array.isArray(history)?history:(history.runs||[]);
    const el=id=>document.getElementById(id);
    if(el('tr-rounds')) el('tr-rounds').textContent=rows.length;

    if(rows.length) {
      const btSharpes=rows.map(r=>parseFloat(r.backtest_sharpe??r.sharpe_ratio??r.sharpe??0)).filter(v=>!isNaN(v)&&v!==0);
      const latest=rows[rows.length-1];
      if(el('tr-best-sharpe')) el('tr-best-sharpe').textContent=btSharpes.length?fmt(Math.max(...btSharpes),2):'—';
      if(el('tr-latest-ret')) el('tr-latest-ret').textContent=fmtPctRaw(parseFloat(latest.backtest_return_pct??latest.total_return_pct??latest.total_return??0),1);
      if(el('tr-latest-val')) el('tr-latest-val').textContent=fmt(latest.val_sharpe??0,2);

      const labels=rows.map((r,i)=>r.timestamp?.slice(0,10)||`Run ${i+1}`);
      const btSharpeData=rows.map(r=>parseFloat(r.backtest_sharpe??r.sharpe_ratio??r.sharpe??0)||null);
      const valSharpeData=rows.map(r=>{ const v=parseFloat(r.val_sharpe); return isNaN(v)||v===0?null:v; });
      const btMddData=rows.map(r=>Math.abs(parseFloat(r.backtest_mdd_pct??r.max_drawdown_pct??r.max_drawdown??0))||null);

      mkChart('ch-tr-sharpe-t',{type:'line',data:{labels,datasets:[
        {label:'Sharpe',data:btSharpeData,borderColor:C.build,backgroundColor:C.buildBg,borderWidth:2,pointRadius:5,fill:true,spanGaps:false}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});
      mkChart('ch-tr-mdd-t',{type:'line',data:{labels,datasets:[
        {label:'Max DD %',data:btMddData,borderColor:C.danger,backgroundColor:C.dangerBg,borderWidth:2,pointRadius:5,fill:true,spanGaps:false}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});

      mkChart('ch-tr-sharpe',{type:'line',data:{labels,datasets:[
        {label:'Backtest Sharpe',data:btSharpeData,borderColor:C.build,backgroundColor:C.buildBg,borderWidth:2,pointRadius:5,fill:true,spanGaps:false},
        {label:'Val Sharpe',data:valSharpeData,borderColor:C.ds,backgroundColor:'transparent',borderWidth:2,pointRadius:5,borderDash:[4,2],spanGaps:false}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});
      mkChart('ch-tr-mdd',{type:'line',data:{labels,datasets:[
        {label:'Backtest Max DD %',data:btMddData,borderColor:C.danger,backgroundColor:C.dangerBg,borderWidth:2,pointRadius:5,fill:true,spanGaps:false}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});
      mkChart('ch-tr-return',{type:'bar',data:{labels,datasets:[
        {label:'BT Return %',data:rows.map(r=>parseFloat(r.backtest_return_pct??r.total_return_pct??r.total_return??0)||null),backgroundColor:C.buildBg,borderColor:C.build,borderWidth:1.5},
        {label:'BT CAGR %',data:rows.map(r=>parseFloat(r.backtest_cagr_pct??r.cagr_pct??r.cagr??0)||null),backgroundColor:C.dsBg,borderColor:C.ds,borderWidth:1.5}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});

      const hasValData=valSharpeData.some(v=>v!==null);
      const valNoData=el('val-no-data'), valChartsWrap=el('val-charts-wrap');
      if(valNoData) valNoData.style.display=hasValData?'none':'';
      if(valChartsWrap) valChartsWrap.style.display=hasValData?'':'none';
      if(hasValData) {
        mkChart('ch-tr-val-sharpe',{type:'line',data:{labels,datasets:[
          {label:'Val Sharpe',data:valSharpeData,borderColor:C.ds,backgroundColor:C.dsBg,borderWidth:2,pointRadius:5,fill:true,spanGaps:false}
        ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});
        mkChart('ch-tr-val-mdd',{type:'line',data:{labels,datasets:[
          {label:'Val Max DD %',data:rows.map(r=>Math.abs(parseFloat(r.val_mdd_pct??0))||null),borderColor:C.danger,backgroundColor:C.dangerBg,borderWidth:2,pointRadius:5,fill:true,spanGaps:false}
        ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});
        el('train-val-tbl').innerHTML=mkTbl(rows.slice().reverse(),[
          {key:'timestamp',label:'Date',mono:true},{key:'instrument',label:'Instrument'},
          {key:'round',label:'Round',mono:true,right:true},
          {key:'val_sharpe',label:'Val Sharpe',mono:true,right:true},
          {key:'val_cagr_pct',label:'Val CAGR%',mono:true,right:true},
          {key:'val_mdd_pct',label:'Val Max DD%',mono:true,right:true},{key:'notes',label:'Notes'}
        ]);
      }

      const cRows=rows.map((r,i)=>{
        const sh=parseFloat(r.backtest_sharpe??r.sharpe_ratio??r.sharpe??0);
        const md=Math.abs(parseFloat(r.backtest_mdd_pct??r.max_drawdown_pct??r.max_drawdown??0));
        const sharpeOk=sh>=0.5, mddOk=md<=25;
        return {
          run:r.timestamp?.slice(0,10)||`Run ${i+1}`,
          sharpe:sh?fmt(sh,3):'—',
          mdd:md?fmtPctRaw(md,1):'—',
          sharpe_ok:sharpeOk?'✓ ≥0.5':'✗ <0.5',
          mdd_ok:mddOk?'✓ ≤25%':'✗ >25%',
          trades:r.backtest_trade_count||'—',
          notes:r.notes||''
        };
      });
      el('train-constraint-tbl').innerHTML=mkTbl(cRows,[
        {key:'run',label:'Run',mono:true},{key:'sharpe',label:'BT Sharpe',mono:true,right:true},
        {key:'sharpe_ok',label:'Sharpe OK',mono:true},{key:'mdd',label:'BT Max DD%',mono:true,right:true},
        {key:'mdd_ok',label:'MDD OK',mono:true},{key:'trades',label:'Trades',mono:true,right:true},{key:'notes',label:'Notes'}
      ]);
      el('train-hist-tbl').innerHTML=mkTbl(rows.slice().reverse(),[
        {key:'timestamp',label:'Date',mono:true},{key:'instrument',label:'Instrument'},
        {key:'timesteps',label:'Timesteps',mono:true,right:true},
        {key:'backtest_sharpe',label:'BT Sharpe',mono:true,right:true},
        {key:'val_sharpe',label:'Val Sharpe',mono:true,right:true},
        {key:'backtest_return_pct',label:'BT Return%',mono:true,right:true},
        {key:'backtest_mdd_pct',label:'BT Max DD%',mono:true,right:true},
        {key:'backtest_trade_count',label:'Trades',mono:true,right:true},{key:'notes',label:'Notes'}
      ]);
    }

    if(progress&&progress.length) {
      const pLabels=progress.map(r=>r.timestep??r.step);
      mkChart('ch-tr-loss',{type:'line',data:{labels:pLabels,datasets:[
        {label:'TD Loss',data:progress.map(r=>parseFloat(r.td_loss??r.loss??0)),borderColor:C.danger,backgroundColor:'transparent',borderWidth:1.5,pointRadius:0,yAxisID:'y'},
        {label:'Reward',data:progress.map(r=>parseFloat(r.reward??r.mean_reward??0)),borderColor:C.build,backgroundColor:'transparent',borderWidth:1.5,pointRadius:0,yAxisID:'y2',borderDash:[3,2]}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{
        x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:10}},
        y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}},
        y2:{position:'right',grid:{display:false},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}
      }}});
      const progEl=el('train-progress-tbl');
      if(progEl) progEl.innerHTML=mkTbl(progress.slice(0,100),[
        {key:'timestep',label:'Timestep',mono:true,right:true},
        {key:'td_loss',label:'TD Loss',mono:true,right:true},
        {key:'reward',label:'Reward',mono:true,right:true}
      ]);
    }
  } catch(e){ console.warn('Training:',e); }
}
