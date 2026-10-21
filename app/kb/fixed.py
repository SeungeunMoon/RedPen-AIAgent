"""검색 없이 준비된 규정 전체를 제공한다. 네트워크·임베딩·LLM 호출 없음."""

import json
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.kb.provider import UnsupportedRegulationDateError
from app.schemas.claim import Claim
from app.schemas.external.law import LawArticleResponse
from app.schemas.regulation import RegulationChunk
from mcp_servers.korean_law.normalize import normalize_regulations


class FixedRegulationProvider:
    def __init__(self, chunks: Sequence[RegulationChunk], *, snapshot_date: date):
        ids = [chunk.chunk_id for chunk in chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("고정 규정의 청크 ID가 중복되었습니다")
        self._chunks = tuple(chunk.model_copy(deep=True) for chunk in chunks)
        self._snapshot_date = snapshot_date

    @classmethod
    def from_law_sample(cls, path: str | Path) -> "FixedRegulationProvider":
        """기존 원본과 .meta.json을 읽는다. 조회일(KST)에만 열린 효력을 인정한다."""
        path = Path(path)
        response = LawArticleResponse.model_validate_json(path.read_text(encoding="utf-8"))
        metadata = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
        if metadata["http_status"] != 200:
            raise ValueError("정상 HTTP 응답 샘플이 아닙니다")
        fetched_at = datetime.fromisoformat(metadata["fetched_at"])
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("조회 시각에 시간대가 필요합니다")
        # 인증값은 포함하지 않고 조회 대상 정보만 출처에 남긴다.
        params = {k: v for k, v in metadata["parameters"].items()
                  if k in {"target", "type", "ID", "MST", "JO"}}
        source_url = metadata["endpoint"] + "?" + urlencode(params)
        chunks = normalize_regulations(response, fetched_at=fetched_at, source_url=source_url)
        return cls(chunks, snapshot_date=fetched_at.astimezone(ZoneInfo("Asia/Seoul")).date())

    async def provide(
        self, claims: Sequence[Claim], *, as_of_date: date,
    ) -> list[RegulationChunk]:
        # fixed 구성은 클레임별 선별 없이 전체 규정을 준다. 빈 클레임도
        # 필수사항 누락 검토가 가능하도록 동일하게 처리한다.
        selected = []
        for chunk in self._chunks:
            if as_of_date < chunk.effective_from:
                continue
            if chunk.effective_to is not None:
                if as_of_date >= chunk.effective_to:
                    continue
            elif as_of_date != self._snapshot_date:
                raise UnsupportedRegulationDateError(
                    "효력 종료일 미확정 규정은 스냅샷 조회일에만 제공할 수 있습니다"
                )
            selected.append(chunk.model_copy(deep=True))
        return selected
