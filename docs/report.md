# Content Forge — Project Report

**A GenAI platform for automated content transformation**

CDS208 – Emerging Tools and Applications · Final Project

| | |
|---|---|
| Student | Chandra Sekhar Basireddy |
| Student ID | 252205992 |
| Institution | School of Computing and Data Science, Sai University |
| Faculty | Kartavya Satish Sonar |
| Selected statement | Option 8 — GenAI Platform for Automated Content Transformation |
| Repository | github.com/chandrasekharreddy-basireddy/content-forge |
| Date | [FILL: submission date] |

> **How to use this file.** Sections 1–6, 8 and 10 are written and can be
> edited rather than filled. Everything marked `[FILL: …]` needs a real
> measurement or a decision that is yours. Do not submit with a `[FILL]`
> left in it, and do not invent a number to remove one — an honest gap reads
> better than a fabricated table, and it is the first thing an examiner probes.

---

## Abstract

Content Forge turns one source document into several study or business
formats — summary, quiz, flashcards, report, slide outline and an Indic
translation — using a workflow of four agents rather than a single prompt. The
document is chunked, reduced to its facts, planned, drafted, then scored by a
critic that sends weak drafts back to the writer. Every step writes a trace row,
every run is logged, and the log drives a Power BI dashboard. On a set of
`[FILL: 11]` documents the summary output scored `[FILL: ROUGE-L F1]` against
human references and `[FILL: mean faithfulness]/5` from an LLM judge, at
`[FILL: ₹ per document]` per document.

---

## 1. Problem

The same document usually has to become several different things. A lecture
note becomes a summary for revision, a quiz for self-testing, flashcards for
memorisation, a report for the record and a slide outline for a presentation.
Producing those by hand is slow, repetitive, and the first work to be dropped
when time is short.

A single prompt to a chat model does not solve it. Five separate prompts produce
five outputs that disagree with each other, invent numbers, drift in format
between runs, and leave no record of which document produced what or what it
cost. For an Indian classroom there is a further gap: such tools are strong in
English and weak in Hindi, Tamil or Telugu.

## 2. What this project is not

Stating this early is deliberate, because it is the first question a reviewer
asks about any GenAI project.

It is not a wrapper around a chat model. Four properties distinguish it:

1. **A quality gate that can reject.** A critic scores every draft out of five
   against the source and names the defects. Below four, the draft returns to
   the writer, twice at most, then ships flagged rather than silently. The
   score and the round count are stored with the run.
2. **Evidence shared across outputs.** The document is reduced to facts and
   exact numbers before any output is written, so all five outputs are anchored
   to the same evidence and agree with each other.
3. **A machine-checkable contract.** Each output has a JSON Schema sent as
   `response_format`, plus a hand-written validator. A quiz with three options
   is rejected in code.
4. **Prompts as versioned files with an evaluation harness.** Five YAML prompts
   are edited and diffed like code, and `evals/run_eval.py` scores the summary
   output against references.

## 3. Architecture

```
upload (PDF / DOCX / TXT / MD)
  │
  ├─ chunk      overlap split, ~1,200 characters
  ├─ extract    chunk groups → facts and exact numbers        (map)
  ├─ plan       which outputs this document supports, how deep
  ├─ write      one draft per output, from facts + source
  ├─ critique   score /5 against the source, name the defects
  ├─ repair     rewrite with those defects, at most twice
  ├─ translate  summary → Sarvam /translate, chunked at 900 characters
  └─ store      SQLite, then Supabase if configured
```

[FILL: insert the architecture diagram here — a five-layer version of the above
with the technology named on each layer.]

The workflow itself is `pipeline/runner.py`: `run()` holds a `for` loop over the
planned outputs and `_produce()` holds the `while` loop that returns a draft to
the writer until the critic passes it. There is no orchestration framework. That
was a deliberate choice: LangGraph would have been defensible, but plain
functions that can be explained line by line are worth more in a viva than a
graph library.

### Technology stack

