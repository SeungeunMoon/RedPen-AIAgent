"""외부 공시 응답 → 내부 상품 스냅샷. 네트워크 호출은 하지 않는다."""

from datetime import datetime
from hashlib import sha256
from typing import Literal

from app.schemas.external.disclosure import DisclosureResponse
from app.schemas.product import ProductSnapshot, RateOption


def normalize_products(
    response: DisclosureResponse, *, product_type: Literal["deposit", "saving"],
    fetched_at: datetime, source_url: str,
) -> list[ProductSnapshot]:
    result = response.result
    if result.err_cd != "000":
        raise ValueError(f"공시 API 업무 오류: {result.err_cd}")
    if "base_list" not in result.model_fields_set or "option_list" not in result.model_fields_set:
        raise ValueError("성공 응답에 baseList와 optionList가 필요합니다")

    def parse_date(value):
        return datetime.strptime(value, "%Y%m%d").date() if value else None

    products = {}
    for base in result.base_list:
        key = (base.dcls_month, base.fin_co_no, base.fin_prdt_cd)
        if key in products:
            raise ValueError(f"중복 상품 식별자: {key}")
        products[key] = ProductSnapshot(
            disclosure_month=base.dcls_month, company_code=base.fin_co_no,
            product_code=base.fin_prdt_cd, product_type=product_type,
            company_name=base.kor_co_nm, product_name=base.fin_prdt_nm,
            preferential_conditions=base.spcl_cnd, join_way=base.join_way,
            join_member=base.join_member, notes=base.etc_note, max_limit=base.max_limit,
            disclosure_start=parse_date(base.dcls_strt_day),
            disclosure_end=parse_date(base.dcls_end_day),
            source_url=source_url, fetched_at=fetched_at,
        )
    seen_options = set()
    for option in result.option_list:
        key = (option.dcls_month, option.fin_co_no, option.fin_prdt_cd)
        if key not in products:
            raise ValueError(f"연결할 상품이 없는 금리 옵션: {key}")
        if product_type == "saving" and not option.rsrv_type:
            raise ValueError(f"적금 옵션의 적립 유형 누락: {key}")
        if product_type == "deposit" and option.rsrv_type is not None:
            raise ValueError(f"예금 옵션에 적금 적립 유형 존재: {key}")
        term = int(option.save_trm)
        identity = (*key, product_type, str(term), option.intr_rate_type, option.rsrv_type or "")
        if identity in seen_options:
            raise ValueError(f"중복 금리 옵션: {identity}")
        seen_options.add(identity)
        option_id = sha256("\x1f".join(identity).encode()).hexdigest()
        products[key].options.append(RateOption(
            option_id=option_id, term_months=term,
            interest_type=option.intr_rate_type, interest_type_name=option.intr_rate_type_nm,
            saving_type=option.rsrv_type, saving_type_name=option.rsrv_type_nm,
            base_rate=option.intr_rate, max_rate=option.intr_rate2,
        ))
    return list(products.values())
