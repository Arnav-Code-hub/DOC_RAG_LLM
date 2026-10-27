from io import BytesIO
from uuid import UUID

import pymupdf
import pytest
from transformers import BertTokenizerFast

from app.config import Settings
from app.ingest import chunk_pages, extract_pages, read_pdf_bytes
from app.schemas import Page


def make_pdf(texts, **save_options):
    with pymupdf.open() as document:
        for text in texts:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        return document.tobytes(**save_options)


@pytest.fixture
def tokenizer(tmp_path):
    vocabulary = [
        "[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]",
        "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
        "iota", "kappa", "tail", "un", "##aff", "##able", "aff", "able", ".", ",",
    ]
    path = tmp_path / "vocab.txt"
    path.write_text("\n".join(vocabulary), encoding="utf-8")
    return BertTokenizerFast(vocab_file=str(path), model_max_length=512)


def source_page(text, page_number=1, document_hash="a" * 64):
    return Page(
        filename="sample.pdf", document_hash=document_hash,
        page_number=page_number, text=text,
    )


def small_settings(**overrides):
    return Settings(_env_file=None, chunk_tokens=10, chunk_overlap=2, **overrides)


def test_bounded_reader_stops_before_consuming_oversized_stream():
    stream = BytesIO(b"x" * 1000)
    with pytest.raises(ValueError, match="size"):
        read_pdf_bytes(stream, settings=small_settings(max_pdf_bytes=100))
    assert stream.tell() == 101


def test_bounded_reader_accepts_exact_limit():
    assert read_pdf_bytes(BytesIO(b"abc"), settings=small_settings(max_pdf_bytes=3)) == b"abc"


def test_blank_pages_keep_physical_numbers_and_warning():
    pages = extract_pages(make_pdf(["First page", "", "Third page"]), "sample.pdf")
    assert [page.page_number for page in pages if page.text] == [1, 3]
    assert pages[1].text == ""
    assert any("no extractable text" in warning.lower() for warning in pages[1].warnings)
    assert any("low text" in warning.lower() for warning in pages[0].warnings)


@pytest.mark.parametrize("content", [b"", b"not a PDF", b"%PDF-1.7\nbroken"])
def test_unreadable_input_rejected(content):
    with pytest.raises(ValueError, match="PDF"):
        extract_pages(content, "misleading.pdf")


@pytest.mark.parametrize("password", ["reader", ""])
def test_encrypted_pdfs_rejected_even_with_empty_user_password(password):
    content = make_pdf(
        ["Confidential"], encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner", user_pw=password,
    )
    with pytest.raises(ValueError, match="[Ee]ncrypted"):
        extract_pages(content, "encrypted.pdf")


def test_oversized_input_rejected_before_extraction():
    content = make_pdf(["Text"])
    with pytest.raises(ValueError, match="size"):
        extract_pages(content, "sample.pdf", settings=small_settings(max_pdf_bytes=len(content) - 1))


def test_more_than_200_pages_rejected():
    with pytest.raises(ValueError, match="page limit"):
        extract_pages(make_pdf([""] * 201), "sample.pdf")


def test_pdf_without_extractable_text_reports_ocr_limitation():
    with pytest.raises(ValueError, match="OCR"):
        extract_pages(make_pdf(["", ""]), "scanned.pdf")


def test_identity_uses_bytes_not_untrusted_filename():
    content = make_pdf(["Document text"])
    first = extract_pages(content, "../../unsafe.txt")[0]
    renamed = extract_pages(content, "renamed.pdf")[0]
    changed = extract_pages(make_pdf(["Different document text"]), "renamed.pdf")[0]
    assert first.filename == "unsafe.txt"
    assert first.document_hash == renamed.document_hash
    assert first.document_hash != changed.document_hash
    assert first.storage_name.endswith(".pdf")
    assert len(first.storage_name) == 68
    assert "/" not in first.storage_name and "\\" not in first.storage_name


