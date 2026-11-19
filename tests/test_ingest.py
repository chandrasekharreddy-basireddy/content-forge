"""Tests for reading files and splitting them into chunks."""

import io

import pytest

from pipeline import ingest


def test_clean_text_joins_hyphenated_line_breaks():
    """A word broken across a PDF line break must come back whole."""
    assert "information" in ingest.clean_text("The infor-\nmation was clear.")


def test_clean_text_collapses_blank_lines_but_keeps_paragraphs():
    cleaned = ingest.clean_text("One.\n\n\n\nTwo.\n\nThree.")
    assert cleaned.count("\n\n") == 2
    assert "One." in cleaned and "Three." in cleaned


def test_chunks_cover_the_whole_document(sample_text):
    """Every chunk boundary is safe: no text is silently dropped."""
    chunks = ingest.chunk_text(sample_text, size=400, overlap=50)
    assert len(chunks) > 1
    # The first and last chunks must still contain the document's edges.
    assert chunks[0].startswith("The pilot programme")
    assert "consolidated into one." in chunks[-1]


def test_chunks_respect_the_size_limit(sample_text):
    """No chunk may exceed the requested size by more than one word."""
    chunks = ingest.chunk_text(sample_text, size=300, overlap=30)
    assert all(len(chunk) <= 320 for chunk in chunks)


def test_chunks_overlap(sample_text):
    """Consecutive chunks share text, so a fact on a boundary survives."""
    chunks = ingest.chunk_text(sample_text, size=300, overlap=60)
    first_tail = chunks[0][-40:]
    assert first_tail.strip()[:20] in chunks[1]


def test_short_text_is_one_chunk():
    assert ingest.chunk_text("Just one sentence.") == ["Just one sentence."]


def test_empty_text_gives_no_chunks():
    assert ingest.chunk_text("   \n  ") == []


def test_overlap_must_be_smaller_than_size():
    """A misconfiguration should fail immediately, not loop forever."""
    with pytest.raises(ValueError):
        ingest.chunk_text("text", size=100, overlap=100)


def test_txt_upload_is_read():
    text = ingest.read_document("notes.txt", b"Fact one. " * 40)
    assert "Fact one." in text


def test_unsupported_extension_is_refused():
    with pytest.raises(ingest.IngestError) as error:
        ingest.read_document("slides.pptx", b"whatever")
    assert ".pptx" in str(error.value)


def test_a_nearly_empty_document_is_refused():
    """A scanned PDF yields no text; say so instead of producing nonsense."""
    with pytest.raises(ingest.IngestError) as error:
        ingest.read_document("scan.txt", b"   ")
    assert "OCR" in str(error.value)


def test_oversized_upload_is_refused(monkeypatch):
    monkeypatch.setattr(ingest.config, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(ingest.IngestError):
        ingest.read_document("big.txt", b"x" * 100)


def test_docx_round_trip(tmp_path):
    """A DOCX written by python-docx reads back through our own reader."""
    import docx

    document = docx.Document()
    document.add_paragraph("The prototype shipped in March. " * 20)
    buffer = io.BytesIO()
    document.save(buffer)

    text = ingest.read_document("report.docx", buffer.getvalue())
    assert "prototype shipped in March" in text
