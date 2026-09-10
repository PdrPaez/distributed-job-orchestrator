# Architecture

FastAPI and Celery workers share one Python package but run as separate processes. FastAPI validates requests and persists `Job` and `JobEvent` rows in SQLite, then sends only the job UUID through Redis/Celery. Workers load authoritative payload and state from SQLite, claim work with guarded lifecycle transitions, and persist progress and outcomes.

SQLite uses WAL, foreign keys, a busy timeout, short transactions, and process-safe `NullPool`. Redis is transport infrastructure, not the source of truth. The WebSocket endpoint polls SQLite for changed snapshots; it does not add a second UI message bus. Metrics are derived from durable rows and events at scrape time.

