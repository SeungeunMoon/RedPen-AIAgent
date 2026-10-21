import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.schemas.external.disclosure import DisclosureResponse
from mcp_servers.fin_disclosure.normalize import normalize_products

ROOT = Path(__file__).resolve().parents[2]


def convert(text, kind):
    response = DisclosureResponse.from_json(text)
    return normalize_products(
        response, product_type=kind,
        fetched_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
        source_url='https://finlife.fss.or.kr/finlifeapi/depositProductsSearch.json',
    )


@pytest.mark.parametrize('kind,expected_products,expected_options', [('deposit',39,158),('saving',59,178)])
def test_real_samples_preserve_products_options_and_rates(kind, expected_products, expected_options):
    path = next((ROOT/'samples/disclosure').glob('*_'+kind+'.json'))
    text = path.read_text()
    raw = json.loads(text, parse_float=Decimal)['result']
    products = convert(text, kind)
    assert len(products) == expected_products
    assert sum(len(p.options) for p in products) == expected_options
    key = lambda r:(r['dcls_month'],r['fin_co_no'],r['fin_prdt_cd'])
    for base, product in zip(raw['baseList'], products):
        assert product.company_code == base['fin_co_no']
        assert product.product_code == base['fin_prdt_cd']
        assert product.preferential_conditions == base['spcl_cnd']
        assert product.max_limit == base['max_limit']
        options = [o for o in raw['optionList'] if key(o)==key(base)]
        for original, option in zip(options, product.options):
            assert option.base_rate == original['intr_rate']
            assert option.max_rate == original['intr_rate2']
            assert isinstance(option.base_rate, Decimal)
            assert option.term_months == int(original['save_trm'])
            assert option.saving_type == original.get('rsrv_type')
    assert products == convert(text, kind)  # 옵션 ID도 안정적


def excerpt():
    return json.loads((ROOT/'tests/fixtures/disclosure/deposit_excerpt.json').read_text())


@pytest.mark.parametrize('kind', ['deposit', 'saving'])
def test_documented_excerpts(kind):
    text = (ROOT / f'tests/fixtures/disclosure/{kind}_excerpt.json').read_text()
    products = convert(text, kind)
    assert len(products) == 1
    assert len(products[0].options) == 2


def test_synthetic_orphan_is_not_dropped():
    raw=excerpt(); raw['result']['optionList'][0]['fin_prdt_cd']='unmatched'
    with pytest.raises(ValueError, match='상품'):
        convert(json.dumps(raw), 'deposit')


def test_synthetic_null_rate_preserved():
    raw=excerpt();raw['result']['optionList'][0]['intr_rate']=None
    assert convert(json.dumps(raw),'deposit')[0].options[0].base_rate is None


def test_synthetic_business_error_rejected():
    with pytest.raises(ValueError, match='업무 오류'):
        convert('{"result":{"err_cd":"TEST_ERROR","err_msg":"synthetic"}}','deposit')


def test_synthetic_missing_success_lists_rejected():
    with pytest.raises(ValueError, match='baseList'):
        convert('{"result":{"err_cd":"000","err_msg":"ok"}}','deposit')


def test_synthetic_duplicate_option_rejected():
    raw=excerpt();raw['result']['optionList']*=2
    with pytest.raises(ValueError, match='중복 금리'):
        convert(json.dumps(raw),'deposit')
