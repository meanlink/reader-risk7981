import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from src.models import Job, Report, Delivery
from src.config.settings import ARTIFACT_DIR
from src.utils.serialization import provenance_of

# 明细导出附带的来源列，供结果页与下载核对训练来源、评分批次与所用阈值。
PROVENANCE_COLUMNS = [
    ('训练来源任务', 'training_job_name'), ('训练来源批次', 'training_dataset_name'),
    ('评分批次', 'scoring_dataset_name'), ('评分批次指纹', 'scoring_dataset_checksum'), ('所用阈值', 'threshold'),
]


def _safe(v):
    if isinstance(v,(int,float)) and not isinstance(v,bool): return v
    text=str(v)
    return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text


def detail_csv(job, provenance):
    """结果明细 CSV：评分任务不含实际结果列；来源与阈值逐行附带。"""
    provenance = {k:v for k,v in (provenance or {}).items() if v is not None}
    out=io.StringIO(); out.write('﻿')
    table=(job.result or {}).get('table',{})
    cols=table.get('columns',[])
    writer=csv.writer(out)
    writer.writerow([_safe(c['label']) for c in cols]+[_safe(label) for label,_ in PROVENANCE_COLUMNS])
    for row in table.get('rows',[]):
        writer.writerow([_safe(row.get(c['key'],'')) for c in cols]+[_safe(provenance.get(key,'')) for _,key in PROVENANCE_COLUMNS])
    return out.getvalue().encode('utf-8')


def provenance_document(job, provenance):
    result = job.result or {}
    return {
        'job': job.name, 'dataset_id': job.dataset_id,
        'mode': (getattr(job,'mode',None) or 'evaluate'),
        'params': job.params, 'provenance': provenance,
        'result': result,
        'checksum': hashlib.sha256(json.dumps({'provenance': provenance, 'result': result}, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
    }


def create(db, data):
    j=db.get(Job,data.job_id)
    if not j or j.status!='completed' or not j.approved:
        raise HTTPException(409,'请先选择已完成且获批准的分析结果')
    if (getattr(j,'mode',None) or 'evaluate')=='score':
        raise HTTPException(409,'评分名单缺少实际续读结果，不能作为已批准分析分发；如需归档请使用结果明细下载')
    r=Report(name=data.name, job_id=j.id, destination=data.destination, interval_seconds=data.interval_seconds, next_run=time.time()+data.delay_seconds, enabled=True)
    db.add(r); db.flush()
    return r


def deliver(db, report):
    j=db.get(Job,report.job_id)
    if not j or not j.approved: return
    provenance={k:v for k,v in provenance_of(j).items() if v is not None}
    data=detail_csv(j, provenance)
    delivery=Delivery(report_id=report.id, created_at=time.time(), checksum=hashlib.sha256(data).hexdigest(), filename='', destination=report.destination)
    db.add(delivery); db.flush()
    delivery.filename=f'report-{report.id}-delivery-{delivery.id}.csv'
    os.makedirs(ARTIFACT_DIR,exist_ok=True)
    with open(os.path.join(ARTIFACT_DIR,delivery.filename),'wb') as f:f.write(data)
    with open(os.path.join(ARTIFACT_DIR,delivery.filename+'.json'),'w') as f: json.dump({'job':j.name,'dataset_id':j.dataset_id,'mode':getattr(j,'mode',None) or 'evaluate','params':j.params,'provenance':provenance,'result':j.result,'checksum':delivery.checksum},f,ensure_ascii=False,allow_nan=False)
    report.next_run=time.time()+report.interval_seconds
    return delivery
