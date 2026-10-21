"""법제처 원본 → 내부 규정. 조문 전체를 보존하며 검색용 세분화는 하지 않는다."""

import json
import re
from datetime import datetime
from hashlib import sha256
from urllib.parse import parse_qsl, urlsplit

from app.schemas.external.law import LawArticleResponse
from app.schemas.regulation import RegulationChunk


def text_parts(value):
    """목내용의 중첩 목록을 순서대로 펼치되 각 문자열은 그대로 보존한다."""
    if isinstance(value, str):
        return [value]
    return [part for child in value for part in text_parts(child)]


def normalize_regulations(
    response: LawArticleResponse, *, fetched_at: datetime, source_url: str,
) -> list[RegulationChunk]:
    """조문당 청크 하나를 반환한다. 네트워크·LLM·임베딩에 의존하지 않는다.

    버전은 응답의 법령키 + 조문 내용 해시로 식별한다. 공식 이력 버전이나
    효력 종료일을 추정하지 않는다. 조회 시각은 ID에 포함하지 않는다.
    """
    url = urlsplit(source_url)
    sensitive = {"oc", "auth", "api_key", "apikey"}
    if url.username or url.password or any(k.lower() in sensitive for k, _ in parse_qsl(url.query)):
        raise ValueError("출처 URL에서 인증정보를 제거해야 합니다")
    law = response.law
    chunks = []
    seen = set()
    hierarchy = []
    for index, article in enumerate(law.article_collection.articles):
        if article.article_kind == '전문':
            match = re.search(r'제\d+(?:의\d+)?(편|장|절|관)', article.text)
            if match:
                level = '편장절관'.index(match.group(1))
                hierarchy = [(rank, text) for rank, text in hierarchy if rank < level]
                hierarchy.append((level, article.text))
            continue
        if article.article_kind != '조문':
            raise ValueError(f'지원하지 않는 조문 구분: {article.article_kind}')
        if article.article_key in seen:
            raise ValueError("동일 조문키가 응답에 중복되었습니다")
        seen.add(article.article_key)
        # 청킹 전 원문을 합친다. 각 본문 문자열의 공백·줄바꿈은 수정하지 않는다.
        parts = [article.text]
        for paragraph in article.paragraphs:
            if paragraph.text is not None:
                parts.append(paragraph.text)
            for item in paragraph.items:
                parts.append(item.text)
                for subitem in item.subitems:
                    parts.extend(text_parts(subitem.text))
        serialized = json.dumps(
            article.model_dump(mode="json", by_alias=True, exclude_unset=True),
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        digest = sha256(serialized.encode("utf-8")).hexdigest()
        version_id = f"{law.law_key}:{digest}"
        chunks.append(RegulationChunk(
            chunk_id=f"law:{law.basic_info.law_id}:{version_id}:{article.article_key}",
            law_id=law.basic_info.law_id, version_id=version_id,
            law_name=law.basic_info.name,
            article_no=article.number + (f'의{article.branch_number}' if article.branch_number else ''),
            hierarchy=[text for _, text in hierarchy],
            source_path='/법령/조문/조문단위',
            title=article.title or None, text="\n".join(parts),
            effective_from=datetime.strptime(article.effective_date, "%Y%m%d").date(),
            effective_to=None, source_url=source_url, fetched_at=fetched_at,
        ))
    return chunks
