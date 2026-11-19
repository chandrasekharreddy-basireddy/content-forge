"""Loading and filling the YAML prompts in prompts/.

Keeping prompts in YAML rather than in Python strings has one purpose: you can
read, diff and rewrite them without touching code, and the prompt text is the
thing you are actually being marked on.

Two rules this file exists to enforce, both learned the hard way:

1. A prompt file is loaded with yaml.safe_load, and the prompt body must be a
   literal block (|) or quoted. A bare line starting with "{" is a YAML flow
   mapping and will fail to parse.
2. Prompt files have their own "id" field. Never pass a value called "id" or
   "name" into render() expecting it to land in the text by accident - the
   template slot is {doc_name}, and anything else is an error, loudly.
"""

from functools import cache
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class PromptError(Exception):
    """Raised when a prompt file is missing, broken or missing a slot."""


@cache
def load(prompt_name: str) -> dict:
    """Read prompts/<prompt_name>.yaml and return it as a dict.

    The result is cached, so calling this in a loop costs nothing after the
    first read. It returns the same dict object every time - treat it as
    read-only.
    """
    path = PROMPTS_DIR / f"{prompt_name}.yaml"
    if not path.exists():
        raise PromptError(f"no prompt file at {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PromptError(
            f"{path.name} is not valid YAML. If a line starts with '{{', put the "
            f"whole prompt in a literal block (|). Details: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise PromptError(f"{path.name} must contain a mapping with system/user keys")

    for key in ("system", "user"):
        if not str(data.get(key, "")).strip():
            raise PromptError(f"{path.name} is missing its '{key}' text")

    return data


def render(template: str, values: dict) -> str:
    """Fill {slots} in a template.

    Unknown slots raise instead of silently disappearing, because a prompt
    with a blank instruction is worse than a crash you can see.
    """
    try:
        return template.format(**values)
    except KeyError as exc:
        missing = exc.args[0]
        available = ", ".join(sorted(values)) or "none"
        raise PromptError(
            f"prompt uses the slot {{{missing}}} but no value was given. "
            f"Values provided: {available}"
        ) from exc
    except (IndexError, ValueError) as exc:
        raise PromptError(
            "prompt contains a brace that is not a slot. To print a literal "
            f"brace, write {{{{ or }}}}. Details: {exc}"
        ) from exc


def build_messages(prompt_name: str, **values) -> list[dict]:
    """Load a prompt and return ready-to-send chat messages.

    Note the first parameter is the prompt's file name, not a template value.
    That is why a document literally called "name" cannot break the renderer.
    """
    prompt = load(prompt_name)
    return [
        {"role": "system", "content": render(prompt["system"], values).strip()},
        {"role": "user", "content": render(prompt["user"], values).strip()},
    ]


def clear_cache() -> None:
    """Forget cached prompts. Used by tests that edit a file on disk."""
    load.cache_clear()
