"""그래프의 직렬화 가능한 데이터. 모델·provider 객체는 런타임에 주입한다."""

from datetime import date
from typing import NotRequired, TypedDict

from app.schemas.claim import ExtractionResult
from app.schemas.product import ProductSnapshot, RateComparison
from app.schemas.regulation import RegulationChunk
from app.schemas.run import ReviewDraft
from app.schemas.verdict import JudgmentResult
from app.schemas.task import ReviewTask, TaskEvent


class ReviewInput(TypedDict):
    ad_text: str
    as_of_date: date
    product: ProductSnapshot | None


class ReviewOutput(TypedDict):
    draft: ReviewDraft


class ReviewState(ReviewInput):
    tasks: NotRequired[list[ReviewTask]]
    events: NotRequired[list[TaskEvent]]
    tasks_prepared: NotRequired[bool]
    active_task_id: NotRequired[str | None]
    next_node: NotRequired[str]
    dispatch_count: NotRequired[int]
    extraction: NotRequired[ExtractionResult]
    regulations: NotRequired[list[RegulationChunk]]
    comparisons_by_claim: NotRequired[dict[str, RateComparison]]
    judgment: NotRequired[JudgmentResult]
    draft: NotRequired[ReviewDraft]