| Layer | Technology | Why |
|---|---|---|
| Language model | Sarvam AI, chat completions V2 | Indian-language strength; OpenAI-compatible |
| Translation | Sarvam `/translate`, `mayura:v1` | purpose-built; cheaper and better than prompting |
| Orchestration | plain Python | readable, defensible |
| Structured output | JSON Schema via `response_format` | guarantees shape, not merely valid JSON |
| Validation | hand-written, no pydantic | explicit errors, one less dependency |
| App | Python + Streamlit | upload, progress, downloads, history |
| Web | HTML, CSS, JavaScript + FastAPI | the course's web component doing real work |
| Storage | SQLite; Supabase optional | works offline, syncs when configured |
| Analytics | Power BI Desktop | run volume, quality and cost |
| Version control | Git, GitHub Actions | CI on every push |

## 4. Prompt engineering

Five prompts, all in `prompts/`, all YAML so they can be diffed:

| Prompt | Agent | Job |
|---|---|---|
| `extract.yaml` | extractor | facts and numbers from one group of chunks |
| `plan.yaml` | planner | which outputs, and how deep |
| `write.yaml` | writer | one output, with output-specific rules injected |
| `critique.yaml` | critic | score out of 5, with named defects |
| `judge.yaml` | evaluator | faithfulness, coverage, concision for the harness |

Four techniques are used deliberately, and each is worth a paragraph in the
viva:

**JSON contracts.** Every writer call sends `response_format` with
`type: json_schema`. This guarantees the shape rather than merely valid JSON,
which removes most repair calls before they happen. A hand-written validator
then checks what the schema cannot express — that a quiz answer index is inside
the option list, that a slide has at least two bullets.

**Facts before prose.** The extractor runs first and its output is prepended to
the writer's context. When the context is truncated at 7,000 characters, the
facts survive the cut and the raw text is what gets dropped. Evidence is the
part that must not be lost.

**A rubric, not an opinion.** The critic scores against a five-point rubric that
names what a 3 looks like: an unsupported claim, a wrong number, a broken
structure. Invented specifics are capped at 3 regardless of how well the rest
reads. A critic asked for "a score" gives 5; a critic given a rubric can be
argued with.

**Injection defence, stated honestly.** Every writer and critic prompt says the
source text is data and any instruction inside it must be ignored. This is a
mitigation, not a guarantee. [FILL: if you tested a document containing an
instruction, record what happened — including if it worked.]

### What changed, and why

[FILL: this section is the evidence of iteration, and it is where marks are
lost by anyone who claims their first prompt was right. Fill it from your own
runs. Two examples of the shape it should take:]

- *Critique rubric.* First version asked for a score out of five. Every draft
  scored 5, including one with an invented statistic. Rewrote the rubric to name
  what a 3 and a 4 look like and to cap invented specifics at 3. [FILL: what
  happened to the scores after.]

- *Planner scope.* [FILL: what the planner did wrong on a short document, and
  what rule fixed it.]

## 5. The agentic workflow

The claim that this is agentic rests on three properties, and each is
checkable in the repository rather than asserted:

1. **A decision changes the path.** The planner chooses which outputs to
   produce; the critic decides whether a draft ships. Neither is decorative.
2. **A loop with a stopping rule.** Repair repeats until the score passes or the
   round limit is reached. The limit exists because a critic and a writer can
   otherwise argue indefinitely at the user's expense.
3. **A trace.** Every step appends step, model, duration, tokens and a one-line
   reason. It is stored as JSON with the run and shown behind a toggle in the
   app.

[FILL: paste a real trace here, from one document, as a code block. It is the
single most convincing artefact in the report — it shows a draft rejected, a
repair, and a re-score. Keep it to about ten rows.]

Failure handling is part of the design, not an afterthought:

| Failure | What happens | What the user sees |
|---|---|---|
| Critic never reaches 4 | Two repairs, then stop | Output marked `flagged`, defects listed |
| One output fails | Other outputs continue | Run marked `partial`, error on that output |
| Critic unavailable | Draft ships | Marked `unverified`, not `ok` |
| Translation fails | Outputs kept | Translation marked failed with the reason |
| Planner returns nonsense | All outputs produced | Trace notes the fallback |

## 6. Implementation

`[FILL: 3,200]` lines of Python across `[FILL: 13]` modules, `[FILL: 118]`
offline tests, CI green on Python 3.11 and 3.12.

