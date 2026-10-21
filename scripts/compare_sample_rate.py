"""실제 공시 샘플 + 수동 합성 Claim 대조. API·LLM을 호출하지 않는다."""

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.ai.stages.factcheck import compare_rate
from app.schemas.claim import Claim, RateClaim
from app.schemas.external.disclosure import DisclosureResponse
from mcp_servers.fin_disclosure.normalize import normalize_products

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product', choices=['deposit','saving'], default='deposit')
    parser.add_argument('--rate', default='4.5', help='합성 광고 금리(퍼센트)')
    args = parser.parse_args()
    filename = ('20261021T004135705571Z_deposit.json' if args.product == 'deposit'
                else '20261021T004200103102Z_saving.json')
    path = ROOT/'samples/disclosure'/filename
    meta = json.loads(path.with_suffix('.meta.json').read_text(encoding='utf-8'))
    fetched = datetime.fromisoformat(meta['fetched_at'])
    products = normalize_products(
        DisclosureResponse.from_json(path.read_text(encoding='utf-8')),
        product_type=args.product, fetched_at=fetched, source_url=meta['endpoint'],
    )
    # 데모에서는 첫 상품의 첫 옵션을 명시적으로 선택한다.
    product = products[0]
    option = product.options[0]
    claim = Claim(id='synthetic-rate-1', quote=f'최고 연 {args.rate}%', kind='interest_rate',
        rate=RateClaim(rate=args.rate, rate_kind='max', term_months=option.term_months,
            interest_type=option.interest_type, saving_type=option.saving_type, tax_basis='before_tax'))
    comparison = compare_rate(claim, product, as_of_date=fetched.astimezone(ZoneInfo('Asia/Seoul')).date())
    print('합성 Claim과 실제 공시 샘플 비교 (광고 원문 추출 결과 아님)')
    print(product.company_name, product.product_name, f'{option.term_months}개월', product.disclosure_month)
    print(comparison.model_dump_json(indent=2))


if __name__ == '__main__':
    main()
