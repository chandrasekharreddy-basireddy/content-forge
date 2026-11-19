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

# A number as it appears in prose, with an optional magnitude suffix:
# 174.55, 2,245, 14%, 78K, 2.90M, 3 lakh.
NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?(k|m|b|crore|lakh|l)?\b", re.IGNORECASE)

SUFFIX = {
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
    "l": 100_000,
    "lakh": 100_000,
    "crore": 10_000_000,
}


def numbers_in(text: str) -> set[str]:
    """Every number in a piece of text, normalised so 2,245 and 2245 match."""
    return {cleaned for cleaned, _value, _suffix in _scan(text)}


def _scan(text: str) -> list[tuple[str, float, bool]]:
    """(as written, value, had a magnitude suffix) for every number in text."""
    found: list[tuple[str, float, bool]] = []
    for match in NUMBER.finditer(text or ""):
        raw = match.group(1)
        suffix = (match.group(2) or "").lower()
        cleaned = raw.replace(",", "").rstrip(".")
        if not cleaned:
            continue
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if suffix in SUFFIX:
            value *= SUFFIX[suffix]
        found.append((cleaned, value, bool(suffix)))
    return found


def _appears(draft: tuple[str, float, bool], source: list[tuple[str, float, bool]]) -> bool:
    """Is this draft number present in the source?

    Written exactly, it must appear exactly. Written in a different form -
    78,000 against 78K, 2.90M against 2,899,158.52 - it is compared by value
    with a one percent tolerance, because rounding to a magnitude is normal
    summarising rather than fabrication. The tolerance only applies above a
    thousand: for small integers one percent is noise, and a draft that says 4
    must not pass because the source says 4.04.
    """
    written, value, had_suffix = draft

    for source_written, _source_value, _source_suffix in source:
        if source_written == written:
            return True

    # A plain number is compared only against source numbers that were written
    # with a magnitude suffix (96000 against 96K). Comparing it against every
    # source value with a tolerance would let 2006 pass as 2026, which is the
    # one kind of error a reader notices first.
    for _written, source_value, source_had_suffix in source:
        if not had_suffix and not source_had_suffix:
            continue
        if source_value and abs(source_value - value) <= max(0.01 * value, 1):
            return True
    return False


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
    source_numbers = _scan(source)
    missing: list[str] = []
    for item in _scan(text_of(draft)):
        if _appears(item, source_numbers):
            continue
        if item[0] not in missing:
            missing.append(item[0])

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
        bullets = draft.get("bullets")
        low, high = SUMMARY_WORDS
        # A list document legitimately needs one bullet per item, and one bullet
        # per item needs room. Judging it by the prose limit alone is what made
        # a ten-project summary "a dump".
        if isinstance(bullets, list) and len(bullets) > 7:
            high = 320
        if words > high:
            defects.append(
                f"the summary is {words} words; it was asked for 120-180, and "
                f"anything over {high} is a dump rather than a summary"
            )
        elif words and words < low:
            defects.append(f"the summary is {words} words, too short to be useful")

        if isinstance(bullets, list) and len(bullets) > 10:
            defects.append(
                f"there are {len(bullets)} bullets; ten is the limit even for a list"
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
