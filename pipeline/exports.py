"""Turning a generated object into a file a person can actually use.

Every function returns bytes, so the Streamlit download button, the FastAPI
response and the CLI all use the same code path. Nothing here calls a model.
"""

import csv
import io
import json
import re
from pathlib import Path

from . import schemas


def markdown(output: str, obj: dict, doc_name: str = "") -> str:
    """The universal export: readable in GitHub, Notion, VS Code and a terminal."""
    lines: list[str] = []
    title = schemas.spec(output)["label"]
    lines.append(f"# {title}")
    if doc_name:
        lines.append(f"*From: {doc_name}*")
    lines.append("")

    if output == "summary":
        lines.append(obj.get("summary", ""))
        lines.append("")
        if obj.get("bullets"):
            lines.append("## Takeaways")
            lines += [f"- {b}" for b in obj["bullets"]]
            lines.append("")
        if obj.get("key_terms"):
            lines.append("## Key terms")
            lines.append(", ".join(obj["key_terms"]))

    elif output == "quiz":
        for number, q in enumerate(obj.get("questions", []), start=1):
            lines.append(f"**Q{number}. {q.get('question', '')}**")
            for index, option in enumerate(q.get("options", [])):
                marker = " (correct)" if index == q.get("answer_index") else ""
                lines.append(f"- {option}{marker}")
            lines.append("")
            lines.append(f"*{q.get('explanation', '')}*")
            lines.append("")

    elif output == "flashcards":
        lines.append("| Front | Back |")
        lines.append("| --- | --- |")
        for card in obj.get("cards", []):
            front = str(card.get("front", "")).replace("|", "\\|")
            back = str(card.get("back", "")).replace("|", "\\|")
            lines.append(f"| {front} | {back} |")

    elif output == "report":
        lines.append(f"## {obj.get('title', '')}")
        lines.append("")
        for section in obj.get("sections", []):
            lines.append(f"### {section.get('heading', '')}")
            lines.append("")
            lines.append(section.get("body", ""))
            lines.append("")

    elif output == "slides":
        for number, slide in enumerate(obj.get("slides", []), start=1):
            lines.append(f"### {number}. {slide.get('title', '')}")
            lines += [f"- {b}" for b in slide.get("bullets", [])]
            if slide.get("notes"):
                lines.append("")
                lines.append(f"> {slide['notes']}")
            lines.append("")

    elif output == "translation":
        lines.append(f"*Language: {obj.get('language', '')}*")
        lines.append("")
        lines.append(obj.get("text", ""))

    return "\n".join(lines).strip() + "\n"


