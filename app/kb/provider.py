"""판정에 제공할 규정의 교체 가능한 계약. DB·검색 구현을 노출하지 않는다."""

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from app.schemas.claim import Claim
from app.schemas.regulation import RegulationChunk


class UnsupportedRegulationDateError(ValueError):
    """보유한 규정으로 해당 기준일의 근거를 확정할 수 없다."""


class RegulationProvider(Protocol):
    async def provide(
        self, claims: Sequence[Claim], *, as_of_date: date,
    ) -> list[RegulationChunk]:
        """클레임 검토에 제공할 근거를 반환한다. 검색 실패를 빈 정상 결과로 숨기지 않는다."""
        ...
