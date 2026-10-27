import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from uuid import uuid4

import numpy as np
import pymupdf
import pytest
from qdrant_client import QdrantClient, models
from transformers import BertTokenizerFast

from app.config import Settings
from app.ingest import ingest_pdf
from app.retrieval import DocumentIndex


def pdf(*texts):
    with pymupdf.open() as document:
        for text in texts:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        return document.tobytes()


class TinyEncoder:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.max_seq_length = 512
        self.calls = []

    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, texts, **kwargs):
        self.calls.append(list(texts))
        return np.asarray([
            [1.0, 0.0, 0.0] if "alpha" in text.lower() else [0.0, 1.0, 0.0]
            for text in texts
        ])


@pytest.fixture
def index(tmp_path):
    vocabulary = tmp_path / "vocab.txt"
    vocabulary.write_text(
        "\n".join(["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "alpha", "beta"]),
        encoding="utf-8",
    )
    encoder = TinyEncoder(BertTokenizerFast(vocab_file=str(vocabulary), model_max_length=512))
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", chunk_tokens=10,
                        chunk_overlap=2, groq_api_key=None)
    client = QdrantClient(":memory:")
    yield DocumentIndex(settings=settings, encoder=encoder, client=client)
    client.close()


def point_count(index):
    return index.client.count(index.settings.qdrant_collection, exact=True).count


def test_repeat_ingestion_is_idempotent(index):
    content = pdf("alpha", "", "alpha alpha")
    first = ingest_pdf(content, "../sample.pdf", index=index)
    calls = len(index.encoder.calls)
    second = ingest_pdf(content, "renamed.pdf", index=index)
    assert first == second
    assert first.document_id == first.document_hash == hashlib.sha256(content).hexdigest()
    assert first.filename == "sample.pdf" and first.page_count == 3 and first.chunk_count == 2
    assert any("Page 2" in warning for warning in first.warnings)
    assert index.list_documents() == [first]
    assert point_count(index) == 2 and len(index.encoder.calls) == calls
    assert (index.settings.data_dir / "pdfs" / f"{first.document_hash}.pdf").read_bytes() == content


def test_failed_ingestion_not_listed(index, monkeypatch):
    ready = ingest_pdf(pdf("alpha"), "ready.pdf", index=index)
    original_upsert = index.client.upsert

    def fail_after_write(*args, **kwargs):
        original_upsert(*args, **kwargs)
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(index.client, "upsert", fail_after_write)
    content = pdf("beta")
    with pytest.raises(RuntimeError, match="simulated write failure"):
        ingest_pdf(content, "failed.pdf", index=index)
    assert index.list_documents() == [ready]
    assert point_count(index) == ready.chunk_count
    assert not (index.settings.data_dir / "pdfs" / f"{hashlib.sha256(content).hexdigest()}.pdf").exists()


def test_registry_failure_rolls_back_new_points_and_keeps_ready_documents(index, monkeypatch):
    ready = ingest_pdf(pdf("alpha"), "ready.pdf", index=index)
    registry = index.settings.data_dir / "documents.json"
    original = registry.read_bytes()

    def fail_replace(path, target):
        raise PermissionError("simulated registry failure")

    monkeypatch.setattr(type(registry), "replace", fail_replace)
    with pytest.raises(PermissionError, match="registry failure"):
        ingest_pdf(pdf("beta"), "failed.pdf", index=index)
    assert index.list_documents() == [ready]
    assert point_count(index) == ready.chunk_count
    assert registry.read_bytes() == original
    assert not registry.with_suffix(".json.tmp").exists()


def test_unselected_document_excluded(index):
    alpha = ingest_pdf(pdf("", "", "alpha"), "alpha.pdf", index=index)
    beta = ingest_pdf(pdf("beta"), "beta.pdf", index=index)
    passages = index.search("beta", [alpha.document_id])
    assert passages and {p.document_id for p in passages} == {alpha.document_id}
    assert all(p.page_number == 3 and p.filename == "alpha.pdf" for p in passages)
    assert passages[0].text == "alpha" and passages[0].score == 0.0
    assert index.search("beta", [beta.document_id])[0].score == 1.0
    assert passages[0].document_hash == alpha.document_hash
    assert passages[0].index_config_id == index.index_config_id
    assert passages[0].text == "alpha"[passages[0].start_char:passages[0].end_char]


@pytest.mark.parametrize("selection", [[], ["unknown"], ["ready", "unknown"]])
def test_invalid_document_selection_fails_before_embedding(index, selection):
    ready = ingest_pdf(pdf("alpha"), "ready.pdf", index=index)
    selection = [ready.document_id if item == "ready" else item for item in selection]
    calls = len(index.encoder.calls)
    with pytest.raises(ValueError, match="select|ready|document"):
        index.search("alpha", selection)
    assert len(index.encoder.calls) == calls


def test_other_index_configuration_is_filtered_inside_qdrant(index):
    ready = ingest_pdf(pdf("alpha"), "alpha.pdf", index=index)
    stored = index.client.scroll(index.settings.qdrant_collection, with_payload=True)[0][0]
    stale = dict(stored.payload, index_config_id="0" * 64, chunk_id=str(uuid4()), text="beta")
    index.client.upsert(index.settings.qdrant_collection, [models.PointStruct(
        id=stale["chunk_id"], vector=[0.0, 1.0, 0.0], payload=stale,
    )])
    passages = index.search("beta", [ready.document_id])
    assert len(passages) == 1 and passages[0].text == "alpha"


def test_ready_registry_survives_index_reload(index):
    ready = ingest_pdf(pdf("alpha"), "alpha.pdf", index=index)
    reloaded = DocumentIndex(settings=index.settings, encoder=index.encoder, client=index.client)
    assert reloaded.list_documents() == [ready]
    assert reloaded.search("alpha", [ready.document_id])[0].document_id == ready.document_id


@pytest.mark.parametrize("size,distance", [(2, models.Distance.COSINE), (3, models.Distance.EUCLID)])
def test_incompatible_collection_fails_without_recreating_it(index, size, distance):
    client = QdrantClient(":memory:")
    client.create_collection(index.settings.qdrant_collection,
                             vectors_config=models.VectorParams(size=size, distance=distance))
    with pytest.raises(ValueError, match="dimension|cosine|Cosine"):
        DocumentIndex(settings=index.settings, encoder=index.encoder, client=client)
    assert client.get_collection(index.settings.qdrant_collection).config.params.vectors.size == size
    client.close()


def test_changed_configuration_refuses_old_ready_registry(index):
    ingest_pdf(pdf("alpha"), "alpha.pdf", index=index)
    settings = index.settings.model_copy(update={"chunk_tokens": 12})
    with pytest.raises(ValueError, match="configuration"):
        DocumentIndex(settings=settings, encoder=index.encoder, client=index.client).list_documents()


def test_missing_collection_does_not_reuse_stale_ready_registry(index):
    ingest_pdf(pdf("alpha"), "alpha.pdf", index=index)
    index.client.delete_collection(index.settings.qdrant_collection)
    with pytest.raises(ValueError, match="missing|Missing"):
        DocumentIndex(settings=index.settings, encoder=index.encoder, client=index.client)


def test_corrupt_registry_is_not_silently_replaced(index):
    ingest_pdf(pdf("alpha"), "alpha.pdf", index=index)
    registry = index.settings.data_dir / "documents.json"
    registry.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="registry"):
        index.list_documents()
    assert registry.read_text(encoding="utf-8") == "not json"


