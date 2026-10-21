import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.external.law import LawArticleResponse, LawSearchResponse

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/law"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_search_alias_and_leading_zero_id():
    raw = load("search_excerpt.json")
    result = LawSearchResponse.model_validate(raw).result
    assert result.result_code == "00"
    assert result.total_count == 2
    assert result.laws[0].law_id == "013704"
    assert result.laws[0].master_id == "277247"
    assert result.laws[0].name == raw["LawSearch"]["law"][0]["법령명한글"]


def test_article_preserves_nested_text_and_unknown_fields():
    raw = load("article_excerpt.json")
    response = LawArticleResponse.model_validate(raw)
    article = response.law.article_collection.articles[0]
    original = raw["법령"]["조문"]["조문단위"]
    assert article.text == original["조문내용"]
    assert article.paragraphs[0].text == original["항"][0]["항내용"]
    assert article.paragraphs[0].items[0].text == original["항"][0]["호"][0]["호내용"]
    assert article.effective_date == "20260102"
    assert response.law.basic_info.model_extra["소관부처"] == raw["법령"]["기본정보"]["소관부처"]


def test_synthetic_object_list_variants_and_subitems():
    raw = load("article_excerpt.json")
    article = raw["법령"]["조문"]["조문단위"]
    paragraph = article["항"][0]
    item = paragraph["호"][0]
    item["목"] = {"목번호": "가.", "목내용": "합성 테스트 목 본문"}
    paragraph["호"] = item
    article["항"] = paragraph
    raw["법령"]["조문"]["조문단위"] = [article, deepcopy(article)]
    articles = LawArticleResponse.model_validate(raw).law.article_collection.articles
    assert len(articles) == 2
    assert articles[0].paragraphs[0].items[0].subitems[0].text == "합성 테스트 목 본문"


def test_synthetic_single_search_item():
    raw = load("search_excerpt.json")
    raw["LawSearch"]["law"] = raw["LawSearch"]["law"][0]
    assert len(LawSearchResponse.model_validate(raw).result.laws) == 1


def test_missing_optional_children_are_empty():
    raw = load("article_excerpt.json")
    del raw["법령"]["조문"]["조문단위"]["항"][0]["호"]
    article = LawArticleResponse.model_validate(raw).law.article_collection.articles[0]
    assert article.paragraphs[0].items == []


@pytest.mark.parametrize("invalid", [None, "잘못된 본문", 22])
def test_synthetic_invalid_children_are_not_silently_dropped(invalid):
    raw = load("article_excerpt.json")
    raw["법령"]["조문"]["조문단위"]["항"] = invalid
    with pytest.raises(ValidationError):
        LawArticleResponse.model_validate(raw)


def test_required_article_structure_is_not_optional():
    with pytest.raises(ValidationError):
        LawArticleResponse.model_validate({"법령": {}})


def test_synthetic_search_error_code_remains_visible():
    raw = load("search_excerpt.json")
    raw["LawSearch"].update(resultCode="TEST_ERROR", resultMsg="합성 오류", totalCnt="0")
    del raw["LawSearch"]["law"]
    result = LawSearchResponse.model_validate(raw).result
    assert result.result_code == "TEST_ERROR"
    assert result.laws == []
    # 업무 성공 판단은 호출부의 책임이며 모델 파싱 성공과 구분한다.


@pytest.mark.parametrize("filename,model", [
    ("20261021T004133411401Z_search.json", LawSearchResponse),
    ("20261021T004141864078Z_article.json", LawArticleResponse),
])
def test_full_real_samples_preserve_every_text_value(filename, model):
    raw = json.loads((ROOT / "samples/law" / filename).read_text(encoding="utf-8"))
    parsed = model.model_validate(raw).model_dump(by_alias=True)

    def assert_preserved(source, output):
        if isinstance(source, dict):
            if isinstance(output, list):
                assert len(output) == 1
                output = output[0]
            for key, value in source.items():
                assert_preserved(value, output[key])
        elif isinstance(source, list):
            assert len(source) == len(output)
            for left, right in zip(source, output):
                assert_preserved(left, right)
        elif isinstance(output, int) and isinstance(source, str):
            assert int(source) == output  # 페이지·건수만 정수로 파싱
        else:
            assert source == output

    assert_preserved(raw, parsed)
