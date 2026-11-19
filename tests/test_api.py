"""Tests for the FastAPI bridge.

Two halves. The guards that protect the student's API key — key check, output
whitelist, body cap, rate limit — and the happy path the landing page actually
takes, which is the part a demo lives or dies on.

The pipeline itself is replaced with a canned record here. That is deliberate:
this file tests the bridge, and `tests/test_runner.py` tests the pipeline.
"""

import pytest
from fastapi.testclient import TestClient

import api


@pytest.fixture(autouse=True)
def clean_rate_limit():
    """The limiter is module state; a test must not inherit another's budget."""
    api._recent.clear()
    api._global.clear()
    yield
    api._recent.clear()
    api._global.clear()


@pytest.fixture
def client():
    return TestClient(api.app)


@pytest.fixture
def keyed(monkeypatch):
    """Pretend a key is configured, so the guards past line one can run."""
    monkeypatch.setattr(api.config, "SARVAM_API_KEY", "test-key-not-real")


def canned_run():
    """A run record shaped like the one runner.run returns."""
    return {
        "id": "abc123def456",
        "doc_name": "web-demo.txt",
        "created_at": "2026-11-19T09:00:00+00:00",
        "status": "ok",
        "words": 400,
        "chunks": 1,
        "plan": {"outputs": ["summary"], "depth": "standard", "reason": "short doc"},
        "outputs": {
            "summary": {
                "object": {"summary": "A short summary.", "bullets": ["a", "b", "c"],
                           "key_terms": ["x", "y"]},
                "score": 5,
                "defects": [],
                "rounds": 0,
                "status": "ok",
                "error": None,
            }
        },
        "translation": None,
        "trace": [],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost_inr": 0.01, "calls": 2},
        "duration_ms": 1200,
    }


# --- the guards ------------------------------------------------------------

def test_health_reports_whether_a_key_is_configured(client, monkeypatch):
    monkeypatch.setattr(api.config, "SARVAM_API_KEY", "")
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["has_key"] is False


def test_health_does_not_advertise_the_model_id(client, monkeypatch):
    """The model id is account detail, not something to hand a stranger."""
    monkeypatch.setattr(api.config, "SARVAM_API_KEY", "test-key")
    assert "model" not in client.get("/api/health").json()


def test_transform_refuses_without_a_key(client, monkeypatch):
    monkeypatch.setattr(api.config, "SARVAM_API_KEY", "")
    response = client.post("/api/transform", json={"text": "x" * 300, "outputs": ["summary"]})
    assert response.status_code == 503
    assert "API key" in response.json()["detail"]


def test_transform_refuses_too_short_text(client, keyed):
    response = client.post("/api/transform", json={"text": "short", "outputs": ["summary"]})
    assert response.status_code == 422  # pydantic min_length


def test_unknown_output_is_rejected_before_any_model_call(client, keyed):
    response = client.post("/api/transform", json={"text": "x" * 300, "outputs": ["podcast"]})
    assert response.status_code == 400
    assert "podcast" in response.json()["detail"]


def test_translation_is_not_accepted_as_an_output(client, keyed):
    """It comes from translate_to, not from the outputs list."""
    response = client.post("/api/transform", json={"text": "x" * 300, "outputs": ["translation"]})
    assert response.status_code == 400


def test_the_demo_caps_outputs_per_request(client, keyed):
    response = client.post(
        "/api/transform",
        json={"text": "x" * 300, "outputs": ["summary", "quiz", "report", "slides"]},
    )
    assert response.status_code == 400
    assert "three" in response.json()["detail"]


