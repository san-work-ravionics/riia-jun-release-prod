import { api } from './api.js';
import { state } from './state.js';
import { DS_C, mkTbl, fmtPctRaw } from './utils.js';
import { mkChart } from '../shared/charts.js';

const C = DS_C;

export async function loadTrades() {
  try {
    const [events, daily] = await Promise.all([
      api('/api/v1/trade-events').catch(()=>[]),
      api('/api/v1/experience/rita/backtest-daily').catch(()=>[])
    ]);
    const entries=events.filter(e=>e.risk_action==='Increased'||e.event_type==='entry'||e.trade_type==='entry');
    const pEx=events.filter(e=>(e.risk_action==='Reduced'||e.event_type==='exit'||e.trade_type==='exit')&&parseFloat(e.pnl??0)>0);
    const lEx=events.filter(e=>(e.risk_action==='Reduced'||e.event_type==='exit'||e.trade_type==='exit')&&parseFloat(e.pnl??0)<=0);
    const wr=(pEx.length+lEx.length)>0?pEx.length/(pEx.length+lEx.length):0;
    const s=(id,v)=>{ const el=document.getElementById(id); if(el) el.textContent=v; };
    s('t-entries',entries.length||events.length); s('t-profit',pEx.length); s('t-loss',lEx.length);
    s('t-winrate',fmtPctRaw(wr*100,1)); s('t-total',events.length);

    const entrySharpes=entries.map(e=>e.sharpe_at_trade).filter(v=>v!=null);
    const exitSharpes=[...pEx,...lEx].map(e=>e.sharpe_at_trade).filter(v=>v!=null);
    const avgEntryS=entrySharpes.length?entrySharpes.reduce((a,b)=>a+b,0)/entrySharpes.length:null;
    const avgExitS =exitSharpes.length ?exitSharpes.reduce((a,b)=>a+b,0)/exitSharpes.length :null;
    const deltaS   =(avgEntryS!=null&&avgExitS!=null)?avgExitS-avgEntryS:null;
    const fmtS=v=>v==null?'—':v.toFixed(2);
    const fmtSEl=(id,v)=>{const el=document.getElementById(id);if(!el)return;el.textContent=fmtS(v);el.className='kpi-value'+(v==null?'':v>0?' pos':v<0?' neg':'');};
    fmtSEl('t-sharpe-entry',avgEntryS); fmtSEl('t-sharpe-exit',avgExitS); fmtSEl('t-sharpe-delta',deltaS);

    if(daily&&daily.length) {
      const labels=daily.map(r=>r.date);
      const prices=daily.map(r=>parseFloat(r.close_price??r.close??r.price??0));
      const pv    =daily.map(r=>parseFloat(r.portfolio_value??1));
      const dd=pv.map((v,i)=>{
        const r=daily[i];
        if(r.drawdown_pct!=null&&r.drawdown_pct!=='') return parseFloat(r.drawdown_pct)*100;
        let peak=pv[0]; for(let j=1;j<=i;j++) if(pv[j]>peak) peak=pv[j];
        return peak>0?(v-peak)/peak*100:0;
      });

      const pvRets=pv.map((v,i)=>i===0?0:(pv[i-1]>0?(v-pv[i-1])/pv[i-1]:0));
      const rollSharpe=pvRets.map((_,i)=>{
        if(i<2) return null;
        const sl=pvRets.slice(Math.max(0,i-63),i);
        const mn=sl.reduce((a,b)=>a+b,0)/sl.length;
        const sd=Math.sqrt(sl.map(x=>(x-mn)**2).reduce((a,b)=>a+b,0)/sl.length);
        return sd>0?(mn/sd)*Math.sqrt(252):null;
      });

      const entryDates      = new Set(entries.map(e=>e.date));
      const profitExitDates = new Set(pEx.map(e=>e.date));
      const lossExitDates   = new Set(lEx.map(e=>e.date));
      const sharpeAtEntry       = labels.map((l,i)=>entryDates.has(l)      ? rollSharpe[i] : null);
      const sharpeAtProfitExit  = labels.map((l,i)=>profitExitDates.has(l) ? rollSharpe[i] : null);
      const sharpeAtLossExit    = labels.map((l,i)=>lossExitDates.has(l)   ? rollSharpe[i] : null);

      const _tradeInstName = state.activeInst?.name || state.activeInst?.id || 'Close';
      if(document.getElementById('trades-chart-title'))
        document.getElementById('trades-chart-title').textContent=
          `Rolling 63d Sharpe & ${_tradeInstName} Close — ▲ Entry (blue) · ▼ Profit Exit (green) · ● Loss Exit (red)`;

      mkChart('ch-trade-combined',{type:'line',data:{labels,datasets:[
        {label:'Rolling 63d Sharpe',data:rollSharpe,borderColor:C.mon,backgroundColor:'transparent',borderWidth:2,pointRadius:0,yAxisID:'y'},
        {label:`${_tradeInstName} Close`,data:prices,borderColor:C.ds,backgroundColor:'transparent',borderWidth:1,borderDash:[3,2],pointRadius:0,yAxisID:'y2'},
        {label:'▲ Entry',data:sharpeAtEntry,pointRadius:8,pointBackgroundColor:'#3B82F6',pointBorderColor:'#3B82F6',pointHoverRadius:10,pointStyle:'triangle',borderColor:'transparent',backgroundColor:'transparent',showLine:false,yAxisID:'y'},
        {label:'▼ Profit Exit',data:sharpeAtProfitExit,pointRadius:8,pointBackgroundColor:'#22C55E',pointBorderColor:'#22C55E',pointHoverRadius:10,pointStyle:'triangle',rotation:180,borderColor:'transparent',backgroundColor:'transparent',showLine:false,yAxisID:'y'},
        {label:'● Loss Exit',data:sharpeAtLossExit,pointRadius:7,pointBackgroundColor:'#EF4444',pointBorderColor:'#EF4444',pointHoverRadius:10,pointStyle:'circle',borderColor:'transparent',backgroundColor:'transparent',showLine:false,yAxisID:'y'}
      ]},options:{
        responsive:true,maintainAspectRatio:false,
        plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},
        scales:{
          x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},
          y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3},
             title:{display:true,text:'Sharpe Ratio',color:C.mon,font:{size:9,family:"'IBM Plex Mono'"}}},
          y2:{position:'right',grid:{display:false},
              ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.ds},
              title:{display:true,text:'Close Price',color:C.ds,font:{size:9,family:"'IBM Plex Mono'"}}}
        }
      }});

      mkChart('ch-trade-pv',{type:'line',data:{labels,datasets:[
        {label:'Portfolio Value',data:pv,borderColor:C.build,backgroundColor:C.buildBg,borderWidth:1.5,pointRadius:0,fill:true}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});
      mkChart('ch-trade-dd',{type:'line',data:{labels,datasets:[
        {label:'Drawdown %',data:dd,borderColor:C.danger,backgroundColor:C.dangerBg,borderWidth:1.5,pointRadius:0,fill:true}
      ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{font:{family:"'IBM Plex Mono'",size:10},color:C.t2}}},scales:{x:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3,maxTicksLimit:12}},y:{grid:{color:C.grid},ticks:{font:{family:"'IBM Plex Mono'",size:9},color:C.t3}}}}});
    }

    const phases={};
    events.forEach(e=>{ const p=e.phase||'All'; if(!phases[p]) phases[p]={phase:p,entries:0,profit:0,loss:0,sharpeEntry:[],sharpeExit:[]};
      if(e.event_type==='entry'||e.trade_type==='entry'){phases[p].entries++;if(e.sharpe_at_trade!=null)phases[p].sharpeEntry.push(e.sharpe_at_trade);}
      else{if(parseFloat(e.pnl??0)>0) phases[p].profit++; else phases[p].loss++;if(e.sharpe_at_trade!=null)phases[p].sharpeExit.push(e.sharpe_at_trade);}});
    const avgArr=a=>a.length?+(a.reduce((x,y)=>x+y,0)/a.length).toFixed(2):null;
    const phRows=Object.values(phases).map(p=>({phase:p.phase,entries:p.entries,profit_exits:p.profit,loss_exits:p.loss,
      win_rate:fmtPctRaw((p.profit+p.loss)>0?p.profit/(p.profit+p.loss)*100:0,1),
      avg_entry_sharpe:avgArr(p.sharpeEntry)??'—', avg_exit_sharpe:avgArr(p.sharpeExit)??'—'}));
    document.getElementById('trade-phase-tbl').innerHTML=mkTbl(phRows,[
      {key:'phase',label:'Phase'},{key:'entries',label:'Entries',mono:true,right:true},
      {key:'profit_exits',label:'Profit Exits',mono:true,right:true},{key:'loss_exits',label:'Loss Exits',mono:true,right:true},
      {key:'win_rate',label:'Win Rate',mono:true,right:true},
      {key:'avg_entry_sharpe',label:'Avg Entry Sharpe',mono:true,right:true},
      {key:'avg_exit_sharpe',label:'Avg Exit Sharpe',mono:true,right:true}
    ]);
    document.getElementById('trade-log-tbl').innerHTML=mkTbl(events,[
      {key:'date',label:'Date',mono:true},{key:'phase',label:'Phase'},
      {key:'risk_action',label:'Action'},{key:'allocation',label:'Alloc',mono:true,right:true},
      {key:'delta_allocation',label:'Δ Alloc',mono:true,right:true},
      {key:'sharpe_at_trade',label:'Sharpe',mono:true,right:true},
      {key:'portfolio_var_95',label:'VaR 95%',mono:true,right:true},{key:'regime',label:'Regime'}
    ]);
  } catch(e){ console.warn('Trades:',e); }
}
