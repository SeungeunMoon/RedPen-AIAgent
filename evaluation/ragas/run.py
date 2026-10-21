"""규정 검색 샘플 수집 → OpenAI judge를 사용하는 RAGAS 검색 평가 CLI."""

import argparse
import asyncio
import hashlib
import json
import math
from datetime import date, datetime, timezone
from importlib.metadata import version
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import Settings
from app.core.environment import load_runtime_environment
from app.kb.search import RagRegulationProvider
from app.schemas.claim import Claim
from app.schemas.regulation import NonBlankText
from evaluation.ragas.config import EvaluatorSettings
from evaluation.retrieval.run import ROOT, validate_cases


class EvaluationSample(BaseModel):
    model_config = ConfigDict(extra='forbid')
    case_id: NonBlankText
    user_input: NonBlankText
    reference: NonBlankText
    reference_contexts: list[NonBlankText] = Field(min_length=1)
    retrieved_contexts: list[NonBlankText]
    retrieved_ids: list[NonBlankText]

    @model_validator(mode='after')
    def align_context_ids(self):
        if len(self.retrieved_ids) != len(self.retrieved_contexts):
            raise ValueError('검색 원문과 ID의 개수가 다릅니다')
        if len(set(self.retrieved_ids)) != len(self.retrieved_ids):
            raise ValueError('검색 ID가 중복되었습니다')
        return self


def read_cases(args):
    raw, cases = validate_cases(args.cases,args.normalized)
    refs = json.loads(args.references.read_text(encoding='utf-8'))
    for case in cases:
        if not refs['references'].get(case.id,'').strip():
            raise ValueError(f'참고답안이 없습니다: {case.id}')
    return raw,cases[:args.limit],refs


def read_samples(path, limit):
    bundle = json.loads(path.read_text(encoding='utf-8'))
    if bundle.get('schema_version') != 1 or bundle.get('status') != 'prepared':
        raise ValueError('prepared 상태의 평가 샘플이 필요합니다')
    samples = [EvaluationSample.model_validate(sample) for sample in bundle['samples']]
    if not samples or len({s.case_id for s in samples}) != len(samples):
        raise ValueError('평가 샘플이 비었거나 case_id가 중복되었습니다')
    return bundle,samples[:limit]


async def collect(args):
    raw,cases,refs = read_cases(args)
    overrides = {'rag_search_method':args.method,'rag_top_k':args.k,'rag_max_chunks':args.max_chunks}
    if args.index_report:
        overrides['rag_index_report'] = args.index_report
    settings = Settings(**overrides)
    report = json.loads(settings.rag_index_report.read_text(encoding='utf-8'))
    provider = await asyncio.to_thread(RagRegulationProvider.from_settings,settings)
    samples = []
    try:
        for case in cases:
            if args.mode == 'single':
                chunks = await provider.search_query(case.query,as_of_date=date.fromisoformat(raw['as_of_date']),k=args.k)
            else:
                chunks = await provider.provide([Claim(id=case.id,quote=case.query,kind='other')],as_of_date=date.fromisoformat(raw['as_of_date']))
            samples.append(EvaluationSample(
                case_id=case.id,user_input=case.query,reference=refs['references'][case.id],
                reference_contexts=[target.quote for target in case.targets],
                retrieved_contexts=[f'{chunk.law_name} 제{chunk.article_no}조\n{chunk.text}' for chunk in chunks],
                retrieved_ids=[chunk.chunk_id for chunk in chunks],
            ))
    finally:
        await provider.aclose()
    return {'schema_version':1,'status':'prepared','as_of_date':raw['as_of_date'],
            'cases_sha256':hashlib.sha256(args.cases.read_bytes()).hexdigest(),
            'references_sha256':hashlib.sha256(args.references.read_bytes()).hexdigest(),
            'provenance':[raw['provenance'],refs['provenance']],
            'retrieval':{'table_name':report['table_name'],'corpus_hash':report['corpus_hash'],
                         'embedding':report['embedding'],'method':args.method,'k':args.k,
                         'mode':args.mode,'max_chunks':args.max_chunks},
            'samples':[sample.model_dump() for sample in samples]},samples


