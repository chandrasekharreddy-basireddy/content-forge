# Content Forge

**One document in. Summaries, quizzes, flashcards, reports and slides out.**

Content Forge is a GenAI content transformation platform: it reads a source
document, extracts the facts from it, and writes study or business material that
stays inside those facts. Every draft is scored by a critic agent and sent back
to the writer until it is good enough to ship.

Built for **CDS208 – Emerging Tools and Applications**, Option 8: *GenAI Platform
for Automated Content Transformation*.

| | |
|---|---|
| Student | Chandra Sekhar Basireddy (252205992) |
| Institution | School of Computing and Data Science, Sai University |
| Mode | Solo build |
| Model provider | Sarvam AI (chat completions V2 and the translation endpoint) |
| Language | Python 3.11+, plain — no orchestration framework |

---

## 1. What it does

Upload a PDF, DOCX, TXT or MD file and the platform produces up to six outputs:

| Output | What it is |
|---|---|
| Summary | 120–180 words of prose, plus takeaways and key terms |
| Quiz | 5 multiple-choice questions with four options and an explanation |
| Flashcards | 8 question/answer cards, one idea each |
| Report | A titled document with 4 headed sections |
| Slide outline | 6 slides with bullets and speaker notes |
| Translation | The summary in Hindi, Tamil, Telugu or any of Sarvam's supported languages |

Each output is downloadable as Markdown, Word, PowerPoint, CSV or JSON. Every
run is logged, and the log feeds a Power BI dashboard.

## 2. Why it is not a ChatGPT wrapper

This is the question to answer before it is asked. Four things separate the
pipeline from a single prompt in a text box:

1. **The critic loop.** A writer drafts, a critic scores out of 5 against the
   source, and anything below 4 goes back to the writer with the named defects,
   twice at most. The score, the defects and the number of rounds are stored with
   every run and shown in the UI. A wrapper has no second opinion.
2. **Map-reduce over chunks.** A long document never goes into one prompt. Each
   chunk is reduced to its facts and numbers first, and every writer works from
   that same evidence, so all five outputs agree with each other.
3. **A machine-checkable contract.** Each output has a JSON Schema sent as
   `response_format`, plus a hand-written validator. A quiz with three options is
   caught in code, not by a human reading the screen.
4. **Prompts as files, with an evaluation harness.** Five YAML prompts can be
   edited and diffed; `evals/run_eval.py` scores the summary output against
   human-written references with ROUGE-L and an LLM judge.

## 3. How it works

```
upload
  │
  ├─ chunk      ingest.py       overlap-split into ~1,200-character pieces
  ├─ extract    agents.py       each chunk → facts and exact numbers   (map)
  ├─ plan       agents.py       which outputs this document supports, how deep
  ├─ write      agents.py       one draft per output, from facts + source
  ├─ critique   agents.py       score /5 against the source, name the defects
  ├─ repair     agents.py       rewrite with those defects, up to twice
  ├─ translate  llm.py          summary → Sarvam /translate, chunked at 900 chars
  └─ store      store.py        SQLite, then Supabase if configured
```

Read **`pipeline/runner.py`** first. It is about a hundred lines: a `for` loop
over the outputs the planner chose, and a `while` loop that sends a draft back
to the writer until the critic is satisfied. Everything else in `pipeline/` is a
part of that loop.

### The files that matter

| File | Lines | What it is |
|---|---|---|
| `pipeline/runner.py` | ~120 | The workflow: chunk → extract → plan → write → critique → repair |
| `pipeline/llm.py` | ~230 | The only file that talks to Sarvam |
| `pipeline/agents.py` | ~200 | Four functions, four prompts |
| `pipeline/schemas.py` | ~290 | The contract for every output type |
| `pipeline/store.py` | ~200 | SQLite, plus the optional Supabase copy |
| `pipeline/exports.py` | ~250 | Markdown, DOCX, PPTX, CSV, JSON |
| `app.py` | ~300 | The Streamlit app — UI only |
| `api.py` | ~120 | The FastAPI bridge for the landing page |
| `web/` | — | The HTML, CSS and JavaScript landing page |

## 4. Running it

```bash
git clone https://github.com/chandrasekharreddy-basireddy/content-forge.git
cd content-forge

python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # then paste your Sarvam key into SARVAM_API_KEY
```

Check the model id before anything else — ids change, and an unknown one returns
a 404:

```bash
curl -H "api-subscription-key: $SARVAM_API_KEY" https://api.sarvam.ai/v2/models
```

