# Building the Power BI dashboard

Forty minutes on a Windows machine. Power BI Desktop does not run on macOS or
Linux, so settle which machine you are using before the day you need it.

The repository deliberately does not contain a `.pbix`. It is a binary file that
cannot be reviewed in a diff, and it is built from data you generate by running
the app — so it is yours to build, once, with the numbers from your own runs.

---

## 1. Generate the data

You need rows in the `runs` table before the dashboard has anything to show.

**With an API key:** run three or four documents through the app or the CLI:

```bash
python scripts/cli.py evals/testset/04_solar_power_in_india.txt
python scripts/cli.py evals/testset/07_kolkata_metro.txt
python scripts/cli.py evals/testset/10_indian_railways.txt
```

**Without a key:** `--fake` still writes real rows to SQLite with the pipeline's
own timings and token counts, so you can build and rehearse the dashboard before
you have credits. Say in the report which rows are fake — the `doc_name` column
makes it obvious.

Then export: **Streamlit → History tab → Download runs as CSV**. Save it as
`content_forge_runs.csv` somewhere you will find it again.

## 2. Load it

1. Power BI Desktop → **Get Data** → **Text/CSV** → the file → **Load**.
2. Rename the table `runs` in the Fields pane (double-click the table name).
3. Select `created_at` → **Column tools** → **Data type** → *Date/Time*. Power
   BI usually gets this right; check it, because a text date breaks every trend
   visual silently.
4. **Modeling** → **New measure**, then paste each measure from
   `powerbi/measures.dax`, naming it exactly as the comment above it says.

## 3. The page

Four visuals, in this order. Resist adding a fifth.

| Position | Visual | Fields |
|---|---|---|
| Row 1 | Four **Card** visuals | `Total Runs`, `Clean Run Rate`, `Avg Critic Score`, `Total Cost INR` |
| Row 2 | **Line chart** | Axis `created_at` (day), Values `Avg Critic Score` |
| Row 3 | **Column chart** | Axis `status`, Values `Total Runs` |
| Row 4 | **Scatter** | X `words`, Y `cost_inr`, Details `id`, Legend `depth` |

Formatting that matters more than it sounds: set the cost card to two decimals
and the score card to one, put the currency in the title rather than in the
number, and sort the status column chart by count descending rather than
alphabetically — `failed / ok / partial` in alphabetical order tells a reader
nothing.

## 4. What to say about it in the report

The dashboard answers three questions about the platform rather than about the
documents:

- **Is quality stable?** The score trend. A falling line means the prompts have
  drifted, not that the documents got harder.
- **Where does it break?** The status column chart. A high `partial` rate is a
  single output type failing repeatedly, which the trace will name.
- **What does it cost?** Cost against document length. If the scatter is flat,
  cost is driven by output count rather than document size — which is true here,
  because extraction is grouped.

## 5. If the Service refuses your account

Publishing to the Power BI Service normally needs a work or school account; a
personal Gmail address often cannot. Do not spend an evening on it. Demo from
Desktop with the `.pbix` open and the CSV in the repository, and say plainly in
the report that the dashboard was demonstrated locally.
