"""법제처 원본 응답 계약. 내부 규정 모델로의 변환·청킹은 수행하지 않는다.

한글 키는 alias로 읽고, 원문·날짜 문자열은 그대로 보존한다.
실제 응답에서 아직 모델링하지 않은 필드는 extra='allow'로 보존한다.
"""

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator
from typing_extensions import TypeAliasType

# 일부 목내용은 문자열이 아니라 문자열을 담은 중첩 목록으로 내려온다.
LawText = TypeAliasType('LawText', str | list['LawText'])


def _object_or_list(value: Any) -> list[Any]:
    """단일 객체는 목록으로 통일하되 잘못된 타입은 숨기지 않는다."""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return value
    raise ValueError("객체 또는 목록이어야 합니다")


class LawAPIModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class LawSearchItem(LawAPIModel):
    law_id: str = Field(alias="법령ID", min_length=1)
    master_id: str = Field(alias="법령일련번호", min_length=1)
    name: str = Field(alias="법령명한글")
    effective_date: str = Field(alias="시행일자")
    promulgation_date: str = Field(alias="공포일자")
    detail_link: str = Field(alias="법령상세링크")


class LawSearchResult(LawAPIModel):
    result_code: str = Field(alias="resultCode")
    result_message: str = Field(alias="resultMsg")
    total_count: int = Field(alias="totalCnt", ge=0)
    page: int = Field(ge=1)
    laws: Annotated[list[LawSearchItem], BeforeValidator(_object_or_list)] = Field(
        default_factory=list, alias="law",
    )


class LawSearchResponse(LawAPIModel):
    result: LawSearchResult = Field(alias="LawSearch")


class LawSubitem(LawAPIModel):
    """목. 전체 응답에서는 목내용이 중첩 목록인 경우도 확인되었다."""

    number: str = Field(alias="목번호")
    text: LawText = Field(alias="목내용")


class LawItem(LawAPIModel):
    number: str = Field(alias="호번호")
    text: str = Field(alias="호내용")
    subitems: Annotated[list[LawSubitem], BeforeValidator(_object_or_list)] = Field(
        default_factory=list, alias="목",
    )


class LawParagraph(LawAPIModel):
    # 항 구분 없이 호가 직접 이어지는 실제 법령도 있다.
    number: str | None = Field(default=None, alias="항번호")
    text: str | None = Field(default=None, alias="항내용")
    items: Annotated[list[LawItem], BeforeValidator(_object_or_list)] = Field(
        default_factory=list, alias="호",
    )

    @model_validator(mode='after')
    def require_content(self) -> 'LawParagraph':
        if not self.text and not self.items:
            raise ValueError('항 본문 또는 하위 호가 필요합니다')
        return self


class LawArticle(LawAPIModel):
    number: str = Field(alias="조문번호")
    article_key: str = Field(alias="조문키")
    article_kind: str = Field(default='조문', alias='조문여부')
    branch_number: str | None = Field(default=None, alias='조문가지번호')
    title: str | None = Field(default=None, alias="조문제목")
    text: str = Field(alias="조문내용")
    effective_date: str = Field(alias="조문시행일자")
    paragraphs: Annotated[list[LawParagraph], BeforeValidator(_object_or_list)] = Field(
        default_factory=list, alias="항",
    )


class LawArticleCollection(LawAPIModel):
    articles: Annotated[list[LawArticle], BeforeValidator(_object_or_list)] = Field(
        alias="조문단위",
    )


class LawBasicInfo(LawAPIModel):
    law_id: str = Field(alias="법령ID", min_length=1)
    name: str = Field(alias="법령명_한글")
    effective_date: str = Field(alias="시행일자")
    promulgation_date: str = Field(alias="공포일자")


class LawBody(LawAPIModel):
    law_key: str = Field(alias="법령키")
    basic_info: LawBasicInfo = Field(alias="기본정보")
    article_collection: LawArticleCollection = Field(alias="조문")


class LawArticleResponse(LawAPIModel):
    law: LawBody = Field(alias="법령")
