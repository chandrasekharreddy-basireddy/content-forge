# Project proposal — Content Forge

**CDS208 – Emerging Tools and Applications · Final Project**

| | |
|---|---|
| Student | Chandra Sekhar Basireddy |
| Student ID | 252205992 |
| Institution | School of Computing and Data Science, Sai University |
| Faculty | Kartavya Satish Sonar |
| Selected statement | **Option 8 — GenAI Platform for Automated Content Transformation** |
| Mode | Individual build |
| Date | 19 November 2026 |

---

## 1. Group members

This is a solo submission: Chandra Sekhar Basireddy, 252205992. The course
prescribes groups of three to four, so the scope below has been cut to what one
person can build and defend — five output types instead of nine, three app
screens, and an eleven-document evaluation set rather than twenty. The single-rater
limitation of the human evaluation is stated openly in the report rather than
worked around.

## 2. Selected project

**Option 8: GenAI Platform for Automated Content Transformation** — *"A platform
that uses generative AI workflows to transform source content into useful
formats such as summaries, quizzes, reports and other outputs."*

Technology focus as listed in the brief: Generative AI, prompt engineering,
agentic workflows, Streamlit.

## 3. Problem

The same source document usually has to become several different things. A
lecture note becomes a summary for revision, a quiz for self-testing, flashcards
for memorisation, a report for the record and a slide outline for a presentation.
Producing those by hand is slow and repetitive, and it is exactly the work that
gets skipped when time is short.

Asking a chat model to do it in one prompt produces a different set of problems:
the outputs disagree with each other, numbers get invented, the format changes
between runs, and there is no record of which document produced what or what it
cost. In an Indian classroom there is a further gap — most of these tools produce
good English and poor Hindi, Tamil or Telugu.

## 4. Proposed solution

Content Forge is a pipeline, not a prompt. One source document goes through five
stages, each of which can be inspected and tested on its own:

1. **Chunk** — the document is split into overlapping pieces so a fact on a
   boundary is never lost.
2. **Extract** — each chunk is reduced to its facts and its exact numbers. This
   is the map half of map-reduce, and it is what keeps the five outputs agreeing
   with each other.
3. **Plan** — a planner agent decides which outputs this particular document can
   honestly support, and how deep to go. A two-page note does not get ten slides.
4. **Write and critique** — a writer drafts one output; a critic scores it out of
   five against the source and names the defects. Below four, the draft goes back
   to the writer with those defects, twice at most, then ships flagged rather
   than silently.
5. **Translate** — the summary is translated through Sarvam's dedicated
   translation endpoint, which is cheaper and better at Indic output than asking
   a chat model to translate.

Every step writes a row to a trace — step, model, duration, tokens, and a note
saying what it decided. The trace is the evidence that the workflow is agentic
rather than decorative, and it is visible in the app behind a toggle.

### Key features

- Six output types: summary, quiz, flashcards, report, slide outline, translation.
- Quality gate: a critic score and a status (`ok`, `flagged`, `unverified`) on
  every output, stored with the run.
- Structured Outputs: each output has a JSON Schema, plus a hand-written
  validator that catches a three-option quiz in code.
- Exports: Markdown, Word, PowerPoint, CSV and JSON.
- Indic translation of the summary into Sarvam's supported languages.
- Full run history in SQLite, optionally mirrored to Supabase, with a CSV export
  that feeds a Power BI dashboard.
- A public landing page in HTML, CSS and JavaScript, backed by a FastAPI bridge
  with a single allowed origin and a per-IP rate limit.
- 118 offline tests that need no API key, including the critic loop itself.

## 5. Technology stack

| Concern | Technology | Why this one |
|---|---|---|
| Language model | Sarvam AI, chat completions V2 | Indian-language strength; OpenAI-compatible shape |
| Translation | Sarvam `/translate`, `mayura:v1` | purpose-built; 11 languages at 1,000 characters per request |
| Orchestration | Plain Python (`pipeline/runner.py`) | readable, and defensible line by line in a viva |
| Structured output | JSON Schema via `response_format` | guarantees shape, not merely valid JSON |
| Validation | hand-written validator, no pydantic | one less dependency, explicit error messages |
| App | Python + Streamlit | upload, live progress, downloads, history |
| Web | HTML, CSS, JavaScript + FastAPI | the course's web component, doing real work |
| Storage | SQLite; Supabase optional | works offline, syncs when configured |
| Analytics | Power BI Desktop | run volume, quality and cost across runs |
| Version control | Git and GitHub | branch protection, CI on the first commit |

## 6. Initial module breakdown

| # | Module | Responsibility | Milestone |
|---|---|---|---|
| 1 | Ingestion | PDF/DOCX/TXT/MD to clean text; overlap chunking | Week 1 |
| 2 | Model layer | Sarvam client: retries, explicit `max_tokens`, structured outputs, chunked translation | Week 1 |
| 3 | Prompt layer | Five YAML prompts, slot rendering that fails loudly | Week 2 |
| 4 | Agents | Extract, plan, write, critique | Week 2 |
| 5 | Workflow | The loop, the trace, per-output failure isolation | Week 3 |
| 6 | Contracts | JSON Schema per output plus a validator | Week 3 |
| 7 | Persistence | SQLite, optional Supabase, CSV export | Week 4 |
| 8 | Exports | Markdown, DOCX, PPTX, CSV, JSON | Week 4 |
| 9 | Streamlit app | Upload, progress, scores, downloads, history | Week 5 |
| 10 | Web layer | Landing page, FastAPI bridge, CORS, rate limit | Week 5 |
| 11 | Analytics | Power BI dashboard over the run log | Week 6 |
| 12 | Evaluation | ROUGE-L and an LLM judge over an eleven-document set | Week 6 |
| 13 | Tests | Offline suite covering all of the above | throughout |

### What is deliberately out of scope

Podcast scripts and mind maps (cut for a solo build); translation of outputs
other than the summary; a multi-user account system; and any fine-tuning. Each
one is a real project on its own, and shipping four outputs that work beats
shipping nine that half-work.
