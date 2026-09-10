"""Exercise the real HTTP API; run with FastAPI, Redis, and a worker already running."""

import json
import os
import time
import urllib.request
from urllib.error import HTTPError

BASE_URL = os.getenv("DJO_API_URL", "http://localhost:8000")


def request(method: str, path: str, body: dict | None = None) -> dict:
    payload = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def text_request(path: str) -> str:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=10) as response:
        return response.read().decode()


def wait_for_terminal(job_id: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = request("GET", f"/api/jobs/{job_id}")
        if job["status"] in {"succeeded", "failed", "dead_letter"}:
            return job
        time.sleep(0.5)
    raise TimeoutError(f"Job {job_id} did not finish")


def main() -> None:
    health = request("GET", "/health")
    assert health["status"] == "ok", health
    key = f"smoke-{time.time_ns()}"
    first = request(
        "POST",
        "/api/jobs",
        {"type": "delayed_sum", "payload": {"numbers": [1, 2, 3]}, "idempotency_key": key},
    )
    duplicate = request(
        "POST",
        "/api/jobs",
        {"type": "delayed_sum", "payload": {"numbers": [1, 2, 3]}, "idempotency_key": key},
    )
    assert first["id"] == duplicate["id"]
    completed = wait_for_terminal(first["id"])
    assert completed["status"] == "succeeded"
    assert completed["result"]["sum"] == 6
    events = request("GET", f"/api/jobs/{first['id']}/events")
    assert [event["event_type"] for event in events][:2] == ["job_created", "queued"]

    batch = request(
        "POST",
        "/api/jobs",
        {"type": "batch_transform", "payload": {"items": ["alpha", "beta"]}},
    )
    batch_completed = wait_for_terminal(batch["id"])
    assert batch_completed["status"] == "succeeded"
    assert [item["output"] for item in batch_completed["result"]["items"]] == ["ALPHA", "BETA"]

    retry = request(
        "POST",
        "/api/jobs",
        {"type": "unstable_demo", "payload": {"fail_until_attempt": 2}},
    )
    retry_completed = wait_for_terminal(retry["id"])
    assert retry_completed["status"] == "succeeded"
    assert retry_completed["attempt_count"] == 2

    dead = request(
        "POST",
        "/api/jobs",
        {"type": "unstable_demo", "payload": {"fail_until_attempt": 4}},
    )
    dead_completed = wait_for_terminal(dead["id"])
    assert dead_completed["status"] == "dead_letter"
    assert dead_completed["attempt_count"] == 3
    recovered = request("POST", f"/api/jobs/{dead['id']}/retry")
    recovered_completed = wait_for_terminal(recovered["id"])
    assert recovered_completed["status"] == "succeeded"
    assert recovered_completed["attempt_count"] == 4
    metrics = text_request("/metrics")
    assert "djo_jobs_created_total" in metrics
    assert "djo_job_retries_total" in metrics
    print("Smoke test passed")


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        raise SystemExit(f"API request failed: {error.code} {error.reason}") from error

