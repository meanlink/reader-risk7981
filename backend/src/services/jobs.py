import time
from fastapi import HTTPException
from redis import Redis
from src.config.settings import REDIS_URL
from src.models import Dataset, Job
from src.services.business import metadata
from src.utils.serialization import dataset_label_state


def _normalized_params(mode, data_params):
    allowed = {p['key']: p for p in metadata().get('parameters', [])}
    if mode == 'score':
        # 评分只允许挑阈值；模型C来自已批准试验，不能在评分时改动。
        scoring = metadata().get('scoring', {}).get('parameter', 'threshold')
        unknown = set(data_params) - {scoring}
        if unknown:
            raise HTTPException(422, '评分沿用试验训练时的模型，只可调整风险阈值；模型C不能在此修改')
    elif set(data_params) - set(allowed):
        raise HTTPException(422, '包含未知分析参数')
    params = {k: p['default'] for k, p in allowed.items()}
    params.update({k: v for k, v in data_params.items() if k in params})
    for key, p in allowed.items():
        v = params[key]
        if p['type'] == 'number':
            try:
                v = float(v)
                if not (p.get('min', -1e9) <= v <= p.get('max', 1e9)):
                    raise ValueError()
                params[key] = v
            except (ValueError, TypeError):
                raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options', [])]:
            raise HTTPException(422, f'{p["label"]} 不是有效选项')
    return params


def _source_trial(db, source_job_id):
    j = db.get(Job, source_job_id) if source_job_id else None
    if not j:
        raise HTTPException(422, '请选择一个已完成且获批准的续读风险试验')
    if j.status != 'completed':
        raise HTTPException(409, '所选试验尚未完成计算，无法复用其模型')
    if not j.approved:
        raise HTTPException(409, '所选试验尚未获批准，不能用于评分')
    if (getattr(j, 'mode', None) or 'evaluate') != 'evaluate':
        raise HTTPException(409, '所选任务不是带标签评估试验，没有训练模型可供复用')
    if not getattr(j, 'model', None):
        raise HTTPException(409, '所选试验没有保存可复用的模型快照（可能由旧版本创建）；请重新运行一次带标签评估后再评分')
    return j


def create(db, data, user):
    dataset = db.get(Dataset, data.dataset_id)
    if not dataset:
        raise HTTPException(404, '数据批次不存在')
    mode = data.mode or 'evaluate'
    state = dataset_label_state(dataset.records)
    if mode == 'evaluate':
        if not state['labeled']:
            raise HTTPException(422, '该批次缺少续读标签，不能用于训练；请选用已批准试验给未标注批次评分')
        source_job_id = None
    elif mode == 'score':
        if state['labeled']:
            raise HTTPException(422, '评分批次应为未标注批次；该批次已有续读标签，请改用带标签评估')
        source = _source_trial(db, data.source_job_id)
        source_job_id = data.source_job_id
    else:
        raise HTTPException(422, '分析模式只能为 evaluate 或 score')
    params = _normalized_params(mode, data.params)
    if mode == 'score':
        # 记录实际沿用的模型C，避免参数页显示一个并未参与评分的默认值。
        try:
            params['regularization'] = float(source.model.get('C'))
        except (TypeError, ValueError):
            raise HTTPException(409, '所选试验的模型快照缺少模型C，无法评分；请重新运行一次带标签评估')
    j = Job(name=data.name, dataset_id=data.dataset_id, params=params, created_by=user.id, created_at=time.time(), status='queued', mode=mode, source_job_id=source_job_id)
    db.add(j)
    db.flush()
    return j


def trials(db):
    """可供评分的已批准试验：已完成、已批准、带标签评估且保存了模型快照。"""
    from sqlalchemy import select
    rows = db.scalars(select(Job).where(Job.status == 'completed', Job.approved == True, Job.mode == 'evaluate').order_by(Job.id.desc()).limit(100))
    items = []
    for j in rows:
        if not j.model:
            continue
        items.append({
            'id': j.id, 'name': j.name, 'dataset_id': j.dataset_id,
            'threshold': j.params.get('threshold'), 'regularization': j.params.get('regularization'),
            'train_rows': j.model.get('train_rows'), 'validation_rows': j.model.get('validation_rows'),
            'trained_at': j.model.get('trained_at'), 'finished_at': j.finished_at,
            'training_dataset': j.model.get('dataset'),
        })
    return items


def enqueue(job_id):
    try:
        r = Redis.from_url(REDIS_URL)
        r.rpush('analysis:queue', job_id)
        r.close()
    except Exception:
        pass  # SQL queued status is the durable fallback
