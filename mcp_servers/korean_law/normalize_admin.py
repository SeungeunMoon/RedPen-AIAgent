"""행정규칙 평문 조문을 같은 RegulationChunk 계약으로 변환한다."""

import re
from datetime import datetime
from hashlib import sha256
from urllib.parse import parse_qsl, urlsplit

from app.schemas.external.administrative_rule import AdministrativeRuleResponse
from app.schemas.regulation import RegulationChunk

HEADER = re.compile(r'^\s*제(?P<article>\d+)조(?:의(?P<branch>\d+))?\s*\((?P<title>[^)]+)\)')


def normalize_administrative_rule(response: AdministrativeRuleResponse, *, fetched_at: datetime,
                                  source_url: str) -> list[RegulationChunk]:
    url = urlsplit(source_url)
    if url.username or url.password or any(k.lower() in {'oc','auth','api_key','apikey'} for k,_ in parse_qsl(url.query)):
        raise ValueError('출처 URL에서 인증정보를 제거해야 합니다')
    rule = response.rule
    chunks = []
    seen = set()
    for index, text in enumerate(rule.articles):
        match = HEADER.match(text)
        if match is None:
            raise ValueError(f'행정규칙 조문 머리말을 해석할 수 없습니다: {index}')
        number = match['article'] + (f'의{match["branch"]}' if match['branch'] else '')
        if number in seen:
            raise ValueError('행정규칙 조문 번호 중복')
        seen.add(number)
        version = rule.info.serial_number + ':' + sha256(text.encode()).hexdigest()
        chunks.append(RegulationChunk(
            chunk_id=f'admrul:{rule.info.rule_id}:{version}:{number}', law_id=rule.info.rule_id,
            version_id=version, law_name=rule.info.name, source_kind='administrative_rule',
            article_no=number, title=match['title'], text=text,
            source_path=f'/AdmRulService/조문내용/{index}',
            effective_from=datetime.strptime(rule.info.effective_date,'%Y%m%d').date(),
            source_url=source_url, fetched_at=fetched_at,
        ))
    return chunks
