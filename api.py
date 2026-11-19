"""The bridge between the static landing page and the pipeline.

Run it with:  uvicorn api:app --reload --port 8000

Why this file exists: the course asks for HTML, CSS and JavaScript, and a
landing page that cannot actually do anything is a mock-up. So the page in
web/ posts real text here, this file runs the real pipeline, and the page
renders the real answer.

Two safety details worth pointing at in a viva:
  - CORS allows exactly one origin, the one in .env, not "*".
  - There is a small in-memory rate limit, because the API key is yours and a
    public demo endpoint is a good way to lose it.
"""

import time
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pipeline import config, runner, schemas, store

app = FastAPI(title="Content Forge API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.WEB_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# ip -> list of request timestamps. Cleared whenever the process restarts,
# which is fine: this is a demo guard, not a billing system.
_recent: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 5
RATE_WINDOW = 3600  # one hour


class TransformRequest(BaseModel):
    """The body the landing page sends."""

    text: str = Field(..., min_length=200, max_length=20000)
    outputs: list[str] = Field(default_factory=lambda: ["summary", "quiz"])
    translate_to: str | None = None


def _rate_limited(ip: str) -> bool:
    """True when this IP has used up its allowance for the hour."""
    now = time.time()
    recent = [stamp for stamp in _recent[ip] if now - stamp < RATE_WINDOW]
    _recent[ip] = recent
    if len(recent) >= RATE_LIMIT:
        return True
    recent.append(now)
    return False


@app.get("/api/health")
def health() -> dict:
    """What the page checks on load, so it can warn instead of failing."""
    return {
        "status": "ok",
        "has_key": config.has_api_key(),
        "model": config.MODEL_STRONG,
        "outputs": [name for name in schemas.OUTPUT_SPECS if name != "translation"],
    }


@app.get("/api/stats")
def stats() -> dict:
    """Run counts for the numbers on the landing page."""
    return store.stats()


@app.post("/api/transform")
def transform(payload: TransformRequest, request: Request) -> dict:
    """Run the pipeline on pasted text and return the outputs."""
    client_ip = request.client.host if request.client else "unknown"
    if _rate_limited(client_ip):
        raise HTTPException(
            status_code=429,
            detail=f"The demo allows {RATE_LIMIT} runs per hour. Try again later.",
        )

    if not config.has_api_key():
        raise HTTPException(status_code=503, detail="The server has no Sarvam API key set.")

    unknown = [name for name in payload.outputs if name not in schemas.OUTPUT_SPECS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown outputs: {', '.join(unknown)}")
    if len(payload.outputs) > 3:
        raise HTTPException(
            status_code=400,
            detail="The public demo produces at most three outputs per request.",
        )

    try:
        result = runner.run(
            doc_name="web-demo.txt",
            text=payload.text,
            outputs=payload.outputs,
            translate_to=payload.translate_to,
        )
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to a page
        raise HTTPException(status_code=500, detail=f"the pipeline failed: {exc}") from exc

    store.save_run(result)

    # The page does not need the full payload; keep the response small.
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


# Serve the static page from the same process, so one URL does everything.
app.mount("/web", StaticFiles(directory="web", html=True), name="web")
