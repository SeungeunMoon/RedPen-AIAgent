from pathlib import Path

import pytest

from evaluation.retrieval.run import ROOT, Target, score, validate_cases
from ingest.normalize import NormalizedDocument


def test_development_gold_quotes_exist_in_actual_source():
    raw, cases = validate_cases(ROOT/'evaluation/retrieval/cases.json', ROOT/'data/regulations/processed/20261021T043743991211Z-whole-article-v1')
    assert len(cases) == 10
    assert '합성' in raw['provenance']


def test_article_hit_without_gold_passage_is_not_evidence_recall():
    source = ROOT/'data/regulations/processed/20261021T043743991211Z-whole-article-v1/consumer_protection_act.normalized.json'
    chunk = NormalizedDocument.model_validate_json(source.read_bytes()).chunks[0]
    target = Target(law_id=chunk.law_id, article_no=chunk.article_no, quote='합성 정답')
    result = score([target], [chunk], 1)
    assert result == {'article_recall':1.0,'evidence_recall':0.0,'mrr':0.0}
    right = chunk.model_copy(update={'text':'합성 정답'})
    assert score([target], [chunk,right], 2)['mrr'] == 0.5
    assert score([target], [chunk,right], 1)['evidence_recall'] == 0


def test_multi_target_recall_and_duplicate_hits():
    source = ROOT/'data/regulations/processed/20261021T043743991211Z-whole-article-v1/consumer_protection_act.normalized.json'
    chunk = NormalizedDocument.model_validate_json(source.read_bytes()).chunks[0]
    target = Target(law_id=chunk.law_id, article_no=chunk.article_no, quote=chunk.text[:10])
    missing = Target(law_id='missing', article_no='1', quote='합성 미회수')
    result = score([target, missing], [chunk,chunk], 2)
    assert result['evidence_recall'] == 0.5
    assert result['article_recall'] == 0.5
    assert score([target], [], 3)['evidence_recall'] == 0
