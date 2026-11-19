# Your checklist

Tick these in order. Steps 1–5 take about twenty minutes; step 6 is the one
that matters.

---

## Before anything: two decisions

- [ ] **Which machine has Windows?** Power BI Desktop is Windows-only. If you
      are on a Mac, decide now which Windows machine or lab PC builds the
      dashboard. Not in week five.
- [ ] **Do you have a Sarvam key?** From dashboard.sarvam.ai → API keys. One key
      is enough; a second from another provider is only useful as a fallback.

## 1. Get the code

```bash
git clone https://github.com/chandrasekharreddy-basireddy/content-forge.git
cd content-forge
```

- [ ] Cloned.

## 2. Install

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

- [ ] Installed. (`requirements-dev.txt` adds pytest and ruff on top of the app.)

## 3. Configure

```bash
cp .env.example .env
```

Open `.env` and paste your key into `SARVAM_API_KEY=`. Nothing else needs
changing to start.

- [ ] Key pasted.
- [ ] `.env` is not committed — it is gitignored. If it ever reaches a commit,
      rotate the key at the dashboard; deleting the commit is not enough.

## 4. Check the key and the model id

```bash
# Bash / macOS / Linux
set -a; . ./.env; set +a
curl -H "api-subscription-key: $SARVAM_API_KEY" https://api.sarvam.ai/v2/models
```

```powershell
# Windows PowerShell - works everywhere, because it is our own client
python -c "from pipeline import llm; print(chr(10).join(llm.list_models()))"
```

On Windows, `curl` is an alias for `Invoke-WebRequest` and `set -a` is not a
thing, so use the Python one-liner.

- [ ] You got a model list back. If you got 403, the header is missing or the
      key is wrong. If you got a list, check that `sarvam-105b` is in it — if it
      is not, set `LLM_MODEL_STRONG` and `LLM_MODEL_FAST` to an id that is.

## 5. Prove it works without spending anything

```bash
python -m pytest                 # expect 118 passed
python scripts/cli.py evals/testset/01_water_budget.txt --fake --trace
```

- [ ] Tests green.
- [ ] The fake run printed a trace with a draft, a critique and a score.

## 6. The first real run — the step that matters

```bash
python scripts/cli.py path/to/your-document.pdf --trace
```

Use a document you did not write and are allowed to send to an API: your own
notes, an open-licence paper, a government PDF. Not a textbook.

- [ ] It ran and produced outputs.
- [ ] **Copy the trace table and the summary into the chat.** Four things to
      look at while you wait:
      - every output scoring 5/5 → the critic is a rubber stamp
      - the planner choosing slides for a two-page note
      - a number in the quiz that is not in the source
      - extract rows near 6,000 input tokens → the window is too big for your
        document

## 7. The app

```bash
streamlit run app.py
```

- [ ] Uploaded a file, watched the progress, downloaded a `.docx`.
- [ ] History tab shows the runs, and the CSV button downloads.
- [ ] Screenshot the finished run and the History tab for the report.

## 8. Tune the prompts (the marked part)

Change one prompt at a time in `prompts/`, re-run the same document, compare.
Expect to touch `critique.yaml` first.

- [ ] At least two prompt changes made, each with a before/after you can quote
      in `docs/report.md` §4 "What changed, and why".

## 9. The reference summaries — yours to write

```bash
ls evals/references/
```

These are drafts written for you, not human references. ROUGE-L against an
AI-written reference measures agreement between models, not summary quality.

- [ ] Rewritten in your own words, having read each full document.
- [ ] You can say in one sentence how they were produced. That sentence is the
      answer to the hardest question in the viva.

## 10. The evaluation

```bash
python evals/run_eval.py --limit 3     # a quick check
python evals/run_eval.py               # the full set
```

- [ ] Ran. Roughly 100 model calls, so split it across two days on a free tier.
- [ ] The table copied into `docs/report.md` §7, replacing the sample rows.

## 11. The dashboard (Windows)

Follow `powerbi/BUILD.md`. Export the CSV from the History tab first.

- [ ] Four visuals built: KPI cards, score trend, status column chart, cost
      scatter.
- [ ] Screenshot for the report.
- [ ] If the Power BI Service refuses your personal account, demo from Desktop
      and say so in the report.

## 12. Deploy

- [ ] **Streamlit Community Cloud:** sign in with GitHub, point it at the repo,
      `app.py` as the entry point, paste the key into Secrets.
- [ ] **GitHub Pages:** Settings → Pages → deploy from branch, `/web` folder.
      Note the URL, `https://<username>.github.io/content-forge`.
- [ ] **Render (or similar):** new web service, start command
      `uvicorn api:app --proxy-headers --forwarded-allow-ips="*"`, environment
      variables from `.env`.
- [ ] **Set `WEB_ORIGIN`** on the API host to the Pages origin, character for
      character: `https`, no trailing slash. CORS fails silently if it is wrong.
- [ ] Open the Pages URL, paste 300 characters, press Transform, get an answer.

## 13. Fill the report

```bash
grep -n "\[FILL" docs/report.md
```

- [ ] Every `[FILL]` replaced with a real number or a real decision.
- [ ] No fabricated figure anywhere. An honest gap beats an invented table.
- [ ] Screenshots inserted: app, history, landing page, dashboard.
- [ ] `docs/viva.md` numbers table updated to match.

## 14. Optional

- [ ] Branch protection on `main` requiring the CI check.
- [ ] A second rater for the evaluation, scoring shuffled outputs.

---

## What to send me, and when

| After step | Send |
|---|---|
| 6 | the trace table and the summary output |
| 8 | the prompt you changed and the two outputs it produced |
| 10 | the results table |
| 12 | the deployed URLs, and any error the deploy gave you |