Then, three ways to use it:

```bash
streamlit run app.py                                  # the full app
python scripts/cli.py document.pdf --trace            # terminal, with the trace
uvicorn api:app --reload --port 8000                  # landing page + API bridge
```

No key yet? Everything runs against a fake model:

```bash
python scripts/cli.py evals/testset/01_water_budget.txt --fake --trace
python evals/run_eval.py --fake
python -m pytest
```

### Tests

```bash
python -m pytest        # 84 tests, no network, no API key
python -m ruff check .  # lint
```

The suite covers the prompt loader, chunking, the output contracts, the critic
loop, storage, exports, the Sarvam client (with `requests` stubbed) and the API
guards. The runner tests are the ones to read: they prove the loop fires, stops,
and survives a broken output.

## 5. Wiring Sarvam correctly

Four settings in this project exist because the defaults are wrong for this use
case. They are worth knowing before an examiner asks.

**Base URL.** Chat uses `https://api.sarvam.ai/v2/chat/completions` — the
OpenAI-compatible endpoint with the full model list. `GET /v2/models` returns the
ids your key can use.

**Auth, both ways.** Sarvam documents `api-subscription-key`; the V2 chat endpoint
also accepts `Authorization: Bearer`. `pipeline/llm.py` sends both. A `403` where
you expected a `401` almost always means the subscription header was missing.

**`max_tokens` is always explicit.** The API default is 2048, which truncates a
ten-question quiz mid-object and makes the repair pass fire every single time.
`config.MAX_TOKENS` is 4096 and `chat()` never omits it.

**`response_format` uses `json_schema`, not `json_object`.** Structured Outputs
guarantee the shape, not merely valid JSON, which removes most repair calls.

**Translation is a separate endpoint.** `POST /translate` with `mayura:v1`
(11 languages, 1,000 characters per request) or `sarvam-translate:v1` (all 22
scheduled languages, 2,000 characters, formal only). Prompting the chat model to
translate is both more expensive and worse. Long text is split at sentence
boundaries and joined back.

## 6. Cost

Cost is computed, never guessed:

```
cost = prompt_tokens / 1e6 × RATE_IN_PER_M  +  completion_tokens / 1e6 × RATE_OUT_PER_M
```

Both rates live in `.env` and default to `sarvam-105b`'s published list price at
the time of writing (₹10 per million input tokens, ₹25 per million output
tokens). **Check the pricing page and put your own numbers in** — a rate from a
blog post is not a source.

Worked example with those rates: a 3,000-word document is about 4 chunks. That
is roughly 4 extraction calls, 1 plan call, and 5 outputs each with a draft and
a critique — around 15 calls, 25,000 input and 8,000 output tokens. That is
₹0.25 + ₹0.20 = **₹0.45 per document**. The real figure is printed in the app,
in the CLI, and in the `cost_inr` column of every run.

## 7. Evaluation

`evals/run_eval.py` scores the summary output two ways:

- **ROUGE-L** — word overlap against a human-written reference, implemented in
  `evals/rouge.py` (longest common subsequence, precision/recall/F1, β = 1.2).
- **An LLM judge** — faithfulness, coverage and concision out of 5, from
  `prompts/judge.yaml`.

Three sample documents ship in `evals/testset/` with references, so the harness
can be demonstrated immediately. **They are synthetic placeholders written to
test the harness, not real sources.** Replace them with 20 documents you did not
write and are licence-safe to send to a third-party API — your own notes, open
licence material, government publications — plus 20 human-written reference
summaries. That is the work, and no tool can do it for you.

The numbers currently in `evals/results.csv` come from `--fake`. They prove the
harness runs. They are not a measurement of the model, and they must not appear
in the report as one.

### What I would say about the evaluation, honestly

With one person rating, a blind human comparison is not credible. So: shuffle
the outputs before scoring them, say plainly in the report that the human rating
is single-rater, and lean on the LLM judge for the numbers that matter. ROUGE-L
rewards copying words and is a weak proxy for a good summary — report it, and
say so.

## 8. Technology stack

