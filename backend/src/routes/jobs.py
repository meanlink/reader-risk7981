import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from src.config.database import get_db
from src.models import Dataset, Job
from src.schemas.job import JobInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import jobs
from src.services.audit import record
from src.services.reports import detail_csv, provenance_document
from src.utils.serialization import job_dict, provenance_of
router=APIRouter(prefix='/jobs')
def _with_dataset(db, j):
    return job_dict(j, db.get(Dataset, j.dataset_id) if j else None)
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [_with_dataset(db,j) for j in db.scalars(select(Job).order_by(Job.id.desc()).limit(100))]
@router.get('/scoring-trials')
def scoring_trials(db=Depends(get_db),u=Depends(current_user)):
    return jobs.trials(db)
@router.post('',status_code=201)
def create(data:JobInput,db=Depends(get_db),u=Depends(can_write)):
    j=jobs.create(db,data,u); record(db,u.email,'job.create',{'id':j.id,'mode':j.mode,'source_job_id':j.source_job_id,'params':j.params})
    db.commit(); jobs.enqueue(j.id); return _with_dataset(db,j)
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    return _with_dataset(db,j)
@router.get('/{id}/export')
def export(id:int,format:str='csv',db=Depends(get_db),u=Depends(current_user)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    if j.status!='completed': raise HTTPException(409,'结果尚未完成，无法下载明细')
    if format not in ('csv','json'): raise HTTPException(422,'支持 CSV 或 JSON')
    provenance={k:v for k,v in provenance_of(j, db.get(Dataset, j.dataset_id)).items() if v is not None}
    if format=='json':
        body=json.dumps(provenance_document(j,provenance),ensure_ascii=False,allow_nan=False)
        return Response(body,media_type='application/json',headers={'Content-Disposition':f'attachment; filename="job-{j.id}-detail.json"'})
    return Response(detail_csv(j,provenance),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="job-{j.id}-detail.csv"'})
@router.post('/{id}/approve')
def approve(id:int,db=Depends(get_db),u=Depends(admin_only)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    if j.status!='completed':raise HTTPException(409,'仅已完成结果可以批准')
    if (getattr(j,'mode',None) or 'evaluate')=='score':
        raise HTTPException(409,'评分名单只是未标注批次的复核建议，没有实际续读结果可供批准为业务结论')
    j.approved=True; record(db,u.email,'job.approve',{'id':id}); db.commit()
    return _with_dataset(db,j)
