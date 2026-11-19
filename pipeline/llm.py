"""The only file in the project that talks to Sarvam.

Two functions matter:

    chat(...)       sends a chat conversation and returns (text, usage)
    translate(...)  sends text to the dedicated translation endpoint

Everything else in the pipeline calls these two and never touches HTTP.
That is deliberate: when a provider changes its API, you edit this file only.
"""

import json
import time
from typing import Any

import requests

from . import config


class LLMError(Exception):
    """Raised when a model call cannot be completed after retrying."""


def _headers() -> dict:
    """Sarvam accepts the key two ways, so we send both.

    The documented header is api-subscription-key. The V2 chat endpoint also
    accepts an Authorization bearer token. Sending both means the client works
    whichever one a given endpoint wants, and a 403 (rather than a 401) usually
    means the subscription header was missing.
    """
    key = config.SARVAM_API_KEY

    # An HTTP header is latin-1. A key with a smart quote or a zero-width space
    # in it - both invisible on screen after a copy from a dashboard - raises
    # UnicodeEncodeError deep inside requests, which is not an LLMError and
    # surfaces as a codec traceback. Say what it actually is.
    try:
        key.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise LLMError(
            "SARVAM_API_KEY contains a character that is not ASCII "
            f"(position {exc.start + 1}). Paste the key again by hand."
        ) from exc

    return {
        "api-subscription-key": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def chat(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    json_schema: dict | None = None,
    retries: int | None = None,
) -> tuple[str, dict]:
    """Send a chat conversation to Sarvam.

    Returns (text, usage). "usage" always has model, prompt_tokens,
    completion_tokens and cost_inr, so callers can log cost without guessing.

    json_schema, when given, turns on Structured Outputs: the API guarantees
    the reply matches that schema, instead of merely being valid JSON.
    """
    if not config.has_api_key():
        raise LLMError(
            "SARVAM_API_KEY is not set. Copy .env.example to .env and paste your key."
        )

    # The agents ask for a role ("fast" or "strong"); the API wants a model id.
    # Resolving it here means a role can never be posted as a model id, which
    # the API answers with a 404.
    model = config.MODELS.get(model or "strong", model or config.MODEL_STRONG)

    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        # Always explicit. The API default is 2048, which silently truncates.
        "max_tokens": max_tokens or config.MAX_TOKENS,
        "temperature": config.TEMPERATURE if temperature is None else temperature,
    }
    if json_schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": json_schema,
        }

    attempts = config.RETRIES if retries is None else retries
    last_error = ""

    for attempt in range(attempts + 1):
        try:
            response = requests.post(
                config.CHAT_URL,
                headers=_headers(),
                json=body,
                timeout=config.TIMEOUT,
            )
        except requests.RequestException as exc:  # network problem, not the API
            last_error = f"network error: {exc}"
            if attempt < attempts:
                time.sleep(2**attempt)
                continue
            raise LLMError(last_error) from exc

        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError as exc:
                # A proxy can return HTML with a 200. Do not let that escape
                # as a JSONDecodeError three frames up.
                raise LLMError(f"non-JSON reply body: {response.text[:200]}") from exc
            return _read_reply(payload, model)

        last_error = f"HTTP {response.status_code}: {response.text[:300]}"

        # 401 means a wrong key; 400 means our request is wrong. Retrying
        # either one wastes time and rate limit, so fail fast with the reason.
        if response.status_code in (400, 401, 403, 404):
            raise LLMError(last_error)

        if attempt < attempts:
            time.sleep(2**attempt)  # 1s, 2s, 4s

    raise LLMError(f"gave up after {attempts + 1} attempts. Last error: {last_error}")


def _read_reply(payload: dict, model: str) -> tuple[str, dict]:
    """Pull the text and the token counts out of an OpenAI-shaped reply."""
    try:
        choice = payload["choices"][0]
        text = choice["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected reply shape: {str(payload)[:300]}") from exc

    if not text.strip():
        # An empty completion is a failure, not an empty draft. The usual cause
        # is finish_reason "length", which means max_tokens was too small.
        reason = choice.get("finish_reason", "unknown")
        raise LLMError(f"empty completion (finish_reason={reason!r})")

    usage = payload.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)

    return text, {
        "model": payload.get("model", model),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_inr": config.cost_inr(prompt_tokens, completion_tokens),
    }


