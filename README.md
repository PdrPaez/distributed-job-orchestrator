# Distributed Job Orchestrator

An intentionally small reference application for reliable asynchronous jobs with FastAPI, Celery, Redis, SQLite, and a React dashboard.

The implementation follows the repository specification in `Distributed Job Orchestrator — Complete Codex Implementation Specification.md`.

## Run locally

Requirements: Python 3.12+, Node 20+, npm, and Docker Desktop for Redis.

```bash
docker compose up -d redis

cd backend
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

In two additional terminals, from `backend/`, run workers with concurrency one:

```bash
celery -A app.worker.celery_app worker --loglevel=INFO --concurrency=1 --hostname=worker1@%h
celery -A app.worker.celery_app worker --loglevel=INFO --concurrency=1 --hostname=worker2@%h
```

Start the dashboard in another terminal:

```bash
cd frontend
npm ci
npm run dev
```

The API is available at `http://localhost:8000`, OpenAPI documentation at `/docs`, and the dashboard at `http://localhost:5173`.

With Redis and at least one worker running, the real-system smoke flow can be run from the repository root:

```bash
python scripts/smoke_test.py
```

The smoke script intentionally requires the external Redis service; the normal automated suite uses direct task execution and does not pretend to reproduce broker delivery.

An optional full Compose run is also available after the local Redis flow is understood:

```bash
docker compose --profile full up --build --scale worker=3
```

The worker service intentionally has no fixed container name so Compose can scale it.

### Docker Desktop on Windows

Docker Desktop must be configured to use the WSL 2 engine. If `docker info` cannot
connect to `dockerDesktopLinuxEngine`, verify that WSL has a Linux distribution:

```powershell
wsl --status
wsl --list --verbose
```

If the list is empty, install a distribution from an elevated PowerShell and
restart Docker Desktop:

```powershell
wsl --install -d Ubuntu
```

The real smoke test is intentionally not replaced with an in-process Redis mock;
it must run against Redis and Celery workers.

## Demonstration

Create a job with `POST /api/jobs`, watch its persisted status and progress, then inspect `GET /api/jobs/{job_id}` and `GET /api/jobs/{job_id}/events`. Use the same `idempotency_key` twice to receive the same Job. `unstable_demo` with `fail_until_attempt: 2` retries once and succeeds; `fail_until_attempt: 4` reaches `dead_letter` after automatic attempts 1–3, then succeeds on an explicit manual retry.

Example request:

```bash
curl -X POST http://localhost:8000/api/jobs ^
  -H "Content-Type: application/json" ^
  -d "{\"type\":\"delayed_sum\",\"payload\":{\"numbers\":[1,2,3,4],\"delay_ms\":200},\"idempotency_key\":\"demo-sum-1\"}"
```

Useful endpoints are `GET /health`, `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/events`, `POST /api/jobs/{id}/retry`, `GET /api/stats`, `GET /metrics`, and WebSocket `/ws/jobs/{id}`.

## Delivery semantics

The API idempotency key deduplicates client submissions in SQLite with a unique constraint. That is separate from Celery's at-least-once delivery: Redis/Celery may deliver a task more than once. Workers therefore reload SQLite state, claim only eligible jobs, and ignore deliveries that reach terminal states. The project does not claim exactly-once execution.

Automatic retries use a three-attempt budget and short exponential backoff. `dead_letter` means that automatic recovery is exhausted; manual retry is explicit and preserves the Job ID, idempotency key, cumulative attempt count, and JobEvent history.

## Validation

```bash
cd backend
python -m ruff check .
python -m pytest

cd ../frontend
npm ci
npm run lint
npm run build
```

## Scope

The project demonstrates at-least-once job delivery, database-backed idempotency, explicit lifecycle transitions, retries, dead-letter recovery, progress, timelines, WebSockets, metrics, and multiple workers. It intentionally excludes authentication, arbitrary code execution, workflow DAGs, cron scheduling, event sourcing, CQRS, Kubernetes, and production high-availability infrastructure.
