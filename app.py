"""The Streamlit app. UI only - no model logic lives here.

Run it with:  streamlit run app.py

Everything it needs is imported from pipeline/. If you are reading this file
to understand the project, you are in the wrong file: start at
pipeline/runner.py, then come back here to see how the results are shown.
"""

import json

import streamlit as st

from pipeline import config, exports, ingest, runner, schemas, store

st.set_page_config(page_title="Content Forge", page_icon="🔨", layout="wide")

OUTPUT_CHOICES = [name for name in schemas.OUTPUT_SPECS if name != "translation"]
LANGUAGES = {
    "Hindi": "hi-IN",
    "Bengali": "bn-IN",
    "Tamil": "ta-IN",
    "Telugu": "te-IN",
    "Marathi": "mr-IN",
    "Gujarati": "gu-IN",
    "Kannada": "kn-IN",
    "Malayalam": "ml-IN",
    "Punjabi": "pa-IN",
    "Odia": "od-IN",
}


def main() -> None:
    st.title("Content Forge")
    st.caption("One document in. Summaries, quizzes, flashcards, reports and slides out.")

    if not config.has_api_key():
        st.warning(
            "No Sarvam key found. Copy .env.example to .env and set "
            "SARVAM_API_KEY, then restart the app.",
            icon="🔑",
        )

    tab_build, tab_history = st.tabs(["Build", "History"])

    with tab_build:
        build_tab()

    with tab_history:
        history_tab()


def build_tab() -> None:
    """Upload, configure, run, download."""
    left, right = st.columns([3, 2])

    with left:
        uploaded = st.file_uploader(
            "Source document",
            type=["pdf", "docx", "txt", "md"],
            help=f"Up to {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB. "
            "Scanned PDFs need OCR first.",
        )

    with right:
        st.markdown("**What to produce**")
        chosen = st.multiselect(
            "Outputs",
            options=OUTPUT_CHOICES,
            default=["summary", "quiz", "flashcards"],
            format_func=lambda name: schemas.spec(name)["label"],
            label_visibility="collapsed",
        )
        translate = st.checkbox("Also translate the summary", value=False)
        language = st.selectbox(
            "Language",
            options=list(LANGUAGES),
            index=0,
            disabled=not translate,
        )

    if uploaded is None:
        st.info("Upload a PDF, DOCX, TXT or MD file to begin.", icon="📄")
        return

    # A new file means the old results are about a different document. Clear
    # them, or the page shows document A's quiz under document B's name.
    if st.session_state.get("last_doc") not in (None, uploaded.name):
        st.session_state.pop("last_run", None)
        st.session_state.pop("last_doc", None)

    data = uploaded.getvalue()
    try:
        text = ingest.read_document(uploaded.name, data)
    except ingest.IngestError as exc:
        st.error(str(exc))
        return

    words = ingest.word_count(text)
    chunks = len(ingest.chunk_text(text))
    first, second, third = st.columns(3)
    first.metric("Words", f"{words:,}")
    second.metric("Chunks", chunks)
    third.metric("Reading time", f"{max(1, words // 200)} min")

    with st.expander("Preview the extracted text"):
        st.text(text[:2000] + ("..." if len(text) > 2000 else ""))

    if st.button("Transform", type="primary", disabled=not chosen):
        result = run_pipeline(uploaded.name, text, chosen, translate, language)
        if result:
            st.session_state["last_run"] = result
            st.session_state["last_doc"] = uploaded.name

    if st.session_state.get("last_run"):
        show_result(st.session_state["last_run"], st.session_state.get("last_doc", ""))


def run_pipeline(doc_name, text, chosen, translate, language) -> dict | None:
    """Run the pipeline with live progress, then save the run."""
    progress = st.status("Starting...", expanded=True)
    lines: list[str] = []

    def on_event(event: dict) -> None:
        lines.append(f"{event['step']}: {event['message']}")
        progress.update(label=event["message"], state="running")
        progress.write(lines[-1])

    try:
        result = runner.run(
            doc_name=doc_name,
            text=text,
            outputs=chosen,
            translate_to=LANGUAGES[language] if translate else None,
            on_event=on_event,
        )
    except Exception as exc:  # noqa: BLE001 - the UI must never show a stack trace
        progress.update(label="Failed", state="error")
        st.error(f"The run failed: {exc}")
        return None

    saved = store.save_run(result)
    if not saved:
        st.warning("The run finished but could not be saved to the local database.")
    progress.update(
        label=f"Done - {result['status']} - ₹{result['usage']['cost_inr']:.4f}",
        state="complete" if result["status"] == "ok" else "error",
        expanded=False,
    )
    return result