def test_table_mentions_are_flagged_for_manual_layout_review():
    pages = extract_pages(make_pdf(["Table 1: Categories and subcategories\nPolicy A  Control B"]), "table.pdf")
    assert any("table" in warning.lower() for warning in pages[0].warnings)


def test_long_page_chunks_cover_all_text_with_token_overlap(tokenizer):
    text = ("alpha beta gamma delta epsilon zeta eta theta iota kappa " * 7) + "tail"
    page = source_page(text)
    chunks = chunk_pages([page], "document", "config", settings=small_settings(), tokenizer=tokenizer)
    assert len(chunks) > 1
    assert chunks[-1].text.endswith("tail")
    covered = set()
    for chunk in chunks:
        assert chunk.text == text[chunk.start_char:chunk.end_char]
        assert len(tokenizer.encode(chunk.text, add_special_tokens=False)) <= 10
        assert chunk.document_hash == page.document_hash
        assert chunk.page_number == 1
        assert chunk.filename == "sample.pdf"
        covered.update(range(chunk.start_char, chunk.end_char))
    assert all(index in covered for index, character in enumerate(text) if not character.isspace())
    for left, right in zip(chunks, chunks[1:]):
        assert tokenizer.encode(left.text, add_special_tokens=False)[-2:] == (
            tokenizer.encode(right.text, add_special_tokens=False)[:2]
        )
        assert right.start_char > left.start_char


def test_chunks_prefer_paragraph_boundary_without_losing_tail(tokenizer):
    text = "alpha beta gamma delta epsilon zeta\n\neta theta iota kappa tail"
    chunks = chunk_pages(
        [source_page(text)], "document", "config", settings=small_settings(), tokenizer=tokenizer
    )
    assert chunks[0].text == "alpha beta gamma delta epsilon zeta"
    assert chunks[-1].text.endswith("tail")


def test_chunks_preserve_original_unicode_and_wordpiece_boundaries(tokenizer):
    text = "Café unaffable unaffable unaffable unaffable, tail."
    page = source_page(text)
    settings = Settings(_env_file=None, chunk_tokens=4, chunk_overlap=1)
    chunks = chunk_pages([page], "document", "config", settings=settings, tokenizer=tokenizer)
    assert chunks[0].text.startswith("Café")
    covered = set()
    for chunk in chunks:
        assert chunk.text == text[chunk.start_char:chunk.end_char]
        assert len(tokenizer.encode(chunk.text, add_special_tokens=False)) <= 4
        covered.update(range(chunk.start_char, chunk.end_char))
    assert all(i in covered for i, character in enumerate(text) if not character.isspace())


@pytest.mark.parametrize("chunk_tokens,chunk_overlap", [(6, 2), (5, 1), (4, 2)])
def test_chunks_start_and_end_on_word_boundaries(tokenizer, chunk_tokens, chunk_overlap):
    text = "alpha unaffable beta unaffable gamma unaffable delta unaffable tail"
    settings = Settings(_env_file=None, chunk_tokens=chunk_tokens, chunk_overlap=chunk_overlap)
    chunks = chunk_pages([source_page(text)], "document", "config", settings=settings, tokenizer=tokenizer)
    covered = set()
    for chunk in chunks:
        assert chunk.text == text[chunk.start_char:chunk.end_char]
        assert len(tokenizer.encode(chunk.text, add_special_tokens=False)) <= chunk_tokens
        assert chunk.start_char == 0 or not text[chunk.start_char - 1].isalnum()
        assert chunk.end_char == len(text) or not text[chunk.end_char].isalnum()
        covered.update(range(chunk.start_char, chunk.end_char))
    assert all(i in covered for i, character in enumerate(text) if not character.isspace())
    assert [chunk.start_char for chunk in chunks] == sorted({chunk.start_char for chunk in chunks})


