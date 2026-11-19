"""Every setting the project needs, in one place.

Nothing in this file is clever. It reads the .env file once, then exposes
plain module-level names that the rest of the code imports. If you want to
know what the app can be configured with, read this file top to bottom.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# The project root is the folder that contains this "pipeline" folder.
ROOT = Path(__file__).resolve().parent.parent

# Load .env if it exists. If it does not, the defaults below are used.
load_dotenv(ROOT / ".env")


def _num(name: str, default: float) -> float:
    """Read a number from the environment, falling back to a default."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# --- Sarvam credentials and endpoints ---------------------------------------

# The one secret in the project. Never commit it, never print it.
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")

# Chat Completions V2 is the OpenAI-compatible endpoint with the full model
# list. Check GET /v2/models for the ids your account can actually use.
CHAT_URL = os.getenv("SARVAM_CHAT_URL", "https://api.sarvam.ai/v2/chat/completions")
MODELS_URL = os.getenv("SARVAM_MODELS_URL", "https://api.sarvam.ai/v2/models")

# Text translation is a separate, purpose-built endpoint (not the chat model).
TRANSLATE_URL = os.getenv("SARVAM_TRANSLATE_URL", "https://api.sarvam.ai/translate")

# Two model roles, so a demo can use a cheap model for planning and a strong
# one for writing. Set both to the same id if your account only has one.
MODEL_STRONG = os.getenv("LLM_MODEL_STRONG", "sarvam-105b")
MODEL_FAST = os.getenv("LLM_MODEL_FAST", "sarvam-105b")

MODELS = {"strong": MODEL_STRONG, "fast": MODEL_FAST}

# max_tokens defaults to 2048 on the API, which truncates a ten-question quiz
# mid-JSON. We always send it explicitly instead of relying on the default.
MAX_TOKENS = int(_num("LLM_MAX_TOKENS", 4096))

# Temperature for the writing agents. Low, because we want JSON, not prose.
TEMPERATURE = _num("LLM_TEMPERATURE", 0.3)

# How many times to retry a 429 or 5xx before giving up on a call.
RETRIES = int(_num("LLM_RETRIES", 3))
TIMEOUT = _num("LLM_TIMEOUT", 90)

# --- Translation ------------------------------------------------------------

TRANSLATE_MODEL = os.getenv("TRANSLATE_MODEL", "mayura:v1")

# mayura:v1 accepts 1,000 characters per request, sarvam-translate:v1 2,000.
# We chunk below the limit so we never trip a 400 on the last chunk.
TRANSLATE_CHUNK = int(_num("TRANSLATE_CHUNK_CHARS", 900))

# --- Storage ----------------------------------------------------------------

DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "data" / "runs.db")))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(ROOT / "outputs")))

# Optional. If both are set, every run is also pushed to Supabase.
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# --- Pipeline behaviour -----------------------------------------------------

# Chunking. 1200 characters is roughly 300 tokens of English, which keeps a
# single chunk comfortably inside a model call and leaves room for output.
CHUNK_SIZE = int(_num("CHUNK_SIZE", 1200))
CHUNK_OVERLAP = int(_num("CHUNK_OVERLAP", 150))

# Extraction is done on groups of chunks, not one call per chunk. A 3,000-word
# document fits in a single call, and spending 21 calls on it is money and rate
# limit for nothing. Groups are packed up to this size, and if there are still
# more groups than the cap, they are sampled evenly across the document.
EXTRACT_WINDOW = int(_num("EXTRACT_WINDOW", 6000))
MAX_EXTRACT_CALLS = int(_num("MAX_EXTRACT_CALLS", 6))

# The critic gives a score out of 5. At or above PASS_SCORE we accept the
# draft. Below it, we send it back with the defects, at most MAX_REPAIRS times.
PASS_SCORE = _num("PASS_SCORE", 4)
MAX_REPAIRS = int(_num("MAX_REPAIRS", 2))

# Which outputs the plan agent is allowed to choose from.
DEFAULT_OUTPUTS = ["summary", "quiz", "flashcards", "report", "slides"]

# Translation is a separate flag, because it needs a language and uses a
# different endpoint. Empty string means "no translation".
TRANSLATE_TO = os.getenv("TRANSLATE_TO", "hi-IN")

# --- Cost -------------------------------------------------------------------

# Rupees per 1,000,000 tokens. The defaults are Sarvam's published list price
# for sarvam-105b at the time of writing; check the pricing page and put your
# own numbers in .env. The formula is in README.md, section "Cost".
RATE_IN_PER_M = _num("RATE_IN_PER_M", 10)
RATE_OUT_PER_M = _num("RATE_OUT_PER_M", 25)

# --- Web bridge -------------------------------------------------------------

# The FastAPI bridge only accepts requests from this origin. It must match the
# page's origin character for character: https, no trailing slash.
WEB_ORIGIN = os.getenv("WEB_ORIGIN", "http://localhost:8000")

# Refuse documents larger than this. A 10 MB upload is already ~5,000 pages.
MAX_UPLOAD_BYTES = int(_num("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))


def cost_inr(prompt_tokens: int, completion_tokens: int) -> float:
    """Turn token counts into rupees, using the rates from .env."""
    cost = prompt_tokens / 1_000_000 * RATE_IN_PER_M
    cost += completion_tokens / 1_000_000 * RATE_OUT_PER_M
    return round(cost, 6)


def has_api_key() -> bool:
    """True when a key is configured. The app checks this before calling out."""
    return bool(SARVAM_API_KEY.strip())
