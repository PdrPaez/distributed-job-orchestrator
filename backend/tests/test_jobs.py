from fastapi.testclient import TestClient

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
from app.jobs.state import InvalidTransition, transition, validate_progress
from app.main import app
from app.models.job import JobStatus


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
