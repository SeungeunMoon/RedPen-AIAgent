"""LangGraph 실행 순서·상태 갱신·실행별 의존성 격리를 확인한다."""

import asyncio
from datetime import date

import pytest

from app.ai import workflow
from app.ai.workflow import ReviewContext, build_review_graph
from app.schemas.claim import ExtractionResult
from app.schemas.verdict import JudgmentResult


def extraction(text):
    return ExtractionResult(claims=[],ad_status='advertisement',ad_status_reason=text)


class RecordingProvider:
    def __init__(self, calls, fail=False):
        self.calls=calls
        self.fail=fail

    async def provide(self, claims, *, as_of_date):
        self.calls.append('retrieve')
        if self.fail:
            raise ValueError('규정 제공 실패')
        return []


def install_stage_doubles(monkeypatch,calls):
    async def extract(text, *, model=None):
        calls.append('extract')
        return extraction(text)

    async def judge(text, ext, regulations, comparisons, *, product=None, model=None):
        calls.append('judge')
        assert ext.ad_status_reason == text
        assert regulations == []
        assert comparisons == []
        return JudgmentResult(verdicts=[])

    monkeypatch.setattr(workflow,'extract_claims',extract)
    monkeypatch.setattr(workflow,'judge_ad',judge)


def test_actual_graph_streams_separate_node_updates(monkeypatch):
    calls=[]
    install_stage_doubles(monkeypatch,calls)
    async def run():
        return [event async for event in build_review_graph().astream(
            {'ad_text':'합성 광고','as_of_date':date(2026,10,21),'product':None},
            context=ReviewContext(provider=RecordingProvider(calls)),stream_mode='updates',
        )]
    updates=asyncio.run(run())
    assert [next(iter(u)) for u in updates] == [
        'supervisor','extract','supervisor','prepare_tasks','supervisor',
        'retrieve','supervisor','judge','supervisor','finalize',
    ]
    assert calls == ['extract','retrieve','judge']
    assert updates[-1]['finalize']['draft'].verification_status == 'not_performed'
    assert all('provider' not in update for u in updates for update in u.values())


def test_provider_failure_prevents_judgment(monkeypatch):
    calls=[]
    install_stage_doubles(monkeypatch,calls)
    with pytest.raises(ValueError,match='규정 제공 실패'):
        asyncio.run(build_review_graph().ainvoke(
            {'ad_text':'합성 광고','as_of_date':date(2026,10,21),'product':None},
            context=ReviewContext(provider=RecordingProvider(calls,fail=True)),
        ))
    assert calls == ['extract','retrieve']


def test_same_compiled_graph_isolates_concurrent_runs(monkeypatch):
    calls=[]
    install_stage_doubles(monkeypatch,calls)
    graph=build_review_graph()
    first_calls=[];second_calls=[]
    async def run():
        return await asyncio.gather(*[
            graph.ainvoke({'ad_text':text,'as_of_date':date(2026,10,21),'product':None},
                context=ReviewContext(provider=RecordingProvider(record)))
            for text,record in [('광고 A',first_calls),('광고 B',second_calls)]
        ])
    first,second=asyncio.run(run())
    assert first['draft'].extraction.ad_status_reason == '광고 A'
    assert second['draft'].extraction.ad_status_reason == '광고 B'
    assert first_calls == second_calls == ['retrieve']
    assert set(first) == {'draft'}
