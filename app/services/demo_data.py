"""화면 연결용 저장 샘플. 외부 API나 비밀 설정을 브라우저에 노출하지 않는다."""

import json
from datetime import date, datetime
from pathlib import Path

from app.kb.factory import create_regulation_provider
from app.core.config import Settings
from app.schemas.external.disclosure import DisclosureResponse
from mcp_servers.fin_disclosure.normalize import normalize_products

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DATE = date(2026, 10, 21)


def load_demo_data():
    provider = create_regulation_provider(Settings())
    products = {}
    for kind, filename in [('deposit','20261021T004135705571Z_deposit.json'),
                           ('saving','20261021T004200103102Z_saving.json')]:
        path = ROOT / 'samples/disclosure' / filename
        meta = json.loads(path.with_suffix('.meta.json').read_text(encoding='utf-8'))
        values = normalize_products(
            DisclosureResponse.from_json(path.read_text(encoding='utf-8')),
            product_type=kind, fetched_at=datetime.fromisoformat(meta['fetched_at']),
            source_url=meta['endpoint'])
        for p in values:
            key = ':'.join([kind,p.disclosure_month,p.company_code,p.product_code])
            products[key] = p
    return provider, products
