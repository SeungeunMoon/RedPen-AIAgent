"""AI 단계에서 복구·실패 상태로 다룰 수 있는 명시적 업무 오류."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError


class StageOutputError(ValueError):
    """보완 요청 후에도 모델 출력이나 근거 참조가 계약에 맞지 않는다."""

    diagnostic_id: str | None = None


    @property
    def public_reason(self) -> str:
        # 원본 모델 응답이나 임의 예외 문자열을 API에 그대로 노출하지 않는다.
        message = str(self)
        for marker, reason in {
            '근거 ID는 중복': '판정의 evidence_ids에 같은 규정 ID가 중복됐습니다.',
            '위반 소지·주의 판정에는 근거': '위반 소지·주의 판정의 evidence_ids가 비어 있습니다. 검색 근거를 연결하거나 근거 부족 시 needs_review로 두세요.',
            '알 수 없는 클레임 ID': '판정이 입력에 없는 클레임을 참조했습니다.',
            '근거 ID': '판정이 허용되지 않은 규정 근거를 참조했습니다.',
            '사람 확인 필요 판정에는 수정안': '사람 확인이 필요한 판정에 수정안이 포함됐습니다.',
            '시점과 수치를 확인하지 못한': '공시 시점·수치를 확인하지 못한 확정 판정입니다.',
            '원문에 없는': '추출 문구가 광고 원문과 일치하지 않습니다.',
        }.items():
            if marker in message:
                return reason
        return '모델 응답이 출력 스키마 검증을 통과하지 못했습니다.'



def output_failure(stage: str, error: Exception, *, raw_output=None) -> StageOutputError:
    """인증 요청 정보 없이 출력 검증 진단만 로컬의 ignored 폴더에 보존한다."""
    failure = StageOutputError(str(error))
    diagnostic_id = f'{stage}-{uuid4().hex}'
    root = Path(__file__).resolve().parents[2] / '.local/troubleshooting/diagnostics'
    payload = {
        'stage':stage, 'created_at':datetime.now(timezone.utc).isoformat(),
        'error_type':type(error).__name__,
        'error_message':str(error),
        'validation_errors':error.errors(include_input=False,include_context=False,include_url=False)
            if isinstance(error,ValidationError) else [],
        'reason':failure.public_reason, 'model_output':raw_output,
    }
    try:
        root.mkdir(parents=True,exist_ok=True)
        (root/f'{diagnostic_id}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
        failure.diagnostic_id = diagnostic_id
    except OSError:
        pass  # 진단 파일 쓰기 실패가 원래 모델 오류를 가리지 않게 한다.
    return failure
