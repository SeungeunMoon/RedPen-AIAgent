"""AI 단계에서 복구·실패 상태로 다룰 수 있는 명시적 업무 오류."""


class StageOutputError(ValueError):
    """보완 요청 후에도 모델 출력이나 근거 참조가 계약에 맞지 않는다."""
