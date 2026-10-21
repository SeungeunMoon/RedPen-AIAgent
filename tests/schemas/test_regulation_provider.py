import asyncio
from datetime import date
from pathlib import Path

import pytest

from app.kb.empty import EmptyRegulationProvider
from app.kb.fixed import FixedRegulationProvider
from app.kb.provider import RegulationProvider, UnsupportedRegulationDateError
from app.schemas.claim import Claim

SAMPLE = Path(__file__).resolve().parents[2] / 'samples/law/20261021T004141864078Z_article.json'
SNAPSHOT = date(2026, 10, 21)
CLAIMS = [Claim(id='c1', quote='무조건 보장', kind='guarantee')]


def provide(provider: RegulationProvider, claims=CLAIMS, as_of_date=SNAPSHOT):
    return asyncio.run(provider.provide(claims, as_of_date=as_of_date))


def test_empty_and_fixed_share_contract():
    assert provide(EmptyRegulationProvider()) == []
    chunks = provide(FixedRegulationProvider.from_law_sample(SAMPLE))
    assert len(chunks) == 1
    assert chunks[0].law_id == '013704'
    assert chunks[0].article_no == '22'
    assert 'OC=' not in str(chunks[0].source_url)
    assert '①' in chunks[0].text


def test_fixed_provides_all_rules_even_for_no_claims():
    provider = FixedRegulationProvider.from_law_sample(SAMPLE)
    assert provide(provider, claims=[]) == provide(provider)


@pytest.mark.parametrize('day', [date(2026,10,20), date(2026,10,22)])
def test_unknown_end_does_not_imply_historical_or_future_validity(day):
    with pytest.raises(UnsupportedRegulationDateError):
        provide(FixedRegulationProvider.from_law_sample(SAMPLE), as_of_date=day)


def test_rules_not_effective_yet_are_excluded():
    assert provide(FixedRegulationProvider.from_law_sample(SAMPLE), as_of_date=date(2025,1,1)) == []


def test_returned_objects_cannot_mutate_provider():
    provider = FixedRegulationProvider.from_law_sample(SAMPLE)
    provide(provider)[0].text = 'changed'
    assert provide(provider)[0].text != 'changed'


def test_synthetic_known_validity_interval():
    chunk = provide(FixedRegulationProvider.from_law_sample(SAMPLE))[0]
    chunk.effective_to = date(2026, 11, 1)  # 합성: 실제 종료일이 아님
    provider = FixedRegulationProvider([chunk], snapshot_date=SNAPSHOT)
    assert len(provide(provider, as_of_date=date(2026,1,2))) == 1
    assert provide(provider, as_of_date=date(2026,11,1)) == []


def test_duplicate_chunks_are_rejected():
    chunk = provide(FixedRegulationProvider.from_law_sample(SAMPLE))[0]
    with pytest.raises(ValueError, match='중복'):
        FixedRegulationProvider([chunk, chunk], snapshot_date=SNAPSHOT)
