"""The bridge between the static landing page and the pipeline.

Run it with:  uvicorn api:app --reload --port 8000

Why this file exists: the course asks for HTML, CSS and JavaScript, and a
landing page that cannot actually do anything is a mock-up. So the page in
web/ posts real text here, this file runs the real pipeline, and the page
renders the real answer.

Four safety decisions, each of which is worth a sentence in a viva:

  - CORS allows exactly one origin, the one in .env, not "*".
  - Every request is charged against a per-address limit AND a process-wide
    ceiling, because a per-address limit alone is bypassed by rotating
    addresses, and the API key is a student's.
  - The body size is capped before it is parsed, not after.
  - Provider errors are logged with a reference id and returned as a generic
    message, so a stranger cannot read the account's internals out of a 500.
"""

import logging
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pipeline import agents, config, llm, runner, schemas, store

log = logging.getLogger("content_forge")

app = FastAPI(title="Content Forge API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.WEB_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# --- rate limiting ---------------------------------------------------------

RATE_LIMIT = 5           # runs per address per hour
GLOBAL_LIMIT = 30        # runs per process per hour, whatever the address
RATE_WINDOW = 3600
MAX_BODY_BYTES = 64 * 1024

_recent: dict[str, deque] = {}
_global: deque = deque(maxlen=GLOBAL_LIMIT)
_lock = threading.Lock()  # the endpoint is sync, so Starlette runs it in a pool


def _rate_limited(address: str) -> bool:
    """Charge one run to this address and to the process. True means refuse.

    The global ceiling is the one that matters in public: an attacker rotating
    source addresses gets a fresh per-address bucket each time, but cannot
    escape the process total.
    """
    now = time.time()
    with _lock:
        # The process ceiling is checked first: an address refused by it never
        # gets a bucket, so rotating addresses cannot grow the dict.
        while _global and now - _global[0] > RATE_WINDOW:
            _global.popleft()
        if len(_global) >= GLOBAL_LIMIT:
            return True

        bucket = _recent.get(address)
        if bucket is None:
            bucket = _recent[address] = deque(maxlen=RATE_LIMIT)
        while bucket and now - bucket[0] > RATE_WINDOW:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT:
            return True

        # Drop buckets whose window has expired, never the caller's own.
        if len(_recent) > 1000:
            for other in [key for key, stamps in _recent.items()
                          if key != address and (not stamps or now - stamps[-1] > RATE_WINDOW)]:
                _recent.pop(other, None)

        bucket.append(now)
        _global.append(now)
        return False


def _client_address(request: Request) -> str:
    """The visitor's address, not the load balancer's.

    Behind Render, Fly or Railway every request arrives from the proxy, so the
    forwarded header is the only thing that distinguishes visitors. Only trust
    it when you actually are behind a proxy you control - which is why this is
    one function, easy to change.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def cap_body_size(request: Request, call_next):
    """Refuse an oversized body before FastAPI reads and parses it.

    Pydantic's max_length runs after the whole body is in memory, which is too
    late to protect a single-process demo from being pushed over.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "request body too large"}, status_code=413)
    return await call_next(request)


# --- request model ---------------------------------------------------------

class TransformRequest(BaseModel):
    """The body the landing page sends."""

    text: str = Field(..., min_length=200, max_length=20000)
    outputs: list[str] = Field(default_factory=lambda: ["summary", "quiz"])
    translate_to: str | None = None


# --- endpoints -------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    """A liveness check the page can call on load."""
    return {"status": "ok", "has_key": config.has_api_key()}


@app.get("/api/stats")
def stats() -> dict:
    """Counts for the landing page. Deliberately no cost figure."""
    summary = store.stats()
    summary.pop("cost_inr", None)  # what the student spends is not public
    return summary


@app.post("/api/transform")
def transform(payload: TransformRequest, request: Request) -> dict:
    """Run the pipeline on pasted text and return the outputs."""
    if not config.has_api_key():
        raise HTTPException(status_code=503, detail="The server has no Sarvam API key set.")

    writable = list(agents.OUTPUT_RULES)
    unknown = [name for name in payload.outputs if name not in writable]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown outputs: {', '.join(unknown)}. Translation is requested "
            "with translate_to, not as an output.",
        )
    if len(payload.outputs) > 3:
        raise HTTPException(
            status_code=400,
            detail="The public demo produces at most three outputs per request.",
        )

    # Charge the limit only once the request is known to be valid, so a
    # rejected request does not cost a visitor their hourly allowance.
    if _rate_limited(_client_address(request)):
        raise HTTPException(
            status_code=429,
            detail=f"The demo allows {RATE_LIMIT} runs per hour. Try again later.",
        )

    reference = uuid.uuid4().hex[:8]
    try:
        result = runner.run(
            doc_name="web-demo.txt",
            text=payload.text,
            outputs=payload.outputs,
            translate_to=payload.translate_to,
        )
    except llm.LLMError:
        log.exception("run %s: provider error", reference)
        raise HTTPException(
            status_code=502,
            detail=f"The model provider rejected the request. Reference {reference}.",
        ) from None
    except Exception:
        log.exception("run %s: internal error", reference)
        raise HTTPException(
            status_code=500,
            detail=f"The pipeline failed. Reference {reference}.",
        ) from None

    # Do not mirror a stranger's pasted text to a cloud database, and keep only
    # the scalars locally: the dashboard needs the counts, not their content.
    store.save_run(result, supabase=False, keep_payload=False)

    return {
        "id": result["id"],
        "status": result["status"],
        "plan": result["plan"],
        "outputs": {
            name: {
                "status": item["status"],
                "score": item["score"],
                "object": item["object"],
            }
            for name, item in result["outputs"].items()
        },
        "translation": result.get("translation"),
        "cost_inr": result["usage"]["cost_inr"],
        "duration_ms": result["duration_ms"],
    }


@app.get("/")
def index() -> RedirectResponse:
    """Send the root to the landing page."""
    return RedirectResponse(url="/web/index.html")


# Serve the static page from the same process. The path is absolute so the app
# starts from any working directory, not only the repository root.
WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/web", StaticFiles(directory=WEB_DIR, html=True), name="web")


# Keep the schemas import meaningful for readers: the page's output list comes
# from the same table the pipeline validates against.
assert schemas.OUTPUT_SPECS, "output specs failed to load"
