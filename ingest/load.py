"""RAG 1단계: 공식 API에서 규정 원본과 출처·조회 버전을 확보한다.

python -m ingest.load
임베딩·DB 적재·실행 중인 provider 교체는 수행하지 않는다.
"""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, quote_plus, urlencode

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SEARCH_URL = 'https://www.law.go.kr/DRF/lawSearch.do'
BODY_URL = 'https://www.law.go.kr/DRF/lawService.do'
CATALOG = (
    ('consumer_protection_act', '금융소비자 보호에 관한 법률', 'eflaw'),
    ('enforcement_decree', '금융소비자 보호에 관한 법률 시행령', 'eflaw'),
    ('supervisory_regulation', '금융소비자 보호에 관한 감독규정', 'admrul'),
)


def exact_match(rows, name, name_field):
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise ValueError('검색 항목이 목록 또는 객체가 아닙니다')
    normalize = lambda value: ''.join(value.split())
    matches = [row for row in rows if normalize(row.get(name_field, '')) == normalize(name)]
    if len(matches) != 1:
        raise ValueError(f'정확한 현행 규정 후보가 {len(matches)}개입니다. 자동으로 버전을 선택하지 않습니다')
    return matches[0]


def redact(body, key):
    for value in {key, quote(key, safe=''), quote_plus(key)}:
        body = body.replace(value, '[REDACTED]')
    return body


def fetch_json(client, endpoint, parameters, key):
    try:
        response = client.get(endpoint, params={'OC': key, 'type': 'JSON', **parameters})
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise RuntimeError(f'외부 조회 실패: {type(error).__name__}') from None
    try:
        return json.loads(redact(response.text, key))
    except json.JSONDecodeError:
        raise ValueError('외부 응답이 JSON이 아닙니다. 인증·서비스 권한을 확인하세요') from None


def save_json(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    path.write_text(text, encoding='utf-8')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def validate_body(body, name, target):
    """HTTP 200 오류 객체를 정상 원문으로 기록하지 않도록 최소 계약을 확인한다."""
    if target == 'eflaw':
        root = body.get('법령', {})
        actual = root.get('기본정보', {}).get('법령명_한글', '')
        content = root.get('조문', {}).get('조문단위')
    else:
        root = body.get('AdmRulService', {})
        actual = root.get('행정규칙기본정보', {}).get('행정규칙명', '')
        content = root.get('조문내용')
    if ''.join(actual.split()) != ''.join(name.split()) or not content:
        raise ValueError('요청한 규정명 또는 본문 구조가 일치하지 않습니다')


def collect(output: Path, key: str, *, client=None):
    output.mkdir(parents=True, exist_ok=True)
    manifest = {'schema_version': 1, 'status': 'collecting',
                'snapshot_at': datetime.now(timezone.utc).isoformat(),
                'ready_for_embedding': False, 'documents': []}
    owns_client = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True)
    try:
        for slug, name, target in CATALOG:
            record = {'slug': slug, 'name': name, 'target': target, 'status': 'pending'}
            manifest['documents'].append(record)
            try:
                search_params = {'target': target, 'query': name,
                                 'nw': '3' if target == 'eflaw' else '1', 'display': '100', 'page': '1'}
                data = fetch_json(client, SEARCH_URL, search_params, key)
                record['search_file'] = f'{slug}.search.json'
                save_json(output / record['search_file'], data)
                item_field = 'law' if target == 'eflaw' else 'admrul'
                containers = [v for v in data.values() if isinstance(v, dict) and item_field in v]
                if len(containers) != 1:
                    raise ValueError('예상 검색 항목이 없습니다. 응답 구조·업무 오류를 확인하세요')
                container = containers[0]
                if int(container.get('totalCnt', 0)) > 100:
                    raise ValueError('검색 결과가 첫 페이지를 초과합니다. 범위를 좁히거나 페이지 처리가 필요합니다')
                name_field = '법령명한글' if target == 'eflaw' else '행정규칙명'
                chosen = exact_match(container[item_field], name, name_field)
                if target == 'eflaw':
                    params = {'target': 'eflaw', 'MST': str(chosen['법령일련번호']),
                              'efYd': str(chosen['시행일자'])}
                    record['document_id'] = str(chosen['법령ID'])
                    record['version_id'] = str(chosen['법령일련번호'])
                else:
                    params = {'target': 'admrul', 'ID': str(chosen['행정규칙일련번호'])}
                    record['document_id'] = str(chosen.get('행정규칙ID', chosen['행정규칙일련번호']))
                    record['version_id'] = str(chosen['행정규칙일련번호'])
                body = fetch_json(client, BODY_URL, params, key)
                if not body or not isinstance(body, dict):
                    raise ValueError('규정 본문이 JSON 객체가 아닙니다')
                validate_body(body, name, target)
                record.update(body_file=f'{slug}.json', request_parameters=params,
                    source_url=BODY_URL+'?'+urlencode({'type': 'JSON', **params}),
                    effective_from=str(chosen.get('시행일자', '')),
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    top_level_fields=list(body), status='downloaded_unprocessed')
                record['sha256'] = save_json(output / record['body_file'], body)
                print(f'{name}: 수신 완료 / 버전 {record["version_id"]} / 최상위 {list(body)}')
            except (ValueError, RuntimeError, KeyError, TypeError) as error:
                record['status'] = 'failed'
                # key가 들어간 예외나 URL을 저장하지 않는다.
                record['error_type'] = type(error).__name__
                print(f'{name}: 수집 실패 ({type(error).__name__}), 저장된 검색 응답 확인 필요')
            save_json(output/'manifest.json', manifest)
        manifest['status'] = 'downloaded' if all(
            r['status'] == 'downloaded_unprocessed' for r in manifest['documents']) else 'partial'
        save_json(output/'manifest.json', manifest)
        return manifest
    finally:
        if owns_client:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    key = os.environ.get('LAW_OC') or dotenv_values(ROOT/'.env').get('LAW_OC')
    if not key:
        raise SystemExit('LAW_OC를 터미널 또는 .env에 설정하세요')
    output = args.output or ROOT/'data/regulations/raw'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    manifest = collect(output, key)
    print('저장 위치:', output)
    if manifest['status'] != 'downloaded':
        raise SystemExit('일부 규정 수집 실패. manifest와 검색 응답을 확인하세요')


if __name__ == '__main__':
    main()
