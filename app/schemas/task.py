"""Supervisor가 관리하는 작업·실행 이력 계약."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task_id: str
    kind: Literal['extract', 'retrieve', 'factcheck', 'judge']
    target_id: str = 'advertisement'
    target_kind: Literal['advertisement', 'claim'] = 'advertisement'
    status: Literal['pending', 'running', 'succeeded', 'skipped', 'failed', 'blocked'] = 'pending'
    depends_on: list[str] = Field(default_factory=list)
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=1, ge=1)
    feedback: str | None = None
    error_code: str | None = None
    retryable: bool = False


class TaskEvent(BaseModel):
    task_id: str
    status: str
    attempt: int
    reason: str | None = None