async def score_samples(samples, metrics, timeout_seconds):
    records = []
    for sample in samples:
        scores = {}
        for name,metric in metrics.items():
            if not sample.retrieved_contexts:
                scores[name] = {'status':'unscored','value':None,'error_type':'EmptyRetrievedContexts'}
                continue
            try:
                result = await asyncio.wait_for(metric.ascore(
                    user_input=sample.user_input,retrieved_contexts=sample.retrieved_contexts,
                    reference=sample.reference),timeout=timeout_seconds)
                value = float(result.value)
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError('유효하지 않은 평가 점수')
                scores[name] = {'status':'scored','value':value}
            except Exception as error:
                # 모델 응답/인증 헤더가 포함될 수 있는 예외 문자열은 기록하지 않는다.
                scores[name] = {'status':'failed','value':None,'error_type':type(error).__name__}
                code = getattr(error,'code',None)
                if isinstance(code,str) and code in {'insufficient_quota','rate_limit_exceeded','invalid_api_key'}:
                    scores[name]['error_code'] = code
                status = getattr(error,'status_code',None)
                if isinstance(status,int):
                    scores[name]['http_status'] = status
        records.append({'case_id':sample.case_id,'metrics':scores})
        print(f'{sample.case_id}: {json.dumps(scores,ensure_ascii=False)}',flush=True)
    summary = {}
    for name in metrics:
        values = [r['metrics'][name]['value'] for r in records if r['metrics'][name]['status']=='scored']
        summary[name] = {'mean':sum(values)/len(values) if values else None,
                         'scored':len(values),'total':len(samples),'unscored':len(samples)-len(values)}
    return records,summary


