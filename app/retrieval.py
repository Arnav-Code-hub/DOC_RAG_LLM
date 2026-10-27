"""Single-process PDF index: publish ready records only after confirmed vector writes."""

import hashlib
import json
from threading import RLock

import numpy as np
import pymupdf
from pydantic import TypeAdapter, ValidationError
from qdrant_client import QdrantClient, models

from app.config import Settings, load_settings
from app.ingest import chunk_pages, extract_pages
from app.schemas import DocumentRecord, Passage

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
RESET_HINT = "run `python -m scripts.reset_index --yes` with the backend stopped, then re-ingest"


class DocumentIndex:
    def __init__(self, *, settings: Settings, encoder=None, client=None):
        self.settings = settings
        if encoder is None:
            from sentence_transformers import SentenceTransformer

            encoder = SentenceTransformer(
                settings.embedding_model, revision=settings.embedding_revision, device="cpu",
                cache_folder=str(settings.hf_home / "hub"), trust_remote_code=False,
            )
        self.encoder = encoder
        self.client = client if client is not None else QdrantClient(
            url=str(settings.qdrant_url), timeout=10,
        )
        self.dimension = encoder.get_sentence_embedding_dimension()
        if not self.dimension or self.dimension < 1:
            raise ValueError("Embedding model must declare a positive vector dimension")
        # Bump schema whenever extraction or chunking output changes, so old indexes fail closed.
        config = {
            "schema": 2, "parser": pymupdf.VersionBind, "collection": settings.qdrant_collection,
            "model": settings.embedding_model, "revision": settings.embedding_revision,
            "dimension": self.dimension, "chunk_tokens": settings.chunk_tokens,
            "chunk_overlap": settings.chunk_overlap, "query_prefix": QUERY_PREFIX,
            "normalized": True,
        }
        self.index_config_id = hashlib.sha256(
            json.dumps(config, sort_keys=True).encode()
        ).hexdigest()
        # shortcut: one cached index/worker owns writes; add a process lock before multiple writers.
        self._lock = RLock()
        self._registry = settings.data_dir / "documents.json"
        ready = self._read_documents()
        if self.client.collection_exists(settings.qdrant_collection):
            vectors = self.client.get_collection(settings.qdrant_collection).config.params.vectors
            if not isinstance(vectors, models.VectorParams) or vectors.size != self.dimension:
                raise ValueError("Existing Qdrant collection has an incompatible vector dimension")
            if vectors.distance != models.Distance.COSINE:
                raise ValueError("Existing Qdrant collection must use cosine distance")
        elif ready:
            raise ValueError(
                f"Qdrant collection is missing but the ready registry exists; {RESET_HINT}"
            )
        else:
            self.client.create_collection(
                settings.qdrant_collection,
                vectors_config=models.VectorParams(size=self.dimension, distance=models.Distance.COSINE),
            )

    def _read_documents(self) -> list[DocumentRecord]:
        if not self._registry.exists():
            return []
        try:
            records = TypeAdapter(list[DocumentRecord]).validate_json(self._registry.read_bytes())
        except ValidationError as error:
            raise ValueError(f"Invalid ready-document registry; restore it or {RESET_HINT}") from error
        if len({r.document_id for r in records}) != len(records) or any(
            r.document_id != r.document_hash for r in records
        ):
            raise ValueError("Invalid or duplicate document identities in the ready registry")
        if any(r.index_config_id != self.index_config_id for r in records):
            raise ValueError(f"Index configuration changed; {RESET_HINT}")
        return records

    def _write_documents(self, records: list[DocumentRecord]) -> None:
        self._registry.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._registry.with_suffix(".json.tmp")
        try:
            temporary.write_text(
                json.dumps([record.model_dump() for record in records], indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self._registry)
        finally:
            temporary.unlink(missing_ok=True)

    def list_documents(self) -> list[DocumentRecord]:
        with self._lock:
            return self._read_documents()

    def _filter(self, document_ids: list[str]) -> models.Filter:
        return models.Filter(must=[
            models.FieldCondition(key="document_id", match=models.MatchAny(any=document_ids)),
            models.FieldCondition(key="index_config_id",
                                  match=models.MatchValue(value=self.index_config_id)),
        ])

    def _delete_document(self, document_id: str) -> None:
        self.client.delete(
            self.settings.qdrant_collection,
            points_selector=self._filter([document_id]), wait=True,
        )

    def _embed(self, texts: list[str]) -> np.ndarray:
        for text in texts:
            count = len(self.encoder.tokenizer.encode(text, truncation=False, verbose=False))
            if count > self.encoder.max_seq_length:
                raise ValueError("Embedding input exceeds the model token limit; refusing truncation")
        vectors = np.asarray(self.encoder.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True,
            batch_size=32, show_progress_bar=False,
        ))
        if vectors.shape != (len(texts), self.dimension) or not np.isfinite(vectors).all():
            raise ValueError("Embedding vectors have invalid dimensions or nonfinite values")
        if not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-3):
            raise ValueError("Embedding vectors must be normalized and nonzero")
        return vectors

    def ingest_pdf(self, pdf_bytes: bytes, filename: str) -> DocumentRecord:
        with self._lock:
            if len(pdf_bytes) > self.settings.max_pdf_bytes:
                raise ValueError("PDF exceeds the configured size limit")
            document_hash = hashlib.sha256(pdf_bytes).hexdigest()
            records = self._read_documents()
            existing = next((r for r in records if r.document_id == document_hash), None)
            if existing is not None:
                return existing
            if len(records) >= self.settings.max_documents:
                raise ValueError("The configured document limit has been reached")
            pages = extract_pages(pdf_bytes, filename, settings=self.settings)
            chunks = chunk_pages(
                pages, document_hash, self.index_config_id,
                settings=self.settings, tokenizer=self.encoder.tokenizer,
            )
            record = DocumentRecord(
                document_id=document_hash, document_hash=document_hash,
                index_config_id=self.index_config_id, filename=pages[0].filename,
                page_count=len(pages), chunk_count=len(chunks), warnings=[
                    f"Page {page.page_number}: {warning}" for page in pages for warning in page.warnings
                ],
            )
            pdf_path = self.settings.data_dir / "pdfs" / pages[0].storage_name
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            self._delete_document(document_hash)
            try:
                pdf_path.write_bytes(pdf_bytes)
                for start in range(0, len(chunks), 32):
                    batch = chunks[start:start + 32]
                    vectors = self._embed([chunk.text for chunk in batch])
                    self.client.upsert(
                        self.settings.qdrant_collection, wait=True, points=[
                            models.PointStruct(id=chunk.chunk_id, vector=vector.tolist(),
                                               payload=chunk.model_dump())
                            for chunk, vector in zip(batch, vectors, strict=True)
                        ],
                    )
                self._write_documents([*records, record])
            except Exception:
                try:
                    self._delete_document(document_hash)
                finally:
                    pdf_path.unlink(missing_ok=True)
                raise
            return record

    def search(
        self, question: str, document_ids: list[str], limit: int = 20,
    ) -> list[Passage]:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Question must be nonempty")
        if len(question) > self.settings.max_question_chars:
            raise ValueError("Question exceeds the configured character limit")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= self.settings.candidate_k:
            raise ValueError("Search limit must be positive and within candidate_k")
        ready = {record.document_id for record in self.list_documents()}
        if not isinstance(document_ids, list) or not document_ids or any(
            not isinstance(document_id, str) or document_id not in ready for document_id in document_ids
        ):
            raise ValueError("Select one or more ready documents; unknown documents are forbidden")
        selection = list(dict.fromkeys(document_ids))
        vector = self._embed([QUERY_PREFIX + question.strip()])[0]
        hits = self.client.query_points(
            self.settings.qdrant_collection, query=vector.tolist(),
            query_filter=self._filter(selection), limit=limit, with_payload=True, with_vectors=False,
        ).points
        passages = []
        for hit in hits:
            passage = Passage(**(hit.payload or {}), score=hit.score)
            if passage.document_id not in selection or passage.index_config_id != self.index_config_id:
                raise ValueError("Qdrant returned a passage outside the selected document configuration")
            if str(hit.id) != passage.chunk_id:
                raise ValueError("Qdrant point ID does not match its passage provenance")
            passages.append(passage)
        return passages


_index: DocumentIndex | None = None
_index_lock = RLock()


def get_index() -> DocumentIndex:
    global _index
    with _index_lock:
        if _index is None:
            _index = DocumentIndex(settings=load_settings())
        return _index


def list_documents() -> list[DocumentRecord]:
    return get_index().list_documents()


def search(question: str, document_ids: list[str], limit: int = 20) -> list[Passage]:
    return get_index().search(question, document_ids, limit)
