"""Tests for the FastAPI bridge.

Only the endpoints that do not call a model are tested here, plus the two
guard rails that protect the key: the key check and the output whitelist.
"""

import pytest
from fastapi.testclient import TestClient

import api


@pytest.fixture
def client():
    return TestClient(api.app)


def test_health_reports_whether_a_key_is_configured(client, monkeypatch):
    monkeypatch.setattr(api.config, "SARVAM_API_KEY", "")
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["has_key"] is False
    assert "summary" in body["outputs"]


def test_transform_refuses_without_a_key(client, monkeypatch):
    monkeypatch.setattr(api.config, "SARVAM_API_KEY", "")
    response = client.post("/api/transform", json={"text": "x" * 300, "outputs": ["summary"]})
    assert response.status_code == 503
    assert "API key" in response.json()["detail"]


def test_transform_refuses_too_short_text(client):
    response = client.post("/api/transform", json={"text": "short", "outputs": ["summary"]})
    assert response.status_code == 422  # pydantic min_length


def test_unknown_output_is_rejected_before_any_model_call(client, monkeypatch):
    monkeypatch.setattr(api.config, "SARVAM_API_KEY", "test-key")
    response = client.post(
        "/api/transform", json={"text": "x" * 300, "outputs": ["podcast"]}
    )
    assert response.status_code == 400
    assert "podcast" in response.json()["detail"]


def test_the_demo_caps_outputs_per_request(client, monkeypatch):
    monkeypatch.setattr(api.config, "SARVAM_API_KEY", "test-key")
    response = client.post(
        "/api/transform",
        json={"text": "x" * 300, "outputs": ["summary", "quiz", "report", "slides"]},
    )
    assert response.status_code == 400
    assert "three" in response.json()["detail"]


def test_the_rate_limit_blocks_the_sixth_request(client, monkeypatch):
    """Five runs an hour per IP, so a public demo cannot drain the key."""
    monkeypatch.setattr(api.config, "SARVAM_API_KEY", "test-key")
    api._recent.clear()
    for _ in range(api.RATE_LIMIT):
        assert api._rate_limited("1.2.3.4") is False
    assert api._rate_limited("1.2.3.4") is True
    api._recent.clear()


def test_cors_allows_only_the_configured_origin(client):
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert response.headers.get("access-control-allow-origin") != "https://evil.example"
