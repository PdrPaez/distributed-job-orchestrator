# Job lifecycle

```text
queued -> running -> succeeded
                 -> retrying -> running
                 -> failed
                 -> dead_letter
failed/dead_letter -> queued (manual retry)
```

`max_attempts` counts automatic worker executions, including the initial attempt. A retryable failure schedules exponential backoff (`1s`, `2s`, ...); the final automatic failure becomes `dead_letter`. Manual retry is explicit operator recovery, preserves the same job and event history, and can create cumulative attempt 4 after automatic attempts 1–3.

The Job row is the current-state source of truth. JobEvents provide an audit-style timeline and are not event sourcing. Terminal duplicate deliveries are ignored so at-least-once broker behavior does not rerun completed work.