| Layer | Choice | Why | Swap for |
|---|---|---|---|
| LLM | Sarvam V2 chat completions | Indian-language strength, OpenAI-compatible | any OpenAI-compatible provider |
| Translation | Sarvam `/translate` (mayura:v1) | purpose-built, cheaper than prompting | sarvam-translate:v1 for the other 11 languages |
| Pipeline | plain Python | readable and defensible in a viva | LangGraph, if you want the graph back |
| Validation | JSON Schema + a hand-written validator | catches bad shape in code | pydantic |
| App | Streamlit | fastest path to a working UI | FastAPI + a React front end |
| Landing page | HTML, CSS, vanilla JS | the course asks for it; no build step | Next.js |
| Web bridge | FastAPI | CORS control, rate limiting | Flask |
| Storage | SQLite, optional Supabase | works offline, syncs when configured | Postgres only |
| Dashboard | Power BI Desktop | course requirement; `.pbix` needs Windows | Metabase |
| Tests | pytest | 84 tests, all offline | unittest |

## 9. Module breakdown

1. **Ingestion** (`pipeline/ingest.py`) — PDF/DOCX/TXT/MD to clean text; overlap chunking; refuses scanned PDFs with a clear message.
2. **Model layer** (`pipeline/llm.py`) — one client, retries on 429/5xx, explicit `max_tokens`, structured outputs, chunked translation.
3. **Prompt layer** (`prompts/*.yaml`, `pipeline/prompts.py`) — five prompts as files, slot rendering that fails loudly.
4. **Agents** (`pipeline/agents.py`) — extract, plan, write, critique.
5. **Workflow** (`pipeline/runner.py`) — the loop, the trace, per-output failure isolation.
6. **Contracts** (`pipeline/schemas.py`) — JSON Schema per output plus a validator.
7. **Persistence** (`pipeline/store.py`, `sql/schema.sql`) — SQLite, optional Supabase, CSV export.
8. **Exports** (`pipeline/exports.py`) — MD, DOCX, PPTX, CSV, JSON.
9. **Streamlit app** (`app.py`) — upload, live progress, scores, downloads, history.
10. **Web layer** (`web/`, `api.py`) — landing page, FastAPI bridge, CORS, rate limit.
11. **Analytics** (`powerbi/measures.dax`) — DAX measures over the run log.
12. **Evaluation** (`evals/`) — ROUGE-L, LLM judge, results CSV.
13. **Tests** (`tests/`) — 84 offline tests.

## 10. Privacy, safety and limits

- **Your key never leaves the machine.** It is read from `.env`, which is
  gitignored. If a key ever reaches a commit, rotate it — deleting the commit is
  not enough.
- **Documents go to a third-party API.** Do not upload a copyrighted textbook or
  anything confidential. The project refuses uploads over 10 MB and unsupported
  file types, but it cannot judge whether you had the right to send a file.
- **Prompt injection is handled, not solved.** Every writer and critic prompt
  says the source is data and its instructions must be ignored. That is a
  mitigation. A document that argues with the model well enough can still bias an
  output, which is why the critic scores against the source.
- **Hallucination is bounded, not eliminated.** Facts are extracted first and the
  writer is told to use only them; the critic is told to score invented specifics
  at 3 or below. Outputs still carry a status — `ok`, `flagged`, `unverified` —
  and a `flagged` output should be read before it is used.
- **No answer key guarantee.** A quiz's `answer_index` is validated as an integer
  in range. It is not validated against the source by a human, so spot-check a
  quiz before handing it to students.

## 11. Known gaps

Written down rather than hidden:

- The Power BI file (`.pbix`) is not in the repository. Power BI Desktop is
  Windows-only, so the file is built locally from the History tab's CSV and the
  measures in `powerbi/measures.dax` are ready to paste. Everything the dashboard
  needs is in that CSV.
- Translation covers the summary only. Translating a whole quiz would mean
  translating values while keeping keys, which is a real piece of work and was
  cut deliberately.
- The planner's output list is advisory. If it chooses badly, the app's
  multi-select overrides it — which is what the multi-select is for.

## 12. Repository layout

```
content-forge/
├── app.py                 Streamlit app
├── api.py                 FastAPI bridge
├── pipeline/              the pipeline (read runner.py first)
├── prompts/               five YAML prompts
├── web/                   landing page: index.html, styles.css, app.js
├── evals/                 run_eval.py, rouge.py, testset/, references/
├── tests/                 84 tests, plus fakes.py
├── scripts/cli.py         terminal entry point
├── sql/schema.sql         Supabase table and view
├── powerbi/measures.dax   dashboard measures
├── docs/proposal.md       the five-part project proposal
├── requirements.txt
└── .env.example
```

## 13. Credits and licence

Course project for CDS208, Sai University. Sarvam AI for the models and the
translation API. Sample documents in `evals/testset/` are synthetic text written
for this project; they are not real publications and should not be cited.

Code is provided for coursework. No licence is granted for commercial use.
