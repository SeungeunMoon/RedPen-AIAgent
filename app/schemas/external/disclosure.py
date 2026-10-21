"""금융상품 한눈에 원본 계약. 금리는 JSON 파싱부터 Decimal로 보존한다."""

import json
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DisclosureAPIModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProductBase(DisclosureAPIModel):
    dcls_month: str = Field(pattern=r"^\d{6}$")
    fin_co_no: str
    fin_prdt_cd: str
    kor_co_nm: str
    fin_prdt_nm: str
    spcl_cnd: str
    join_way: str | None = None
    join_member: str | None = None
    etc_note: str | None = None
    max_limit: int | None = None
    dcls_strt_day: str | None = None
    dcls_end_day: str | None = None


class ProductOption(DisclosureAPIModel):
    dcls_month: str = Field(pattern=r"^\d{6}$")
    fin_co_no: str
    fin_prdt_cd: str
    intr_rate_type: str
    intr_rate_type_nm: str
    save_trm: str
    intr_rate: Decimal | None = None
    intr_rate2: Decimal | None = None
    rsrv_type: str | None = None
    rsrv_type_nm: str | None = None


class DisclosureResult(DisclosureAPIModel):
    err_cd: str
    err_msg: str
    total_count: int | None = Field(default=None, ge=0)
    max_page_no: int | None = Field(default=None, ge=0)
    now_page_no: int | None = Field(default=None, ge=1)
    base_list: list[ProductBase] = Field(default_factory=list, alias="baseList")
    option_list: list[ProductOption] = Field(default_factory=list, alias="optionList")


class DisclosureResponse(DisclosureAPIModel):
    result: DisclosureResult

    @classmethod
    def from_json(cls, text: str) -> "DisclosureResponse":
        # float를 거치지 않고 소수 표기를 Decimal로 읽는다.
        return cls.model_validate(json.loads(text, parse_float=Decimal))
