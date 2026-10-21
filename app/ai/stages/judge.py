"""광고·클레임·규정·수치 대조를 컨텍스트로 전달해 미검증 1차 판정을 생성한다."""

import json
from pathlib import Path
from collections.abc import Sequence

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

from app.ai.llm import get_chat_model
from app.ai.errors import StageOutputError
from app.schemas.claim import ExtractionResult
from app.schemas.product import ProductSnapshot, RateComparison
from app.schemas.regulation import RegulationChunk
from app.schemas.verdict import JudgmentResult, VerificationResult


async def judge_ad(
    ad_text: str, extraction: ExtractionResult, regulations: Sequence[RegulationChunk],
    comparisons: Sequence[RateComparison], *, product: ProductSnapshot | None = None,
    model: BaseChatModel | None = None,
) -> JudgmentResult:
    extraction.validate_source(ad_text)
    claim_ids = {c.id for c in extraction.claims}
    if any(c.claim_id not in claim_ids for c in comparisons):
        raise ValueError('대조 결과가 알 수 없는 클레임을 참조합니다')
    evidence_ids = {r.chunk_id for r in regulations}
    context = json.dumps({
        'ad_text': ad_text, 'extraction': extraction.model_dump(mode='json'),
        'regulations': [r.model_dump(mode='json') for r in regulations],
        'comparisons': [c.model_dump(mode='json') for c in comparisons],
        'product': product.model_dump(mode='json') if product else None,
    }, ensure_ascii=False)
    prompt_text = (Path(__file__).resolve().parents[1] / 'prompts/judge.txt').read_text(encoding='utf-8')
    prompt = ChatPromptTemplate.from_messages([
        ('system', prompt_text), ('human', '{context}'), ('human', '출력 검증 보완 지시: {feedback}'),
    ])
    llm = model if model is not None else get_chat_model('judge')
    chain = (prompt | llm.with_structured_output(JudgmentResult, method='json_schema')).with_config(
        {'run_name': 'judge_ad', 'tags': ['judge']})
    feedback = '첫 요청입니다.'
    for attempt in range(2):
        try:
            output = await chain.ainvoke({'context': context, 'feedback': feedback})
            result = JudgmentResult.model_validate(output)
            ids = [v.id for v in result.verdicts]
            if len(ids) != len(set(ids)):
                raise ValueError('중복 판정 ID')
            for verdict in result.verdicts:
                if verdict.violation_type == 'missing_notice':
                    raise ValueError('체크리스트 미연결: 누락 판정은 아직 지원하지 않습니다')
                if verdict.claim_id not in claim_ids:
                    raise ValueError('알 수 없는 클레임 ID')
                verdict.validate_evidence(evidence_ids)
                if verdict.violation_type == 'disclosure_mismatch' and verdict.severity != 'needs_review':
                    related = [c for c in comparisons if c.claim_id == verdict.claim_id]
                    if not any(c.status == 'mismatch' and c.timing_status == 'aligned' for c in related):
                        raise ValueError('시점과 수치를 확인하지 못한 금리 판정은 사람 확인이 필요합니다')
                # LLM의 자체 검증 주장을 제거한다. 실제 검증은 아직 수행하지 않았다.
                verdict.verification = VerificationResult()
            return result
        except (ValueError, ValidationError, OutputParserException) as error:
            if attempt:
                raise StageOutputError(str(error)) from error
            feedback = '허용된 ID, 근거, 대조 상태를 다시 확인하세요. 확인되지 않은 금리 판정은 needs_review로 두세요.'
    raise RuntimeError('판정 재시도 종료')
