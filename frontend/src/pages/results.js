import {jobs} from '../api/entities.js';
import {downloadJob} from '../api/client.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {chart} from '../components/common/chart.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {esc,fmt,date,notify} from '../utils/dom.js';

function sourceCard(p, j){
 if(!p)return '';
 const name=(v,id)=>v||(id==null?'未记录':('#'+id));
 const scope=p.mode==='score'?'独立评分批次':(p.scoring_scope==='validation_split'?'验证留出子集':'未记录');
 const rows=[
   ['训练来源试验', name(p.training_job_name,p.training_job_id)],
   ['训练来源批次', name(p.training_dataset_name,p.training_dataset_id)],
   ['训练 / 验证样本', (p.training_rows??'—')+' / '+(p.validation_rows??'—')],
   ['评分批次', name(p.scoring_dataset_name,p.scoring_dataset_id)+' · '+scope],
   ['评分批次样本', p.scored_rows??'—'],
   ['所用阈值', fmt(p.threshold)],
   ['模型C', fmt(p.regularization)],
 ];
 const legacy=p.mode==='evaluate'&&p.model_snapshot===false;
 return '<section class="panel provenance"><div class="section-title"><h2>训练来源与评分批次</h2><span>'+(p.mode==='score'?'沿用试验模型 · 未重新训练':legacy?'旧版本结果 · 原评估保留':'本次训练并验证')+'</span></div><div class="provenance-grid">'+rows.map(([k,v])=>'<div><span>'+esc(k)+'</span><strong>'+esc(v)+'</strong></div>').join('')+'</div>'+(p.mode==='score'?'<p class="hint">评分批次不参与训练；该名单没有实际续读结果，因此不显示实际结果、AUC、精确率或召回率。阈值只改变名单，风险概率由所沿用的模型固定。</p>':'<p class="hint">验证成绩只来自本批次分层留出的验证子集，不是另一下游批次；评分模式才会出现独立的评分批次。</p>')+(legacy?'<p class="warning">该结果由旧版本生成，升级后原评估仍可查看和下载，但没有保存可复用的模型快照，因此不能选作评分来源；如要评分请重新运行一次带标签评估并批准。</p>':'')+'<p class="hint">'+(p.mode==='score'?'本页与下载明细都会标注训练来源、评分批次和所用阈值；离线 JSON 另含评分字段口径。':'离线明细下载包含训练来源、评分批次与阈值，可与结果页逐项核对。')+'</p></section>';
}
export async function results(id){
 workspace.jobs=await jobs.list();const j=id?await jobs.get(id):(workspace.jobs.find(j=>j.id===workspace.selectedJob)||workspace.jobs[0]);
 if(j&&!workspace.jobs.some(x=>x.id===j.id))workspace.jobs.push(j);
 if(!j)return heading('04 / REVIEW','结果复核','尚无分析结果。')+'<div class="empty">先到分析工作台，选择批次并提交一次计算。<a href="#/workbench">前往工作台 ↗</a></div>';
 workspace.selectedJob=j.id;const r=j.result||{},p=j.provenance||r.provenance,scoring=(j.mode||p?.mode)==='score';
 const approval=scoring?'评分名单 · 仅供复核，不分发':(j.approved?'已获业务批准':'待负责人复核');
  return heading('04 / REVIEW','结果复核与业务解释',j.name,'<div class="heading-actions"><button class="button" id="refresh-results">刷新结果 ↻</button>'+(j.status==='completed'?'<button class="button" id="export-csv">明细 CSV ↓</button><button class="button" id="export-json">来源 JSON ↓</button>':'')+'</div>')+'<div class="result-selector"><label>分析记录<select id="select-job">'+workspace.jobs.map(x=>'<option value="'+x.id+'" '+(x.id===j.id?'selected':'')+'>'+esc(x.name)+' · '+esc(x.status)+'</option>').join('')+'</select></label>'+status(j.status)+'<span>'+date(j.created_at)+'</span><span class="approval">'+esc(approval)+'</span><span>'+(scoring?'评分模式':'评估模式')+'</span></div>'+(j.status==='completed'?'<section class="result-lead"><p class="eyebrow">COMPUTED FINDING</p><h2>'+esc(r.summary)+'</h2><div class="metrics">'+(r.metrics||[]).map(m=>'<div><span>'+esc(m.label)+'</span><strong>'+esc(fmt(m.value))+'<small>'+esc(m.unit||'')+'</small></strong></div>').join('')+'</div></section>'+sourceCard(p,j)+'<section class="panel">'+chart(r.chart)+'</section><div class="two-columns"><section class="panel"><div class="section-title"><h2>业务解释</h2><span>由计算结果生成</span></div><ol class="questions">'+(r.findings||[]).map(v=>'<li>'+esc(v)+'</li>').join('')+'</ol>'+(r.warnings||[]).map(v=>'<p class="warning">'+esc(v)+'</p>').join('')+'</section><section class="method-sheet compact"><p class="eyebrow">REPRODUCIBILITY</p><h3>计算口径与参数</h3><p>'+esc(r.method)+'</p><pre>'+esc(JSON.stringify(j.params,null,2))+'</pre>'+(session.user.role==='admin'&&!j.approved&&!scoring?'<button class="primary" id="approve-job">批准此业务结论</button>':'')+'<p class="hint">'+(scoring?'评分名单没有实际续读结果，不能批准为业务结论，也不能建立分发计划。':'仅批准结果可进入定时分发档案。')+'</p></section></div><section class="panel"><div class="section-title"><h2>结果明细</h2><span>'+(r.table?.rows?.length||0)+' 行'+(scoring?' · 无实际结果列':'')+'</span></div>'+table(r.table?.columns||[],r.table?.rows||[])+'</section>':'<section class="panel empty">'+(j.status==='failed'?'计算失败：'+esc(j.error)+'。请返回工作台调整参数或数据。':'后台正在执行计算。点击刷新结果查看最新进展。')+'<a href="#/workbench">返回工作台 ↗</a></section>');
}
export function bindResults(refresh){document.querySelector('#refresh-results')?.addEventListener('click',refresh);document.querySelector('#export-csv')?.addEventListener('click',()=>downloadJob(workspace.selectedJob,'csv').catch(e=>notify(e.message,true)));document.querySelector('#export-json')?.addEventListener('click',()=>downloadJob(workspace.selectedJob,'json').catch(e=>notify(e.message,true)));document.querySelector('#select-job')?.addEventListener('change',e=>{workspace.selectedJob=Number(e.target.value);location.hash='#/results/'+e.target.value;});document.querySelector('#approve-job')?.addEventListener('click',async()=>{try{await jobs.approve(workspace.selectedJob);notify('已批准，可创建分发计划');await refresh();}catch(e){notify(e.message,true);}});}
