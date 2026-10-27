import httpx
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings


def test_health_does_not_require_or_call_groq(monkeypatch):
    def ready(url, **kwargs):
        assert str(url) == "http://localhost:6333/readyz"
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "get", ready)
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "qdrant": "ready", "generation": "not_configured"
    }


def test_dependency_failure_is_sanitized(monkeypatch):
    def unavailable(url, **kwargs):
        raise httpx.ConnectError("internal-sensitive-detail")

    monkeypatch.setattr(httpx, "get", unavailable)
    settings = Settings(_env_file=None, groq_api_key="private-test-key", groq_model="test")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["qdrant"] == "unavailable"
    assert response.json()["generation"] == "configured_not_verified"
    assert "private-test-key" not in response.text
    assert "internal-sensitive-detail" not in response.text
