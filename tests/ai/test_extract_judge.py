"""모델 출력만 대역으로 제공. 실제 LangChain 프롬프트·서비스 연결을 검증한다."""

import asyncio
import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
from langchain_core.runnables import RunnableLambda

from app.ai.stages.extract import extract_claims
from app.ai.stages.judge import ModelJudgmentResult, judge_ad
from app.kb.empty import EmptyRegulationProvider
from app.kb.fixed import FixedRegulationProvider
from app.services.review_service import review_ad
from app.schemas.claim import ExtractionResult

ROOT = Path(__file__).resolve().parents[2]
AD = '12개월 정기예금, 세전 최고 연 4.5%. 누구나 보장.'


def test_generation_schema_requires_evidence_for_supported_verdict():
    definitions = ModelJudgmentResult.model_json_schema()['$defs']
    supported = definitions['SupportedVerdict']
    assert 'evidence_ids' in supported['required']
    assert supported['properties']['evidence_ids']['minItems'] == 1
    assert definitions['NeedsReviewVerdict']['properties']['suggested_revision']['type'] == 'null'


def extraction():
    return {'claims':[
        {'id':'c1','quote':'최고 연 4.5%','kind':'interest_rate',
         'rate':{'rate':'4.5','rate_kind':'max','term_months':12,'tax_basis':'before_tax'}},
        {'id':'c2','quote':'누구나 보장','kind':'guarantee'},
    ],'ad_status':'advertisement','ad_status_reason':'합성 테스트 광고'}


def fake_model(outputs, captured):
    model = Mock()
    responses = iter(outputs)
    def structured(schema, **kwargs):
        assert kwargs['method'] == 'json_schema'
        async def respond(prompt):
            captured.append(prompt.to_messages())
            return schema.model_validate(next(responses))
        return RunnableLambda(respond)
    model.with_structured_output.side_effect = structured
    return model


def test_extraction_uses_source_and_code_generated_spans():
    captured=[]
    result=asyncio.run(extract_claims(AD,model=fake_model([extraction()],captured)))
    assert result.claims[0].rate.term_months == 12
    assert AD[result.claims[0].span.start:result.claims[0].span.end] == '최고 연 4.5%'
    assert AD in captured[0][1].content


def test_hallucinated_quote_retries_then_rejects():
    raw=extraction();raw['claims'][0]['quote']='원문에 없는 문구'
    captured=[]
    with pytest.raises(ValueError,match='원문에 없는'):
        asyncio.run(extract_claims(AD,model=fake_model([raw,raw],captured)))
    assert len(captured) == 2


def test_repeated_quote_does_not_guess_position():
    captured=[]
    result=asyncio.run(extract_claims(AD+' 최고 연 4.5%',model=fake_model([extraction()],captured)))
    assert result.claims[0].span is None


def test_pipeline_uses_extracted_claims_in_comparison_and_context():
    extracted_calls=[];judged_calls=[]
    result=asyncio.run(review_ad(AD,provider=EmptyRegulationProvider(),as_of_date=date(2026,10,21),
        extract_model=fake_model([extraction()],extracted_calls),
        judge_model=fake_model([{'verdicts':[]}],judged_calls)))
    assert result.comparisons[0].claim_id == 'c1'
    assert result.comparisons[0].status == 'skipped'
    context=json.loads(judged_calls[0][1].content)
    assert context['ad_text'] == AD
    assert context['extraction']['claims'][0]['rate']['rate'] == '4.5'
    assert context['comparisons'][0]['status'] == 'skipped'
    assert result.verification_status == 'not_performed'


def test_judge_receives_real_fixed_evidence_and_rejects_invented_id():
    provider=FixedRegulationProvider.from_law_sample(ROOT/'samples/law/20261021T004141864078Z_article.json')
    ext=ExtractionResult.model_validate(extraction())
    rules=asyncio.run(provider.provide(ext.claims,as_of_date=date(2026,10,21)))
    bad={'verdicts':[dict(id='v1',claim_id='c2',violation_type='misleading_guarantee',
        severity='caution',reason='합성 판정',evidence_ids=['invented'])]}
    captured=[]
    with pytest.raises(ValueError,match='근거 ID'):
        asyncio.run(judge_ad(AD,ext,rules,[],model=fake_model([bad,bad],captured)))
    assert json.loads(captured[0][1].content)['regulations'][0]['chunk_id'] == rules[0].chunk_id
    assert 'version_id' not in json.loads(captured[0][1].content)['regulations'][0]
    assert rules[0].text == json.loads(captured[0][1].content)['regulations'][0]['text']


def test_llm_cannot_self_certify_verification():
    ext=ExtractionResult.model_validate(extraction())
    output={'verdicts':[dict(id='v1',claim_id='c2',violation_type='misleading_guarantee',
        severity='needs_review',reason='합성 판정',verification={
            'source_exists':'passed','wording_matches':'passed',
            'version_matches':'passed','supports_verdict':'passed'})]}
    result=asyncio.run(judge_ad(AD,ext,[],[],model=fake_model([output],[])))
    assert not result.verdicts[0].verification.passed


def test_unknown_claim_id_is_rejected():
    ext=ExtractionResult.model_validate(extraction())
    output={'verdicts':[dict(id='v1',claim_id='unknown',violation_type='exaggeration',
                            severity='needs_review',reason='합성 판정')]}
    with pytest.raises(ValueError,match='클레임 ID'):
        asyncio.run(judge_ad(AD,ext,[],[],model=fake_model([output,output],[])))


def test_pipeline_compares_extracted_rate_with_real_sample():
    from datetime import datetime
    from app.schemas.external.disclosure import DisclosureResponse
    from mcp_servers.fin_disclosure.normalize import normalize_products
    path=ROOT/'samples/disclosure/20261021T004135705571Z_deposit.json'
    meta=json.loads(path.with_suffix('.meta.json').read_text())
    products=normalize_products(DisclosureResponse.from_json(path.read_text()),product_type='deposit',
        fetched_at=datetime.fromisoformat(meta['fetched_at']),source_url=meta['endpoint'])
    captured=[]
    result=asyncio.run(review_ad(AD,provider=EmptyRegulationProvider(),as_of_date=date(2026,10,21),
        product=products[0],extract_model=fake_model([extraction()],[]),
        judge_model=fake_model([{'verdicts':[]}],captured)))
    assert result.comparisons[0].status in ('match','mismatch')
    assert result.comparisons[0].advertised_rate == result.extraction.claims[0].rate.rate
    context=json.loads(captured[0][1].content)
    assert context['product']['preferential_conditions'] == products[0].preferential_conditions
    assert context['comparisons'][0]['selected_option_id']
