"""광고·클레임·규정·수치 대조를 컨텍스트로 전달해 미검증 1차 판정을 생성한다."""

import json
from pathlib import Path
from collections.abc import Sequence
from typing import Literal

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.ai.llm import get_chat_model
from app.ai.errors import StageOutputError, output_failure
from app.schemas.claim import ExtractionResult
from app.schemas.product import ProductSnapshot, RateComparison
from app.schemas.regulation import RegulationChunk
from app.schemas.verdict import ClaimVerdict, JudgmentResult, VerificationResult
from app.schemas.regulation import NonBlankText


class ModelClaimVerdict(BaseModel):
    """모델 출력 계약. 내부 판정의 참조 정합성은 변환 단계에서 처리한다."""
    model_config = ConfigDict(extra='forbid')
    id: NonBlankText
    claim_id: NonBlankText
    checklist_item_id: NonBlankText | None = None
    violation_type: Literal['disclosure_mismatch', 'exaggeration', 'misleading_guarantee']
    severity: Literal['potential_violation', 'caution', 'needs_review']
    reason: NonBlankText
    evidence_ids: list[NonBlankText] = Field(default_factory=list)
    suggested_revision: NonBlankText | None = None
    verification: VerificationResult = Field(default_factory=VerificationResult)

    @field_validator('evidence_ids',mode='before')
    @classmethod
    def deduplicate_evidence(cls,value):
        return list(dict.fromkeys(value)) if isinstance(value,list) and all(isinstance(v,str) for v in value) else value


class SupportedVerdict(ModelClaimVerdict):
    """Pydantic 사후 검사뿐 아니라 생성 JSON 스키마에도 근거 필수를 표현한다."""
    severity: Literal['potential_violation', 'caution']
    evidence_ids: list[NonBlankText] = Field(min_length=1)


class NeedsReviewVerdict(ModelClaimVerdict):
    severity: Literal['needs_review']
    suggested_revision: None = None


class ModelJudgmentResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    verdicts: list[SupportedVerdict | NeedsReviewVerdict]


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
        'allowed_claim_ids': sorted(claim_ids),
        'allowed_evidence_ids': sorted(evidence_ids),
        # 버전·출처의 전체 메타데이터는 최종 리포트에 보존한다.
        # 모델에는 근거 ID, 위치, 시행일과 인용 원문 위주로 전달해 문맥 예산을 아낀다.
        'regulations': [r.model_dump(mode='json', include={
            'chunk_id','law_name','article_no','paragraph_no','title','text','effective_from',
        }) for r in regulations],
        'comparisons': [c.model_dump(mode='json') for c in comparisons],
        'product': product.model_dump(mode='json') if product else None,
    }, ensure_ascii=False)
    prompt_text = (Path(__file__).resolve().parents[1] / 'prompts/judge.txt').read_text(encoding='utf-8')
    prompt = ChatPromptTemplate.from_messages([
        ('system', prompt_text), ('human', '{context}'), ('human', '출력 검증 보완 지시: {feedback}'),
    ])
    llm = model if model is not None else get_chat_model('judge')
    chain = (prompt | llm.with_structured_output(ModelJudgmentResult, method='json_schema', include_raw=True)).with_config(
        {'run_name': 'judge_ad', 'tags': ['judge']})
    feedback = '첫 요청입니다.'
    for attempt in range(2):
        raw_output = None
        try:
            output = await chain.ainvoke({'context': context, 'feedback': feedback})
            if isinstance(output, dict) and 'parsed' in output:
                raw_output = getattr(output.get('raw'), 'content', None)
                if output.get('parsing_error') is not None:
                    raise output['parsing_error']
                output = output['parsed']
            result = ModelJudgmentResult.model_validate(output)
            ids = [v.id for v in result.verdicts]
            if len(ids) != len(set(ids)):
                raise ValueError('중복 판정 ID')
            verdicts = []
            for verdict in result.verdicts:
                if verdict.violation_type == 'missing_notice':
                    raise ValueError('체크리스트 미연결: 누락 판정은 아직 지원하지 않습니다')
                if verdict.claim_id not in claim_ids:
                    raise ValueError('알 수 없는 클레임 ID')
                original_severity = verdict.severity
                data = verdict.model_dump()
                unresolved = [identifier for identifier in verdict.evidence_ids if identifier not in evidence_ids]
                valid = [identifier for identifier in verdict.evidence_ids if identifier in evidence_ids]
                verification = VerificationResult()
                if unresolved:
                    data['severity'] = 'needs_review'
                    data['suggested_revision'] = None
                    verification = VerificationResult(source_exists='unavailable',
                        reason='검색 결과에 없는 근거 ID가 포함돼 있어 사람 확인이 필요합니다.')
                if verdict.violation_type == 'disclosure_mismatch' and data['severity'] != 'needs_review':
                    related = [c for c in comparisons if c.claim_id == verdict.claim_id]
                    if not any(c.status == 'mismatch' and c.timing_status == 'aligned' for c in related):
                        raise ValueError('시점과 수치를 확인하지 못한 금리 판정은 사람 확인이 필요합니다')
                # LLM의 자체 검증 주장을 제거한다. 실제 검증은 아직 수행하지 않았다.
                verdicts.append(ClaimVerdict.model_validate({
                    **data, 'evidence_ids':valid,
                    'unresolved_evidence_ids':unresolved,
                    'original_severity':original_severity if unresolved else None,
                    'verification':verification,
                }))
            return JudgmentResult(verdicts=verdicts)
        except (ValueError, ValidationError, OutputParserException) as error:
            if attempt:
                raise output_failure('judge', error, raw_output=raw_output) from error
            feedback = (StageOutputError(str(error)).public_reason +
                        ' 허용된 ID와 대조 상태를 확인하세요. needs_review이면 suggested_revision은 반드시 null입니다.')
    raise RuntimeError('판정 재시도 종료')
