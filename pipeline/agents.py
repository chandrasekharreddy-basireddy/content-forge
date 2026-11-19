"""The three agents, as three plain functions.

    plan(...)      decides what to produce and how deeply
    write(...)     drafts one output from one chunk
    critique(...)  scores a draft and names its defects

There is no framework here on purpose. Each function builds messages, calls
the model, parses JSON and returns the object. That is the whole trick, and
you can explain any line of it in a viva.

Every function takes "call" as its last argument, defaulting to llm.chat. That
one parameter is why the tests can run the entire pipeline offline with a fake
model - and why the runner can swap in a cached model later without touching
a single prompt.
"""

import json
from collections.abc import Callable

from . import checks, config, llm, schemas
from .prompts import build_messages

# A model call: (messages, **kwargs) -> (text, usage). llm.chat matches this.
Call = Callable[..., tuple[str, dict]]


class AgentError(Exception):
    """Raised when an agent cannot produce a usable object."""


# What each output needs, beyond the shared rules in prompts/write.yaml.
# This is the only place output-specific instruction text lives.
OUTPUT_RULES: dict[str, str] = {
    "summary": (
        "Return {\"summary\": string, \"bullets\": [string], \"key_terms\": [string]}.\n"
        "- summary: 120-180 words of flowing prose, no bullet points inside it.\n"
        "- bullets: 4-7 one-line takeaways, each a full idea, not a fragment.\n"
        "- key_terms: 4-8 terms or names the reader should remember, as written "
        "in the source."
    ),
    "quiz": (
        "Return {\"questions\": [{\"question\": string, \"options\": [4 strings], "
        "\"answer_index\": integer 0-3, \"explanation\": string}]}.\n"
        "- Write 5 questions at standard depth, 3 at short, 8 at deep.\n"
        "- Exactly 4 options per question. Exactly one is correct.\n"
        "- answer_index is the 0-based position of the correct option.\n"
        "- Every question must be answerable from the source alone.\n"
        "- No question may have 'all of the above' or 'none of the above'.\n"
        "- explanation: one sentence saying why the answer is right."
    ),
    "flashcards": (
        "Return {\"cards\": [{\"front\": string, \"back\": string}]}.\n"
        "- Write 8 cards at standard depth, 5 at short, 12 at deep.\n"
        "- front is a question or a term; back is the answer, 25 words at most.\n"
        "- One idea per card. No card may be a copy of another."
    ),
    "report": (
        "Return {\"title\": string, \"sections\": [{\"heading\": string, "
        "\"body\": string}]}.\n"
        "- 4 sections at standard depth, 3 at short, 6 at deep.\n"
        "- Each body is 100-180 words of prose. No bullet lists inside a body.\n"
        "- Use headings the source actually supports: Background, Findings, "
        "Implications, Limitations - skip any the source cannot fill."
    ),
    "slides": (
        "Return {\"slides\": [{\"title\": string, \"bullets\": [string], "
        "\"notes\": string}]}.\n"
        "- 6 slides at standard depth, 4 at short, 10 at deep.\n"
        "- 3-5 bullets per slide, each 12 words at most.\n"
        "- notes: 2-3 sentences of speaker notes for that slide.\n"
        "- The first slide is a title slide: title only, one bullet naming the "
        "source."
    ),
}

# How much source the critic sees. It must be at least what the writer saw, or
# the critic flags real content as invented: with a 6,000-character cut on an
# 8,462-character document, the writer's last paragraph looked fabricated and
# the critic correctly - but wrongly - called it a hallucination. The writer's
# context is capped at 7,000 characters, so 12,000 leaves headroom.
SOURCE_LIMIT = 12_000
DRAFT_LIMIT = 8_000

# The plan is not a user-facing output, so its schema lives here rather than
# in schemas.py.
PLAN_SCHEMA = {
    "name": "plan",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "outputs": {"type": "array", "items": {"type": "string"}},
            "depth": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["outputs", "depth", "reason"],
        "additionalProperties": False,
    },
}

CRITIQUE_SCHEMA = {
    "name": "critique",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer"},
            "verdict": {"type": "string"},
            # Structured, because a bare string list invites the model to write
            # down the checks it performed and passed. A quote plus a problem
            # has no room for "this is correct, but".
            "defects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "quote": {"type": "string"},
                        "problem": {"type": "string"},
                    },
                    "required": ["quote", "problem"],
                    "additionalProperties": False,
                },
            },
            "reason": {"type": "string"},
        },
        "required": ["score", "verdict", "defects", "reason"],
        "additionalProperties": False,
    },
}

FACT_SCHEMA = {
    "name": "facts",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "facts": {"type": "array", "items": {"type": "string"}},
            "numbers": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["facts", "numbers"],
        "additionalProperties": False,
    },
}

DEPTHS = ("short", "standard", "deep")


def extract(chunk: str, part: int, parts: int, call: Call = llm.chat) -> tuple[dict, dict]:
    """Pull the load-bearing facts out of one chunk. Returns (facts, usage).

    This is the "map" half of map-reduce. A long document cannot go into one
    prompt, so each chunk is reduced to its facts first, and the writers work
    from the facts rather than from the raw text. Fewer tokens, and every
    output is anchored to the same evidence.
    """
    messages = build_messages("extract", part=part, parts=parts, chunk=chunk)
    text, usage = call(messages, model="fast", json_schema=FACT_SCHEMA)

    try:
        result = llm.parse_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise AgentError(f"extractor returned invalid JSON: {exc}") from exc

    facts = result.get("facts")
    numbers = result.get("numbers")
    return {
        "facts": [str(f) for f in facts] if isinstance(facts, list) else [],
        "numbers": [str(n) for n in numbers] if isinstance(numbers, list) else [],
    }, usage


