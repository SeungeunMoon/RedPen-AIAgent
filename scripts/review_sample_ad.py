"""광고 파일 → 실제 LLM 추출·판정. 외부 API 대신 저장된 공시·규정 샘플을 사용한다."""

import argparse
import asyncio
import json
from datetime import date, datetime
from pathlib import Path

from app.core.environment import load_runtime_environment

# LangChain/LangSmith 초기화 전에 적용한다. 인증값은 출력하지 않는다.
load_runtime_environment()

from app.kb.factory import create_regulation_provider
from app.core.config import Settings
from app.schemas.external.disclosure import DisclosureResponse
from app.services.review_service import review_ad
from mcp_servers.fin_disclosure.normalize import normalize_products

ROOT = Path(__file__).resolve().parents[1]


async def run(args):
    product = None
    if args.product_code:
        filename = ('20261021T004135705571Z_deposit.json' if args.product == 'deposit'
                    else '20261021T004200103102Z_saving.json')
        path = ROOT / 'samples/disclosure' / filename
        meta = json.loads(path.with_suffix('.meta.json').read_text(encoding='utf-8'))
        products = normalize_products(
            DisclosureResponse.from_json(path.read_text(encoding='utf-8')),
            product_type=args.product, fetched_at=datetime.fromisoformat(meta['fetched_at']),
            source_url=meta['endpoint'],
        )
        matches = [p for p in products if p.company_code == args.company_code and p.product_code == args.product_code]
        if len(matches) != 1:
            raise ValueError('선택한 금융사·상품 코드를 샘플에서 찾지 못했습니다')
        product = matches[0]
    settings = Settings(**({'regulation_provider': args.provider} if args.provider else {}))
    provider = create_regulation_provider(settings)
    try:
        result = await review_ad(
            args.ad_file.read_text(encoding='utf-8'), provider=provider,
            as_of_date=args.as_of_date, product=product,
        )
    finally:
        if hasattr(provider, 'aclose'):
            await provider.aclose()
    print(result.model_dump_json(indent=2))
    # 짧은 CLI 프로세스가 종료되기 전 추적 전송을 기다린다.
    from langchain_core.tracers.langchain import wait_for_all_tracers
    wait_for_all_tracers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ad-file', type=Path, required=True)
    parser.add_argument('--as-of-date', type=date.fromisoformat, required=True)
    parser.add_argument('--provider', choices=['rag', 'fixed', 'empty'])
    parser.add_argument('--product', choices=['deposit','saving'], default='deposit')
    parser.add_argument('--company-code')
    parser.add_argument('--product-code')
    args = parser.parse_args()
    if bool(args.company_code) != bool(args.product_code):
        parser.error('--company-code와 --product-code는 함께 지정하세요')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
