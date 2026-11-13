from pydantic import BaseModel, Field
class JobInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    dataset_id: int
    mode: str = Field(default='evaluate', pattern='^(evaluate|score)$')
    source_job_id: int | None = None
    params: dict = Field(default_factory=dict)
