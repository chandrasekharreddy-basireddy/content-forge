"""Does the critic actually discriminate? Measure it, don't argue about it.

    python evals/critic_test.py                      # default document
    python evals/critic_test.py path/to/doc.txt
    python evals/critic_test.py --fake               # offline smoke test

The question this answers: when the writer produces something wrong, does the
critic notice? A critic that scores everything 5 is decoration, and "it scored
5" is not evidence either way - a good draft deserves a 5.

So the test does this, on one document:

    1. generate a summary
    2. ask the critic to score it                      -> score A
    3. corrupt the summary in a way a reader would catch
       (a changed number, or an invented statistic)
    4. ask the critic to score the corrupted version    -> score B

If B is not lower than A, the critic is not reading the source, and the
agentic claim in the report does not hold. That comparison is the whole test,
and it is cheap: four model calls.

Two corruptions are tried because they fail differently. A changed number is
the easy one - the source contradicts it directly. An invented statistic is
the one that matters in practice: it looks plausible, appears nowhere in the
document, and is exactly what a student would hand in by accident.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import agents, ingest, llm  # noqa: E402

DEFAULT_DOC = ROOT / "evals" / "testset" / "04_solar_power_in_india.txt"

INVENTED = (
    " Independent analysis also found that installed capacity fell by 42% in "
    "2024, reversing three years of growth."
)


def summarise(text: str, call) -> tuple[str, dict]:
    """One extract pass and one write pass, enough to have a draft to corrupt."""
    facts, numbers = [], []
    for index, chunk in enumerate(ingest.chunk_text(text), start=1):
        try:
            result, _ = agents.extract(chunk, index, 1, call=call)
            facts += result["facts"]
            numbers += result["numbers"]
        except Exception:  # noqa: BLE001 - a missing chunk must not stop the test
            continue

    context = "\n".join(facts) + "\n" + "\n".join(numbers) + "\n\n" + text[:4000]
    draft, _ = agents.write(
        output="summary", chunk=context, part=1, parts=1, depth="standard", call=call
    )
    return str(draft.get("summary", "")), draft


def corrupt_number(text: str) -> tuple[str, str, str]:
    """Change one digit of a substantive number. Returns (text, before, after).

    It prefers a figure with a unit - "174.55 GW", "14%", "2,245 MW" - because
    changing a year is close to a typo, and a typo is the easy case. A changed
    quantity is what would actually mislead a reader.
    """
    patterns = [
        r"\d[\d,.]*\s?(?:GW|MW|kW|%|percent|tonnes?|crore|lakh|km|sq km)",
        r"\d[\d,.]*",
    ]
    match = None
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            break
    if not match:
        return text + INVENTED, "nothing", "an invented statistic"

    before = match.group(0)
    index = match.start()
    original = text[index]
    replacement = "9" if original != "9" else "1"
    after = replacement + before[1:]
    return text[:index] + after + text[index + len(before) :], before, after


def score(draft: dict, source: str, call) -> dict:
    """Ask the critic for a verdict on one draft."""
    verdict, _ = agents.critique("summary", draft, source, call=call)
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description="Test whether the critic discriminates.")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_DOC))
    parser.add_argument("--fake", action="store_true", help="offline, with the fake model")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.is_file():
        print(f"No such file: {path}")
        return 1

    call = llm.chat
    if args.fake:
        sys.path.insert(0, str(ROOT / "tests"))
        from fakes import FakeModel  # noqa: PLC0415

        call = FakeModel(scores=[5, 5, 5, 5])

    source = ingest.read_document(path.name, path.read_bytes())
    print(f"{path.name}: {ingest.word_count(source)} words\n")

    text, draft = summarise(source, call)
    print("--- generated summary ---")
    print(text[:600] + ("..." if len(text) > 600 else ""))
    print()

    honest = score(draft, source, call)
    print(f"honest draft      : {honest['score']}/5, {len(honest['defects'])} defects")
    for defect in honest["defects"]:
        print(f"    - {defect}")

    results = {}

    # Corruption 1: a figure the source contradicts.
    changed_text, before, after = corrupt_number(text)
    changed = dict(draft)
    changed["summary"] = changed_text
    first = score(changed, source, call)
    results["a changed figure"] = first
    print(f"\nchanged figure    : {before!r} -> {after!r} "
          f"(scored {first['score']}/5, {len(first['defects'])} defects)")
    for defect in first["defects"]:
        print(f"    - {defect}")

    # Corruption 2: a statistic that appears nowhere in the source.
    invented = dict(draft)
    invented["summary"] = text + INVENTED
    second = score(invented, source, call)
    results["an invented statistic"] = second
    print(f"\ninvented statistic: {second['score']}/5, {len(second['defects'])} defects")
    for defect in second["defects"]:
        print(f"    - {defect}")

    print("\n--- verdict ---")
    failures = 0
    for label, verdict in results.items():
        if verdict["score"] < honest["score"]:
            print(f"  caught {label}: {honest['score']} -> {verdict['score']}")
        else:
            failures += 1
            print(f"  MISSED {label}: still {verdict['score']}, same as the honest draft")

    if failures:
        print(
            "\nThe critic is not discriminating on this document. Two honest\n"
            "conclusions are possible: the rubric needs to be stricter, or this\n"
            "document is too easy to be a test - the model can summarise it from\n"
            "memory. Try a document the model cannot have seen before reporting\n"
            "that the critic works."
        )
        return 1

    print("\nThe critic lowered its score for both corruptions. That is evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
