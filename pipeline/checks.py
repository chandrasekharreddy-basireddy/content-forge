"""Deterministic checks that do not need a model.

The critic is a model, and a model can be talked out of its own rubric: in one
measured run it found an invented figure and still scored the draft 4 out of 5,
when the rubric said an unsourced number caps the score at 2. Prompting harder
is not the fix for that. A rule that must hold is better expressed in code.

So: the model proposes a score, and this file disposes. Every number in the
draft is looked up in the source. One that is not there is a defect, and it
overrides the score.

It is deliberately narrow. It checks numbers, because numbers are checkable
without judgement, and because a fabricated statistic is the failure that
actually damages generated study material. It does not try to check claims.
"""

import json
import re

# A number as it appears in prose: 174.55, 2,245, 14%, 2026, 11th.
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    """Every number in a piece of text, normalised so 2,245 and 2245 match."""
    found = set()
    for match in NUMBER.findall(text or ""):
        cleaned = match.replace(",", "").rstrip(".")
        if cleaned:
            found.add(cleaned)
    return found


def text_of(draft) -> str:
    """All the string values in a draft, flattened, so keys are not searched."""
    if isinstance(draft, dict):
        return " ".join(text_of(value) for value in draft.values())
    if isinstance(draft, list):
        return " ".join(text_of(item) for item in draft)
    if isinstance(draft, str):
        return draft
    return str(draft) if draft is not None else ""


def unsourced_numbers(draft, source: str) -> list[str]:
    """Numbers in the draft that appear nowhere in the source, in order.

    Returns the values, deduplicated, so the defect line can name them.
    """
    source_numbers = numbers_in(source)
    missing: list[str] = []
    for value in numbers_in(text_of(draft)):
        if value in source_numbers:
            continue
        # "2026" in the source may be written "2026." or inside a range; the
        # set already normalises commas, so a plain miss is a real miss.
        if value not in missing:
            missing.append(value)

    # Longest first: a fabricated "974.55" is more informative than "9".
    missing.sort(key=len, reverse=True)
    return missing


def defect_line(values: list[str]) -> str:
    """One readable defect naming the unsourced numbers."""
    shown = ", ".join(values[:5])
    return (
        f'"{shown}" - this number does not appear anywhere in the source document, '
        "so it is unsourced regardless of how plausible it reads"
    )


def grounding_defects(draft, source: str, existing: list[str] | None = None) -> list[str]:
    """Defect lines for unsourced numbers, skipping ones already reported.

    The critic often names the same figure itself, and a review that lists one
    problem twice reads as two problems. Values already mentioned in the
    critic's own defects are left out here.
    """
    missing = unsourced_numbers(draft, source)
    if not missing:
        return []

    already = " ".join(existing or [])
    fresh = [value for value in missing if value not in already]
    return [defect_line(fresh)] if fresh else []


# The writer is asked for 120-180 words of summary. A measured run produced
# 320 words of numeric dump and the critic passed it at 4/5, so the range is
# checked here rather than trusted.
SUMMARY_WORDS = (80, 220)


def length_defects(output: str, draft) -> list[str]:
    """Deterministic shape complaints that do not need a model to see."""
    if not isinstance(draft, dict):
        return []

    defects: list[str] = []

    if output == "summary":
        prose = str(draft.get("summary", ""))
        words = len(prose.split())
        low, high = SUMMARY_WORDS
        if words > high:
            defects.append(
                f"the summary is {words} words; it was asked for 120-180, and "
                f"anything over {high} is a dump rather than a summary"
            )
        elif words and words < low:
            defects.append(f"the summary is {words} words, too short to be useful")

        bullets = draft.get("bullets")
        if isinstance(bullets, list) and len(bullets) > 8:
            defects.append(
                f"there are {len(bullets)} bullets; five to seven is a summary, "
                "more is a transcript"
            )

    elif output == "quiz":
        questions = draft.get("questions")
        if isinstance(questions, list) and len(questions) > 10:
            defects.append(
                f"there are {len(questions)} questions; eight is the deep setting"
            )

    elif output == "flashcards":
        cards = draft.get("cards")
        if isinstance(cards, list) and len(cards) > 14:
            defects.append(f"there are {len(cards)} cards; twelve is the deep setting")

    return defects


def summarise_for_trace(draft) -> str:
    """A short fingerprint of a draft, for a log line that stays readable."""
    return json.dumps(text_of(draft))[:120]
