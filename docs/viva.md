# Viva preparation — twelve questions and answers

Answer each in under ninety seconds. The pattern that works: state the decision,
give the reason, then point at the file where it is visible.

---

**1. Why is this agentic rather than a prompt with extra steps?**

Because a decision changes the path and a loop can reject. The planner chooses
which outputs to build, and the critic decides whether a draft ships — a draft
below four goes back to the writer with named defects, twice at most. You can
see both in `pipeline/runner.py`, and the trace stored with every run shows the
rejection and the repair.

**2. What stops the critic and writer arguing forever?**

`MAX_REPAIRS` in `pipeline/config.py`, default 2. When the budget is spent the
best draft ships marked `flagged` with the remaining defects listed. The run
never silently upgrades a bad output to good.

**3. How do you know the outputs are grounded in the document?**

Two mechanisms. Facts and exact numbers are extracted before anything is
written, and the writer's context puts those facts first so they survive
truncation. Then the critic is told to score invented specifics at 3 or below
regardless of how well the rest reads. Neither is a proof — a `flagged` output
still needs a human read, and the report says so.

**4. Why chunk the document at all if the model has a 128k context?**

Two reasons, and neither is context length. Cost and control: one extraction
call per 6,000 characters is far cheaper than sending a whole book, and
chunking gives a natural place to cap a 200-page document at six calls. The
chunks also overlap by 150 characters so a fact on a boundary appears whole in
at least one chunk.

**5. What happens if one output fails?**

The run continues and is marked `partial`. Each output has its own status —
`ok`, `flagged`, `unverified`, `failed` — and the failure is recorded with its
error. A failed quiz must not cost you the summary you already have.

**6. Why no LangGraph, when the course mentions agentic workflows?**

LangGraph is a reasonable choice and I started there. I dropped it because the
workflow is a for loop and a while loop, and a hundred lines of plain Python
that you can explain line by line is worth more in a viva than a graph library
you have to hand-wave about. The trade-off is real: if the workflow grew
branches or needed persistence between steps, a framework would earn its place.

**7. Why Structured Outputs and a hand-written validator? Isn't that
duplicated work?**

They catch different things. `response_format` guarantees the JSON matches the
schema — right keys, right types. It cannot express "the answer index must point
at one of the four options" or "a slide needs at least two bullets". Those live
in `pipeline/schemas.py`. And the API guarantee only covers API replies; a
cached reply or a repair that went wrong still passes through the validator.

**8. What is the critic actually scoring against?**

The source text, not the writer's output alone. It sees the source and the
draft and is asked whether every claim is traceable. That is why it can catch a
plausible statistic that is not in the document — the failure mode that makes
generated study material dangerous.

**9. Why is translation a separate API call rather than a prompt?**

Sarvam's `/translate` is a purpose-built translation model: cheaper, better at
Indic output, and it handles language detection. Prompting a chat model to
translate costs more tokens and produces a translation that drifts stylistically
from the source. The catch is a hard limit — `mayura:v1` takes 1,000 characters
per request — so `pipeline/llm.py` splits on sentence boundaries and rejoins.

**10. How do you know any of this works?**

Eighty-seven offline tests that need no key, including the critic loop firing
and stopping, a failing output not killing a run, a 429 being retried while a
400 fails fast, and the CSV export quoting commas so Power BI can read it. Plus
an evaluation harness with ROUGE-L and an LLM judge over eleven documents, whose
results are in the report. [Adjust the numbers to what you actually ran.]

**11. What is the weakest part of the project?**

The evaluation. The reference summaries are `[state plainly what they are]`,
ROUGE-L is a weak proxy for a good summary, and with a single rater the human
scores are anecdote. I report the judge scores beside ROUGE-L and say so rather
than presenting one number as if it settled the question.

**12. If you had two more weeks, what would you build?**

OCR for scanned PDFs, which is the single biggest practical gap — a scanned
document is refused outright today. Then a two-rater evaluation with a shuffled
sample, which would make the human numbers mean something. Then translation of
full outputs, keeping JSON keys in English while translating values.

---

## Numbers to have ready

Memorise these; they get asked and they should match the repository.

| Thing | Value |
|---|---|
| Tests | `[FILL]` |
| Python modules / lines | `[FILL]` |
| Chunk size / overlap | 1,200 / 150 characters |
| Extraction window / max calls | 6,000 characters / 6 |
| Pass score / max repairs | 4 of 5 / 2 |
| `max_tokens` sent | 4,096 (API default is 2,048) |
| Translation chunk | 900 characters (API limit 1,000) |
| Cost per document | `[FILL: measured]` |
| Mean ROUGE-L F1 | `[FILL: measured]` |
| Mean judge faithfulness | `[FILL: measured]` |
