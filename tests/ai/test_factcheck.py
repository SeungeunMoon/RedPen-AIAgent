from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.ai.stages.factcheck import compare_rate
from app.schemas.claim import Claim, RateClaim
from app.schemas.product import ProductSnapshot, RateOption

DAY = date(2026,10,21)


def product():
    # 수치·상품은 분기 확인용 합성 자료다.
    return ProductSnapshot(disclosure_month='202610',company_code='001',product_code='p1',
        product_type='deposit',company_name='합성은행',product_name='합성예금',
        preferential_conditions='조건 원문',source_url='https://example.test/products',
        fetched_at=datetime(2026,10,21,tzinfo=timezone.utc),options=[
            RateOption(option_id='o12',term_months=12,interest_type='S',interest_type_name='단리',
                       base_rate='3.0',max_rate='3.8'),
            RateOption(option_id='o24',term_months=24,interest_type='S',interest_type_name='단리',
                       base_rate='3.5',max_rate='4.0'),
        ])


def claim(**changes):
    values=dict(rate='4.5',rate_kind='max',term_months=12,interest_type='S',tax_basis='before_tax')
    values.update(changes)
    return Claim(id='c1',quote='합성 금리 문구',kind='interest_rate',rate=RateClaim(**values))


def test_selects_same_term_not_product_maximum():
    result=compare_rate(claim(),product(),as_of_date=DAY)
    assert result.status == 'mismatch'
    assert result.selected_option_id == 'o12'
    assert result.disclosed_rate == Decimal('3.8')
    assert result.difference_pp == Decimal('0.7')
    assert result.timing_status == 'unknown'


def test_base_rate_and_match():
    result=compare_rate(claim(rate='3.0',rate_kind='base'),product(),as_of_date=DAY)
    assert result.status == 'match'
    assert result.difference_pp == 0


@pytest.mark.parametrize('changes',[
    {'term_months':None}, {'rate_kind':'unknown'}, {'tax_basis':'unknown'}, {'tax_basis':'after_tax'},
])
def test_missing_conditions_are_not_guessed(changes):
    assert compare_rate(claim(**changes),product(),as_of_date=DAY).status == 'ambiguous'


def test_multiple_types_remain_ambiguous():
    p=product()
    p.options.append(RateOption(option_id='compound12',term_months=12,interest_type='C',
                               interest_type_name='복리',base_rate='3.1',max_rate='3.9'))
    result=compare_rate(claim(interest_type=None),p,as_of_date=DAY)
    assert result.status == 'ambiguous'
    assert len(result.candidate_option_ids) == 2


def test_saving_requires_unique_saving_type():
    p=product();p.product_type='saving'
    p.options=[RateOption(option_id=f's{kind}',term_months=12,interest_type='S',interest_type_name='단리',
                         saving_type=kind,base_rate='3',max_rate='4') for kind in ['S','F']]
    assert compare_rate(claim(),p,as_of_date=DAY).status == 'ambiguous'
    assert compare_rate(claim(saving_type='F'),p,as_of_date=DAY).selected_option_id == 'sF'


def test_no_matching_option_or_missing_rate():
    assert compare_rate(claim(term_months=36),product(),as_of_date=DAY).status == 'unavailable'
    p=product();p.options[0].max_rate=None
    assert compare_rate(claim(),p,as_of_date=DAY).status == 'unavailable'


def test_skips_non_rate_and_unselected_product():
    assert compare_rate(claim(),None,as_of_date=DAY).status == 'skipped'
    c=Claim(id='c2',quote='안전 보장',kind='guarantee')
    assert compare_rate(c,product(),as_of_date=DAY).status == 'skipped'


def test_snapshot_cannot_prove_past_rate():
    result=compare_rate(claim(),product(),as_of_date=date(2026,9,21))
    assert result.status == 'ambiguous'
    assert result.timing_status == 'different'
    assert result.disclosed_rate is None
