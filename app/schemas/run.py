"""검토 실행의 반환 계약. 최종 검증 전 결과임을 명시한다."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.claim import ExtractionResult
from app.schemas.product import RateComparison
from app.schemas.regulation import RegulationChunk
from app.schemas.verdict import JudgmentResult
from app.schemas.task import ReviewTask, TaskEvent


class ReviewDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    extraction: ExtractionResult | None = None
    regulations: list[RegulationChunk]
    comparisons: list[RateComparison]
    judgment: JudgmentResult | None = None
    verification_status: Literal['not_performed'] = 'not_performed'
    run_status: Literal['completed', 'partial', 'failed'] = 'completed'
    tasks: list[ReviewTask] = Field(default_factory=list)
    events: list[TaskEvent] = Field(default_factory=list)
