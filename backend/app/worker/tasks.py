import logging
import socket
from datetime import UTC, datetime
from uuid import UUID

from app.database.session import SessionLocal
from app.jobs.handlers import JOB_REGISTRY, HandlerContext, RetryableJobError
from app.jobs.service import (
    claim_job,
    dead_letter_job,
    fail_job,
    schedule_retry,
    succeed_job,
    update_progress,
)
from app.models.job import Job, JobStatus
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.worker.execute_job", bind=True)
def execute_job(self, job_id: str) -> None:
    session = SessionLocal()
    try:
        job = session.get(Job, UUID(job_id))
        if job is None:
            logger.warning("job_missing", extra={"job_id": job_id})
            return
        if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.DEAD_LETTER}:
            logger.info("duplicate_delivery_ignored", extra={"job_id": job_id, "status": job.status})
            return
        if not claim_job(session, job, self.request.id):
            logger.info("task_claim_skipped", extra={"job_id": job_id, "status": job.status})
            return
        attempt = job.attempt_count
        schema, handler = JOB_REGISTRY[job.type]
        payload = schema.model_validate(job.payload)
        started = datetime.now(UTC)
        logger.info(
            "job_started",
            extra={"job_id": job_id, "job_type": job.type, "attempt": attempt, "worker": socket.gethostname()},
        )
        context = HandlerContext(
            attempt=attempt,
            update_progress=lambda progress, message: update_progress(session, job, progress, message),
        )
        try:
            result = handler(payload, context)
        except RetryableJobError as exc:
            if attempt < job.max_attempts:
                delay = 2 ** (attempt - 1)
                schedule_retry(session, job, str(exc), delay)
                execute_job.apply_async(args=[job_id], countdown=delay)
            else:
                dead_letter_job(session, job, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("job_failed", extra={"job_id": job_id, "attempt": attempt})
            fail_job(session, job, str(exc))
            return
        succeed_job(session, job, result)
        logger.info(
            "job_succeeded",
            extra={
                "job_id": job_id,
                "attempt": attempt,
                "duration_seconds": (datetime.now(UTC) - started).total_seconds(),
            },
        )
    finally:
        session.close()
