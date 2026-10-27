"""Download the fixed NIST corpus and verify its recorded bytes/page counts."""

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024


def fetch_document(record: dict, output_dir: Path, *, record_hashes: bool = False) -> dict:
    identifier = record["id"]
    source = urlparse(record["url"])
    if not re.fullmatch(r"[a-z0-9-]+", identifier):
        raise ValueError("Invalid corpus document id")
    if source.scheme != "https" or source.netloc != "nvlpubs.nist.gov":
        raise ValueError("Only official NIST HTTPS sources are allowed")
    expected_hash = record.get("sha256")
    if not expected_hash and not record_hashes:
        raise ValueError("Missing pinned hash; initial recording requires --record-hashes")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{identifier}.pdf"
    if target.exists():
        content = target.read_bytes()
    else:
        with urlopen(record["url"], timeout=60) as response:
            content = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(content) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"{identifier}: download exceeds size limit")
    actual_hash = hashlib.sha256(content).hexdigest()
    if expected_hash and actual_hash != expected_hash:
        raise ValueError(f"{identifier}: SHA-256 hash mismatch; existing pin was preserved")
    if not content.startswith(b"%PDF-"):
        raise ValueError(f"{identifier}: response is not a PDF")
    with pymupdf.open(stream=content, filetype="pdf") as document:
        if document.needs_pass or not 0 < len(document) <= 200:
            raise ValueError(f"{identifier}: encrypted PDF or invalid page count")
        pages = len(document)
    if record.get("pages") and pages != record["pages"]:
        raise ValueError(f"{identifier}: page count mismatch")
    if not target.exists():
        # shortcut: exclusive writes avoid Windows rename locks; add atomic staging for concurrency.
        with target.open("xb") as output:
            output.write(content)
    return {**record, "sha256": actual_hash, "pages": pages, "bytes": len(content)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-hashes", action="store_true", help="Record initial pins only")
    arguments = parser.parse_args()
    manifest_path = ROOT / "corpus/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = [
        fetch_document(record, ROOT / "corpus/pdfs", record_hashes=arguments.record_hashes)
        for record in manifest["documents"]
    ]
    if arguments.record_hashes:
        manifest.update(recorded_on=date.today().isoformat(), documents=documents)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for record in documents:
        print(f"{record['id']}: {record['pages']} pages; SHA-256 verified {record['sha256']}")


if __name__ == "__main__":
    main()