def test_word_longer_than_chunk_budget_is_split_rather_than_dropped(tokenizer):
    text = "unaffable"
    settings = Settings(_env_file=None, chunk_tokens=2, chunk_overlap=1)
    chunks = chunk_pages([source_page(text)], "document", "config", settings=settings, tokenizer=tokenizer)
    assert "".join(chunk.text for chunk in chunks).startswith("unaff")
    assert chunks[-1].text.endswith("able")


def test_line_break_hyphens_follow_the_documents_own_spelling():
    pages = extract_pages(make_pdf([
        "We cali-\nbrate models be-\ncause of drift and need context-\nrelevant data.",
        "Because we calibrate models, decision-making uses context and relevant tools.\n"
        "Then decision-\nmaking matters.",
    ]), "sample.pdf")
    assert "calibrate models because of drift" in pages[0].text
    assert "context-relevant data" in pages[0].text
    assert "decision-making matters" in pages[1].text
    assert "-\n" not in pages[0].text + pages[1].text


def test_unconfirmed_line_break_compounds_keep_the_hyphen_and_warn():
    page = extract_pages(make_pdf([
        "Use long-\nterm evidence and cost-\neffective controls.",
    ]), "compound.pdf")[0]
    assert "long-term evidence" in page.text
    assert "cost-effective controls" in page.text
    assert any("hyphen" in warning.lower() for warning in page.warnings)


def test_ids_are_deterministic_config_sensitive_and_page_local(tokenizer):
    pages = extract_pages(make_pdf(["alpha beta", "", "gamma delta"]), "sample.pdf")
    first = chunk_pages(pages, "document", "config-a", settings=small_settings(), tokenizer=tokenizer)
    again = chunk_pages(pages, "document", "config-a", settings=small_settings(), tokenizer=tokenizer)
    changed = chunk_pages(pages, "document", "config-b", settings=small_settings(), tokenizer=tokenizer)
    assert first == again
    assert [chunk.page_number for chunk in first] == [1, 3]
    assert first[0].chunk_id != first[1].chunk_id
    assert {chunk.chunk_id for chunk in first}.isdisjoint(chunk.chunk_id for chunk in changed)
    assert all(UUID(chunk.chunk_id).version == 5 for chunk in first)


def test_rejects_chunk_budget_exceeding_model_input_limit(tokenizer):
    tokenizer.model_max_length = 8
    with pytest.raises(ValueError, match="token"):
        chunk_pages(
            [source_page("alpha beta")], "document", "config",
            settings=small_settings(), tokenizer=tokenizer,
        )


def test_rejects_mixed_document_pages(tokenizer):
    with pytest.raises(ValueError, match="one document"):
        chunk_pages(
            [source_page("alpha"), source_page("beta", document_hash="b" * 64)],
            "document", "config", settings=small_settings(), tokenizer=tokenizer,
        )


@pytest.mark.parametrize(
    "text",
    ["Cafe\u0301", "\u0301alpha beta tail\u0301", "alpha\u0301 beta\u0301 gamma\u0301 tail\u0301"],
)
def test_tokenizer_ignored_accents_are_preserved_at_edges_and_boundaries(tokenizer, text):
    settings = Settings(_env_file=None, chunk_tokens=2, chunk_overlap=0)
    chunks = chunk_pages([source_page(text)], "document", "config", settings=settings, tokenizer=tokenizer)
    covered = set()
    for chunk in chunks:
        assert chunk.text == text[chunk.start_char:chunk.end_char]
        assert len(tokenizer.encode(chunk.text, add_special_tokens=False)) <= 2
        covered.update(range(chunk.start_char, chunk.end_char))
    assert all(i in covered for i, character in enumerate(text) if not character.isspace())


def test_nonempty_page_without_token_offsets_fails_explicitly(tokenizer):
    with pytest.raises(ValueError, match="tokeniz"):
        chunk_pages(
            [source_page("\u0301")], "document", "config",
            settings=small_settings(), tokenizer=tokenizer,
        )
