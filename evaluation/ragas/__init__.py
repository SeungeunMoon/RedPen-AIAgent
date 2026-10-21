"""RAGAS 평가 도구. 서비스 실행 경로에서는 import하지 않는다."""

import os

os.environ.setdefault('RAGAS_DO_NOT_TRACK', 'true')
