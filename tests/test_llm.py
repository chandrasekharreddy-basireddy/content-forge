"""Tests for the Sarvam client.

No network here: requests.post is replaced with a stub that records the body
it was given. That makes the important guarantees checkable:

  - max_tokens is always sent (the API default of 2048 truncates quizzes)
  - both auth headers go out
  - response_format uses json_schema, not plain json_object
  - a 429 is retried, a 400 is not
  - translation is chunked under the 1,000 character limit
"""

import pytest

from pipeline import config, llm


class FakeResponse:
    """The bits of requests.Response that llm.py actually uses."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or str(payload)

    def json(self):
        return self._payload


def reply(content="hello", prompt_tokens=100, completion_tokens=50):
    return {
        "model": "sarvam-105b",
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    """Every test in this file pretends a key is configured."""
    monkeypatch.setattr(config, "SARVAM_API_KEY", "test-key-not-real")


@pytest.fixture
def sent(monkeypatch):
    """Records every request body, and answers with a canned reply."""
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "body": json})
        return FakeResponse(200, reply())

    monkeypatch.setattr(llm.requests, "post", fake_post)
    return calls


def test_chat_sends_the_key_both_ways(sent):
    llm.chat([{"role": "user", "content": "hi"}])
    headers = sent[0]["headers"]
    assert headers["api-subscription-key"] == "test-key-not-real"
    assert headers["Authorization"] == "Bearer test-key-not-real"


def test_max_tokens_is_always_explicit(sent):
    """Never rely on the 2048 default: a quiz gets cut off mid-JSON."""
    llm.chat([{"role": "user", "content": "hi"}])
    assert sent[0]["body"]["max_tokens"] == config.MAX_TOKENS
    assert sent[0]["body"]["max_tokens"] > 2048


def test_structured_output_uses_json_schema(sent):
    schema = {"name": "summary", "strict": True, "schema": {"type": "object"}}
    llm.chat([{"role": "user", "content": "hi"}], json_schema=schema)
    response_format = sent[0]["body"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "summary"


def test_no_response_format_when_no_schema(sent):
    llm.chat([{"role": "user", "content": "hi"}])
    assert "response_format" not in sent[0]["body"]


def test_usage_and_cost_come_back_with_the_text(sent):
    text, usage = llm.chat([{"role": "user", "content": "hi"}])
    assert text == "hello"
    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 50
    assert usage["cost_inr"] > 0


def test_a_429_is_retried_then_succeeds(monkeypatch):
    """Rate limits are normal on a free tier; retry them, with a backoff."""
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    responses = [FakeResponse(429, {"error": "slow down"}), FakeResponse(200, reply("ok"))]

    def fake_post(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(llm.requests, "post", fake_post)
    text, _ = llm.chat([{"role": "user", "content": "hi"}])
    assert text == "ok"
    assert responses == []


def test_a_400_fails_immediately(monkeypatch):
    """A bad request will never fix itself, so do not burn the rate limit."""
    attempts = []

    def fake_post(*args, **kwargs):
        attempts.append(1)
        return FakeResponse(400, {"error": "bad model id"})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    with pytest.raises(llm.LLMError) as error:
        llm.chat([{"role": "user", "content": "hi"}])
    assert "400" in str(error.value)
    assert len(attempts) == 1


def test_giving_up_after_the_retry_budget(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        llm.requests, "post", lambda *a, **k: FakeResponse(503, {"error": "down"})
    )
    with pytest.raises(llm.LLMError) as error:
        llm.chat([{"role": "user", "content": "hi"}], retries=1)
    assert "gave up" in str(error.value)


def test_no_key_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(config, "SARVAM_API_KEY", "")
    with pytest.raises(llm.LLMError) as error:
        llm.chat([{"role": "user", "content": "hi"}])
    assert ".env" in str(error.value)


def test_parse_json_handles_markdown_fences():
    fenced = '```json\n{"a": 1}\n```'
    assert llm.parse_json(fenced) == {"a": 1}


def test_parse_json_finds_an_object_in_chatter():
    assert llm.parse_json('Sure! Here you go: {"a": 2} Hope that helps.') == {"a": 2}


def test_parse_json_raises_when_there_is_nothing_to_parse():
    with pytest.raises(ValueError):
        llm.parse_json("no json at all")


def test_translation_is_chunked_under_the_limit():
    """mayura:v1 rejects anything over 1,000 characters, so we split first."""
    text = ("A sentence about a pilot programme. " * 120).strip()
    pieces = llm.split_for_translation(text, 900)
    assert len(pieces) > 1
    assert all(len(piece) <= 900 for piece in pieces)
    assert "pilot programme" in pieces[0]


def test_a_single_enormous_word_is_hard_split():
    pieces = llm.split_for_translation("x" * 2500, 900)
    assert all(len(piece) <= 900 for piece in pieces)


def test_translate_posts_each_chunk_and_joins_the_reply(monkeypatch):
    bodies = []

    def fake_post(url, headers=None, json=None, timeout=None):
        bodies.append({"url": url, "body": json})
        return FakeResponse(200, {"translated_text": "अनुवाद", "source_language_code": "en-IN"})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    result = llm.translate("Hello there. " * 200, target_language="hi-IN")

    assert result.startswith("अनुवाद")
    assert all(call["url"] == config.TRANSLATE_URL for call in bodies)
    assert all(call["body"]["target_language_code"] == "hi-IN" for call in bodies)
    assert all(call["body"]["model"] == config.TRANSLATE_MODEL for call in bodies)
    assert all(len(call["body"]["input"]) <= config.TRANSLATE_CHUNK for call in bodies)


def test_empty_translation_is_not_sent(monkeypatch):
    monkeypatch.setattr(
        llm.requests, "post", lambda *a, **k: FakeResponse(200, {"translated_text": "x"})
    )
    assert llm.translate("   ") == ""


def test_a_role_name_is_resolved_to_a_real_model_id(sent):
    """The agents ask for "fast"/"strong"; the API needs an id, not a role."""
    llm.chat([{"role": "user", "content": "hi"}], model="fast")
    assert sent[0]["body"]["model"] == config.MODEL_FAST
    assert sent[0]["body"]["model"] not in ("fast", "strong")

    llm.chat([{"role": "user", "content": "hi"}], model="strong")
    assert sent[1]["body"]["model"] == config.MODEL_STRONG


def test_a_real_model_id_passes_through_untouched(sent):
    llm.chat([{"role": "user", "content": "hi"}], model="gemma4")
    assert sent[0]["body"]["model"] == "gemma4"


def test_a_network_error_is_retried_then_raised(monkeypatch):
    """Bad wifi in a viva room is the failure this must survive."""
    import requests

    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    attempts = []

    def flaky(*args, **kwargs):
        attempts.append(1)
        raise requests.ConnectionError("dns fail")

    monkeypatch.setattr(llm.requests, "post", flaky)
    with pytest.raises(llm.LLMError) as error:
        llm.chat([{"role": "user", "content": "hi"}], retries=2)
    assert "network error" in str(error.value)
    assert len(attempts) == 3  # one try plus two retries


def test_a_reply_with_no_choices_is_an_error(monkeypatch):
    monkeypatch.setattr(
        llm.requests, "post", lambda *a, **k: FakeResponse(200, {"nope": 1})
    )
    with pytest.raises(llm.LLMError) as error:
        llm.chat([{"role": "user", "content": "hi"}])
    assert "unexpected reply shape" in str(error.value)


def test_an_empty_completion_is_an_error_not_an_empty_draft(monkeypatch):
    """finish_reason "length" is the usual cause; say so instead of shipping ""."""
    monkeypatch.setattr(
        llm.requests,
        "post",
        lambda *a, **k: FakeResponse(
            200,
            {
                "model": "sarvam-105b",
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4096},
            },
        ),
    )
    with pytest.raises(llm.LLMError) as error:
        llm.chat([{"role": "user", "content": "hi"}])
    assert "length" in str(error.value)


def test_a_translation_400_is_not_retried(monkeypatch):
    attempts = []

    def fake_post(*args, **kwargs):
        attempts.append(1)
        return FakeResponse(400, {"error": "input too long"})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    with pytest.raises(llm.LLMError):
        llm.translate("hello", target_language="hi-IN")
    assert len(attempts) == 1
