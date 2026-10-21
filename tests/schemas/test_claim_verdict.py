from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.claim import Claim, ExtractionResult
from app.schemas.product import RateComparison
from app.schemas.verdict import Verdict


def test_claim_source_and_unknown_conditions():
    quote='최고 연 4.5%'
    claim=Claim(id='c1',quote=quote,kind='interest_rate',rate={'rate':'4.5','rate_kind':'max'})
    assert claim.rate.rate == Decimal('4.5')
    assert claim.rate.term_months is None
    result=ExtractionResult(claims=[claim],ad_status='advertisement',ad_status_reason='합성 테스트')
    result.validate_source(quote)
    with pytest.raises(ValueError, match='원문에 없는'):
        result.validate_source('다른 문안')


def test_missing_notice_does_not_need_fake_claim():
    verdict=Verdict(id='v1',checklist_item_id='required1',violation_type='missing_notice',
                    severity='caution',reason='합성 누락 판정',evidence_ids=['r1'])
    assert verdict.claim_id is None
    with pytest.raises(ValueError, match='검색 결과'):
        verdict.validate_evidence({'r2'})


@pytest.mark.parametrize('updates',[
    {'suggested_revision':'확정 수정안'},
    {'severity':'caution'},
])
def test_ungrounded_verdict_or_review_revision_rejected(updates):
    data=dict(id='v1',claim_id='c1',violation_type='exaggeration',severity='needs_review',reason='확인 필요')
    with pytest.raises(ValidationError):
        Verdict(**{**data,**updates})


def test_verification_failure_requires_downgrade():
    with pytest.raises(ValidationError, match='강등'):
        Verdict(id='v1',claim_id='c1',violation_type='exaggeration',severity='caution',
                reason='합성 판정',evidence_ids=['r1'],verification={'supports_verdict':'failed'})


def test_comparison_uses_percentage_points():
    comparison=RateComparison(claim_id='c1',status='mismatch',selected_option_id='o1',
        advertised_rate='4.5',disclosed_rate='3.8',difference_pp='0.7',reason='합성 금리 비교')
    assert comparison.difference_pp == Decimal('0.7')
    with pytest.raises(ValidationError):
        RateComparison(**{**comparison.model_dump(),'difference_pp':'0.6'})
