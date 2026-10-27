"""Verify local corpus extraction/chunking with cached tokenizers; no model/API requests."""

import hashlib
import json
from pathlib import Path

from transformers import AutoTokenizer

from app.config import load_settings
from app.ingest import chunk_pages, extract_pages, read_pdf_bytes


def main() -> None:
    settings = load_settings()
    tokenizers = [
        AutoTokenizer.from_pretrained(
            model, revision=revision, cache_dir=str((settings.hf_home / "hub").resolve()),
            local_files_only=True, use_fast=True, trust_remote_code=False,
        )
        for model, revision in (
            (settings.embedding_model, settings.embedding_revision),
            (settings.reranker_model, settings.reranker_revision),
        )
    ]
    embedding_tokenizer, reranker_tokenizer = tokenizers
    configuration = {
        "embedding_model": settings.embedding_model,
        "embedding_revision": settings.embedding_revision,
        "chunk_tokens": settings.chunk_tokens,
        "chunk_overlap": settings.chunk_overlap,
    }
    config_id = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
    manifest = json.loads(Path("corpus/manifest.json").read_text(encoding="utf-8"))
    results = []
    for record in manifest["documents"]:
        path = Path("corpus/pdfs") / f"{record['id']}.pdf"
        with path.open("rb") as source:
            content = read_pdf_bytes(source, settings=settings)
        pages = extract_pages(content, path.name, settings=settings)
        assert len(pages) == record["pages"], "Corpus page count changed"
        assert pages[0].document_hash == record["sha256"], "Corpus hash changed"
        chunks = chunk_pages(
            pages, record["id"], config_id, settings=settings, tokenizer=embedding_tokenizer
        )
        assert len({chunk.chunk_id for chunk in chunks}) == len(chunks), "Duplicate chunk IDs"
        by_page = {page.page_number: [] for page in pages}
        max_embedding_tokens = max_pair_tokens = 0
        for chunk in chunks:
            page = pages[chunk.page_number - 1]
            assert chunk.text == page.text[chunk.start_char:chunk.end_char]
            assert not (chunk.start_char > 0 and page.text[chunk.start_char - 1].isalnum()
                        and page.text[chunk.start_char].isalnum()), "Corpus chunk starts mid-word"
            assert not (chunk.end_char < len(page.text) and page.text[chunk.end_char - 1].isalnum()
                        and page.text[chunk.end_char].isalnum()), "Corpus chunk ends mid-word"
            plain_count = len(embedding_tokenizer.encode(chunk.text, add_special_tokens=False))
            embedding_count = len(embedding_tokenizer.encode(chunk.text))
            pair_count = len(reranker_tokenizer.encode(
                "What does this framework recommend for managing risks?", chunk.text
            ))
            assert plain_count <= settings.chunk_tokens
            assert embedding_count <= embedding_tokenizer.model_max_length
            assert pair_count <= reranker_tokenizer.model_max_length
            max_embedding_tokens = max(max_embedding_tokens, embedding_count)
            max_pair_tokens = max(max_pair_tokens, pair_count)
            by_page[chunk.page_number].append(chunk)
        for page in pages:
            covered_end = 0
            for chunk in by_page[page.page_number]:
                assert not page.text[covered_end:chunk.start_char].strip(), "Missing source text"
                covered_end = max(covered_end, chunk.end_char)
            assert not page.text[covered_end:].strip(), "Missing page tail"
        results.append({
            "document_id": record["id"], "pages": len(pages), "chunks": len(chunks),
            "pages_with_warnings": sum(bool(page.warnings) for page in pages),
            "max_embedding_tokens_including_special": max_embedding_tokens,
            "max_reranker_pair_tokens_for_sample_question": max_pair_tokens,
        })
    print(json.dumps({
        "status": "passed_extraction_chunking_checks_not_answer_evaluation",
        "configuration": configuration, "documents": results,
    }, indent=2))


if __name__ == "__main__":
    main()
