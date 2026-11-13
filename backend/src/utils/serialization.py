import hashlib, json

PROVENANCE_KEYS = [
    'mode', 'model_reused', 'training_job_id', 'training_job_name', 'training_dataset_id',
    'training_dataset_name', 'training_dataset_checksum', 'training_rows', 'validation_rows',
    'model_trained_at', 'scoring_scope', 'scoring_dataset_label', 'scoring_dataset_id', 'scoring_dataset_name', 'scoring_dataset_checksum',
    'scored_rows', 'threshold', 'regularization', 'features',
]


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def dataset_label_state(records):
    rows = records or []
    labeled = sum(1 for row in rows if row.get('renewed') not in (None, ''))
    return {'labeled': bool(rows) and labeled == len(rows), 'labeled_rows': labeled, 'unlabeled_rows': len(rows) - labeled}


def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at, **dataset_label_state(d.records)}


def provenance_of(job, dataset=None):
    """结果与下载共用的可核对来源：训练来源、评分批次、所用阈值。

    新任务把来源写入 result.provenance；旧任务没有快照时只回退到可确定的字段，
    不虚构模型来源、实际续读结果或验证成绩。
    """
    result = job.result or {}
    saved = result.get('provenance') or {}
    mode = saved.get('mode') or getattr(job, 'mode', None) or 'evaluate'
    data = {k: saved.get(k) for k in PROVENANCE_KEYS}
    data['mode'] = mode
    data['threshold'] = saved.get('threshold', (job.params or {}).get('threshold'))
    data['regularization'] = saved.get('regularization', (job.params or {}).get('regularization'))
    data['training_job_id'] = saved.get('training_job_id', getattr(job, 'source_job_id', None) if mode == 'score' else job.id)
    data['scoring_dataset_id'] = saved.get('scoring_dataset_id', job.dataset_id)
    if dataset is not None and dataset.id == data.get('scoring_dataset_id'):
        data.setdefault('scoring_dataset_name', None)
        data['scoring_dataset_name'] = data['scoring_dataset_name'] or dataset.name
        data['scoring_dataset_checksum'] = data['scoring_dataset_checksum'] or dataset.checksum
    data['model_snapshot'] = bool(saved) or bool(getattr(job, 'model', None))
    return data


def job_dict(job, dataset=None):
    data = {k:getattr(job,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
    data['mode'] = getattr(job,'mode',None) or 'evaluate'
    data['source_job_id'] = getattr(job,'source_job_id',None)
    data['has_model'] = bool(getattr(job,'model',None))
    data['provenance'] = provenance_of(job, dataset)
    return data


def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}


def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
