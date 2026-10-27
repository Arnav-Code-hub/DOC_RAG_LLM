"""Explicit local-model download and assertion-based smoke check; never calls Groq."""

import json
import os
from pathlib import Path
from time import perf_counter

import numpy as np
import pymupdf
from sentence_transformers import CrossEncoder, SentenceTransformer

from app.config import load_settings


def main() -> None:
    settings = load_settings()
    os.environ.setdefault("HF_HOME", str(settings.hf_home.resolve()))
    started = perf_counter()
    encoder = SentenceTransformer(
        settings.embedding_model, revision=settings.embedding_revision, device="cpu",
        cache_folder=str(settings.hf_home / "hub"), trust_remote_code=False,
    )
    reranker = CrossEncoder(
        settings.reranker_model, revision=settings.reranker_revision, device="cpu",
        cache_folder=str(settings.hf_home / "hub"),
        trust_remote_code=False,
    )
    model_load_seconds = perf_counter() - started
    manifest = json.loads(Path("corpus/manifest.json").read_text(encoding="utf-8"))
    document_id = manifest["documents"][0]["id"]
    with pymupdf.open(Path("corpus/pdfs") / f"{document_id}.pdf") as document:
        page_number, text = next(
            (number + 1, page.get_text()) for number, page in enumerate(document)
            if len(page.get_text().strip()) > 1500
        )
    tokens = encoder.tokenizer.encode(text, add_special_tokens=False)[:settings.chunk_tokens]
    passage = encoder.tokenizer.decode(tokens, skip_special_tokens=True)
    question = "What is the purpose of the AI Risk Management Framework?"
    embedding_length = len(encoder.tokenizer.encode(passage))
    pair_length = len(reranker.tokenizer.encode(question, passage))
    assert embedding_length <= encoder.max_seq_length, "Embedding input would be truncated"
    assert pair_length <= reranker.config.max_position_embeddings, "Reranker pair would be truncated"
    started = perf_counter()
    vector = encoder.encode([passage], normalize_embeddings=True)
    scores = np.asarray(reranker.predict([(question, passage)]))
    assert vector.shape == (1, encoder.get_sentence_embedding_dimension())
    assert np.isfinite(vector).all() and np.isclose(np.linalg.norm(vector[0]), 1, atol=1e-4)
    assert scores.size == 1 and np.isfinite(scores).all()
    result = {
        "embedding_model": settings.embedding_model,
        "embedding_revision": settings.embedding_revision,
        "reranker_model": settings.reranker_model,
        "reranker_revision": settings.reranker_revision,
        "source_document": document_id,
        "physical_page": page_number,
        "embedding_dimension": vector.shape[1],
        "embedding_input_tokens": embedding_length,
        "reranker_pair_tokens": pair_length,
        "model_load_seconds": round(model_load_seconds, 3),
        "inference_seconds": round(perf_counter() - started, 3),
        "status": "passed_smoke_check_not_quality_evaluation",
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