async def publish(payload,args):
    from evaluation.ragas.tracking import upload_result
    try:
        payload['langsmith'] = await asyncio.to_thread(upload_result,payload,args.experiment_name)
        print('LangSmith:',payload['langsmith']['url'])
    except Exception as error:
        payload['langsmith'] = {'status':'failed','error_type':type(error).__name__}
        print('LangSmith 업로드 실패:',type(error).__name__, '로컬 결과는 보존됩니다.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


async def run(args):
    if getattr(args,'upload_result',None):
        payload = json.loads(args.upload_result.read_text(encoding='utf-8'))
        if args.dry_run:
            print('dry-run: 저장 결과 업로드 예정. 외부 호출 없음')
            return 0
        await publish(payload,args)
        print('결과:',args.output)
        return 0 if payload['langsmith']['status']=='uploaded' else 1
    evaluator = EvaluatorSettings(**({'model':args.model} if args.model else {}))
    if args.samples:
        bundle,samples = read_samples(args.samples,args.limit)
        bundle = {**bundle,'input_samples_sha256':hashlib.sha256(args.samples.read_bytes()).hexdigest()}
        count = len(samples)
    else:
        _,cases,_ = read_cases(args)
        count = len(cases)
    if args.dry_run:
        print(json.dumps({'status':'dry_run','case_count':count,'judge_model':evaluator.model,
                          'judge_api_key_configured':evaluator.api_key is not None,
                          'metrics':args.metrics,'api_calls':0,'db_calls':0,
                          'next_step':'--dry-run을 빼면 저장 샘플을 OpenAI로 채점' if args.samples else '--prepare-only로 검색 결과 저장 후 --samples로 평가'},ensure_ascii=False,indent=2))
        return 0
    judge = None
    if not args.prepare_only:
        from evaluation.ragas.judge import create_judge
        judge = create_judge(evaluator)
    if not args.samples:
        bundle,samples = await collect(args)
    if args.prepare_only:
        payload = bundle
    else:
        from ragas.metrics.collections import ContextPrecision,ContextRecall
        classes = {'context_precision':ContextPrecision,'context_recall':ContextRecall}
        metrics = {name:classes[name](llm=judge) for name in args.metrics}
        records,summary = await score_samples(samples,metrics,evaluator.metric_timeout_seconds)
        complete = all(value['unscored']==0 for value in summary.values())
        payload = {**bundle,'samples':[s.model_dump() for s in samples],
                   'status':'scored' if complete else 'incomplete',
                   'ragas_version':version('ragas'),
                   'judge':{'provider':'openai','model':evaluator.model,'temperature':0,
                            'timeout_seconds':evaluator.timeout_seconds,'max_retries':evaluator.max_retries},
                   'records':records,'summary':summary,'judge_calls':judge.calls,
                   'notes':['검색 평가이며 광고 추출·판정 LLM은 호출하지 않는다.',
                            '참고답안은 개발 초안이다. 독립 평가 및 법적 정확성 검증이 아니다.',
                            '평가 실패는 0점으로 바꾸지 않고 평균에서 제외하며 성공 수를 함께 표시한다.']}
    if not args.prepare_only:
        payload['prepared_at'] = bundle.get('created_at')
    payload['created_at'] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('결과:',args.output)
    if getattr(args,'langsmith',False) and not args.prepare_only:
        await publish(payload,args)
        if payload['langsmith']['status'] != 'uploaded':
            return 1
    return 0 if payload['status'] in {'prepared','scored'} else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,default=ROOT/'evaluation/retrieval/cases.json')
    parser.add_argument('--references',type=Path,default=ROOT/'evaluation/ragas/references.json')
    parser.add_argument('--normalized',type=Path,default=ROOT/'data/regulations/processed/20261021T043743991211Z-whole-article-v1')
    parser.add_argument('--index-report',type=Path)
    parser.add_argument('--method',choices=['dense','mmr'],default='dense')
    parser.add_argument('--mode',choices=['single','provider'],default='single')
    parser.add_argument('--k',type=int,default=4)
    parser.add_argument('--max-chunks',type=int,default=12)
    parser.add_argument('--limit',type=int,default=1)
    parser.add_argument('--model',help='평가 전용 OpenAI 모델. RAGAS_MODEL보다 우선')
    parser.add_argument('--metrics',nargs='+',choices=['context_precision','context_recall'],default=['context_precision','context_recall'])
    parser.add_argument('--samples',type=Path,help='저장한 검색 결과를 평가. DB·Ollama 재접속 없음')
    parser.add_argument('--prepare-only',action='store_true',help='검색 결과 수집만 수행. OpenAI 호출 없음')
    parser.add_argument('--dry-run',action='store_true',help='설정·데이터 검증만 수행. 외부 호출 없음')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--langsmith',action='store_true',help='평가 후 LangSmith 실험 등록 및 링크 출력')
    parser.add_argument('--experiment-name',default='regulation-ragas',help='실험 이름 접두사. 고유 접미사는 자동 부여')
    parser.add_argument('--upload-result',type=Path,help='기존 채점 결과를 LangSmith에 등록. OpenAI/검색 재실행 없음')
    args = parser.parse_args()
    args.output = args.output or ROOT/'.local/troubleshooting/artifacts'/('ragas-samples.json' if args.prepare_only else 'ragas-result.json')
    if args.upload_result and (args.samples or args.prepare_only):
        parser.error('--upload-result는 --samples/--prepare-only와 함께 지정할 수 없습니다')
    if args.prepare_only and args.langsmith:
        parser.error('--langsmith는 채점 결과에만 적용됩니다')
    if args.limit<1 or not 1<=args.k<=20 or not 1<=args.max_chunks<=40:
        parser.error('limit는 1 이상, k는 1~20, max-chunks는 1~40으로 지정하세요')
    if args.samples and (args.prepare_only or args.samples.resolve()==args.output.resolve()):
        parser.error('--samples 입력을 덮어쓰거나 --prepare-only와 함께 지정할 수 없습니다')
    load_runtime_environment()
    try:
        status = asyncio.run(run(args))
    except Exception as error:
        message = str(error) if type(error) is ValueError else type(error).__name__
        parser.exit(1,f'RAGAS 평가를 시작할 수 없습니다: {message}\n')
    parser.exit(status)


if __name__ == '__main__':
    main()
