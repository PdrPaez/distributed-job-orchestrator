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


def wait_for_terminal(job_id: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = request("GET", f"/api/jobs/{job_id}")
        if job["status"] in {"succeeded", "failed", "dead_letter"}:
            return job
        time.sleep(0.5)
    raise TimeoutError(f"Job {job_id} did not finish")


def main() -> None:
    request("GET", "/health")
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
    assert wait_for_terminal(first["id"])["status"] == "succeeded"

    retry = request(
        "POST",
        "/api/jobs",
        {"type": "unstable_demo", "payload": {"fail_until_attempt": 2}},
    )
    assert wait_for_terminal(retry["id"])["status"] == "succeeded"

    dead = request(
        "POST",
        "/api/jobs",
        {"type": "unstable_demo", "payload": {"fail_until_attempt": 4}},
    )
    assert wait_for_terminal(dead["id"])["status"] == "dead_letter"
    recovered = request("POST", f"/api/jobs/{dead['id']}/retry")
    assert wait_for_terminal(recovered["id"])["status"] == "succeeded"
    print("Smoke test passed")


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        raise SystemExit(f"API request failed: {error.code} {error.reason}") from error

