from uuid import uuid4

from sqlalchemy import select

from app.database.session import SessionLocal, init_db
from app.jobs.service import claim_job, create_job
from app.models.job import Job


def test_worker_claim_is_guarded_across_sessions() -> None:
    init_db()
    key = f"test-claim-{uuid4()}"
    with SessionLocal() as creator:
        job, _ = create_job(creator, "delayed_sum", {"numbers": [1]}, key)
        job_id = job.id

    first = SessionLocal()
    second = SessionLocal()
    try:
        first_job = first.get(Job, job_id)
        second_job = second.get(Job, job_id)
        assert first_job is not None and second_job is not None
        assert claim_job(first, first_job, "worker-one") is True
        assert claim_job(second, second_job, "worker-two") is False
        refreshed = first.scalar(select(Job).where(Job.id == job_id))
        assert refreshed is not None
        assert refreshed.attempt_count == 1
        assert refreshed.celery_task_id == "worker-one"
    finally:
        first_job = first.get(Job, job_id)
        if first_job is not None:
            first.delete(first_job)
            first.commit()
        first.close()
        second.close()

