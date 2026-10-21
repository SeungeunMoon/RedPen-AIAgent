import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.schemas.claim import ExtractionResult
from app.schemas.run import ReviewDraft
from app.schemas.task import TaskEvent
from app.schemas.verdict import JudgmentResult


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('REGULATION_PROVIDER','fixed')
    monkeypatch.setenv('LANGSMITH_TRACING','false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2','false')
    from app.main import create_app
    with TestClient(create_app()) as client:
        yield client


async def fake_runner(ad_text, *, on_update, **kwargs):
    await on_update('supervisor', {'events':[
        TaskEvent(task_id='extract',status='running',attempt=1),
    ]})
    await on_update('extract', {'events':[
        TaskEvent(task_id='extract',status='running',attempt=1),
        TaskEvent(task_id='extract',status='succeeded',attempt=1),
    ]})
    return ReviewDraft(extraction=ExtractionResult(claims=[],ad_status='advertisement',
        ad_status_reason=ad_text),regulations=[],comparisons=[],judgment=JudgmentResult(verdicts=[]))


def test_health_and_real_sample_products(client):
    assert client.get('/api/health').json()['snapshot_date'] == '2026-10-21'
    products=client.get('/api/products').json()
    assert len(products) == 98
    assert products[0]['options'][0]['base_rate'] is not None


def test_create_stream_and_report_with_replay(client):
    client.app.state.manager.runner=fake_runner
    response=client.post('/api/runs',json={'ad_text':'테스트 광고','as_of_date':'2026-10-21'})
    assert response.status_code == 202
    run_id=response.json()['run_id']
    stream=client.get(f'/api/runs/{run_id}/events')
    assert stream.status_code == 200
    assert stream.text.count('event: stage') == 2
    assert 'event: done' in stream.text
    assert 'running' in stream.text and 'succeeded' in stream.text
    replay=client.get(f'/api/runs/{run_id}/events',headers={'Last-Event-ID':'2'})
    assert 'event: stage' not in replay.text
    assert 'event: done' in replay.text
    result=client.get(f'/api/runs/{run_id}').json()
    assert result['status'] == 'completed'
    assert result['report']['extraction']['ad_status_reason'] == '테스트 광고'


def test_invalid_inputs_and_unknown_run(client):
    assert client.post('/api/runs',json={'ad_text':'   ','as_of_date':'2026-10-21'}).status_code == 422
    assert client.post('/api/runs',json={'ad_text':'광고','as_of_date':'2026-10-20'}).status_code == 422
    assert client.post('/api/runs',json={'ad_text':'광고','as_of_date':'2026-10-21','product_id':'wrong'}).status_code == 422
    assert client.get('/api/runs/not-found').status_code == 404
    assert client.get('/api/not-found').status_code == 404


def test_provider_exception_is_sanitized_and_done_is_sent(client):
    async def fail(*args,**kwargs):
        raise RuntimeError('secret-token-in-url')
    client.app.state.manager.runner=fail
    run_id=client.post('/api/runs',json={'ad_text':'광고','as_of_date':'2026-10-21'}).json()['run_id']
    text=client.get(f'/api/runs/{run_id}/events').text
    assert 'event: error' in text and 'event: done' in text
    assert 'secret-token' not in text
    assert client.get(f'/api/runs/{run_id}').json()['status'] == 'failed'


def test_only_one_active_run_and_shutdown_cancels(client):
    started=asyncio.Event()
    async def waiting(*args,**kwargs):
        started.set()
        await asyncio.Event().wait()
    client.app.state.manager.runner=waiting
    body={'ad_text':'광고','as_of_date':'2026-10-21'}
    assert client.post('/api/runs',json=body).status_code == 202
    assert client.post('/api/runs',json=body).status_code == 409


def test_fastapi_serves_vue_build_and_does_not_hide_api(client,monkeypatch,tmp_path):
    import app.main as main
    (tmp_path/'index.html').write_text('<html>Vue build test</html>')
    (tmp_path/'assets').mkdir()
    (tmp_path/'assets/app.js').write_text('export const ok = true')
    monkeypatch.setattr(main,'DIST',tmp_path)
    assert 'Vue build test' in client.get('/').text
    assert client.get('/assets/app.js').status_code == 200
    assert client.get('/assets/missing.js').status_code == 404
    assert client.get('/api/missing').status_code == 404

