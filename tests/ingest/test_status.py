"""AI 호출 없이 적재 누락·변조·차원 오류를 구별하는 상태 점검 계약."""

import json

import pytest
from langchain_core.documents import Document

from app.core.config import Settings
from ingest.status import check_status, inspect_rows


def document():
    return Document(id='a',page_content='합성 규정 원문',metadata={'regulation':{'article_no':'1'}})


def row():
    doc = document()
    return {'langchain_id':doc.id,'content':doc.page_content,
            'langchain_metadata':doc.metadata,'dimensions':1024}


def test_ready_requires_exact_content_metadata_and_dimension():
    result = inspect_rows([document()],[row()],1024)
    assert result['status'] == 'ready'
    assert result['stored_chunks'] == result['expected_chunks'] == 1


@pytest.mark.parametrize('field,value,problem',[
    ('dimensions',None,'missing_vectors'),
    ('dimensions',1536,'wrong_dimensions'),
    ('content','합성 변조','content_or_metadata_mismatch'),
    ('langchain_metadata',{},'content_or_metadata_mismatch'),
])
def test_invalid_rows_are_not_ready(field,value,problem):
    altered = {**row(),field:value}
    result = inspect_rows([document()],[altered],1024)
    assert result['status'] == 'invalid'
    assert result[problem] == ['a']


def test_missing_and_unexpected_ids_are_both_reported():
    result = inspect_rows([document()],[{**row(),'langchain_id':'unknown'}],1024)
    assert result['status'] == 'invalid'
    assert result['missing_ids'] == ['a']
    assert result['unexpected_ids'] == ['unknown']


def test_incomplete_report_is_rejected_without_database(tmp_path,monkeypatch):
    def unexpected_connection(*args,**kwargs):
        raise AssertionError('미완료 보고서로 DB를 조회하면 안 됩니다')
    monkeypatch.setattr('ingest.status.psycopg.connect',unexpected_connection)
    path = tmp_path/'index-report.json'
    path.write_text(json.dumps({'status':'failed'}))
    with pytest.raises(ValueError,match='완료 검증'):
        check_status(Settings(_env_file=None),path)
