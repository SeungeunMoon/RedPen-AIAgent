"""LangChain 구조화 출력으로 광고에서 Claim을 생성한다."""

from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

from app.ai.llm import get_chat_model
from app.schemas.claim import ExtractionResult, TextSpan

PROMPT = Path(__file__).resolve().parents[1] / 'prompts/extract.txt'


async def extract_claims(ad_text: str, *, model: BaseChatModel | None = None) -> ExtractionResult:
    if not ad_text.strip():
        raise ValueError('광고 원문이 비어 있습니다')
    prompt = ChatPromptTemplate.from_messages([
        ('system', PROMPT.read_text(encoding='utf-8')),
        ('human', '{ad_text}'),
        ('human', '출력 검증 보완 지시: {feedback}'),
    ])
    llm = model if model is not None else get_chat_model('extract')
    chain = (prompt | llm.with_structured_output(ExtractionResult, method='json_schema')).with_config(
        {'run_name': 'extract_claims', 'tags': ['extract']})
    feedback = '첫 요청입니다.'
    for attempt in range(2):
        try:
            output = await chain.ainvoke({'ad_text': ad_text, 'feedback': feedback})
            data = output.model_dump() if isinstance(output, ExtractionResult) else output
            # 모델이 반환한 위치는 믿지 않고 원문에서 다시 계산한다.
            if isinstance(data, dict):
                for claim in data.get('claims', []):
                    claim['span'] = None
            result = ExtractionResult.model_validate(data)
            result.validate_source(ad_text)
            for claim in result.claims:
                start = ad_text.find(claim.quote)
                # 반복 문구는 첫 위치로 단정하지 않는다.
                if ad_text.find(claim.quote, start + 1) == -1:
                    claim.span = TextSpan(start=start, end=start + len(claim.quote))
            return result
        except (ValueError, ValidationError, OutputParserException):
            if attempt:
                raise
            feedback = '스키마와 원문 인용을 다시 확인하세요. 원문에 없는 구절이나 조건을 만들지 마세요.'
    raise RuntimeError('추출 재시도 종료')
