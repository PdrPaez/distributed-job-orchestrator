# Design decisions

- SQLite is sufficient for a local portfolio application and is the durable domain source of truth.
- Redis is the only external service and is used as Celery transport.
- Celery messages carry only `job_id`; workers reload the persisted payload.
- There is no transactional outbox. Enqueue failures are surfaced as visible job failures.
- WebSockets poll SQLite because the dashboard does not need a second broker path.
- Metrics are derived from persistent jobs and events so HTTP and workers do not need shared metric memory.
- Dead-letter is an application state, not a separate queue product.
- The three handlers are explicit and do not execute arbitrary code.

