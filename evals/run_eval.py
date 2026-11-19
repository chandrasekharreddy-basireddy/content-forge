"""The evaluation harness. This is the file that answers "does it work?".

Run it:

    python evals/run_eval.py                 # real Sarvam calls
    python evals/run_eval.py --fake          # no key, fake model, pipeline only
    python evals/run_eval.py --limit 3       # a quick check

It compares the generated summary of each document with a human-written
reference summary, in two ways:

    ROUGE-L      word overlap, computed locally in evals/rouge.py
    LLM judge    faithfulness, coverage and concision, scored 1-5 by a model

ROUGE-L alone is a poor measure: a summary can score well by copying words and
still be wrong. The judge alone is expensive and not reproducible. Reporting
both, and saying plainly which one is noisy, is the honest answer.

Expected layout:

    evals/testset/          20 documents you did not write, licence-safe
    evals/references/       one human-written summary per document, same name
"""

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import config, llm, runner  # noqa: E402
from pipeline.prompts import build_messages  # noqa: E402

sys.path.insert(0, str(ROOT / "evals"))
from rouge import corpus_rouge_l, rouge_l  # noqa: E402

TESTSET = ROOT / "evals" / "testset"
REFERENCES = ROOT / "evals" / "references"
RESULTS = ROOT / "evals" / "results.csv"

JUDGE_SCHEMA = {
    "name": "judge",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "faithfulness": {"type": "integer"},
            "coverage": {"type": "integer"},
            "concision": {"type": "integer"},
            "reason": {"type": "string"},
        },
        "required": ["faithfulness", "coverage", "concision", "reason"],
        "additionalProperties": False,
    },
}


def judge(source: str, reference: str, generated: str, call=None) -> dict:
    """Ask the model to score one summary. Returns zeros if it cannot."""
    messages = build_messages(
        "judge",
        source=source[:6000],
        reference=reference[:3000],
        generated=generated[:3000],
    )
    try:
        text, _ = (call or llm.chat)(messages, model="strong", json_schema=JUDGE_SCHEMA)
        result = llm.parse_json(text)
    except Exception as exc:  # noqa: BLE001 - one bad judge call must not stop the run
        return {
            "faithfulness": 0,
            "coverage": 0,
            "concision": 0,
            "reason": f"judge failed: {exc}",
        }
    return result


def evaluate(
    limit: int = 0, use_fake: bool = False, translate: bool = False
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Run the pipeline over the test set and score every document.

    Returns (rows, pairs): one row per document for the CSV, and the
    (generated, reference) text pairs that corpus ROUGE-L needs.
    """
    documents = sorted(TESTSET.glob("*.txt"))
    if limit:
        documents = documents[:limit]

    if not documents:
        print(f"No documents found in {TESTSET}")
        print("Put .txt files there, plus a matching file in evals/references/.")
        return [], []

    call = llm.chat
    if use_fake:
        sys.path.insert(0, str(ROOT / "tests"))
        from fakes import FakeModel, FakeTranslator  # noqa: PLC0415

        call = FakeModel(scores=[5] * 100)
        translate_fn = FakeTranslator()
    else:
        translate_fn = llm.translate

    rows: list[dict] = []
    pairs: list[tuple[str, str]] = []

    for index, path in enumerate(documents, start=1):
        reference_path = REFERENCES / path.name
        if not reference_path.exists():
            print(f"[{index}/{len(documents)}] {path.name}: no reference summary, skipped")
            continue

        source = path.read_text(encoding="utf-8")
        reference = reference_path.read_text(encoding="utf-8")

        print(f"[{index}/{len(documents)}] {path.name} ... ", end="", flush=True)

        record = runner.run(
            doc_name=path.name,
            text=source,
            outputs=["summary"],
            translate_to="hi-IN" if translate else None,
            call=call,
            translate_fn=translate_fn,
        )
        summary = (record["outputs"].get("summary") or {}).get("object") or {}
        generated = str(summary.get("summary", ""))

        scores = rouge_l(generated, reference)
        judged = judge(source, reference, generated, call=call)
        pairs.append((generated, reference))

        rows.append(
            {
                "document": path.name,
                "rouge_l_precision": scores["precision"],
                "rouge_l_recall": scores["recall"],
                "rouge_l_f1": scores["f1"],
                "judge_faithfulness": judged.get("faithfulness", 0),
                "judge_coverage": judged.get("coverage", 0),
                "judge_concision": judged.get("concision", 0),
                "critic_score": (record["outputs"].get("summary") or {}).get("score"),
                "status": record["status"],
                "words": record["words"],
                "cost_inr": record["usage"]["cost_inr"],
                "duration_ms": record["duration_ms"],
            }
        )
        print(f"ROUGE-L F1 {scores['f1']:.3f}, faithfulness {judged.get('faithfulness')}/5")

    return rows, pairs


def report(rows: list[dict], pairs: list[tuple[str, str]]) -> None:
    """Print the table you paste into the project report."""
    if not rows:
        return

    print()
    print(f"{'document':28} {'R-L P':>6} {'R-L R':>6} {'R-L F1':>7} "
          f"{'faith':>6} {'cover':>6} {'conc':>5}")
    print("-" * 74)
    for row in rows:
        print(
            f"{row['document'][:28]:28} {row['rouge_l_precision']:>6.3f} "
            f"{row['rouge_l_recall']:>6.3f} {row['rouge_l_f1']:>7.3f} "
            f"{row['judge_faithfulness']:>6} {row['judge_coverage']:>6} "
            f"{row['judge_concision']:>5}"
        )

    count = len(rows)
    mean = lambda key: sum(row[key] for row in rows) / count  # noqa: E731

    print("-" * 74)
    print(
        f"{'mean':28} {mean('rouge_l_precision'):>6.3f} "
        f"{mean('rouge_l_recall'):>6.3f} {mean('rouge_l_f1'):>7.3f} "
        f"{mean('judge_faithfulness'):>6.2f} {mean('judge_coverage'):>6.2f} "
        f"{mean('judge_concision'):>5.2f}"
    )
    corpus = corpus_rouge_l(pairs)
    print(
        f"\n{count} documents, corpus ROUGE-L F1 {corpus['f1']:.3f}, "
        f"total cost ₹{sum(r['cost_inr'] for r in rows):.4f}"
    )
    print("ROUGE-L is word overlap, not correctness. Report the judge score too.")


def write_csv(rows: list[dict]) -> None:
    """Save the results, so the numbers in the report are reproducible."""
    if not rows:
        return
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} rows to {RESULTS.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the pipeline against references.")
    parser.add_argument("--limit", type=int, default=0, help="only the first N documents")
    parser.add_argument("--fake", action="store_true", help="run offline with a fake model")
    parser.add_argument("--translate", action="store_true", help="also translate summaries")
    args = parser.parse_args()

    if not args.fake and not config.has_api_key():
        print("No SARVAM_API_KEY set. Use --fake to check the harness offline.")
        return

    rows, pairs = evaluate(limit=args.limit, use_fake=args.fake, translate=args.translate)
    report(rows, pairs)
    write_csv(rows)


if __name__ == "__main__":
    main()