def translate(
    text: str,
    target_language: str = "hi-IN",
    source_language: str = "auto",
    model: str | None = None,
    retries: int | None = None,
) -> str:
    """Translate text with Sarvam's translation endpoint, chunking as needed.

    mayura:v1 takes 1,000 characters per request and sarvam-translate:v1 takes
    2,000, so long text is split on sentence boundaries and joined back
    together. The chat model is never used for this: a purpose-built
    translation model is cheaper and better at Indic output.
    """
    text = (text or "").strip()
    if not text:
        return ""

    model = model or config.TRANSLATE_MODEL
    limit = config.TRANSLATE_CHUNK
    pieces = split_for_translation(text, limit)

    translated: list[str] = []
    for piece in pieces:
        body = {
            "input": piece,
            "source_language_code": source_language,
            "target_language_code": target_language,
            "model": model,
        }
        translated.append(_translate_one(body, retries))

    joiner = "\n\n" if "\n\n" in text else " "
    return joiner.join(translated)


def _translate_one(body: dict, retries: int | None) -> str:
    """One translation request, with the same retry rules as chat()."""
    if not config.has_api_key():
        raise LLMError(
            "SARVAM_API_KEY is not set. Copy .env.example to .env and paste your key."
        )

    attempts = config.RETRIES if retries is None else retries
    last_error = ""

    for attempt in range(attempts + 1):
        try:
            response = requests.post(
                config.TRANSLATE_URL,
                headers=_headers(),
                json=body,
                timeout=config.TIMEOUT,
            )
        except requests.RequestException as exc:
            last_error = f"network error: {exc}"
            if attempt < attempts:
                time.sleep(2**attempt)
                continue
            raise LLMError(last_error) from exc

        if response.status_code == 200:
            return response.json().get("translated_text", "")

        last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        if response.status_code in (400, 401, 403, 404):
            raise LLMError(last_error)
        if attempt < attempts:
            time.sleep(2**attempt)

    raise LLMError(f"translation failed. Last error: {last_error}")


def split_for_translation(text: str, limit: int) -> list[str]:
    """Split text into pieces no longer than "limit" characters.

    It tries to break on paragraphs, then sentences, then words, and only
    hard-splits a single word that is longer than the limit.
    """
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []

    pieces: list[str] = []
    buffer = ""

    for paragraph in text.split("\n\n"):
        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if len(candidate) <= limit:
            buffer = candidate
            continue
        if buffer:
            pieces.append(buffer)
            buffer = ""
        # The paragraph itself is too long, so break it on sentence ends.
        for sentence in _sentences(paragraph):
            candidate = f"{buffer} {sentence}".strip() if buffer else sentence
            if len(candidate) <= limit:
                buffer = candidate
                continue
            if buffer:
                pieces.append(buffer)
                buffer = ""
            if len(sentence) <= limit:
                buffer = sentence
            else:
                pieces.extend(_hard_split(sentence, limit))

    if buffer:
        pieces.append(buffer)
    return [p for p in pieces if p.strip()]


def _sentences(paragraph: str) -> list[str]:
    """A deliberately simple sentence splitter: enough for prose, no NLP."""
    out: list[str] = []
    current = ""
    for char in paragraph:
        current += char
        if char in ".!?।" and len(current.strip()) > 20:
            out.append(current.strip())
            current = ""
    if current.strip():
        out.append(current.strip())
    return out


def _hard_split(text: str, limit: int) -> list[str]:
    """Last resort: split on spaces, or mid-word if a word is enormous."""
    words = text.split()
    pieces: list[str] = []
    buffer = ""
    for word in words:
        if len(word) > limit:
            if buffer:
                pieces.append(buffer)
                buffer = ""
            pieces.extend(word[i : i + limit] for i in range(0, len(word), limit))
            continue
        candidate = f"{buffer} {word}".strip() if buffer else word
        if len(candidate) <= limit:
            buffer = candidate
        else:
            pieces.append(buffer)
            buffer = word
    if buffer:
        pieces.append(buffer)
    return pieces


def list_models() -> list[str]:
    """Ask the API which model ids this key can use. Handy before a demo."""
    response = requests.get(config.MODELS_URL, headers=_headers(), timeout=config.TIMEOUT)
    if response.status_code != 200:
        raise LLMError(f"HTTP {response.status_code}: {response.text[:300]}")
    return [item.get("id", "") for item in response.json().get("data", [])]


def parse_json(text: str) -> dict:
    """Turn a model reply into a dict, tolerating markdown fences.

    Structured Outputs should make this unnecessary, but the repair pass and
    any hand-pasted prompt still benefit from it. Raises ValueError if there
    is genuinely no JSON in the reply.
    """
    cleaned = (text or "").strip()

    if cleaned.startswith("```"):
        # Drop the opening fence line and the closing fence.
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]

    cleaned = cleaned.strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return json.loads(cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object found in reply: {cleaned[:200]!r}")
    return json.loads(cleaned[start : end + 1])
