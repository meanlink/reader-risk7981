from sqlalchemy import String, JSON, Double, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    # evaluate：带标签训练与验证；score：复用已批准试验训练时的模型给未标注批次评分
    mode: Mapped[str] = mapped_column(String(20), default='evaluate')
    source_job_id: Mapped[int | None] = mapped_column(ForeignKey('jobs.id'), nullable=True)
    # 模型快照只在带标签训练时写入；评分任务不重新训练，也不保存新模型
    model: Mapped[dict | None] = mapped_column(JSON, nullable=True)
