"""외부 API 없이 실제 RAGAS 지표와 LangChain 어댑터 계약을 검증한다."""

import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip('ragas',reason='uv sync --group eval로 평가 의존성을 설치하세요')

from langchain_core.runnables import RunnableLambda
from ragas.metrics.collections import ContextPrecision,ContextRecall

from evaluation.ragas.config import EvaluatorSettings
from evaluation.ragas.judge import LangChainRagasJudge,create_judge
from evaluation.ragas.run import EvaluationSample,ROOT,read_cases,read_samples,score_samples,run


class FakeChat:
    def with_structured_output(self,schema,**kwargs):
        assert kwargs == {'method':'json_schema','include_raw':True}
        def respond(prompt):
            if schema.__name__=='ContextPrecisionOutput':
                return schema.model_validate({'reason':'합성 관련 근거','verdict':1})
            return schema.model_validate({'classifications':[
                {'statement':'합성 문장1','reason':'일치','attributed':1},
                {'statement':'합성 문장2','reason':'미회수','attributed':0},
            ]})
        return RunnableLambda(respond)


def sample(contexts=None):
    contexts=['합성 검색 문맥'] if contexts is None else contexts
    return EvaluationSample(case_id='a',user_input='합성 질문',reference='합성 정답',
        reference_contexts=['합성 원문'],retrieved_contexts=contexts,
        retrieved_ids=[f'id{i}' for i in range(len(contexts))])


def test_actual_ragas_metrics_use_langchain_adapter():
    judge=LangChainRagasJudge(FakeChat())
    metrics={'context_precision':ContextPrecision(llm=judge),'context_recall':ContextRecall(llm=judge)}
    records,summary=asyncio.run(score_samples([sample()],metrics,10))
    assert records[0]['metrics']['context_precision']['value']==pytest.approx(1)
    assert records[0]['metrics']['context_recall']['value']==pytest.approx(0.5)
    assert summary['context_recall']['scored']==1
    assert len(judge.calls)==2
    assert judge.calls[1]['output']['classifications'][1]['attributed']==0


def test_factory_is_openai_and_independent_from_service(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER','ollama')
    monkeypatch.setenv('LLM_BASE_URL','http://localhost:11434')
    settings=EvaluatorSettings(_env_file=None,RAGAS_OPENAI_API_KEY='test-key',model='gpt-4o-mini')
    judge=create_judge(settings)
    assert judge.model.model_name=='gpt-4o-mini'
    assert judge.model.openai_api_base=='https://api.openai.com/v1'
    assert 'test-key' not in repr(settings)
    with pytest.raises(ValueError,match='API_KEY'):
        create_judge(EvaluatorSettings(_env_file=None,RAGAS_OPENAI_API_KEY=None))


def test_reference_answers_cover_existing_cases():
    args=SimpleNamespace(cases=ROOT/'evaluation/retrieval/cases.json',
        normalized=ROOT/'data/regulations/processed/20261021T043743991211Z-whole-article-v1',
        references=ROOT/'evaluation/ragas/references.json',limit=10)
    _,cases,refs=read_cases(args)
    assert len(cases)==10
    assert all(refs['references'][case.id] for case in cases)


def test_failed_scores_are_not_zero_and_nan_is_rejected():
    class FailedMetric:
        async def ascore(self,**kwargs):
            raise TimeoutError()
    class NanMetric:
        async def ascore(self,**kwargs):
            return SimpleNamespace(value=float('nan'))
    records,summary=asyncio.run(score_samples([sample()],{'timeout':FailedMetric(),'nan':NanMetric()},1))
    for name in summary:
        assert summary[name]=={'mean':None,'scored':0,'total':1,'unscored':1}
        assert records[0]['metrics'][name]['status']=='failed'
        assert records[0]['metrics'][name]['value'] is None


def test_empty_contexts_are_reported_without_judge_calls():
    class UnexpectedMetric:
        async def ascore(self,**kwargs):
            raise AssertionError('검색 결과가 비면 API를 호출하지 않는다')
    records,_=asyncio.run(score_samples([sample([])],{'context_recall':UnexpectedMetric()},1))
    assert records[0]['metrics']['context_recall']['error_type']=='EmptyRetrievedContexts'


def test_cached_sample_validation_and_ids(tmp_path):
    path=tmp_path/'samples.json'
    path.write_text(json.dumps({'schema_version':1,'status':'prepared','samples':[sample().model_dump()]}))
    _,samples=read_samples(path,1)
    assert samples[0].user_input=='합성 질문'
    with pytest.raises(ValueError,match='개수'):
        EvaluationSample.model_validate({**sample().model_dump(),'retrieved_ids':[]})


def test_dry_run_has_no_provider_calls(monkeypatch,capsys):
    def unexpected(*args,**kwargs):
        raise AssertionError('dry-run에서 외부 호출 금지')
    monkeypatch.setattr('evaluation.ragas.run.RagRegulationProvider.from_settings',unexpected)
    args=SimpleNamespace(samples=None,model=None,dry_run=True,limit=2,
        cases=ROOT/'evaluation/retrieval/cases.json',references=ROOT/'evaluation/ragas/references.json',
        normalized=ROOT/'data/regulations/processed/20261021T043743991211Z-whole-article-v1',
        metrics=['context_precision','context_recall'])
    assert asyncio.run(run(args))==0
    assert json.loads(capsys.readouterr().out)['api_calls']==0


def test_langsmith_cached_upload_reuses_dataset_and_preserves_failures():
    from evaluation.ragas.tracking import upload_result
    class FakeClient:
        def __init__(self):
            self.examples=[]
            self.datasets=0
        def has_dataset(self,**kwargs):
            return bool(self.datasets)
        def create_dataset(self,**kwargs):
            self.datasets+=1
            return SimpleNamespace(id='dataset')
        def read_dataset(self,**kwargs):
            return SimpleNamespace(id='dataset')
        def list_examples(self,**kwargs):
            return self.examples
        def create_example(self,**kwargs):
            e=SimpleNamespace(inputs=kwargs['inputs'],outputs=kwargs['outputs'])
            self.examples.append(e)
            return e
        def read_project(self,**kwargs):
            return SimpleNamespace(url='https://example.test/experiment')
    client=FakeClient()
    payload={'status':'incomplete','samples':[sample().model_dump()],
        'records':[{'case_id':'a','metrics':{
            'context_precision':{'status':'scored','value':0.5},
            'context_recall':{'status':'failed','value':None,'http_status':429}}}],
        'summary':{},'retrieval':{'method':'dense'}}
    def fake_evaluate(target,**kwargs):
        outputs=target(kwargs['data'][0].inputs)
        feedback=kwargs['evaluators'][0](SimpleNamespace(outputs=outputs),None)['results']
        assert {'key':'context_precision','score':0.5} in feedback
        assert not any(f['key']=='context_recall' for f in feedback)
        assert {'key':'context_recall_scored','score':0} in feedback
        assert kwargs['metadata']['retrieval']==payload['retrieval']
        return SimpleNamespace(experiment_name='test')
    first=upload_result(payload,'baseline',client=client,evaluate_fn=fake_evaluate)
    payload['retrieval']['method']='mmr'
    second=upload_result(payload,'mmr',client=client,evaluate_fn=fake_evaluate)
    assert first['dataset_name']==second['dataset_name']
    assert client.datasets==1 and len(client.examples)==1
    assert second['url']=='https://example.test/experiment'
