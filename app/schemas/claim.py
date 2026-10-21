"""광고에 실제로 있는 문구와 조건을 추출하는 계약. 위반 판정은 포함하지 않는다."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.regulation import NonBlankText


class ClaimModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextSpan(ClaimModel):
    """Python 문자열 기준 [start, end). 위치 계산은 모델이 아닌 코드가 수행한다."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> "TextSpan":
        if self.end <= self.start:
            raise ValueError("end는 start보다 커야 합니다")
        return self


class RateClaim(ClaimModel):
    rate: Decimal = Field(allow_inf_nan=False, description="퍼센트 단위. 예: 4.5")
    rate_kind: Literal["base", "max", "unknown"] = "unknown"
    term_months: int | None = Field(default=None, gt=0)
    interest_type: str | None = None
    saving_type: str | None = None
    tax_basis: Literal["before_tax", "after_tax", "unknown"] = "unknown"
    conditions_text: str | None = None


class Claim(ClaimModel):
    id: NonBlankText
    quote: NonBlankText
    kind: Literal["interest_rate", "term", "condition", "exaggeration", "guarantee", "notice", "other"]
    span: TextSpan | None = None
    rate: RateClaim | None = None

    @model_validator(mode="after")
    def validate_rate(self) -> "Claim":
        if (self.kind == "interest_rate") != (self.rate is not None):
            raise ValueError("금리 클레임에만 RateClaim이 반드시 필요합니다")
        return self


class ExtractionResult(ClaimModel):
    claims: list[Claim]
    ad_status: Literal["advertisement", "not_advertisement", "uncertain"]
    ad_status_reason: NonBlankText
    present_notices: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "ExtractionResult":
        ids = [claim.id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("클레임 ID는 중복될 수 없습니다")
        return self

    def validate_source(self, text: str) -> None:
        """원문과의 관계는 필드 타입 검증 후 명시적으로 확인한다."""
        for claim in self.claims:
            if claim.quote not in text:
                raise ValueError(f"원문에 없는 인용: {claim.id}")
            if claim.span and (
                claim.span.end > len(text)
                or text[claim.span.start:claim.span.end] != claim.quote
            ):
                raise ValueError(f"원문 위치와 인용 불일치: {claim.id}")
