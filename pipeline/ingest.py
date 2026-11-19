"""Turning an uploaded file into clean text, then into chunks.

Three public functions:

    read_document(name, data)  bytes in, text out
    clean_text(text)           normalise whitespace and de-hyphenate
    chunk_text(text)           split into overlapping chunks for the model
"""

import io
import re
from pathlib import Path

from . import config

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}


class IngestError(Exception):
    """Raised when a file cannot be read or has no usable text."""


def read_document(name: str, data: bytes) -> str:
    """Extract text from an uploaded PDF, DOCX, TXT or MD file."""
    suffix = Path(name).suffix.lower()

    if len(data) > config.MAX_UPLOAD_BYTES:
        limit = config.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise IngestError(f"{name} is larger than the {limit} MB limit.")

    if suffix == ".pdf":
        text = _read_pdf(data)
    elif suffix == ".docx":
        text = _read_docx(data)
    elif suffix in (".txt", ".md"):
        text = data.decode("utf-8", errors="replace")
    else:
        raise IngestError(
            f"{suffix or 'this file type'} is not supported. "
            f"Use one of: {', '.join(sorted(SUPPORTED))}."
        )

    text = clean_text(text)
    if len(text) < 200:
        raise IngestError(
            "Almost no text came out of that file. If it is a scanned PDF it "
            "needs OCR first."
        )
    return text


def _read_pdf(data: bytes) -> str:
    """PDF text, page by page. Scanned pages come back empty by design."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency problem
        raise IngestError("pypdf is not installed: pip install pypdf") from exc

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:  # a broken page should not kill the whole document
            page_text = ""
        if page_text.strip():
            pages.append(f"[page {number}]\n{page_text.strip()}")
    return "\n\n".join(pages)


def _read_docx(data: bytes) -> str:
    """DOCX text, including tables, which python-docx keeps separate."""
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - dependency problem
        raise IngestError("python-docx is not installed: pip install python-docx") from exc

    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)


def clean_text(text: str) -> str:
    """Fix the damage PDFs and Word files do to plain text."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00ad", "")  # soft hyphens

    # "informa-\ntion" -> "information". Only when a real word is split.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # A single newline inside a paragraph is a line break, not a paragraph.
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)

    # Collapse runs of spaces and of blank lines.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """Split text into chunks of about "size" characters that overlap a little.

    The overlap matters: a fact split across a boundary still appears whole in
    at least one chunk, so the model is less likely to lose it.
    """
    size = size or config.CHUNK_SIZE
    overlap = config.CHUNK_OVERLAP if overlap is None else overlap

    if size <= 0:
        raise ValueError("size must be positive")
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")

    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer to cut at a paragraph break, then a sentence end, then a
            # space, and only cut mid-word if none of those is nearby.
            window = text[start:end]
            for marker in ("\n\n", ". ", " "):
                cut = window.rfind(marker)
                if cut > size * 0.6:
                    end = start + cut + len(marker)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)

    return chunks


def word_count(text: str) -> int:
    """Cheap word count, used for the run summary and the UI."""
    return len((text or "").split())
