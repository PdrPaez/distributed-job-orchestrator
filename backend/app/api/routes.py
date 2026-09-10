import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import JobCreateRequest, JobEventResponse, JobResponse, StatsResponse
from app.config import get_settings
from app.database.session import SessionLocal, get_db
from app.jobs.handlers import JOB_REGISTRY
from app.jobs.service import add_event, create_job, fail_job, manually_retry
from app.models.job import Job, JobEvent, JobStatus
from app.worker.tasks import execute_job

router = APIRouter()


def _duration(job: Job) -> float | None:
    if not job.started_at:
        return None
    started_at = job.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    end = job.completed_at or datetime.now(UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return max(0.0, (end - started_at).total_seconds())


def _response(job: Job) -> JobResponse:
    return JobResponse.model_validate({**job.__dict__, "duration_seconds": _duration(job)})


@router.post("/api/jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job_endpoint(request: JobCreateRequest, db: Session = Depends(get_db)) -> JobResponse:
    if request.type not in JOB_REGISTRY:
        raise HTTPException(status_code=422, detail=f"Unsupported job type: {request.type}")
    key = request.idempotency_key or str(uuid4())
    try:
        job, created = create_job(db, request.type, request.payload, key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if created:
        try:
            task = execute_job.delay(str(job.id))
            job.celery_task_id = task.id
            db.commit()
        except Exception as exc:  # noqa: BLE001
            fail_job(db, job, "Unable to enqueue job")
            add_event(db, job, "enqueue_failed", "Broker publication failed")
            raise HTTPException(status_code=503, detail="Job could not be queued") from exc
    return _response(job)


@router.get("/api/jobs", response_model=list[JobResponse])
def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    job_type: str | None = Query(default=None, alias="type"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[JobResponse]:
    query = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if status_filter:
        query = query.where(Job.status == status_filter)
    if job_type:
        query = query.where(Job.type == job_type)
    return [_response(job) for job in db.scalars(query).all()]


@router.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: UUID, db: Session = Depends(get_db)) -> JobResponse:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _response(job)


@router.get("/api/jobs/{job_id}/events", response_model=list[JobEventResponse])
def get_job_events(job_id: UUID, db: Session = Depends(get_db)) -> list[JobEventResponse]:
    if not db.get(Job, job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    events = db.scalars(
        select(JobEvent)
        .where(JobEvent.job_id == job_id)
        .order_by(JobEvent.timestamp, JobEvent.sequence, JobEvent.id)
    ).all()
    return [JobEventResponse.model_validate(event) for event in events]


@router.post("/api/jobs/{job_id}/retry", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_job(job_id: UUID, db: Session = Depends(get_db)) -> JobResponse:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        manually_retry(db, job)
        task = execute_job.delay(str(job.id))
        job.celery_task_id = task.id
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        fail_job(db, job, "Unable to enqueue manual retry")
        add_event(db, job, "enqueue_failed", "Broker publication failed for manual retry")
        raise HTTPException(status_code=503, detail="Job could not be queued") from exc
    return _response(job)


@router.get("/api/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)) -> StatsResponse:
    counts = {status.value: 0 for status in JobStatus}
    rows = db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    for job_status, count in rows:
        status_value = job_status.value if isinstance(job_status, JobStatus) else job_status
        counts[status_value] = count
    return StatsResponse(**counts, total=sum(counts.values()))


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    database = "ok"
    broker = "ok"
    try:
        db.execute(select(func.count()).select_from(Job))
    except Exception:  # noqa: BLE001
        database = "error"
    try:
        redis.Redis.from_url(get_settings().redis_url).ping()
    except Exception:  # noqa: BLE001
        broker = "error"
    result = {"status": "ok" if database == broker == "ok" else "degraded", "database": database, "redis": broker}
    return result


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> object:
    registry = CollectorRegistry()
    gauges = {
        "djo_jobs_created_total": Gauge("djo_jobs_created_total", "Jobs created", registry=registry),
        "djo_jobs_succeeded_total": Gauge("djo_jobs_succeeded_total", "Jobs succeeded", registry=registry),
        "djo_jobs_failed_total": Gauge("djo_jobs_failed_total", "Jobs failed", registry=registry),
        "djo_jobs_dead_lettered_total": Gauge("djo_jobs_dead_lettered_total", "Jobs dead-lettered", registry=registry),
        "djo_job_retries_total": Gauge("djo_job_retries_total", "Job retries", registry=registry),
        "djo_jobs_queued": Gauge("djo_jobs_queued", "Queued jobs", registry=registry),
        "djo_jobs_running": Gauge("djo_jobs_running", "Running jobs", registry=registry),
        "djo_job_execution_duration_seconds": Gauge(
            "djo_job_execution_duration_seconds", "Average completed job duration", registry=registry
        ),
    }
    gauges["djo_jobs_created_total"].set(db.scalar(select(func.count()).select_from(Job)) or 0)
    event_counts = dict(
        db.execute(select(JobEvent.event_type, func.count()).group_by(JobEvent.event_type)).all()
    )
    for event_type, metric_name in {
        "job_succeeded": "djo_jobs_succeeded_total",
        "job_failed": "djo_jobs_failed_total",
        "job_dead_lettered": "djo_jobs_dead_lettered_total",
        "retry_scheduled": "djo_job_retries_total",
    }.items():
        gauges[metric_name].set(event_counts.get(event_type, 0))
    status_counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    gauges["djo_jobs_queued"].set(status_counts.get(JobStatus.QUEUED, 0))
    gauges["djo_jobs_running"].set(status_counts.get(JobStatus.RUNNING, 0))
    durations = [
        (job.completed_at - job.started_at).total_seconds()
        for job in db.scalars(select(Job)).all()
        if job.completed_at and job.started_at
    ]
    gauges["djo_job_execution_duration_seconds"].set(sum(durations) / len(durations) if durations else 0)
    from fastapi.responses import Response

    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


@router.websocket("/ws/jobs/{job_id}")
async def job_socket(websocket: WebSocket, job_id: UUID) -> None:
    await websocket.accept()
    settings = get_settings()
    last_snapshot = None
    try:
        while True:
            db = SessionLocal()
            try:
                job = db.get(Job, job_id)
                if job is None:
                    await websocket.send_json({"type": "error", "detail": "Job not found"})
                    await websocket.close(code=1008)
                    return
                snapshot = _response(job).model_dump(mode="json")
            finally:
                db.close()
            encoded = json.dumps(snapshot, sort_keys=True)
            if encoded != last_snapshot:
                await websocket.send_json({"type": "job.updated", "job": snapshot})
                last_snapshot = encoded
            if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.DEAD_LETTER}:
                return
            await asyncio.sleep(settings.websocket_poll_interval_ms / 1000)
    except WebSocketDisconnect:
        return
