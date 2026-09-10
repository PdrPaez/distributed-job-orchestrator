from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.jobs.handlers import JOB_REGISTRY
from app.jobs.state import transition, validate_progress
from app.models.job import Job, JobEvent, JobStatus


def add_event(
    session: Session,
    job: Job,
    event_type: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> JobEvent:
    event = JobEvent(job_id=job.id, event_type=event_type, message=message, event_metadata=metadata)
    session.add(event)
    return event


def find_job(session: Session, job_id: UUID) -> Job | None:
    return session.get(Job, job_id)


def create_job(
    session: Session,
    job_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> tuple[Job, bool]:
    schema, _handler = JOB_REGISTRY[job_type]
    normalized = schema.model_validate(payload).model_dump()
    existing = session.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if existing:
        return existing, False
    job = Job(
        type=job_type,
        payload=normalized,
        status=JobStatus.QUEUED,
        idempotency_key=idempotency_key,
        max_attempts=get_settings().default_max_attempts,
    )
    session.add(job)
    add_event(session, job, "job_created", "Job created")
    add_event(session, job, "queued", "Job queued")
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
        if existing is None:
            raise
        return existing, False
    session.refresh(job)
    return job, True


def claim_job(session: Session, job: Job, task_id: str | None = None) -> bool:
    if job.status not in {JobStatus.QUEUED, JobStatus.RETRYING}:
        return False
    job.status = transition(job.status, JobStatus.RUNNING)
    job.attempt_count += 1
    job.started_at = datetime.now(UTC)
    job.completed_at = None
    job.celery_task_id = task_id
    job.updated_at = datetime.now(UTC)
    add_event(session, job, "worker_started", f"Worker started attempt {job.attempt_count}")
    session.commit()
    return True


def update_progress(session: Session, job: Job, progress: int, message: str | None = None) -> None:
    validate_progress(progress)
    job.progress = progress
    job.updated_at = datetime.now(UTC)
    if message and progress in {25, 50, 75, 100}:
        add_event(session, job, "progress_updated", message, {"progress": progress})
    session.commit()


def succeed_job(session: Session, job: Job, result: dict[str, Any]) -> None:
    job.status = transition(job.status, JobStatus.SUCCEEDED)
    job.progress = 100
    job.result = result
    job.error_message = None
    job.completed_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)
    add_event(session, job, "job_succeeded", "Job succeeded")
    session.commit()


def fail_job(session: Session, job: Job, message: str) -> None:
    job.status = transition(job.status, JobStatus.FAILED)
    job.error_message = message[:500]
    job.completed_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)
    add_event(session, job, "job_failed", job.error_message)
    session.commit()


def schedule_retry(session: Session, job: Job, message: str, delay: int) -> None:
    job.status = transition(job.status, JobStatus.RETRYING)
    job.progress = 0
    job.error_message = message[:500]
    job.updated_at = datetime.now(UTC)
    add_event(session, job, "attempt_failed", job.error_message)
    add_event(session, job, "retry_scheduled", f"Retry scheduled in {delay} seconds", {"delay": delay})
    session.commit()


def dead_letter_job(session: Session, job: Job, message: str) -> None:
    job.status = transition(job.status, JobStatus.DEAD_LETTER)
    job.error_message = message[:500]
    job.completed_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)
    add_event(session, job, "attempt_failed", job.error_message)
    add_event(session, job, "job_dead_lettered", "Automatic retry budget exhausted")
    session.commit()


def manually_retry(session: Session, job: Job) -> Job:
    if job.status not in {JobStatus.FAILED, JobStatus.DEAD_LETTER}:
        raise ValueError("Only failed or dead-lettered jobs can be retried manually")
    job.status = transition(job.status, JobStatus.QUEUED)
    job.progress = 0
    job.result = None
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    job.updated_at = datetime.now(UTC)
    add_event(session, job, "manual_retry", "Manual retry requested")
    add_event(session, job, "queued", "Job queued for manual retry")
    session.commit()
    return job
