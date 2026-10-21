"""초기 순차 실행: 추출 → 규정 제공 → 수치 대조 → 미검증 판정."""

from datetime import date

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, ConfigDict

from app.ai.stages.extract import extract_claims
from app.ai.stages.factcheck import compare_rate
from app.ai.stages.judge import JudgmentResult, judge_ad
from app.kb.provider import RegulationProvider
from app.schemas.claim import ExtractionResult
from app.schemas.product import ProductSnapshot, RateComparison
from app.schemas.regulation import RegulationChunk


class ReviewDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    extraction: ExtractionResult
    regulations: list[RegulationChunk]
    comparisons: list[RateComparison]
    judgment: JudgmentResult
    verification_status: str = 'not_performed'


async def review_ad(
    ad_text: str, *, provider: RegulationProvider, as_of_date: date,
    product: ProductSnapshot | None = None, extract_model: BaseChatModel | None = None,
    judge_model: BaseChatModel | None = None,
) -> ReviewDraft:
    async def run(text: str) -> ReviewDraft:
        extraction = await extract_claims(text, model=extract_model)
        regulations = await provider.provide(extraction.claims, as_of_date=as_of_date)
        comparisons = [compare_rate(c, product, as_of_date=as_of_date)
                       for c in extraction.claims if c.kind == 'interest_rate']
        judgment = await judge_ad(text, extraction, regulations, comparisons,
                                  product=product, model=judge_model)
        return ReviewDraft(extraction=extraction, regulations=regulations,
                           comparisons=comparisons, judgment=judgment)
    return await RunnableLambda(run).with_config({'run_name': 'review_ad_draft'}).ainvoke(ad_text)
