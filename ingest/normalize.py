"""수집 manifest를 검증하고 전체 응답을 정규화한다. 임베딩은 수행하지 않는다."""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.external.administrative_rule import AdministrativeRuleResponse
from app.schemas.external.law import LawArticleResponse
from app.schemas.regulation import RegulationChunk
from mcp_servers.korean_law.normalize import normalize_regulations
from mcp_servers.korean_law.normalize_admin import normalize_administrative_rule

ROOT = Path(__file__).resolve().parents[1]


class NormalizedDocument(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_id: str
    source_version_id: str
    source_kind: Literal['law','administrative_rule']
    name: str
    raw_file: str
    raw_sha256: str
    chunks: list[RegulationChunk]
    headings: list[dict[str, JsonValue]] = Field(default_factory=list)
    supplementary: dict[str, JsonValue] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def normalize_document(raw: dict, record: dict) -> NormalizedDocument:
    fetched_at = datetime.fromisoformat(record['fetched_at'])
    if record['target'] == 'eflaw':
        response = LawArticleResponse.model_validate(raw)
        if response.law.basic_info.law_id != record['document_id']:
            raise ValueError('manifest와 법령 ID 불일치')
        actual_name = response.law.basic_info.name
        chunks = normalize_regulations(response,fetched_at=fetched_at,source_url=record['source_url'])
        source = raw['법령']
        articles = source['조문']['조문단위']
        is_list = isinstance(articles,list)
        articles = articles if is_list else [articles]
        headings = [a for a in articles if a.get('조문여부','조문') == '전문']
        paths = {a['조문키']: '/법령/조문/조문단위'+(f'/{i}' if is_list else '')
                 for i,a in enumerate(articles) if a.get('조문여부','조문') == '조문'}
        for chunk, article in zip(chunks,[a for a in articles if a.get('조문여부','조문') == '조문']):
            chunk.source_path = paths[article['조문키']]
        kind = 'law'
        ignored = {'법령키','기본정보','조문'}
    elif record['target'] == 'admrul':
        response = AdministrativeRuleResponse.model_validate(raw)
        if response.rule.info.rule_id != record['document_id'] or response.rule.info.serial_number != record['version_id']:
            raise ValueError('manifest와 행정규칙 ID·버전 불일치')
        actual_name = response.rule.info.name
        chunks = normalize_administrative_rule(response,fetched_at=fetched_at,source_url=record['source_url'])
        source = raw['AdmRulService']
        headings = []
        kind = 'administrative_rule'
        ignored = {'행정규칙기본정보','조문내용'}
    else:
        raise ValueError('지원하지 않는 원천 종류')
    if ''.join(actual_name.split()) != ''.join(record['name'].split()):
        raise ValueError('manifest와 규정명 불일치')
    # 부칙·별표·개정문·첨부 링크 등 본문 외 영역은 원본 JSON 구조 그대로 보존.
    # 효력 해석·표 정규화 전에는 검색 대상으로 자동 포함하지 않는다.
    supplementary = {k:v for k,v in source.items() if k not in ignored}
    return NormalizedDocument(
        document_id=record['document_id'],source_version_id=record['version_id'],
        source_kind=kind,name=actual_name,raw_file=record['body_file'],raw_sha256=record['sha256'],
        chunks=chunks,headings=headings,supplementary=supplementary,
        warnings=['효력 종료일은 미확정이며 과거 시점 유효성을 보장하지 않습니다.',
                  '부칙·별표·첨부자료는 보존했지만 아직 검색·임베딩 대상이 아닙니다.'],
    )


def normalize_snapshot(input_dir: Path, output_dir: Path):
    manifest = json.loads((input_dir/'manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'downloaded':
        raise ValueError('정상 수집 완료된 manifest만 정규화합니다')
    # 전체를 검증한 뒤 새 출력 폴더를 만든다. 실패하면 일부 성공을 정상 corpus로 남기지 않는다.
    documents = []
    for record in manifest['documents']:
        if record['status'] != 'downloaded_unprocessed':
            raise ValueError('수집 실패 또는 미완료 규정이 있습니다')
        path = (input_dir/record['body_file']).resolve()
        if not path.is_relative_to(input_dir.resolve()):
            raise ValueError('원본 파일 경로가 수집 폴더 밖입니다')
        raw_bytes = path.read_bytes()
        if hashlib.sha256(raw_bytes).hexdigest() != record['sha256']:
            raise ValueError('원본 파일 해시 불일치')
        documents.append(normalize_document(json.loads(raw_bytes),record))
    if not documents:
        raise ValueError('규정 원본이 없습니다')
    output_dir.mkdir(parents=True,exist_ok=False)
    summary = {'schema_version':1,'normalization_version':'whole-article-v1',
               'raw_snapshot':input_dir.name,'status':'normalized',
               'ready_for_embedding':False,'supplementary_indexed':False,'documents':[]}
    for record,doc in zip(manifest['documents'],documents):
        name=record['slug']+'.normalized.json'
        text=doc.model_dump_json(indent=2)+'\n'
        (output_dir/name).write_text(text,encoding='utf-8')
        summary['documents'].append({'name':doc.name,'file':name,'document_id':doc.document_id,
            'source_version_id':doc.source_version_id,'articles':len(doc.chunks),
            'headings':len(doc.headings),'supplementary_sections':list(doc.supplementary),
            'sha256':hashlib.sha256(text.encode()).hexdigest()})
        print(f'{doc.name}: 조문 {len(doc.chunks)}개 / 구조 제목 {len(doc.headings)}개 / 부속 영역 {list(doc.supplementary)}')
    (output_dir/'manifest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    output=args.output or ROOT/'data/regulations/processed'/(args.input.name+'-whole-article-v1')
    normalize_snapshot(args.input,output)
    print('저장 위치:',output)


if __name__ == '__main__':
    main()
