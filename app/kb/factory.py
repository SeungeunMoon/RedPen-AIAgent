"""화면과 CLI가 함께 사용하는 규정 공급자 선택."""

from app.core.config import PROJECT_ROOT, Settings
from app.kb.empty import EmptyRegulationProvider
from app.kb.fixed import FixedRegulationProvider
from app.kb.search import RagRegulationProvider


def create_regulation_provider(settings: Settings):
    if settings.regulation_provider == 'rag':
        return RagRegulationProvider.from_settings(settings)
    if settings.regulation_provider == 'empty':
        return EmptyRegulationProvider()
    return FixedRegulationProvider.from_law_sample(
        PROJECT_ROOT / 'samples/law/20261021T004141864078Z_article.json')