def show_result(result: dict, doc_name: str) -> None:
    """Metrics, then one expander per output with download buttons."""
    st.divider()

    scores = [
        item["score"] for item in result["outputs"].values() if isinstance(item["score"], int)
    ]
    a, b, c, d = st.columns(4)
    a.metric("Status", result["status"])
    b.metric("Average score", f"{sum(scores) / len(scores):.1f} / 5" if scores else "-")
    c.metric("Tokens", f"{result['usage']['prompt_tokens'] + result['usage']['completion_tokens']:,}")
    d.metric("Cost", f"₹{result['usage']['cost_inr']:.4f}")

    st.caption(
        f"Planner: {result['plan']['reason']} "
        f"Depth: {result['plan']['depth']}. "
        f"Took {result['duration_ms'] / 1000:.1f}s across {result['usage']['calls']} calls."
    )

    for name, item in result["outputs"].items():
        label = schemas.spec(name)["label"]
        badge = {
            "ok": "✅",
            "flagged": "⚠️",
            "unverified": "❔",
            "failed": "❌",
        }.get(item["status"], "")
        heading = f"{badge} {label}"
        if item["score"] is not None:
            heading += f" - {item['score']}/5"

        with st.expander(heading, expanded=(name == "summary")):
            if item["object"] is None:
                st.error(item["error"] or "this output was not produced")
                continue
            if item["error"]:
                st.warning(item["error"])
            if item["defects"]:
                st.caption("Defects the critic still sees: " + "; ".join(item["defects"]))

            preview(name, item["object"])
            downloads(name, item["object"], doc_name)

    if result.get("translation"):
        translation = result["translation"]
        with st.expander(f"🌐 Translation - {translation['language']}"):
            if translation["status"] == "ok":
                st.write(translation["text"])
                st.download_button(
                    "Download .txt",
                    translation["text"].encode("utf-8"),
                    file_name=f"translation_{translation['language']}.txt",
                )
            else:
                st.error(translation.get("error") or "translation failed")

    with st.expander("🔍 Trace - what each agent did"):
        st.dataframe(result["trace"], use_container_width=True)
        st.download_button(
            "Download trace as JSON",
            json.dumps(result["trace"], indent=2),
            file_name=f"trace_{result['id']}.json",
        )


def preview(name: str, obj: dict) -> None:
    """A human-readable view of one output. No exports involved."""
    if name == "summary":
        st.write(obj.get("summary", ""))
        for bullet in obj.get("bullets", []):
            st.markdown(f"- {bullet}")
        st.caption("Key terms: " + ", ".join(obj.get("key_terms", [])))

    elif name == "quiz":
        for number, question in enumerate(obj.get("questions", []), start=1):
            st.markdown(f"**Q{number}. {question.get('question', '')}**")
            for index, option in enumerate(question.get("options", [])):
                if index == question.get("answer_index"):
                    st.markdown(f"- **{option}** ✅")
                else:
                    st.markdown(f"- {option}")
            st.caption(question.get("explanation", ""))
            st.write("")

    elif name == "flashcards":
        columns = st.columns(2)
        for index, card in enumerate(obj.get("cards", [])):
            with columns[index % 2]:
                st.markdown(f"**{card.get('front', '')}**")
                st.caption(card.get("back", ""))

    elif name == "report":
        st.subheader(obj.get("title", ""))
        for section in obj.get("sections", []):
            st.markdown(f"#### {section.get('heading', '')}")
            st.write(section.get("body", ""))

    elif name == "slides":
        for number, slide in enumerate(obj.get("slides", []), start=1):
            st.markdown(f"**{number}. {slide.get('title', '')}**")
            for bullet in slide.get("bullets", []):
                st.markdown(f"- {bullet}")
            if slide.get("notes"):
                st.caption(f"Notes: {slide['notes']}")


def downloads(name: str, obj: dict, doc_name: str) -> None:
    """One download button per format, side by side."""
    formats = exports.formats_for(name)
    columns = st.columns(len(formats))
    for column, fmt in zip(columns, formats, strict=True):
        content, filename, mime = exports.render(name, obj, fmt, doc_name)
        column.download_button(
            fmt.upper(),
            content,
            file_name=filename,
            mime=mime,
            key=f"{name}-{fmt}",
            use_container_width=True,
        )


def history_tab() -> None:
    """Past runs, and the CSV that feeds the Power BI dashboard."""
    runs = store.list_runs(limit=100)

    if not runs:
        st.info("No runs yet. Build one on the Build tab.")
        return

    summary = store.stats()
    a, b, c, d = st.columns(4)
    a.metric("Runs", summary["runs"])
    b.metric("Outputs produced", summary["outputs"])
    c.metric("Average score", f"{summary['avg_score']} / 5")
    d.metric("Total cost", f"₹{summary['cost_inr']:.4f}")

    st.dataframe(runs, use_container_width=True)

    st.download_button(
        "Download runs as CSV",
        store.runs_as_csv(),
        file_name="content_forge_runs.csv",
        mime="text/csv",
        help="Load this into Power BI: Get Data > Text/CSV.",
    )

    st.caption(
        "Every row here is one pipeline run. The dashboard in powerbi/ is built "
        "on exactly this file."
    )


if __name__ == "__main__":
    main()
