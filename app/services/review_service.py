"""검토 서비스 진입점. 업무 순서와 상태 관리는 LangGraph에 위임한다."""

from datetime import date

from langchain_core.language_models.chat_models import BaseChatModel

from app.ai.workflow import ReviewContext, build_review_graph
from app.kb.provider import RegulationProvider
from app.schemas.product import ProductSnapshot
from app.schemas.run import ReviewDraft

# 그래프 구조는 재사용하되 상태와 의존성은 매 호출마다 전달한다.
_graph = build_review_graph()


async def review_ad(
    ad_text: str, *, provider: RegulationProvider, as_of_date: date,
    product: ProductSnapshot | None = None, extract_model: BaseChatModel | None = None,
    judge_model: BaseChatModel | None = None,
) -> ReviewDraft:
    if not ad_text.strip():
        raise ValueError('광고 원문이 비어 있습니다')
    result = await _graph.ainvoke(
        {'ad_text': ad_text, 'as_of_date': as_of_date, 'product': product},
        context=ReviewContext(provider=provider, extract_model=extract_model, judge_model=judge_model),
        config={'run_name': 'review_ad_draft'},
    )
    return result['draft']
