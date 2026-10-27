import hashlib
from io import BytesIO

import pymupdf
import pytest

from scripts.fetch_corpus import fetch_document


def pdf_bytes():
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Synthetic test page")
        return document.tobytes()


def test_fetch_verifies_hash_and_pages_before_accepting(monkeypatch, tmp_path):
    content = pdf_bytes()
    monkeypatch.setattr("scripts.fetch_corpus.urlopen", lambda *a, **kw: BytesIO(content))
    record = {
        "id": "sample", "url": "https://nvlpubs.nist.gov/sample.pdf",
        "sha256": hashlib.sha256(content).hexdigest(), "pages": 1,
    }
    result = fetch_document(record, tmp_path)
    assert result["pages"] == 1
    assert (tmp_path / "sample.pdf").read_bytes() == content


def test_bad_hash_does_not_replace_existing_file(monkeypatch, tmp_path):
    content = pdf_bytes()
    monkeypatch.setattr("scripts.fetch_corpus.urlopen", lambda *a, **kw: BytesIO(content))
    record = {
        "id": "sample", "url": "https://nvlpubs.nist.gov/sample.pdf",
        "sha256": "0" * 64, "pages": 1,
    }
    with pytest.raises(ValueError, match="hash"):
        fetch_document(record, tmp_path)
    assert not (tmp_path / "sample.pdf").exists()


def test_invalid_source_or_filename_rejected(tmp_path):
    for source in (
        {"id": "../escape", "url": "https://nvlpubs.nist.gov/sample.pdf"},
        {"id": "sample", "url": "http://nvlpubs.nist.gov/sample.pdf"},
        {"id": "sample", "url": "https://untrusted.invalid/sample.pdf"},
    ):
        with pytest.raises(ValueError):
            fetch_document(source, tmp_path)


def test_existing_corrupt_file_is_not_overwritten(tmp_path):
    target = tmp_path / "sample.pdf"
    target.write_bytes(b"existing-file")
    record = {
        "id": "sample", "url": "https://nvlpubs.nist.gov/sample.pdf",
        "sha256": "0" * 64, "pages": 1,
    }
    with pytest.raises(ValueError, match="hash"):
        fetch_document(record, tmp_path)
    assert target.read_bytes() == b"existing-file"
