"""실행 진입점에서 .env를 프로세스 환경으로 로딩한다. 터미널 설정이 우선이다."""

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def load_runtime_environment(path: Path | None = None) -> None:
    path = path if path is not None else ROOT / '.env'
    original = dict(os.environ)
    values = dotenv_values(path)
    load_dotenv(path, override=False)
    # 기존 프로젝트의 LANGCHAIN_* 설정도 공식 LANGSMITH_* 이름에 연결한다.
    aliases = {
        'LANGSMITH_TRACING': 'LANGCHAIN_TRACING_V2',
        'LANGSMITH_API_KEY': 'LANGCHAIN_API_KEY',
        'LANGSMITH_PROJECT': 'LANGCHAIN_PROJECT',
        'LANGSMITH_ENDPOINT': 'LANGCHAIN_ENDPOINT',
    }
    for modern, legacy in aliases.items():
        for source, key in ((original, modern), (original, legacy), (values, modern), (values, legacy)):
            if source.get(key):
                os.environ[modern] = source[key]
                break
