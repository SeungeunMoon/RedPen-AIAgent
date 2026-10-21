"""감독규정 원본 계약. 평문 조문 안의 항·호를 임의로 다시 나누지 않는다."""

from pydantic import Field

from app.schemas.external.law import LawAPIModel


class AdministrativeRuleInfo(LawAPIModel):
    rule_id: str = Field(alias='행정규칙ID')
    serial_number: str = Field(alias='행정규칙일련번호')
    name: str = Field(alias='행정규칙명')
    effective_date: str = Field(alias='시행일자')
    current: str = Field(alias='현행여부')


class AdministrativeRuleBody(LawAPIModel):
    info: AdministrativeRuleInfo = Field(alias='행정규칙기본정보')
    articles: list[str] = Field(alias='조문내용', min_length=1)


class AdministrativeRuleResponse(LawAPIModel):
    rule: AdministrativeRuleBody = Field(alias='AdmRulService')
