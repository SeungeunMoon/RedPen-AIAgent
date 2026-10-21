"""상품 스냅샷과 조건별 금리. 외부 API 구조와 독립적인 내부 계약."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.schemas.regulation import NonBlankText


class ProductModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RateOption(ProductModel):
    option_id: NonBlankText
    term_months: int = Field(gt=0)
    interest_type: NonBlankText
    interest_type_name: str
    saving_type: str | None = None
    saving_type_name: str | None = None
    base_rate: Decimal | None = Field(default=None, allow_inf_nan=False)
    max_rate: Decimal | None = Field(default=None, allow_inf_nan=False)


class ProductSnapshot(ProductModel):
    disclosure_month: str = Field(pattern=r"^\d{4}(0[1-9]|1[0-2])$")
    company_code: NonBlankText
    product_code: NonBlankText
    product_type: Literal["deposit", "saving"]
    company_name: NonBlankText
    product_name: NonBlankText
    preferential_conditions: str
    join_way: str | None = None
    join_member: str | None = None
    notes: str | None = None
    max_limit: int | None = None
    disclosure_start: date | None = None
    disclosure_end: date | None = None
    source_url: HttpUrl
    fetched_at: AwareDatetime
    options: list[RateOption] = Field(default_factory=list)


class RateComparison(ProductModel):
    claim_id: NonBlankText
    status: Literal["match", "mismatch", "ambiguous", "unavailable", "skipped"]
    selected_option_id: str | None = None
    candidate_option_ids: list[str] = Field(default_factory=list)
    advertised_rate: Decimal | None = Field(default=None, allow_inf_nan=False)
    disclosed_rate: Decimal | None = Field(default=None, allow_inf_nan=False)
    difference_pp: Decimal | None = Field(default=None, allow_inf_nan=False)
    timing_status: Literal["aligned", "unknown", "different"] = "unknown"
    reason: NonBlankText

    @model_validator(mode="after")
    def validate_comparison(self) -> "RateComparison":
        if self.status in ("match", "mismatch"):
            if not self.selected_option_id or self.advertised_rate is None or self.disclosed_rate is None:
                raise ValueError("금리 비교에는 선택 옵션과 두 금리가 필요합니다")
            difference = self.advertised_rate - self.disclosed_rate
            if self.difference_pp != difference:
                raise ValueError("금리 차이는 광고 금리 - 공시 금리여야 합니다")
            if (self.status == "match") != (difference == 0):
                raise ValueError("비교 상태와 금리 차이가 일치하지 않습니다")
        return self