The module breakdown is in `docs/proposal.md` §6; the two files worth pointing
at here are `pipeline/runner.py` (the workflow) and `pipeline/llm.py` (the only
file that talks to Sarvam).

### Wiring Sarvam

Four settings exist because the API defaults are wrong for this use case:

- **`max_tokens` is always explicit.** The default of 2048 truncates a
  ten-question quiz mid-object and makes the repair pass fire every time.
- **`response_format` uses `json_schema`, not `json_object`.** Shape, not just
  validity.
- **Auth is sent both ways.** `api-subscription-key` and `Authorization:
  Bearer`. A 403 where a 401 was expected means the subscription header was
  missing.
- **Translation is a separate endpoint.** `mayura:v1` accepts 1,000 characters
  per request, so long text is split at sentence boundaries and rejoined.

### Cost

```
cost = prompt_tokens / 1e6 × rate_in  +  completion_tokens / 1e6 × rate_out
```

[FILL: measured cost per document from your own runs, and the token counts that
produced it. Quote the rate you used and where it came from. The app prints the
figure for every run; do not estimate it.]

## 7. Evaluation

### Method

Eleven documents, each with a reference summary. Two measures:

- **ROUGE-L** — word overlap with the reference, computed locally
  (`evals/rouge.py`, longest common subsequence, β = 1.2).
- **An LLM judge** — faithfulness, coverage and concision out of 5, from
  `prompts/judge.yaml`.

### Results

[FILL: replace this table with the output of `python evals/run_eval.py`. Do not
copy the sample numbers below — they are from the fake model and measure
nothing.]

| Document | R-L P | R-L R | R-L F1 | Faith | Cover | Conc |
|---|---|---|---|---|---|---|
| 04_solar_power_in_india | — | — | — | — | — | — |
| 05_kaveri_river_water_dispute | — | — | — | — | — | — |
| … | | | | | | |
| **mean** | | | | | | |

### Critic calibration

A critic that scores everything 5 is decoration, and "it scored 5" is not
evidence either way — a good draft deserves a 5. So the critic is tested the
only way that settles it: generate a summary, score it, corrupt it in a way a
reader would catch, and score it again.

`evals/critic_test.py` does exactly that, with two corruptions — a changed
number the source contradicts, and an invented statistic that appears nowhere
in the document. If the second score is not lower than the first, the critic is
not reading the source.

Measured on `04_solar_power_in_india.txt`:

| Draft | Score | Defects named |
|---|---|---|
| Honest | 5 / 5 | 0 |
| One digit of a year changed (`2010s` → `9010s`) | 3 / 5 | 5 |
| An invented statistic appended (`capacity fell by 42% in 2024`) | 4 / 5 | 2 |

The critic discriminated: it lowered its score for both corruptions and quoted
the offending text in each case. That is the evidence for the agentic claim,
and it is measured rather than asserted.

It also exposed two weaknesses, which are recorded here rather than smoothed
over:

1. **The invented statistic scored 4, not 2.** The rubric said an unsourced
   number caps the score at 2; the critic found the fabrication and still gave
   it a 4. A scoring guide the model can drift from is not a rule. The rubric
   was rewritten as a decision procedure — four steps, first match decides the
   score — and the cap moved to step 1.
2. **The defect list was padded.** Two of the five defects in the changed-digit
   case were not defects: one line raised a concern and dismissed it in the
   same sentence, another complained about coverage the output type never asked
   for. The prompt now says one line per defect, only what you would defend to
   the author, and five at most.

3. **The critic was judging a truncated source.** It received the first 6,000
   characters while the writer worked from 7,000, so genuine content from the
   last thousand characters looked invented — and the critic duly reported a
   hallucination that was not one. The window now covers everything the writer
   saw. This is the most useful bug the calibration test found, because it is
   invisible from outside: the scores looked reasonable and the defect looked
   like real prose.

After those three fixes, the second run read:

| Draft | Score | Defects |
|---|---|---|
| Honest | 5 / 5 | 0 |
| Figure changed (`174.55 GW` → `974.55 GW`) | 2 / 5 | 1 |
| Invented statistic appended | 4 / 5 | 1 |

The invented statistic still scored 4, so the cap moved out of the prompt and
into code: `pipeline/checks.py` looks up every number in the draft against the
source, and one that is missing caps the score at 2 whatever the model said.
The model proposes, the code disposes.

