# Distributed Job Orchestrator

An intentionally small reference application for reliable asynchronous jobs with FastAPI, Celery, Redis, SQLite, and a React dashboard.

The implementation follows the repository specification in `Distributed Job Orchestrator — Complete Codex Implementation Specification.md`.

## Status

The repository foundation is established. Backend, workers, frontend, tests, and operational documentation are added incrementally by `DJO-XXX` cards.

## Scope

The project demonstrates at-least-once job delivery, database-backed idempotency, explicit lifecycle transitions, retries, dead-letter recovery, progress, timelines, WebSockets, metrics, and multiple workers. It intentionally excludes authentication, arbitrary code execution, workflow DAGs, and production high-availability infrastructure.