def test_serialized_ingestion_preserves_both_ready_records(index):
    contents = [pdf("alpha"), pdf("beta")]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ingest_pdf, content, f"{i}.pdf", index=index)
                   for i, content in enumerate(contents)]
        ready = [future.result() for future in futures]
    assert {r.document_id for r in index.list_documents()} == {r.document_id for r in ready}
    assert point_count(index) == 2


@pytest.mark.parametrize("vectors", [[[float("nan"), 0, 0]], [[0, 0, 0]], [[1, 0]]])
def test_invalid_embeddings_never_become_ready(index, monkeypatch, vectors):
    monkeypatch.setattr(index.encoder, "encode", lambda *args, **kwargs: np.asarray(vectors))
    with pytest.raises(ValueError, match="embedding|vector"):
        ingest_pdf(pdf("alpha"), "bad.pdf", index=index)
    assert index.list_documents() == [] and point_count(index) == 0


def test_query_cannot_silently_truncate(index):
    ready = ingest_pdf(pdf("alpha"), "alpha.pdf", index=index)
    with pytest.raises(ValueError, match="token"):
        index.search("!" * 600, [ready.document_id])


def test_document_limit_preserves_existing_index(index):
    index.settings.max_documents = 1
    ready = ingest_pdf(pdf("alpha"), "alpha.pdf", index=index)
    with pytest.raises(ValueError, match="document limit"):
        ingest_pdf(pdf("beta"), "beta.pdf", index=index)
    assert index.list_documents() == [ready] and point_count(index) == 1


def test_duplicate_registry_records_fail_closed(index):
    ready = ingest_pdf(pdf("alpha"), "alpha.pdf", index=index)
    registry = index.settings.data_dir / "documents.json"
    registry.write_text(json.dumps([ready.model_dump(), ready.model_dump()]), encoding="utf-8")
    with pytest.raises(ValueError, match="registry"):
        index.list_documents()


def test_concurrent_first_requests_load_only_one_shared_index(monkeypatch):
    from app import retrieval

    created = []

    def create_index(**kwargs):
        instance = object()
        created.append(instance)
        sleep(0.05)  # Simulate slow model loading so concurrent cache misses overlap.
        return instance

    monkeypatch.setattr(retrieval, "DocumentIndex", create_index)
    monkeypatch.setattr(retrieval, "_index", None, raising=False)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: retrieval.get_index(), range(8)))
    assert len(created) == 1
    assert all(result is results[0] for result in results)
