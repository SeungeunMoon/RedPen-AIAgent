"""동일 조건의 공시 옵션을 선택하고 수치를 대조한다. 법적 위반은 판단하지 않는다."""

from datetime import date
from zoneinfo import ZoneInfo

from app.schemas.claim import Claim
from app.schemas.product import ProductSnapshot, RateComparison


def compare_rate(
    claim: Claim, product: ProductSnapshot | None, *, as_of_date: date,
) -> RateComparison:
    """선택 상품 하나에 대한 대조. 네트워크·LLM 없이 내부 모델만 사용한다."""
    advertised = claim.rate.rate if claim.rate else None

    def result(status, reason, candidates=(), selected=None, disclosed=None, timing="unknown"):
        return RateComparison(
            claim_id=claim.id, status=status, advertised_rate=advertised,
            candidate_option_ids=[o.option_id for o in candidates],
            selected_option_id=selected.option_id if selected else None,
            disclosed_rate=disclosed,
            difference_pp=advertised - disclosed if advertised is not None and disclosed is not None else None,
            timing_status=timing, reason=reason,
        )

    if claim.kind != "interest_rate":
        return result("skipped", "금리 클레임이 아니므로 수치 대조를 수행하지 않았습니다")
    if product is None:
        return result("skipped", "선택한 상품이 없어 공시 대조를 수행하지 않았습니다")
    rate = claim.rate
    assert rate is not None  # Claim 검증에서 금리 유형에 RateClaim 존재를 보장
    candidates = [o for o in product.options
                  if (rate.term_months is None or o.term_months == rate.term_months)
                  and (rate.interest_type is None or o.interest_type == rate.interest_type)
                  and (rate.saving_type is None or o.saving_type == rate.saving_type)]
    if not candidates:
        return result("unavailable", "광고 조건과 일치하는 공시 금리 옵션이 없습니다")
    if rate.term_months is None or rate.rate_kind == "unknown":
        return result("ambiguous", "가입 기간 또는 기본·최고 금리 구분을 확인해야 합니다", candidates)
    if rate.tax_basis != "before_tax":
        return result("ambiguous", "세전 금리인지 확인되지 않아 공시 금리와 직접 비교할 수 없습니다", candidates)
    if product.product_type == "deposit" and rate.saving_type is not None:
        return result("ambiguous", "예금 상품에 적금 적립 유형이 지정되어 있습니다", candidates)
    if len(candidates) != 1:
        return result("ambiguous", "금리 유형·적립 유형을 확정할 수 없어 여러 옵션이 남았습니다", candidates)
    # 현행 스냅샷을 과거·미래 광고의 확정 비교값으로 사용하지 않는다.
    snapshot_day = product.fetched_at.astimezone(ZoneInfo("Asia/Seoul")).date()
    if as_of_date != snapshot_day:
        return result("ambiguous", "검토 기준일과 스냅샷 조회일이 달라 해당 날짜의 금리를 확인할 수 없습니다", candidates, timing="different")
    option = candidates[0]
    disclosed = option.base_rate if rate.rate_kind == "base" else option.max_rate
    if disclosed is None:
        return result("unavailable", "선택한 옵션의 비교 금리가 공시에 없습니다", candidates, selected=option)
    status = "match" if rate.rate == disclosed else "mismatch"
    return result(
        status,
        "동일 옵션의 세전 금리 수치 비교입니다. 공시월만으로 일별 유효성이나 우대조건 충족을 보장하지 않으며 법적 위반 판정은 별도입니다",
        candidates, selected=option, disclosed=disclosed,
    )
