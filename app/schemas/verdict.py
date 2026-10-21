"""근거에 연결된 판정과 검증 계약. 누락 판정에는 가짜 원문 인용을 요구하지 않는다."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.regulation import NonBlankText

CheckStatus = Literal["passed", "failed", "unavailable", "not_checked"]


class VerdictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerificationResult(VerdictModel):
    source_exists: CheckStatus = "not_checked"
    wording_matches: CheckStatus = "not_checked"
    version_matches: CheckStatus = "not_checked"
    supports_verdict: CheckStatus = "not_checked"
    reason: str | None = None
    retryable: bool = False

    @property
    def passed(self) -> bool:
        return all(getattr(self, key) == "passed" for key in (
            "source_exists", "wording_matches", "version_matches", "supports_verdict",
        ))


class Verdict(VerdictModel):
    id: NonBlankText
    claim_id: NonBlankText | None = None
    checklist_item_id: NonBlankText | None = None
    violation_type: Literal["missing_notice", "disclosure_mismatch", "exaggeration", "misleading_guarantee"]
    severity: Literal["potential_violation", "caution", "needs_review"]
    reason: NonBlankText
    evidence_ids: list[NonBlankText] = Field(default_factory=list)
    unresolved_evidence_ids: list[NonBlankText] = Field(default_factory=list, description='검색 결과에 없어 근거로 인정하지 않은 모델 참조')
    original_severity: Literal['potential_violation', 'caution', 'needs_review'] | None = None
    suggested_revision: NonBlankText | None = None
    verification: VerificationResult = Field(default_factory=VerificationResult)

    @model_validator(mode="after")
    def validate_target_and_evidence(self) -> "Verdict":
        if self.violation_type == "missing_notice":
            if not self.checklist_item_id:
                raise ValueError("누락 판정에는 체크리스트 항목이 필요합니다")
        elif not self.claim_id:
            raise ValueError("문구 판정에는 클레임 ID가 필요합니다")
        if self.severity != "needs_review" and not self.evidence_ids:
            raise ValueError("위반 소지·주의 판정에는 근거가 필요합니다")
        if self.severity == "needs_review" and self.suggested_revision is not None:
            raise ValueError("사람 확인 필요 판정에는 수정안을 노출하지 않습니다")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("근거 ID는 중복될 수 없습니다")
        if self.unresolved_evidence_ids:
            if self.severity != 'needs_review':
                raise ValueError('확인되지 않은 근거가 있는 판정은 사람 확인이 필요합니다')
            if set(self.evidence_ids) & set(self.unresolved_evidence_ids):
                raise ValueError('확인된 근거와 미확인 근거는 분리해야 합니다')
        if any(getattr(self.verification, key) in ("failed", "unavailable") for key in (
            "source_exists", "wording_matches", "version_matches", "supports_verdict",
        )) and self.severity != "needs_review":
            raise ValueError("검증 실패 판정은 사람 확인 필요로 강등해야 합니다")
        return self

    def validate_evidence(self, allowed_ids: set[str]) -> None:
        if set(self.evidence_ids) - allowed_ids:
            raise ValueError("검색 결과에 없는 근거 ID입니다")


class ClaimVerdict(Verdict):
    """현재 문구 판정 출력에서는 Claim 참조가 필수다."""

    claim_id: NonBlankText = Field(description="입력 extraction.claims의 id. 판정 자체의 id와 별개")
    violation_type: Literal['disclosure_mismatch', 'exaggeration', 'misleading_guarantee']


class JudgmentResult(VerdictModel):
    verdicts: list[ClaimVerdict]