def plan(
    doc_name: str,
    chunks: list[str],
    allowed: list[str],
    call: Call = llm.chat,
) -> tuple[dict, dict]:
    """Ask the planner what to build. Returns (plan, usage).

    The plan is advisory, not authoritative: whatever the model says is
    filtered against the allowed list, and a failure falls back to a sane
    default rather than stopping the run.
    """
    preview = chunks[0][:1500] if chunks else ""
    structure = describe_structure(chunks)

    messages = build_messages(
        "plan",
        allowed=", ".join(allowed),
        doc_name=doc_name,
        words=sum(len(c.split()) for c in chunks),
        chunks=len(chunks),
        structure=structure,
        preview=preview,
    )

    text, usage = call(messages, model="fast", json_schema=PLAN_SCHEMA)
    try:
        result = llm.parse_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise AgentError(f"planner did not return JSON: {exc}") from exc

    outputs = [o for o in result.get("outputs", []) if o in allowed]
    depth = result.get("depth") if result.get("depth") in DEPTHS else "standard"

    if not outputs:
        outputs = list(allowed)

    return {
        "outputs": outputs,
        "depth": depth,
        "reason": str(result.get("reason", "")).strip() or "planned by the model",
    }, usage


def write(
    output: str,
    chunk: str,
    part: int,
    parts: int,
    depth: str = "standard",
    feedback: str = "",
    call: Call = llm.chat,
) -> tuple[dict, dict]:
    """Draft one output from one chunk. Returns (object, usage).

    "feedback" carries the critic's defects back in on a repair pass, which is
    the whole mechanism behind the loop in runner.py.
    """
    if output not in OUTPUT_RULES:
        raise AgentError(f"no writing rules for output '{output}'")

    feedback_block = ""
    if feedback:
        feedback_block = (
            "A previous draft was rejected. Fix exactly these defects and keep "
            f"everything that was already correct:\n{feedback}"
        )

    messages = build_messages(
        "write",
        output=output,
        rules=OUTPUT_RULES[output],
        depth=depth,
        feedback=feedback_block,
        part=part,
        parts=parts,
        chunk=chunk,
    )

    text, usage = call(
        messages,
        model=schemas.spec(output)["model"],
        json_schema=schemas.json_schema(output),
    )

    try:
        result = llm.parse_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise AgentError(f"writer returned invalid JSON: {exc}") from exc

    return result, usage


def critique(
    output: str,
    draft: dict,
    source: str,
    call: Call = llm.chat,
) -> tuple[dict, dict]:
    """Score a draft against its source. Returns (critique, usage)."""
    messages = build_messages(
        "critique",
        output=output,
        source=source[:SOURCE_LIMIT],
        draft=json.dumps(draft, ensure_ascii=False, indent=2)[:DRAFT_LIMIT],
    )

    text, usage = call(messages, model="strong", json_schema=CRITIQUE_SCHEMA)
    try:
        result = llm.parse_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise AgentError(f"critic did not return JSON: {exc}") from exc

    score = result.get("score")
    if not isinstance(score, int) or isinstance(score, bool):
        raise AgentError(f"critic returned a non-integer score: {score!r}")

    defects = _read_defects(result.get("defects"))
    score = max(1, min(5, score))
    verdict = str(result.get("verdict", "revise"))

    # The critic is a model and can be talked out of its own rubric: in one
    # measured run it found an invented figure and still scored 4. A number the
    # source does not contain is checkable without judgement, so check it here
    # and let it override.
    if config.GROUNDING_CHECK:
        # The cap applies whenever an unsourced number exists, whether or not
        # the critic named it: who reported the problem must not change the
        # score, only the wording.
        missing = checks.unsourced_numbers(draft, source)
        if missing:
            defects = checks.grounding_defects(draft, source, existing=defects) + defects
            if score > 2:
                score = 2
            verdict = "revise"

    return {
        "score": score,
        "verdict": verdict,
        "defects": defects,
        "reason": str(result.get("reason", "")).strip(),
    }, usage


def _read_defects(raw) -> list[str]:
    """Flatten the critic's defects into readable lines.

    The schema asks for {"quote", "problem"} objects. A plain string is still
    accepted, because a cached reply or a test fake may use the older shape,
    and refusing it would turn a cosmetic mismatch into a failed run.
    """
    if not isinstance(raw, list):
        return [str(raw)] if raw else []

    lines: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            quote = str(item.get("quote", "")).strip().strip('"')
            problem = str(item.get("problem", "")).strip()
            if problem:
                lines.append(f'"{quote}" - {problem}' if quote else problem)
        elif str(item).strip():
            lines.append(str(item))
    return lines


def describe_structure(chunks: list[str]) -> str:
    """A one-line guess at what kind of document this is.

    Cheap heuristics, not a classifier. It gives the planner something better
    than "some text" without spending a model call on it.
    """
    text = "\n".join(chunks)
    lower = text.lower()

    signals = {
        "numbered sections": text.count("\n1.") + text.count("\n2."),
        "page markers": lower.count("[page "),
        "table rows": text.count(" | "),
        "percentages": text.count("%"),
    }
    present = [name for name, count in signals.items() if count > 0]

    if not present:
        return "plain prose, no headings or tables detected"
    return "contains " + ", ".join(present)
