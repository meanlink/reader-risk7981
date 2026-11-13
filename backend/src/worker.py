import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import evaluate, score, evaluation_provenance
from src.services.reports import deliver
from src.services.audit import record
logging.basicConfig(level=logging.INFO)


def _dataset_meta(d):
    return {'id': d.id, 'name': d.name, 'checksum': d.checksum} if d else None


def execute(job_id):
    with Session() as db:
        j = db.get(Job, job_id)
        if not j or j.status != 'queued':
            return
        j.status = 'running'
        db.commit()
        try:
            d = db.get(Dataset, j.dataset_id)
            if d is None:
                raise ValueError('数据批次不存在，无法计算。')
            meta = _dataset_meta(d)
            mode = getattr(j, 'mode', None) or 'evaluate'
            if mode == 'score':
                source = db.get(Job, j.source_job_id) if j.source_job_id else None
                if not source or source.status != 'completed' or not source.approved:
                    raise ValueError('所选试验不再处于已批准状态，评分被拒绝；请重新选择已批准试验。')
                if not source.model:
                    raise ValueError('所选试验缺少模型快照，评分被拒绝；请重新运行一次带标签评估。')
                result = score(d.records, source.model, j.params, meta,
                               {'id': source.id, 'name': source.name})
                j.model = None
            else:
                trained = evaluate(d.records, j.params)
                result = trained['result']
                model = dict(trained['model'])
                model['dataset'] = meta
                j.model = model
                result['provenance'] = evaluation_provenance(j.id, j.name, meta, j.params, model)
            j.result = result
            j.status = 'completed'
            j.finished_at = time.time()
            json.dumps(j.result, ensure_ascii=False, allow_nan=False)
            record(db, 'worker', 'job.completed', {'id': j.id, 'mode': mode, 'source_job_id': j.source_job_id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status = 'failed'
            j.error = str(e)[:990]
            j.finished_at = time.time()
            record(db, 'worker', 'job.failed', {'id': j.id, 'error': j.error})
        db.commit()


def tick():
    with Session() as db:
        queued = list(db.scalars(select(Job.id).where(Job.status == 'queued').limit(3)))
    for job_id in queued:
        execute(job_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled == True, Report.next_run <= time.time())):
            d = deliver(db, r)
            if d:
                record(db, 'worker', 'report.delivered', {'id': r.id, 'delivery': d.id})
        db.commit()


def main():
    r = Redis.from_url(REDIS_URL, socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status == 'running')):
            j.status = 'queued'
            record(db, 'worker', 'job.recovered', {'id': j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item = r.blpop('analysis:queue', timeout=1)
            if item:
                execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry')
            time.sleep(2)


if __name__ == '__main__':
    main()
