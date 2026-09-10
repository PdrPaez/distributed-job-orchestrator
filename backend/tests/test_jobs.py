from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database.session import SessionLocal, init_db
from app.jobs.handlers import (
    BatchTransformPayload,
    DelayedSumPayload,
    HandlerContext,
    RetryableJobError,
    UnstableDemoPayload,
    run_batch_transform,
    run_delayed_sum,
    run_unstable_demo,
)
from app.jobs.service import create_job, manually_retry
from app.jobs.state import InvalidTransition, transition, validate_progress
from app.main import app
from app.models.job import Job, JobEvent, JobStatus
from app.worker.tasks import execute_job


def test_delayed_sum_is_deterministic_and_reports_progress() -> None:
    progress: list[int] = []
    result = run_delayed_sum(
        DelayedSumPayload(numbers=[1, 2, 3], delay_ms=0),
        HandlerContext(attempt=1, update_progress=lambda value, _message: progress.append(value)),
    )

    assert result == {"sum": 6, "items_processed": 3}
    assert progress == [33, 67, 100]


def test_batch_transform_uses_stable_checksum() -> None:
    result = run_batch_transform(
        BatchTransformPayload(items=["alpha"]),
        HandlerContext(attempt=1, update_progress=lambda _value, _message: None),
    )

    assert result["items"][0]["output"] == "ALPHA"
    assert result["items"][0]["checksum"] == "8ed3f6ad685b"


def test_unstable_demo_fails_until_requested_attempt() -> None:
    context = HandlerContext(attempt=1, update_progress=lambda _value, _message: None)
    try:
        run_unstable_demo(UnstableDemoPayload(fail_until_attempt=2), context)
    except RetryableJobError:
        pass
    else:
        raise AssertionError("attempt one must be retryable")

    assert run_unstable_demo(
        UnstableDemoPayload(fail_until_attempt=2),
        HandlerContext(attempt=2, update_progress=lambda _value, _message: None),
    )["attempt"] == 2


def test_state_machine_rejects_invalid_transition() -> None:
    assert transition(JobStatus.QUEUED, JobStatus.RUNNING) == JobStatus.RUNNING
    try:
        transition(JobStatus.SUCCEEDED, JobStatus.RUNNING)
    except InvalidTransition:
        pass
    else:
        raise AssertionError("terminal jobs must not restart implicitly")


def test_progress_boundaries() -> None:
    assert validate_progress(0) == 0
    assert validate_progress(100) == 100
    for invalid in (-1, 101):
        try:
            validate_progress(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid progress must be rejected")


def test_unknown_job_type_is_rejected_at_api_boundary() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/jobs",
            json={"type": "unknown", "payload": {}, "idempotency_key": "test-unknown"},
        )

    assert response.status_code == 422


def test_duplicate_idempotency_returns_one_persisted_job(monkeypatch) -> None:
    init_db()
    monkeypatch.setattr(execute_job, "delay", lambda job_id: type("Task", (), {"id": "test-task"})())
    key = "test-idempotency-key"
    payload = {"type": "delayed_sum", "payload": {"numbers": [2, 3]}, "idempotency_key": key}
    with TestClient(app) as client:
        first = client.post("/api/jobs", json=payload)
        second = client.post("/api/jobs", json=payload)

    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    with SessionLocal() as session:
        job = session.scalar(select(Job).where(Job.idempotency_key == key))
        assert job is not None
        assert session.scalar(
            select(func.count(JobEvent.id)).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == "job_created",
            )
        ) == 1
        session.delete(job)
        session.commit()


def test_worker_completes_job_and_ignores_terminal_duplicate(monkeypatch) -> None:
    init_db()
    monkeypatch.setattr(execute_job, "delay", lambda job_id: type("Task", (), {"id": "test-task"})())
    key = "test-worker-job"
    with TestClient(app) as client:
        response = client.post(
            "/api/jobs",
            json={"type": "delayed_sum", "payload": {"numbers": [4, 5]}, "idempotency_key": key},
        )
    job_id = response.json()["id"]
    execute_job.apply(args=[job_id])
    execute_job.apply(args=[job_id])

    with SessionLocal() as session:
        job = session.get(Job, UUID(job_id))
        assert job is not None
        assert job.status == JobStatus.SUCCEEDED
        assert job.attempt_count == 1
        assert session.scalar(
            select(func.count(JobEvent.id)).where(
                JobEvent.job_id == job.id,
                JobEvent.event_type == "job_succeeded",
            )
        ) == 1
        session.delete(job)
        session.commit()


def test_unstable_job_retries_dead_letters_and_manual_retry_succeeds(monkeypatch) -> None:
    init_db()
    monkeypatch.setattr(execute_job, "apply_async", lambda *args, **kwargs: None)
    key = "test-dead-letter-recovery"
    with SessionLocal() as session:
        job, created = create_job(session, "unstable_demo", {"fail_until_attempt": 4}, key)
        assert created
        job_id = str(job.id)
        execute_job.apply(args=[job_id])
        execute_job.apply(args=[job_id])
        execute_job.apply(args=[job_id])
        session.refresh(job)
        assert job.status == JobStatus.DEAD_LETTER
        assert job.attempt_count == 3
        assert session.scalar(select(func.count(JobEvent.id)).where(JobEvent.job_id == job.id)) >= 7
        manually_retry(session, job)
        execute_job.apply(args=[job_id])
        session.refresh(job)
        assert job.status == JobStatus.SUCCEEDED
        assert job.attempt_count == 4
        session.delete(job)
        session.commit()
