"""The contract for every output type, in one table.

Each entry in OUTPUT_SPECS says three things:

    label        what a human calls it
    model        "fast" or "strong" - which model role writes it
    schema       the JSON Schema sent to the API as response_format
    required     the keys our own validator insists on

Why hand-write a validator when the API can guarantee the shape? Because the
API guarantee only covers the API. A cached reply, a fake model in a test, or
a repair that went wrong can all arrive without a key, and a KeyError in the
export step would take the whole run down. This file is the safety net.
"""

OUTPUT_SPECS: dict[str, dict] = {
    "summary": {
        "label": "Summary",
        "model": "fast",
        "required": ["summary", "bullets", "key_terms"],
        "schema": {
            "name": "summary",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                    "key_terms": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["summary", "bullets", "key_terms"],
                "additionalProperties": False,
            },
        },
    },
    "quiz": {
        "label": "Quiz",
        "model": "strong",
        "required": ["questions"],
        "schema": {
            "name": "quiz",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string"},
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "answer_index": {"type": "integer"},
                                "explanation": {"type": "string"},
                            },
                            "required": [
                                "question",
                                "options",
                                "answer_index",
                                "explanation",
                            ],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["questions"],
                "additionalProperties": False,
            },
        },
    },
    "flashcards": {
        "label": "Flashcards",
        "model": "fast",
        "required": ["cards"],
        "schema": {
            "name": "flashcards",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "cards": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "front": {"type": "string"},
                                "back": {"type": "string"},
                            },
                            "required": ["front", "back"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["cards"],
                "additionalProperties": False,
            },
        },
    },
    "report": {
        "label": "Report",
        "model": "strong",
        "required": ["title", "sections"],
        "schema": {
            "name": "report",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "body": {"type": "string"},
                            },
                            "required": ["heading", "body"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "sections"],
                "additionalProperties": False,
            },
        },
    },
    "slides": {
        "label": "Slide outline",
        "model": "strong",
        "required": ["slides"],
        "schema": {
            "name": "slides",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "slides": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "bullets": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "notes": {"type": "string"},
                            },
                            "required": ["title", "bullets", "notes"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["slides"],
                "additionalProperties": False,
            },
        },
    },
    # Translation is produced by the /translate endpoint, not the chat model,
    # so it has a schema for storage but no writing agent.
    "translation": {
        "label": "Translation",
        "model": None,
        "required": ["language", "text"],
        "schema": None,
    },
}


def spec(name: str) -> dict:
    """Look up an output spec, with a helpful error if the name is wrong."""
    if name not in OUTPUT_SPECS:
        raise KeyError(f"unknown output '{name}'. Known: {', '.join(OUTPUT_SPECS)}")
    return OUTPUT_SPECS[name]


def json_schema(name: str) -> dict | None:
    """The response_format block for a given output, ready to send."""
    entry = spec(name)
    if not entry["schema"]:
        return None
    return entry["schema"]


def validate(name: str, obj) -> tuple[bool, list[str]]:
    """Check one output object against its spec.

    Returns (ok, problems). It never raises, because the runner wants to turn
    a bad output into a note rather than a crash.
    """
    problems: list[str] = []

    if not isinstance(obj, dict):
        return False, [f"expected a JSON object, got {type(obj).__name__}"]

    for key in spec(name)["required"]:
        if key not in obj:
            problems.append(f"missing key '{key}'")

    if problems:
        return False, problems

    if name == "summary":
        problems += _check_list(obj, "bullets", minimum=3)
        problems += _check_list(obj, "key_terms", minimum=2)
        if not str(obj.get("summary", "")).strip():
            problems.append("summary is empty")

    elif name == "quiz":
        questions = obj.get("questions")
        if not isinstance(questions, list) or not questions:
            problems.append("questions must be a non-empty list")
        else:
            for i, q in enumerate(questions):
                label = f"questions[{i}]"
                if not isinstance(q, dict):
                    problems.append(f"{label} is not an object")
                    continue
                if not str(q.get("question", "")).strip():
                    problems.append(f"{label}.question is empty")
                options = q.get("options")
                if not isinstance(options, list) or len(options) != 4:
                    problems.append(f"{label}.options must hold exactly 4 items")
                index = q.get("answer_index")
                if not isinstance(index, int) or isinstance(index, bool):
                    problems.append(f"{label}.answer_index must be an integer")
                elif isinstance(options, list) and not 0 <= index < len(options):
                    problems.append(f"{label}.answer_index is out of range")

    elif name == "flashcards":
        cards = obj.get("cards")
        if not isinstance(cards, list) or not cards:
            problems.append("cards must be a non-empty list")
        else:
            for i, card in enumerate(cards):
                if not isinstance(card, dict):
                    problems.append(f"cards[{i}] is not an object")
                elif not str(card.get("front", "")).strip() or not str(
                    card.get("back", "")
                ).strip():
                    problems.append(f"cards[{i}] has an empty side")

    elif name == "report":
        sections = obj.get("sections")
        if not isinstance(sections, list) or not sections:
            problems.append("sections must be a non-empty list")
        else:
            for i, section in enumerate(sections):
                if not isinstance(section, dict):
                    problems.append(f"sections[{i}] is not an object")
                elif not str(section.get("body", "")).strip():
                    problems.append(f"sections[{i}].body is empty")

    elif name == "slides":
        slides = obj.get("slides")
        if not isinstance(slides, list) or not slides:
            problems.append("slides must be a non-empty list")
        else:
            for i, slide in enumerate(slides):
                if not isinstance(slide, dict):
                    problems.append(f"slides[{i}] is not an object")
                    continue
                problems += _check_list(slide, "bullets", minimum=2, where=f"slides[{i}]")

    elif name == "translation":
        if not str(obj.get("text", "")).strip():
            problems.append("translated text is empty")

    return (len(problems) == 0), problems


def _check_list(obj: dict, key: str, minimum: int, where: str = "") -> list[str]:
    """Shared check: a list of non-empty strings with at least "minimum" items."""
    prefix = f"{where}." if where else ""
    value = obj.get(key)
    if not isinstance(value, list):
        return [f"{prefix}{key} must be a list"]
    if len(value) < minimum:
        return [f"{prefix}{key} needs at least {minimum} items, got {len(value)}"]
    if any(not str(item).strip() for item in value):
        return [f"{prefix}{key} contains an empty item"]
    return []
