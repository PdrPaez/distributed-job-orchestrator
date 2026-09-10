from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert set(response.json()) == {"status", "database", "redis"}
    assert response.json()["database"] == "ok"

