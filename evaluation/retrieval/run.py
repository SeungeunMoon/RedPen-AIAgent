"""작은 합성 질의셋으로 청킹/검색 방식의 회수 성능을 비교한다."""

import argparse
import asyncio
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.core.environment import load_runtime_environment
from app.kb.search import RagRegulationProvider
from app.schemas.claim import Claim
from app.schemas.regulation import RegulationChunk
from ingest.normalize import NormalizedDocument

ROOT = Path(__file__).resolve().parents[2]


class Target(BaseModel):
    model_config = ConfigDict(extra='forbid')
    law_id: str
    article_no: str
    quote: str = Field(min_length=1)


class Case(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    query: str = Field(min_length=1)
    targets: list[Target] = Field(min_length=1)


def validate_cases(path: Path, normalized_dir: Path):
    raw = json.loads(path.read_text(encoding='utf-8'))
    cases = [Case.model_validate(case) for case in raw['cases']]
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError('정답셋이 비었거나 ID가 중복되었습니다')
    originals = {}
    for source in normalized_dir.glob('*.normalized.json'):
        doc = NormalizedDocument.model_validate_json(source.read_bytes())
        originals.update({(chunk.law_id, chunk.article_no):chunk.text for chunk in doc.chunks})
    for case in cases:
        for target in case.targets:
            if target.quote not in originals.get((target.law_id, target.article_no), ''):
                raise ValueError(f'원문에 없는 정답 인용: {case.id}')
        identities = [(t.law_id, t.article_no, t.quote) for t in case.targets]
        if len(identities) != len(set(identities)):
            raise ValueError(f'중복 정답: {case.id}')
    return raw, cases


def score(targets: list[Target], chunks: list[RegulationChunk], k: int) -> dict:
    selected = chunks[:k]
    # 조문 전체를 맞힌 경우와 실제 필요한 인용 문장을 회수한 경우를 구분한다.
    articles = {(target.law_id, target.article_no) for target in targets}
    found = {(chunk.law_id, chunk.article_no) for chunk in selected}
    matches = [any(chunk.law_id == target.law_id and chunk.article_no == target.article_no
                   and target.quote in chunk.text for chunk in selected) for target in targets]
    first = next((rank for rank, chunk in enumerate(selected, 1) if any(
        chunk.law_id == target.law_id and chunk.article_no == target.article_no and target.quote in chunk.text
        for target in targets)), None)
    return {'article_recall':len(articles & found) / len(articles),
            'evidence_recall':sum(matches) / len(matches),
            'mrr':1 / first if first else 0.0}


async def evaluate(report_path: Path, method: str, cases, as_of_date, ks):
    settings = Settings(rag_index_report=report_path, rag_search_method=method)
    provider = await asyncio.to_thread(RagRegulationProvider.from_settings, settings)
    records = []
    try:
        for case in cases:
            # 단일 질의와 운영 provider의 공통 질의 병합을 별도로 측정한다.
            for mode in ['single_query', 'provider']:
                start = perf_counter()
                if mode == 'single_query':
                    chunks = await provider.search_query(case.query, as_of_date=as_of_date, k=max(ks))
                else:
                    chunks = await provider.provide([Claim(id=case.id, quote=case.query, kind='other')], as_of_date=as_of_date)
                records.append({
                    'case_id':case.id, 'mode':mode, 'latency_ms':round((perf_counter()-start)*1000, 2),
                    'metrics':{str(k):score(case.targets, chunks, k) for k in ks},
                    'retrieved':[{'chunk_id':c.chunk_id,'law_id':c.law_id,'article_no':c.article_no,
                                  'source_path':c.source_path,'text':c.text} for c in chunks],
                })
    finally:
        await provider.aclose()
    summary = {}
    for mode in ['single_query', 'provider']:
        subset = [record for record in records if record['mode'] == mode]
        summary[mode] = {str(k):{metric:round(sum(r['metrics'][str(k)][metric] for r in subset)/len(subset),4)
                                       for metric in ['article_recall','evidence_recall','mrr']} for k in ks}
        summary[mode]['mean_latency_ms'] = round(sum(r['latency_ms'] for r in subset)/len(subset),2)
    report = json.loads(report_path.read_text())
    return {'index_report':str(report_path.relative_to(ROOT)) if report_path.is_relative_to(ROOT) else str(report_path),
            'table_name':report['table_name'],'embedding':report['embedding'], 'corpus_hash':report['corpus_hash'],
            'chunk_snapshot':report['chunk_snapshot'],'method':method,
            'provider_top_k':settings.rag_top_k,'provider_max_chunks':settings.rag_max_chunks,
            'summary':summary,'records':records}


async def run(args):
    raw, cases = validate_cases(args.cases, args.normalized)
    results = []
    for report in args.index_report:
        for method in args.methods:
            result = await evaluate(report.resolve(), method, cases, date.fromisoformat(raw['as_of_date']), args.ks)
            results.append(result)
            print(result['chunk_snapshot'], method, json.dumps(result['summary']['single_query'],ensure_ascii=False), flush=True)
    payload = {'schema_version':1, 'created_at':datetime.now(timezone.utc).isoformat(),
               'cases_sha256':hashlib.sha256(args.cases.read_bytes()).hexdigest(),
               'case_count':len(cases),'provenance':raw['provenance'],
               'notes':['개발용 작은 합성 정답셋이며 독립 테스트가 아니다.',
                        'evidence_recall은 같은 청크 내 완전 인용 일치로 계산하며 경계를 가로지르면 미회수로 본다.',
                        '순서가 고정된 단일 실행이며 캐시·워밍업 영향이 있어 속도 우열을 단정하지 않는다.'],
               'results':results}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,default=ROOT/'evaluation/retrieval/cases.json')
    parser.add_argument('--normalized',type=Path,default=ROOT/'data/regulations/processed/20261021T043743991211Z-whole-article-v1')
    parser.add_argument('--index-report',type=Path,action='append',required=True)
    parser.add_argument('--methods',nargs='+',choices=['dense','mmr'],default=['dense','mmr'])
    parser.add_argument('--ks',nargs='+',type=int,default=[1,3,5,10])
    parser.add_argument('--output',type=Path,default=ROOT/'evaluation/retrieval/results/latest.json')
    args = parser.parse_args()
    if not args.ks or min(args.ks)<1 or max(args.ks)>40:
        parser.error('K는 1~40이어야 합니다')
    load_runtime_environment()
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
