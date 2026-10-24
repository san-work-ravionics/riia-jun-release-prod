const fs=require('fs');
eval(fs.readFileSync(__dirname+'/calc_body.js','utf8')+'\nglobalThis.calc=calc;globalThis.MAX_AGE=MAX_AGE;');
const base={need:2000,infl:.025,now:35,ret:55,end:85,tax:.3,partial:.5,exit:70,hValue:400000,hAppr:.03,hSell:60,hTax:.3,h2Price:250000,h2Mode:'new',
 sv:[{age:50,amt:100000},{age:55,amt:100000},{age:60,amt:100000}],bx:[{age:55,amt:500000},{age:60,amt:100000},{age:65,amt:0}],
 idxMonthly:1000,idxRate:.07,eqMonthly:700,eqRate:.10,comMonthly:150,comRate:.04,altMonthly:150,altRate:.05};
const sc={defaults:{},
 same_house:{h2Mode:'same'},
 partial_0:{partial:0}, partial_100:{partial:1},
 exit_eq_ret:{exit:55}, ret_60:{ret:60}, no_invest:{idxMonthly:0,eqMonthly:0,comMonthly:0,altMonthly:0},
 no_events:{sv:[{age:50,amt:0},{age:55,amt:0},{age:60,amt:0}],bx:[{age:55,amt:0},{age:60,amt:0},{age:65,amt:0}]},
 zero_tax:{tax:0,hTax:0}, zero_infl:{infl:0}, end_70:{end:70}, now_50:{now:50,sv:[{age:50,amt:100000},{age:55,amt:100000},{age:60,amt:100000}]}};
const out={start_year:new Date().getFullYear(),max_age:MAX_AGE,scenarios:{}};
for(const [k,v] of Object.entries(sc)){const p={...base,...v};const r=calc(p);
 const strip=port=>({runOut:port.runOut,corpusOut:port.corpusOut,points:port.points.map(x=>({age:x.age,pot:x.pot,corpus:x.corpus,putIn:x.putIn,income:x.income,need:x.need,sold:x.sold,bal:x.bal,basis:x.basis}))});
 out.scenarios[k]={input:p,output:{years:r.years,total:r.total,assets:r.assets.map(a=>({key:a.key,monthly:a.monthly,rate:a.rate,put:a.put,value:a.value,gain:a.gain,profitM:a.profitM,withdrawnNet:a.withdrawnNet})),
 monthly:r.monthly,put:r.put,value:r.value,pot:r.pot,portfolio:strip(r.portfolio),portfolio0:strip(r.portfolio0),hValueAt:r.hValueAt,hGain:r.hGain,hTaxAmt:r.hTaxAmt,hNet:r.hNet,h2At:r.h2At,houseRelease:r.houseRelease,bigExpenses:r.bigExpenses,savings:r.savings,target:r.target,needAll:r.needAll,needRet:r.needRet,byAge:r.byAge,atRet:r.atRet}};}
fs.writeFileSync(__dirname+'/what_i_need_golden.json',JSON.stringify(out));
const d=out.scenarios.defaults.output;console.log('55',d.byAge[0].monthly,'70',d.byAge[3].monthly,'corpus70',d.byAge[3].corpus,'runOut',d.portfolio.runOut,'p0',d.portfolio0.runOut,'corpusOut',d.portfolio.corpusOut);
