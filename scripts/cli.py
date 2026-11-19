"""Run Content Forge from the terminal, without Streamlit.

    python scripts/cli.py document.pdf
    python scripts/cli.py document.pdf --outputs summary quiz --translate hi-IN
    python scripts/cli.py document.pdf --fake        # no key needed
    python scripts/cli.py document.pdf --trace       # show what each agent did

Exports land in outputs/. This is the script to use when something in the app
looks wrong: it has no UI in the way, so the trace is the whole story.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import config, exports, ingest, runner, schemas, store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Transform one document.")
    parser.add_argument("path", help="a .pdf, .docx, .txt or .md file")
    parser.add_argument(
        "--outputs",
        nargs="+",
        choices=[name for name in schemas.OUTPUT_SPECS if name != "translation"],
        help="force these outputs instead of asking the planner",
    )
    parser.add_argument("--depth", choices=["short", "standard", "deep"])
    parser.add_argument("--translate", metavar="LANG", help="e.g. hi-IN")
    parser.add_argument("--fake", action="store_true", help="use the fake model, no key")
    parser.add_argument("--trace", action="store_true", help="print the trace table")
    parser.add_argument("--no-save", action="store_true", help="do not write to the database")
    parser.add_argument("--no-write", action="store_true", help="do not write export files")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"No such file: {path}")
        return 1

    if not args.fake and not config.has_api_key():
        print("No SARVAM_API_KEY set. Copy .env.example to .env, or pass --fake.")
        return 1

    call = None
    translate_fn = None
    if args.fake:
        sys.path.insert(0, str(ROOT / "tests"))
        from fakes import FakeModel, FakeTranslator  # noqa: PLC0415

        call = FakeModel(scores=[5] * 20)
        translate_fn = FakeTranslator()

    text = ingest.read_document(path.name, path.read_bytes())
    print(f"{path.name}: {ingest.word_count(text)} words, "
          f"{len(ingest.chunk_text(text))} chunks\n")

    result = runner.run(
        doc_name=path.name,
        text=text,
        outputs=args.outputs,
        depth=args.depth,
        translate_to=args.translate,
        on_event=lambda event: print(f"  {event['step']:<12} {event['message']}"),
        **({"call": call} if call else {}),
        **({"translate_fn": translate_fn} if translate_fn else {}),
    )

    print(f"\nstatus: {result['status']}")
    for name, item in result["outputs"].items():
        score = f"{item['score']}/5" if item["score"] else item["status"]
        print(f"  {name:<12} {score:<8} {item['error'] or ''}")

    if args.trace:
        print(f"\n{'step':<20} {'model':<22} {'ms':>6} {'in':>7} {'out':>6}  note")
        print("-" * 92)
        for row in result["trace"]:
            print(
                f"{row['step'][:20]:<20} {row['model'][:22]:<22} {row['ms']:>6} "
                f"{row['tokens_in']:>7} {row['tokens_out']:>6}  {row['note'][:40]}"
            )

    written: list[str] = []
    if not args.no_write:
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for name, item in result["outputs"].items():
            if item["object"] is None:
                continue
            for fmt in ("md", "docx"):
                content, filename, _ = exports.render(name, item["object"], fmt, path.name)
                (config.OUTPUT_DIR / filename).write_bytes(content)
                written.append(filename)

        if result.get("translation") and result["translation"]["status"] == "ok":
            filename = f"translation_{result['translation']['language']}.txt"
            (config.OUTPUT_DIR / filename).write_text(
                result["translation"]["text"], encoding="utf-8"
            )
            written.append(filename)

    if not args.no_save:
        store.save_run(result)

    if args.no_write:
        print("\n--no-write: no export files were written")
    else:
        print(f"\n{len(written)} files written to {config.OUTPUT_DIR}/")
    print(f"cost: ₹{result['usage']['cost_inr']:.4f} "
          f"({result['usage']['prompt_tokens']} in, "
          f"{result['usage']['completion_tokens']} out), "
          f"{result['duration_ms'] / 1000:.1f}s")
    return 0 if result["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