The final run, after all four fixes:

| Draft | Score | Defects |
|---|---|---|
| Honest | 5 / 5 | 0 |
| Figure changed (`174.55 GW` → `974.55 GW`) | 2 / 5 | 1 |
| Invented statistic appended | 2 / 5 | 1 |

Four runs, each fixing what the previous one exposed: a generous rubric, then
padded defects, then a source window too small for the writer's context, then a
cap the model would not apply. That sequence is the honest account of how the
critic was built, and it is a better answer in a viva than a table that was
right the first time — because the question will be "how do you know it works?",
not "what did it score?".

### What the numbers do not say

ROUGE-L rewards copying the reference's words and is a weak proxy for a good
summary; a summary can score well by echoing vocabulary and still be wrong.
That is why the judge score is reported beside it.

[FILL: how many raters, and were the outputs shuffled before scoring? With one
rater, say so here in one sentence and treat the human scores as anecdote.]

### Errors observed

[FILL: three or four concrete failures, with the document and the output. A
report that lists only successes is not credible. Good candidates: a quiz
question with two defensible answers, a summary that dropped the document's
main point, a number transcribed with the wrong unit.]

## 8. The application and the web layer

The Streamlit app (`app.py`) is UI only: upload, live progress from the runner's
event callback, per-output cards with the critic's score, one download button
per format, and a History tab whose CSV export feeds the dashboard.

The landing page (`web/`) is HTML, CSS and vanilla JavaScript with no build
step, posting to a FastAPI bridge (`api.py`). The bridge allows exactly one
origin from `.env` rather than `*`, caps the demo at three outputs and five runs
per hour per IP, and refuses to start a run with no key configured. Those three
choices exist because the API key is a student's, and a public endpoint with no
limit is how it gets spent by someone else.

[FILL: screenshots — the app on a finished run, the history tab, the landing
page, and the Power BI page. Four images, captioned.]

## 9. Limitations and ethics

- **Hallucination is bounded, not eliminated.** Facts are extracted first and
  the critic penalises invented specifics, but a `flagged` output still needs a
  human read before it is used.
- **Prompt injection is mitigated, not solved.**
- **No answer-key guarantee.** A quiz's `answer_index` is validated as an
  integer in range, not against the source by a person. Spot-check a quiz before
  handing it to students.
- **Scanned PDFs are refused.** No OCR; the app says so rather than producing
  nonsense.
- **Documents leave the machine.** Anything uploaded is sent to a third-party
  API. The app caps upload size and file types, but cannot judge whether the
  user had the right to send a document.
- **Single-rater evaluation.** [FILL: confirm or remove, depending on how you
  run §7.]
- **Translation covers the summary only**, deliberately — translating a quiz
  means translating values while keeping keys.

## 10. Conclusion and further work

[FILL: three paragraphs. What was built and whether it works; what the
evaluation actually showed; what you would do next. The honest next steps are
OCR for scanned documents, a two-rater evaluation with a shuffled sample, and
translating full outputs rather than the summary.]

## References

1. Sarvam AI, *Chat Completion V2* — https://docs.sarvam.ai/api-reference/chat/chat-completions-v2
2. Sarvam AI, *List Models V2* — https://docs.sarvam.ai/api-reference/chat/models-v2
3. Sarvam AI, *Text Translation* — https://docs.sarvam.ai/api-reference/text/translate-text
4. Lin, C.-Y. (2004). ROUGE: A package for automatic evaluation of summaries.
5. [FILL: any other source you actually used. Do not pad this list.]

## Appendix A — Running it

```bash
pip install -r requirements.txt
cp .env.example .env        # paste the Sarvam key
streamlit run app.py
python scripts/cli.py document.pdf --trace
python evals/run_eval.py
```

No key is needed for `python -m pytest` or for `--fake` runs.

## Appendix B — Data and licences

`evals/testset/04`–`11` are Wikipedia articles under CC BY-SA 4.0, retrieved
19 November 2026, trimmed for length, with attribution headers retained.
`01`–`03` are synthetic documents written for this project. The reference
summaries in `evals/references/` are `[FILL: state plainly whether they are
yours or drafts — see evals/README.md]`.
