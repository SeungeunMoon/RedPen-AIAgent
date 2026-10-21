import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.schemas.external.law import LawArticleResponse
from mcp_servers.korean_law.normalize import normalize_regulations

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'https://www.law.go.kr/DRF/lawService.do?target=lawjosub&ID=013704&JO=002200'
FETCHED = datetime(2026, 10, 21, tzinfo=timezone.utc)


def sample():
    return json.loads((ROOT/'samples/law/20261021T004141864078Z_article.json').read_text())


def convert(raw, **kwargs):
    return normalize_regulations(LawArticleResponse.model_validate(raw),
        fetched_at=kwargs.get('fetched_at', FETCHED), source_url=kwargs.get('source_url', SOURCE))


def test_real_article_preserves_all_nested_text_and_identity():
    raw = sample()
    chunks = convert(raw)
    assert len(chunks) == 1
    chunk = chunks[0]
    article = raw['법령']['조문']['조문단위']
    parts = [article['조문내용']]
    for paragraph in article['항']:
        parts.append(paragraph['항내용'])
        for item in paragraph.get('호', []):
            parts.append(item['호내용'])
            parts.extend(sub['목내용'] for sub in item.get('목', []))
    assert chunk.text == '\n'.join(parts)
    assert chunk.law_id == '013704'
    assert chunk.article_no == '22'
    assert chunk.effective_from == date(2026, 1, 2)
    assert chunk.effective_to is None
    assert chunk.paragraph_no is None  # 항 단위가 아닌 조문 전체


def test_id_stable_across_fetches_but_changes_with_content():
    raw=sample()
    original=convert(raw)[0]
    assert original.chunk_id == convert(raw, fetched_at=datetime(2026,10,22,tzinfo=timezone.utc))[0].chunk_id
    raw['법령']['조문']['조문단위']['항'][0]['항내용'] += ' 합성 변경'
    assert original.chunk_id != convert(raw)[0].chunk_id


def test_synthetic_multiple_articles_subitem_and_no_paragraph():
    raw=sample()
    article=raw['법령']['조문']['조문단위']
    article['항'][0]['호'][0]['목']={'목번호':'가.','목내용':'합성 목 본문'}
    raw['법령']['조문']['조문단위']=[article,{
        '조문키':'synthetic-key','조문번호':'99','조문내용':'합성 조문 본문',
        '조문시행일자':'20260102',
    }]
    chunks=convert(raw)
    assert '합성 목 본문' in chunks[0].text
    assert chunks[1].text == '합성 조문 본문'


def test_duplicate_article_rejected():
    raw=sample();article=raw['법령']['조문']['조문단위']
    raw['법령']['조문']['조문단위']=[article,article]
    with pytest.raises(ValueError,match='중복'):
        convert(raw)


def test_invalid_date_rejected():
    raw=sample();raw['법령']['조문']['조문단위']['조문시행일자']='20260230'
    with pytest.raises(ValueError):
        convert(raw)


def test_credential_url_rejected():
    with pytest.raises(ValueError,match='인증정보'):
        convert(sample(),source_url=SOURCE+'&OC=test-secret')
