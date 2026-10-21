"""근거를 제공하지 않는 LLM 단독 비교 구성."""

from collections.abc import Sequence
from datetime import date

from app.schemas.claim import Claim
from app.schemas.regulation import RegulationChunk


class EmptyRegulationProvider:
    async def provide(
        self, claims: Sequence[Claim], *, as_of_date: date,
    ) -> list[RegulationChunk]:
        return []