def docx_bytes(output: str, obj: dict, doc_name: str = "") -> bytes:
    """A Word document, with real headings so the navigation pane works."""
    import docx
    from docx.shared import Pt

    document = docx.Document()
    document.add_heading(schemas.spec(output)["label"], level=0)
    if doc_name:
        subtitle = document.add_paragraph(f"From: {doc_name}")
        subtitle.runs[0].font.size = Pt(9)

    if output == "summary":
        document.add_paragraph(obj.get("summary", ""))
        document.add_heading("Takeaways", level=1)
        for bullet in obj.get("bullets", []):
            document.add_paragraph(bullet, style="List Bullet")
        document.add_heading("Key terms", level=1)
        document.add_paragraph(", ".join(obj.get("key_terms", [])))

    elif output == "quiz":
        for number, q in enumerate(obj.get("questions", []), start=1):
            document.add_heading(f"Q{number}. {q.get('question', '')}", level=2)
            for index, option in enumerate(q.get("options", [])):
                paragraph = document.add_paragraph(str(option), style="List Number")
                # An empty option produces a paragraph with no runs, so guard
                # before reaching for runs[0].
                if index == q.get("answer_index") and paragraph.runs:
                    paragraph.runs[0].bold = True
            note = document.add_paragraph(str(q.get("explanation", "")))
            if note.runs:
                note.runs[0].italic = True

    elif output == "flashcards":
        table = document.add_table(rows=1, cols=2)
        table.style = "Table Grid"
        header = table.rows[0].cells
        header[0].text = "Front"
        header[1].text = "Back"
        for card in obj.get("cards", []):
            cells = table.add_row().cells
            cells[0].text = str(card.get("front", ""))
            cells[1].text = str(card.get("back", ""))

    elif output == "report":
        document.add_heading(obj.get("title", ""), level=1)
        for section in obj.get("sections", []):
            document.add_heading(section.get("heading", ""), level=2)
            document.add_paragraph(section.get("body", ""))

    elif output == "slides":
        for number, slide in enumerate(obj.get("slides", []), start=1):
            document.add_heading(f"{number}. {slide.get('title', '')}", level=2)
            for bullet in slide.get("bullets", []):
                document.add_paragraph(bullet, style="List Bullet")
            if slide.get("notes"):
                note = document.add_paragraph(f"Speaker notes: {slide['notes']}")
                if note.runs:
                    note.runs[0].italic = True

    elif output == "translation":
        document.add_paragraph(obj.get("text", ""))

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def pptx_bytes(output: str, obj: dict, doc_name: str = "") -> bytes:
    """A .pptx. For slides this is the real export; for a report it is a deck."""
    from pptx import Presentation
    from pptx.util import Pt

    presentation = Presentation()

    if output == "slides":
        slides = obj.get("slides", [])
    elif output == "report":
        slides = [{"title": obj.get("title", "Report"), "bullets": []}]
        slides += [
            {
                "title": s.get("heading", ""),
                "bullets": _split_sentences(s.get("body", ""), limit=5),
            }
            for s in obj.get("sections", [])
        ]
    else:
        slides = [{"title": schemas.spec(output)["label"], "bullets": []}]

    for index, slide in enumerate(slides):
        layout = presentation.slide_layouts[0 if index == 0 else 1]
        built = presentation.slides.add_slide(layout)
        built.shapes.title.text = str(slide.get("title", ""))

        body = None
        for placeholder in built.placeholders:
            if placeholder.placeholder_format.idx == 1:
                body = placeholder

        bullets = slide.get("bullets") or []
        if body is not None and bullets:
            frame = body.text_frame
            frame.text = str(bullets[0])
            for bullet in bullets[1:]:
                frame.add_paragraph().text = str(bullet)
            for paragraph in frame.paragraphs:
                paragraph.font.size = Pt(18)

        if slide.get("notes"):
            built.notes_slide.notes_text_frame.text = str(slide["notes"])

    if doc_name:
        presentation.core_properties.subject = doc_name

    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def csv_text(output: str, obj: dict) -> str:
    """A CSV for the outputs that are naturally tabular."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    if output == "quiz":
        writer.writerow(["question", "option_a", "option_b", "option_c", "option_d",
                         "answer", "explanation"])
        for q in obj.get("questions", []):
            options = list(q.get("options", [])) + ["", "", "", ""]
            index = q.get("answer_index")
            if not isinstance(index, int) or isinstance(index, bool):
                index = -1  # a non-integer index must not reach the comparison
            answer = options[index] if 0 <= index < len(options) else ""
            writer.writerow(
                [q.get("question", ""), *options[:4], answer, q.get("explanation", "")]
            )

    elif output == "flashcards":
        writer.writerow(["front", "back"])
        for card in obj.get("cards", []):
            writer.writerow([card.get("front", ""), card.get("back", "")])

    elif output == "slides":
        writer.writerow(["slide", "title", "bullets", "notes"])
        for number, slide in enumerate(obj.get("slides", []), start=1):
            writer.writerow(
                [
                    number,
                    slide.get("title", ""),
                    " | ".join(slide.get("bullets", [])),
                    slide.get("notes", ""),
                ]
            )

    else:
        writer.writerow(["key", "value"])
        for key, value in obj.items():
            writer.writerow([key, json.dumps(value, ensure_ascii=False)])

    return buffer.getvalue()


def formats_for(output: str) -> list[str]:
    """Which download buttons to show for this output type."""
    if output in ("quiz", "flashcards", "slides"):
        return ["md", "docx", "pptx", "csv", "json"]
    if output == "report":
        return ["md", "docx", "pptx", "json"]
    return ["md", "docx", "json"]


def render(output: str, obj: dict, fmt: str, doc_name: str = "") -> tuple[bytes, str, str]:
    """Return (content, filename, mime type) for one output in one format."""
    # The filename becomes a path in the CLI, so strip anything that could
    # climb out of the output folder or upset a filesystem.
    stem = Path(doc_name).stem if doc_name else ""
    base = f"{stem}_{output}" if stem else output
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:80] or output

    if fmt == "md":
        return markdown(output, obj, doc_name).encode("utf-8"), f"{base}.md", "text/markdown"
    if fmt == "docx":
        return (
            docx_bytes(output, obj, doc_name),
            f"{base}.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    if fmt == "pptx":
        return (
            pptx_bytes(output, obj, doc_name),
            f"{base}.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    if fmt == "csv":
        return csv_text(output, obj).encode("utf-8"), f"{base}.csv", "text/csv"
    if fmt == "json":
        return (
            json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"),
            f"{base}.json",
            "application/json",
        )
    raise ValueError(f"unknown format '{fmt}'. Use one of: md, docx, pptx, csv, json")


def _split_sentences(text: str, limit: int = 5) -> list[str]:
    """Split prose into at most "limit" sentence-ish bullets for a slide."""
    out: list[str] = []
    current = ""
    for char in text:
        current += char
        if char in ".!?" and len(current.strip()) > 40:
            out.append(current.strip())
            current = ""
    if current.strip():
        out.append(current.strip())
    return out[:limit]
