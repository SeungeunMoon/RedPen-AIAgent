"""검색·판정·검증에서 공유하는 내부 규정 모델.

외부 API의 키와 중첩 구조에 의존하지 않는다. 원문 파싱, 날짜 변환,
청킹, 안정적인 ID 생성은 후속 정규화·적재 코드에서 수행한다.
"""

from datetime import date
from typing import Annotated

from pydantic import (
    AwareDatetime,
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    model_validator,
)

# 공백뿐인 값은 거부하되 원문 자체를 strip하거나 변경하지 않는다.
def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("공백만 있는 문자열은 허용하지 않습니다")
    return value


# 제공자마다 정규식 지원이 달라 공백 검증은 Pydantic에서 수행한다.
NonBlankText = Annotated[str, StringConstraints(min_length=1), AfterValidator(_require_nonblank)]


class RegulationChunk(BaseModel):
    """근거로 인용할 수 있는 규정 청크 하나.

    chunk_id는 버전과 조항 위치를 포함하는 안정적인 식별자다.
    effective_to는 효력이 끝나는 첫 날짜(미포함)이며, None은 종료일
    미확정이다. None만 보고 과거·미래 전체에 유효하다고 판단하지 않는다.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: NonBlankText = Field(description="버전·조항 위치를 구분하는 청크 ID")
    law_id: NonBlankText = Field(description="앞자리 0을 보존한 법령 식별자")
    version_id: NonBlankText = Field(description="조회한 법령 버전을 식별하는 값")
    law_name: NonBlankText = Field(description="법령 또는 규정의 이름")

    # 숫자형으로 바꾸지 않아 가지번호와 목의 문자 표현을 보존한다.
    article_no: NonBlankText = Field(description="조 번호. 예: 22, 10의2")
    paragraph_no: NonBlankText | None = Field(default=None, description="항 번호")
    item_no: NonBlankText | None = Field(default=None, description="호 번호")
    subitem_no: NonBlankText | None = Field(default=None, description="목 번호")
    title: NonBlankText | None = Field(default=None, description="조문 제목")
    text: NonBlankText = Field(description="하위 본문을 포함해 보존한 청크 원문")

    effective_from: date = Field(description="해당 조문 버전의 시행 시작일")
    effective_to: date | None = Field(default=None, description="효력 종료 경계일, 미포함")
    source_url: HttpUrl = Field(description="인증값을 제외한 원문 출처 URL")
    fetched_at: AwareDatetime = Field(description="시간대가 포함된 원천 조회 시각")

    @model_validator(mode="after")
    def validate_effective_period(self) -> "RegulationChunk":
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("효력 종료일은 시행 시작일보다 뒤여야 합니다")
        return self
