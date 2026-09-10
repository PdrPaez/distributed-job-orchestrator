# Changelog

## Unreleased

### Added

- Repository foundation for the Distributed Job Orchestrator.
- FastAPI API, SQLite job persistence, Celery worker integration, and three deterministic demo handlers.
- Idempotent job creation, guarded worker claims, retries, dead-letter recovery, WebSockets, metrics, and structured logs.
- React/Tailwind dashboard, local Redis integration, CI workflow, documentation, and smoke-test script.

### Changed

- Job event timelines now use persisted per-job sequence numbers for deterministic ordering.
