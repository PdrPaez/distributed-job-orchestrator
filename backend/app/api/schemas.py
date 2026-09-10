from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.job import JobStatus


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any]
    idempotency_key: str | None = Field(default=None, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def non_empty_key(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("idempotency_key cannot be empty")
        return value


class JobEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    event_type: str
    message: str
    timestamp: datetime
    metadata: dict[str, Any] | None = Field(validation_alias="event_metadata", serialization_alias="metadata")


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    type: str
    payload: dict[str, Any]
    status: JobStatus
    progress: int
    result: dict[str, Any] | None
    error_message: str | None
    idempotency_key: str
    attempt_count: int
    max_attempts: int
    celery_task_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
    duration_seconds: float | None = None


class StatsResponse(BaseModel):
    queued: int
    running: int
    retrying: int
    succeeded: int
    failed: int
    dead_letter: int
    total: int
