import math
import time
from fastapi import HTTPException
from sqlalchemy import select
from src.models import Dataset
from src.services.business import metadata
from src.utils.serialization import checksum
def create(db, data):
    name=data.name.strip()
    if len(name)<2: raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(Dataset).where(Dataset.name==name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')
    optional={c['key'] for c in metadata()['columns'] if c.get('optional')}
    label_rows=0
    for index,row in enumerate(data.records):
        for c in metadata()['columns']:
            key=c['key']; value=row.get(key)
            missing = value is None or value==''
            if missing and key in optional:
                continue
            if missing:
                raise HTTPException(422, f'第 {index+1} 行缺少字段 {c["label"]}')
            if c['type']=='number':
                try:
                    if isinstance(value,bool) or not math.isfinite(float(value)): raise ValueError()
                    row[key]=float(value)
                except (TypeError, ValueError, OverflowError): raise HTTPException(422, f'第 {index+1} 行 {c["label"]} 必须为有限数值')
        if row.get('renewed') not in (None, ''):
            label_rows += 1
            if row['renewed'] not in (0.0, 1.0):
                raise HTTPException(422, f'第 {index+1} 行 实际续读(1/0) 只能为 0 或 1')
    # 标签要么整批提供，要么整批省略：半标注批次无法判断哪些读者参与训练。
    if label_rows not in (0, len(data.records)):
        raise HTTPException(422, '续读标签必须整批提供或整批省略；半标注批次无法明确训练范围')
    d=Dataset(name=name, source=data.source, records=data.records, checksum=checksum(data.records), created_at=time.time())
    db.add(d); db.flush()
    return d
