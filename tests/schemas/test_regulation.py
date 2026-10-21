from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.regulation import RegulationChunk


@pytest.fixture
def chunk_data():
    # 내부 계약 확인용 합성 데이터. 실제 정규화 결과나 실제 버전 ID가 아니다.
    return {
        "chunk_id": "law:013704:sample-version:22:1",
        "law_id": "013704",
        "version_id": "sample-version",
        "law_name": "금융소비자 보호에 관한 법률",
        "article_no": "22",
        "paragraph_no": "1",
        "text": "  원문 공백과\n줄바꿈을 유지합니다.  ",
        "effective_from": "2026-01-02",
        "source_url": "https://www.law.go.kr/법령/금융소비자보호법",
        "fetched_at": "2026-10-21T00:41:41+00:00",
    }


def test_preserves_identifier_text_and_unknown_end_date(chunk_data):
    chunk = RegulationChunk.model_validate(chunk_data)
    assert chunk.law_id == "013704"
    assert chunk.text == chunk_data["text"]
    assert chunk.effective_from == date(2026, 1, 2)
    assert chunk.effective_to is None
    assert chunk.fetched_at == datetime(2026, 10, 21, 0, 41, 41, tzinfo=timezone.utc)
    assert RegulationChunk.model_validate_json(chunk.model_dump_json()) == chunk


@pytest.mark.parametrize("end_date", ["2026-01-01", "2026-01-02"])
def test_rejects_invalid_effective_period(chunk_data, end_date):
    with pytest.raises(ValidationError, match="종료일"):
        RegulationChunk.model_validate({**chunk_data, "effective_to": end_date})


@pytest.mark.parametrize("field,value", [
    ("text", " \n "),
    ("law_id", 13704),
    ("fetched_at", "2026-10-21T09:41:41"),
    ("source_url", "원문 주소 미확인"),
])
def test_rejects_invalid_boundary_data(chunk_data, field, value):
    with pytest.raises(ValidationError):
        RegulationChunk.model_validate({**chunk_data, field: value})


def test_rejects_unexpected_fields(chunk_data):
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RegulationChunk.model_validate({**chunk_data, "법령ID": "013704"})


def test_nonblank_contract_is_provider_compatible_and_preserves_multiline(chunk_data):
    from app.schemas.claim import ExtractionResult
    from app.schemas.verdict import JudgmentResult
    import json
    assert '"pattern"' not in json.dumps(ExtractionResult.model_json_schema())
    assert '"pattern"' not in json.dumps(JudgmentResult.model_json_schema())
    chunk=RegulationChunk.model_validate({**chunk_data,'text':'\n  본문\n'})
    assert chunk.text == '\n  본문\n'