def test_an_oversized_body_is_refused_before_it_is_parsed(client, keyed):
    """max_length runs after the body is buffered; the middleware runs first."""
    response = client.post(
        "/api/transform",
        content=b"x" * (api.MAX_BODY_BYTES + 10),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_a_rejected_request_does_not_cost_the_visitor_their_allowance(client, keyed):
    """Validation runs before the limiter charges, so five typos do not lock you out."""
    for _ in range(api.RATE_LIMIT + 1):
        assert client.post(
            "/api/transform", json={"text": "x" * 300, "outputs": ["podcast"]}
        ).status_code == 400
    assert api._recent == {}


def test_the_rate_limit_blocks_the_sixth_run(client, keyed, monkeypatch):
    monkeypatch.setattr(api.runner, "run", lambda **kwargs: canned_run())
    monkeypatch.setattr(api.store, "save_run", lambda *a, **k: True)

    body = {"text": "x" * 300, "outputs": ["summary"]}
    for _ in range(api.RATE_LIMIT):
        assert client.post("/api/transform", json=body).status_code == 200
    assert client.post("/api/transform", json=body).status_code == 429


def test_the_process_wide_ceiling_holds_when_addresses_rotate():
    """A per-address limit alone is bypassed by rotating source addresses."""
    for index in range(api.GLOBAL_LIMIT):
        assert api._rate_limited(f"10.0.0.{index}") is False
    assert api._rate_limited("10.0.0.999") is True


def test_the_limiter_does_not_grow_without_bound():
    for index in range(50):
        api._rate_limited(f"192.168.0.{index}")
    assert len(api._recent) <= api.GLOBAL_LIMIT + 1


def test_cors_allows_the_configured_origin_and_nothing_else(client):
    """Assert the positive case: without it the test passes with no CORS at all."""
    allowed = client.get("/api/health", headers={"Origin": api.config.WEB_ORIGIN})
    assert allowed.headers.get("access-control-allow-origin") == api.config.WEB_ORIGIN

    refused = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in refused.headers


def test_stats_does_not_publish_what_the_student_spent(client):
    body = client.get("/api/stats").json()
    assert "cost_inr" not in body
    assert "runs" in body


# --- the happy path --------------------------------------------------------

def test_the_happy_path_returns_the_contract_the_page_expects(client, keyed, monkeypatch):
    saved = {}

    def record_save(record, **kwargs):
        saved["record"] = record
        saved["kwargs"] = kwargs
        return True

    monkeypatch.setattr(api.runner, "run", lambda **kwargs: canned_run())
    monkeypatch.setattr(api.store, "save_run", record_save)

    response = client.post(
        "/api/transform", json={"text": "x" * 300, "outputs": ["summary"]}
    )
    assert response.status_code == 200

    body = response.json()
    assert set(body) == {
        "id", "status", "plan", "outputs", "translation", "cost_inr", "duration_ms",
    }
    assert set(body["outputs"]["summary"]) == {"status", "score", "object"}
    assert body["outputs"]["summary"]["object"]["summary"] == "A short summary."
    assert body["status"] == "ok"

    # A stranger's pasted text is not mirrored to a cloud database and its
    # content is not kept locally.
    assert saved["kwargs"] == {"supabase": False, "keep_payload": False}


def test_a_provider_failure_returns_a_generic_message(client, keyed, monkeypatch):
    """The provider's error body can name the account; a stranger must not see it."""

    def explode(**kwargs):
        raise api.llm.LLMError(
            'HTTP 403: {"error":{"message":"insufficient_quota","org_id":"org_9x2"}}'
        )

    monkeypatch.setattr(api.runner, "run", explode)
    response = client.post("/api/transform", json={"text": "x" * 300, "outputs": ["summary"]})

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "org_9x2" not in detail
    assert "insufficient_quota" not in detail
    assert "Reference" in detail  # so a log line can be found


def test_an_internal_failure_returns_a_generic_message(client, keyed, monkeypatch):
    def explode(**kwargs):
        raise RuntimeError("secret internal detail: /home/student/.env line 4")

    monkeypatch.setattr(api.runner, "run", explode)
    response = client.post("/api/transform", json={"text": "x" * 300, "outputs": ["summary"]})

    assert response.status_code == 500
    assert "secret internal detail" not in response.json()["detail"]
