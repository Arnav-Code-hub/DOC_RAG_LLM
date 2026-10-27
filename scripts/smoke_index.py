"""Explicit real-Qdrant/cached-model checks; never contacts Groq or grades answers."""

import argparse
import hashlib
import json
from pathlib import Path

import pymupdf

from app.ingest import ingest_pdf, read_pdf_bytes
from app.retrieval import get_index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true",
                        help="Check persisted corpus records after restart without ingesting")
    args = parser.parse_args()
    index = get_index()
    collection = index.settings.qdrant_collection
    manifest = json.loads(Path("corpus/manifest.json").read_text(encoding="utf-8"))
    before = index.client.count(collection, exact=True).count
    records = []
    try:
        for document in manifest["documents"]:
            with (Path("corpus/pdfs") / f"{document['id']}.pdf").open("rb") as source:
                content = read_pdf_bytes(source, settings=index.settings)
            assert hashlib.sha256(content).hexdigest() == document["sha256"], "Corpus hash changed"
            if args.verify_only:
                record = next(r for r in index.list_documents()
                              if r.document_id == document["sha256"])
            else:
                record = ingest_pdf(content, f"{document['id']}.pdf", index=index)
                count = index.client.count(collection, exact=True).count
                assert ingest_pdf(content, "renamed.pdf", index=index) == record
                assert index.client.count(collection, exact=True).count == count, "Duplicate points"
            assert record.page_count == document["pages"]
            assert record.document_hash == document["sha256"]
            assert record.index_config_id == index.index_config_id
            stored = index.settings.data_dir / "pdfs" / f"{record.document_hash}.pdf"
            assert hashlib.sha256(stored.read_bytes()).hexdigest() == record.document_hash
            records.append(record)

        for record in records:
            passages = index.search("What does this framework say about risk management?",
                                    [record.document_id])
            assert passages and {p.document_id for p in passages} == {record.document_id}
            assert all(p.document_hash == record.document_hash and p.filename == record.filename
                       and 1 <= p.page_number <= record.page_count for p in passages)
        selected = [r.document_id for r in records[:2]]
        assert all(p.document_id in selected for p in index.search("cybersecurity", selected))

        if not args.verify_only:
            ready_before = index.list_documents()
            count_before = index.client.count(collection, exact=True).count
            with pymupdf.open() as document:
                document.new_page().insert_text((72, 72), "Phase two failure cleanup probe.")
                failed_pdf = document.tobytes()
            failed_hash = hashlib.sha256(failed_pdf).hexdigest()
            original_upsert = index.client.upsert

            def fail_after_write(*positional, **keywords):
                original_upsert(*positional, **keywords)
                raise RuntimeError("Intentional Phase 2 partial-write probe")

            index.client.upsert = fail_after_write
            try:
                try:
                    ingest_pdf(failed_pdf, "phase2-failure-probe.pdf", index=index)
                except RuntimeError as error:
                    assert str(error) == "Intentional Phase 2 partial-write probe"
                else:
                    raise AssertionError("Partial-write probe did not fail")
            finally:
                index.client.upsert = original_upsert
            assert index.list_documents() == ready_before
            assert index.client.count(collection, exact=True).count == count_before
            assert not (index.settings.data_dir / "pdfs" / f"{failed_hash}.pdf").exists()

        count = index.client.count(collection, exact=True).count
        if args.verify_only:
            assert count == before, "Verification must not change vector count"
        print(json.dumps({
            "status": "passed_persistence_filter_checks_not_answer_evaluation",
            "mode": "verify_only" if args.verify_only else "ingest_and_failure_probe",
            "collection": collection, "dimension": index.dimension,
            "index_config_id": index.index_config_id,
            "corpus_documents": len(records), "corpus_chunks": sum(r.chunk_count for r in records),
            "collection_points": count,
            "documents": [{"id": document["id"], "document_id": record.document_id,
                           "pages": record.page_count, "chunks": record.chunk_count}
                          for document, record in zip(manifest["documents"], records, strict=True)],
            "groq_requests": 0,
        }, indent=2))
    finally:
        index.client.close()


if __name__ == "__main__":
    main()
