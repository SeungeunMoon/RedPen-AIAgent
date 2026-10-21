"""작업 정책은 LLM·네트워크 없이 검증한다."""

import asyncio
from datetime import date

from app.ai import workflow
from app.ai.supervisor import MAX_DISPATCHES, supervisor_node
from app.ai.workflow import ReviewContext, build_review_graph
from app.schemas.claim import ExtractionResult, Claim, RateClaim
from app.schemas.task import ReviewTask
from app.schemas.verdict import JudgmentResult


def test_dependency_ready_task_is_selected_and_input_is_not_mutated():
    tasks=[ReviewTask(task_id='extract',kind='extract',status='succeeded'),
           ReviewTask(task_id='retrieve',kind='retrieve',depends_on=['extract'])]
    result=supervisor_node({'tasks':tasks,'tasks_prepared':True})
    assert result['next_node'] == 'retrieve'
    assert result['tasks'][1].attempts == 1
    assert tasks[1].status == 'pending'


def test_failed_dependency_blocks_downstream():
    tasks=[ReviewTask(task_id='extract',kind='extract',status='failed'),
           ReviewTask(task_id='retrieve',kind='retrieve',depends_on=['extract']),
           ReviewTask(task_id='judge',kind='judge',depends_on=['retrieve'])]
    result=supervisor_node({'tasks':tasks,'tasks_prepared':True})
    assert result['next_node'] == 'finalize'
    assert [t.status for t in result['tasks']] == ['failed','blocked','blocked']


def test_cycles_and_dispatch_budget_terminate():
    tasks=[ReviewTask(task_id='extract',kind='extract',status='succeeded'),
           ReviewTask(task_id='a',kind='retrieve',depends_on=['b']),
           ReviewTask(task_id='b',kind='judge',depends_on=['a'])]
    result=supervisor_node({'tasks':tasks,'tasks_prepared':True})
    assert result['next_node'] == 'finalize'
    assert all(t.status=='blocked' for t in result['tasks'][1:])
    assert supervisor_node({'dispatch_count':MAX_DISPATCHES})['next_node'] == 'finalize'


def install(monkeypatch):
    calls=[]
    async def extract(text,*,model=None):
        calls.append('extract')
        return ExtractionResult(claims=[Claim(id='c1',quote='최고 4%',kind='interest_rate',
            rate=RateClaim(rate='4',rate_kind='max'))],ad_status='advertisement',ad_status_reason='합성 테스트')
    async def judge(*args,**kwargs):
        calls.append('judge')
        return JudgmentResult(verdicts=[])
    monkeypatch.setattr(workflow,'extract_claims',extract)
    monkeypatch.setattr(workflow,'judge_ad',judge)
    return calls


class TransientProvider:
    def __init__(self,failures):
        self.calls=0;self.failures=failures
    async def provide(self,claims,*,as_of_date):
        self.calls+=1
        if self.calls<=self.failures:
            raise TimeoutError('secret must not be recorded')
        return []


def run(provider):
    return asyncio.run(build_review_graph().ainvoke(
        {'ad_text':'최고 4%','as_of_date':date(2026,10,21),'product':None},
        context=ReviewContext(provider=provider)))['draft']


def test_retry_only_failed_work_and_skip_unselected_product(monkeypatch):
    calls=install(monkeypatch);provider=TransientProvider(1)
    draft=run(provider)
    assert calls == ['extract','judge']
    assert provider.calls == 2
    tasks={t.task_id:t for t in draft.tasks}
    assert tasks['retrieve'].attempts == 2
    assert tasks['factcheck:c1'].status == 'skipped'
    assert draft.comparisons[0].status == 'skipped'
    assert draft.run_status == 'completed'
    assert draft.verification_status == 'not_performed'
    assert 'secret must' not in draft.model_dump_json()


def test_exhausted_retry_is_failed_not_automatic_success(monkeypatch):
    calls=install(monkeypatch);provider=TransientProvider(99)
    draft=run(provider)
    assert provider.calls == 2
    assert calls == ['extract']
    assert draft.run_status == 'failed'
    assert draft.judgment is None
    assert draft.extraction is not None
    assert next(t for t in draft.tasks if t.task_id=='judge').status == 'blocked'


def test_invalid_model_output_is_failed_without_judging(monkeypatch):
    from app.ai.errors import StageOutputError
    async def extract(*args,**kwargs):
        raise StageOutputError('합성 계약 위반')
    monkeypatch.setattr(workflow,'extract_claims',extract)
    provider=TransientProvider(0)
    draft=run(provider)
    assert draft.run_status == 'failed'
    assert draft.extraction is None
    assert provider.calls == 0
    assert draft.tasks[0].error_code == 'StageOutputError'
