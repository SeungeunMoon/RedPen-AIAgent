"""실제 전체 응답의 본문·부속 자료 보존과 합성 경계 사례를 검증한다."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.schemas.external.law import LawArticleResponse
from ingest.normalize import normalize_document, normalize_snapshot

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT/'data/regulations/raw/20261021T043743991211Z'
MANIFEST = json.loads((RAW/'manifest.json').read_text())


def strings(value):
    if isinstance(value,str):
        return [value]
    if isinstance(value,list):
        return [s for v in value for s in strings(v)]
    return []


def article_texts(article):
    parts=[article['조문내용']]
    paragraphs=article.get('항',[])
    if isinstance(paragraphs,dict): paragraphs=[paragraphs]
    for paragraph in paragraphs:
        if '항내용' in paragraph: parts.append(paragraph['항내용'])
        items=paragraph.get('호',[])
        if isinstance(items,dict): items=[items]
        for item in items:
            parts.append(item['호내용'])
            subitems=item.get('목',[])
            if isinstance(subitems,dict): subitems=[subitems]
            for subitem in subitems:
                parts.extend(strings(subitem['목내용']))
    return parts


@pytest.mark.parametrize('index,expected',[ (0,73),(1,53),(2,36) ])
def test_real_documents_preserve_text_supplements_and_locations(index,expected):
    record=MANIFEST['documents'][index]
    raw=json.loads((RAW/record['body_file']).read_text())
    doc=normalize_document(raw,record)
    assert len(doc.chunks)==expected
    assert len({c.chunk_id for c in doc.chunks})==expected
    if index<2:
        source=raw['법령']
        original=[a for a in source['조문']['조문단위'] if a['조문여부']=='조문']
        for article,chunk in zip(original,doc.chunks):
            assert chunk.text=='\n'.join(article_texts(article))
            assert chunk.effective_from.isoformat().replace('-','')==article['조문시행일자']
            assert chunk.article_no==article['조문번호']+(f'의{article["조문가지번호"]}' if article.get('조문가지번호') else '')
        headings=[a for a in source['조문']['조문단위'] if a['조문여부']=='전문']
        assert doc.headings==headings
        assert all(c.title is not None or c.text for c in doc.chunks)
        consumed={'법령키','기본정보','조문'}
    else:
        source=raw['AdmRulService']
        assert [c.text for c in doc.chunks]==source['조문내용']
        assert all(c.source_kind=='administrative_rule' for c in doc.chunks)
        consumed={'행정규칙기본정보','조문내용'}
    assert doc.supplementary=={k:v for k,v in source.items() if k not in consumed}
    for chunk in doc.chunks:
        value=raw
        for part in chunk.source_path.lstrip('/').split('/'):
            value=value[int(part)] if isinstance(value,list) else value[part]
        assert value
    assert all(chunk.effective_to is None for chunk in doc.chunks)


def test_headings_are_context_not_regulation_chunks():
    record=MANIFEST['documents'][0]
    raw=json.loads((RAW/record['body_file']).read_text())
    doc=normalize_document(raw,record)
    assert len(doc.headings)==14
    assert doc.chunks[0].hierarchy==[raw['법령']['조문']['조문단위'][0]['조문내용']]
    assert not any(chunk.article_no=='1' and not chunk.title for chunk in doc.chunks)


def test_manifest_hash_tampering_does_not_create_output(tmp_path):
    copied=tmp_path/'raw';copied.mkdir()
    manifest=deepcopy(MANIFEST)
    manifest['documents']=manifest['documents'][:1]
    (copied/'manifest.json').write_text(json.dumps(manifest))
    (copied/manifest['documents'][0]['body_file']).write_text('{}')
    out=tmp_path/'processed'
    with pytest.raises(ValueError,match='해시'):
        normalize_snapshot(copied,out)
    assert not out.exists()


def test_full_snapshot_is_deterministic_and_not_embedding_ready(tmp_path):
    first=tmp_path/'first';second=tmp_path/'second'
    summary=normalize_snapshot(RAW,first)
    normalize_snapshot(RAW,second)
    assert sum(d['articles'] for d in summary['documents'])==162
    assert summary['ready_for_embedding'] is False
    assert summary['supplementary_indexed'] is False
    for doc in summary['documents']:
        assert (first/doc['file']).read_bytes()==(second/doc['file']).read_bytes()
    with pytest.raises(FileExistsError):
        normalize_snapshot(RAW,first)


def test_synthetic_empty_paragraph_is_not_silently_dropped():
    raw=json.loads((RAW/'consumer_protection_act.json').read_text())
    raw['법령']['조문']['조문단위'][1]['항']={}
    with pytest.raises(ValueError,match='항 본문'):
        LawArticleResponse.model_validate(raw)


def test_admin_unknown_header_is_rejected():
    record=MANIFEST['documents'][2]
    raw=json.loads((RAW/record['body_file']).read_text())
    raw['AdmRulService']['조문내용'][0]='합성: 해석할 수 없는 머리말'
    with pytest.raises(ValueError,match='머리말'):
        normalize_document(raw,record)
