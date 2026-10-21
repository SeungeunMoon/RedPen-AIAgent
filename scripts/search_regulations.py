"""LLM 판정 없이 검색 질의 하나의 근거·순위·원문을 확인한다."""

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path
from time import perf_counter

from app.core.config import Settings
from app.core.environment import load_runtime_environment
from app.kb.search import RagRegulationProvider
from app.schemas.claim import Claim


async def run(args):
    overrides = {'rag_search_method':args.method, 'rag_top_k':args.k,
                 'rag_max_chunks':args.max_chunks}
    if args.index_report:
        overrides['rag_index_report'] = args.index_report
    settings = Settings(**overrides)
    provider = await asyncio.to_thread(RagRegulationProvider.from_settings, settings)
    start = perf_counter()
    try:
        if args.mode == 'single':
            chunks = await provider.search_query(args.query, as_of_date=args.as_of_date, k=args.k)
        else:
            chunks = await provider.provide([Claim(id='cli-claim', quote=args.query, kind='other')], as_of_date=args.as_of_date)
    finally:
        await provider.aclose()
    payload = {
        'query':args.query,'as_of_date':args.as_of_date.isoformat(),
        'mode':args.mode,'method':args.method,'k':args.k,'max_chunks':args.max_chunks,
        'index_report':str(settings.rag_index_report),'embedding_model':settings.embedding_model,
        'latency_ms':round((perf_counter()-start)*1000,2),
        'results':[{'rank':rank, **chunk.model_dump(mode='json')} for rank, chunk in enumerate(chunks,1)],
    }
    text = json.dumps(payload,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text,encoding='utf-8')
    print(text,end='')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query',required=True)
    parser.add_argument('--as-of-date',type=date.fromisoformat,default=date(2026,10,21))
    parser.add_argument('--method',choices=['dense','mmr'],default='dense')
    parser.add_argument('--mode',choices=['single','provider'],default='single',
                        help='single: 단일 질의, provider: 운영의 일반 광고 질의와 함께 검색')
    parser.add_argument('--k',type=int,default=4)
    parser.add_argument('--max-chunks',type=int,default=12)
    parser.add_argument('--index-report',type=Path)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    if not args.query.strip() or not 1 <= args.k <= 20 or not 1 <= args.max_chunks <= 40:
        parser.error('질의는 비어 있을 수 없으며 k=1~20, max-chunks=1~40이어야 합니다')
    load_runtime_environment()
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
