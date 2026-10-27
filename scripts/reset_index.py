"""Delete the ready-document list, stored PDFs and Qdrant collection so documents can be re-ingested.

Stop the backend first: a running backend keeps its loaded index and would write to a deleted collection.
"""

import argparse
import shutil

from qdrant_client import QdrantClient

from app.config import Settings, load_settings


def reset_index(settings: Settings, client: QdrantClient) -> list[str]:
    data_dir = settings.data_dir.resolve()
    registry = data_dir / "documents.json"
    pdfs = data_dir / "pdfs"
    if data_dir.parent == data_dir or registry.resolve() != registry or pdfs.resolve() != pdfs:
        raise ValueError("Unsafe reset target: filesystem roots and redirected/symlink paths are forbidden")
    if pdfs.exists() and not pdfs.is_dir():
        raise ValueError("Unsafe reset target: the configured PDF path is not a directory")
    # Check connectivity before deleting the only local copy of an uploaded PDF.
    collection_exists = client.collection_exists(settings.qdrant_collection)
    # Remove the ready list first so an interrupted reset never leaves documents selectable.
    removed = []
    if registry.exists():
        registry.unlink()
        removed.append(str(registry))
    if pdfs.exists():
        shutil.rmtree(pdfs)
        removed.append(str(pdfs))
    if collection_exists:
        client.delete_collection(settings.qdrant_collection)
        removed.append(f"Qdrant collection {settings.qdrant_collection}")
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Confirm deleting the index")
    arguments = parser.parse_args()
    if not arguments.yes:
        parser.error("this deletes all indexed documents; rerun with --yes to confirm")
    settings = load_settings()
    client = QdrantClient(url=str(settings.qdrant_url), timeout=10)
    try:
        removed = reset_index(settings, client)
    finally:
        client.close()
    print("\n".join(f"Removed {item}" for item in removed) or "Nothing to remove")


if __name__ == "__main__":
    main()
