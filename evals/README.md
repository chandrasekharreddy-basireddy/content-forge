# The evaluation set

Eleven documents, each with a reference summary in `references/`. This is the
data the numbers in the report come from, so it is worth knowing exactly what
it is.

| Files | What they are | Licence |
|---|---|---|
| `01`–`03` | Synthetic sample documents, written for this project to test the harness | none needed — original text |
| `04`–`11` | Eight Wikipedia articles, unmodified except for length | CC BY-SA 4.0 |

The eight real documents were retrieved on 19 November 2026 and trimmed to
roughly 1,300 words each so a full evaluation run stays inside a free tier's
rate limit. Source URLs and licences are recorded per file in `manifest.json`
and in the header of each document.

**CC BY-SA 4.0 means two things if you redistribute these files:** keep the
attribution header, and keep the same licence on the text. It does not restrict
sending the text to an API.

## Read this before you trust the numbers

**The reference summaries are drafts, not human references.** They were written
by the assistant that scaffolded this project, from the opening of each
document. That makes them a starting point and a typing shortcut, not a
measurement instrument.

Two consequences, and both matter for the report:

1. **Rewrite them in your own words.** A reference summary produced by the same
   kind of model as the one being evaluated measures agreement between models,
   not the quality of a summary. ROUGE-L against an AI-written reference is
   close to meaningless.
2. **Check them against the full document.** A reference written from the first
   few paragraphs can miss the point the article is actually making. The
   summaries for the eight Wikipedia files were written from the lead sections.

If you submit the numbers without doing both of these, you are reporting a
figure you cannot defend when someone asks how the reference was produced. That
is worse than having no figure.

## Running it

```bash
python evals/run_eval.py --limit 3     # a quick check on three documents
python evals/run_eval.py               # the full set
python evals/run_eval.py --fake        # the harness itself, no API key
```

Results are written to `evals/results.csv`, which is gitignored — it is a
measurement, not source. Copy the table into the report.

## Adding a document

Drop a `.txt` in `testset/` and a summary with the same file name in
`references/`. The harness pairs them by name and skips any document without a
reference, so a half-finished set still runs.
