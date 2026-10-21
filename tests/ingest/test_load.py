"""원천 수집 경계 테스트. 네트워크는 합성 httpx 응답으로 대체한다."""

import json
from pathlib import Path

import httpx
import pytest

from ingest.load import collect, exact_match, validate_body


def test_exact_match_does_not_select_decree_for_act():
    rows=[{'법령명한글':'금융소비자 보호에 관한 법률 시행령'},
          {'법령명한글':'금융소비자 보호에 관한 법률'}]
    assert exact_match(rows,'금융소비자 보호에 관한 법률','법령명한글') == rows[1]
    with pytest.raises(ValueError,match='2개'):
        exact_match([rows[1],rows[1]],rows[1]['법령명한글'],'법령명한글')


def test_fake_collection_preserves_versions_and_redacts_key(tmp_path):
    names={}
    def handler(request):
        params=request.url.params
        assert params['OC'] == 'test-secret-only'
        if 'query' in params:
            name=params['query'];target=params['target'];names[target]=name
            row={'법령명한글':name,'법령ID':'001','법령일련번호':'v1','시행일자':'20260102'}
            if target=='admrul':
                assert params['nw']=='1'
                row={'행정규칙명':name,'행정규칙ID':'002','행정규칙일련번호':'r1','시행일자':'20260102'}
            else:
                assert params['nw']=='3'
            return httpx.Response(200,json={'Search':{'totalCnt':'1',('law' if target=='eflaw' else 'admrul'):row}})
        target=params['target'];name=names[target]
        if target=='eflaw':
            data={'법령':{'기본정보':{'법령명_한글':name},'조문':{'조문단위':{'조문내용':'합성 본문'}}}}
        else:
            data={'AdmRulService':{'행정규칙기본정보':{'행정규칙명':name},'조문내용':['합성 본문']}}
        data['echo']='test-secret-only'
        return httpx.Response(200,json=data)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        manifest=collect(tmp_path,'test-secret-only',client=client)
    assert manifest['status']=='downloaded'
    assert manifest['ready_for_embedding'] is False
    assert len(manifest['documents'])==3
    for path in tmp_path.glob('*.json'):
        assert 'test-secret-only' not in path.read_text()
    for doc in manifest['documents']:
        assert doc['sha256']
        assert 'OC=' not in doc['source_url']


def test_http_200_error_is_not_a_valid_body():
    with pytest.raises(ValueError):
        validate_body({'error':'synthetic'},'규정명','eflaw')


def test_collected_real_bodies_match_catalog():
    from ingest.load import CATALOG
    directory=Path(__file__).resolve().parents[2]/'data/regulations/raw/20261021T043743991211Z'
    for slug,name,target in CATALOG:
        validate_body(json.loads((directory/f'{slug}.json').read_text()),name,target)
