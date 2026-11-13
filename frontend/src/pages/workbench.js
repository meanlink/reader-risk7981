import {datasets,jobs} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
export async function workbench(){
 const [list,trials]=await Promise.all([datasets.list(),jobs.scoringTrials()]);workspace.datasets=list;workspace.trials=trials;
 const m=workspace.meta,labeled=list.filter(d=>d.labeled),unlabeled=list.filter(d=>!d.labeled);
 const threshold=m.parameters.find(p=>p.key==='threshold'),regularization=m.parameters.find(p=>p.key==='regularization');
 const disabled=session.user.role==='viewer';
 return heading('03 / ANALYSIS LAB',m.workbench_title,'带标签批次训练并独立验证；未标注批次沿用已批准试验的模型评分，不把待评分读者并入训练。')+'<div class="workbench-grid"><section class="panel"><form id="job-form"><label>分析任务名称<input name="name" required minlength="2" value="'+esc(m.name)+' · 复核试算"></label><label>分析方式<select name="mode" id="mode-select"><option value="evaluate">带标签评估（训练并验证）</option><option value="score" '+(unlabeled.length?'':'disabled')+'>复用已批准试验评分（未标注批次）</option></select></label><div id="evaluate-fields"><label>已标注数据批次<select name="dataset_id">'+labeled.map(d=>'<option value="'+d.id+'">'+esc(d.name)+' · '+d.rows+' 条</option>').join('')+'</select></label><p class="hint">'+(labeled.length?'训练与验证都来自该批次；续读标签用于计算AUC、精确率和召回率。':'尚无已标注批次，请先接入带续读标签的数据。')+'</p></div><div id="score-fields" hidden><label>已批准试验（训练来源）<select name="source_job_id">'+(trials.length?trials.map(t=>'<option value="'+t.id+'">'+esc(t.name)+' · 训练 '+(t.train_rows??'—')+' 条 · 阈值 '+esc(t.threshold)+'</option>').join(''):'<option value="">暂无可复用试验</option>')+'</select></label>'+(trials.length?'':'<p class="warning">尚无可复用试验：需要一位分析员先完成带标签评估，并由负责人批准。旧版本创建且缺少模型快照的试验会被明确拒绝评分。</p>')+'<label>未标注评分批次<select name="score_dataset_id">'+unlabeled.map(d=>'<option value="'+d.id+'">'+esc(d.name)+' · '+d.rows+' 条 · 无续读标签</option>').join('')+'</select></label><p class="hint">评分批次只用于计算风险概率与阈值名单，不参与训练，也不显示实际续读结果或验证成绩。</p></div><div class="parameter-grid"><label>'+esc(threshold.label)+'<input type="number" step="any" name="param-threshold" value="'+esc(threshold.default)+'" min="'+esc(threshold.min)+'" max="'+esc(threshold.max)+'" required></label><label id="regularization-field">'+esc(regularization.label)+'<input type="number" step="any" name="param-regularization" value="'+esc(regularization.default)+'" min="'+esc(regularization.min)+'" max="'+esc(regularization.max)+'" required></label></div><p class="hint" id="score-param-hint" hidden>评分沿用试验训练时的模型C，只能调整阈值；改阈值只改变进入复核的名单，不改变风险概率。</p><button type="submit" class="primary" '+(disabled?'':'')+'>'+esc(m.action_label)+' ↗</button><p class="hint">提交后由后台任务计算。观察员可查看参数和结果，无法提交。</p></form></section><section class="method-sheet"><p class="eyebrow">METHOD / BUSINESS RULE</p><h2>'+esc(m.method)+'</h2><p>'+esc(m.tagline)+'</p><h3>复用已批准试验</h3><p>'+esc(m.score_method)+'</p><h3>业务判读边界</h3><ul>'+m.limitations.map(v=>'<li>'+esc(v)+'</li>').join('')+'</ul><div class="method-trace"><span>输入</span><strong>'+esc(m.dataset_name)+'</strong><span>输出</span><strong>可复核结果 / 参数版本 / 分发归档</strong></div></section></div>';
}
function syncMode(){
 const mode=document.querySelector('#mode-select').value,score=mode==='score';
 document.querySelector('#evaluate-fields').hidden=score;document.querySelector('#score-fields').hidden=!score;
 document.querySelector('#regularization-field').hidden=score;document.querySelector('#score-param-hint').hidden=!score;
 const button=document.querySelector('#job-form [type=submit]');button.textContent=(score?workspace.meta.score_action_label||'沿用试验生成复核名单':workspace.meta.action_label||'执行分析')+' ↗';
 if(score)button.disabled=!workspace.trials.length||!document.querySelector('#score-fields select[name=score_dataset_id]')?.options.length;else button.disabled=false;
 const name=document.querySelector('[name=name]');name.value=score?workspace.meta.name+' · 未标注批次评分名单':workspace.meta.name+' · 复核试算';
}
export function bindWorkbench(){
 const form=document.querySelector('#job-form');document.querySelector('#mode-select').onchange=syncMode;
 const trialSelect=document.querySelector('#score-fields select[name=source_job_id]');
 trialSelect?.addEventListener('change',()=>{const t=workspace.trials.find(t=>String(t.id)===trialSelect.value);if(t&&t.threshold!=null)document.querySelector('[name=param-threshold]').value=t.threshold;});
 submit(form,async f=>{
   const mode=f.get('mode'),params={threshold:Number(f.get('param-threshold'))};
   if(mode==='evaluate')params.regularization=Number(f.get('param-regularization'));
   const payload={name:f.get('name'),mode,params};
   if(mode==='score'){payload.dataset_id=Number(f.get('score_dataset_id'));payload.source_job_id=Number(f.get('source_job_id'));}
   else payload.dataset_id=Number(f.get('dataset_id'));
   const j=await jobs.create(payload);workspace.selectedJob=j.id;notify(mode==='score'?'评分任务已提交，将沿用所选试验的模型':'分析任务已提交');location.hash='#/results/'+j.id;
 });
}
