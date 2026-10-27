import hashlib
import re
from bisect import bisect_right
from functools import lru_cache
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING, BinaryIO
from uuid import NAMESPACE_URL, uuid5

import pymupdf
from transformers import AutoTokenizer, PreTrainedTokenizerFast

from app.config import Settings, load_settings
from app.schemas import Chunk, DocumentRecord, Page

if TYPE_CHECKING:
    from app.retrieval import DocumentIndex

LINE_BREAK_HYPHEN = re.compile(r"([A-Za-z]+)-\n *([A-Za-z]+)")


def read_pdf_bytes(stream: BinaryIO, *, settings: Settings | None = None) -> bytes:
    settings = settings if settings is not None else load_settings()
    content = stream.read(settings.max_pdf_bytes + 1)
    if len(content) > settings.max_pdf_bytes:
        raise ValueError("PDF exceeds the configured size limit")
    return content


def extract_pages(
    pdf_bytes: bytes, filename: str, *, settings: Settings | None = None
) -> list[Page]:
    settings = settings if settings is not None else load_settings()
    if len(pdf_bytes) > settings.max_pdf_bytes:
        raise ValueError("PDF exceeds the configured size limit")
    if not pdf_bytes or b"%PDF-" not in pdf_bytes[:1024]:
        raise ValueError("Input is not a readable PDF")
    display_name = PureWindowsPath(filename).name
    if display_name in ("", ".", "..") or "\x00" in display_name:
        raise ValueError("PDF filename must have a valid display name")
    document_hash = hashlib.sha256(pdf_bytes).hexdigest()
    texts = []
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
            if document.needs_pass or (document.metadata or {}).get("encryption"):
                raise ValueError("Encrypted PDFs are unsupported; provide an unencrypted copy")
            if len(document) > settings.max_pages:
                raise ValueError(f"PDF exceeds the {settings.max_pages}-page limit")
            for page in document:
                raw = page.get_text("text", sort=True)
                text = re.sub(r"[^\S\n]+", " ", raw.replace("\r\n", "\n").replace("\r", "\n"))
                texts.append(re.sub(r"\n{3,}", "\n\n", text).strip())
    except (pymupdf.FileDataError, RuntimeError) as error:
        raise ValueError("Input is not a readable PDF or text extraction failed") from error
    pages = []
    for number, text in enumerate(_repair_line_break_hyphens(texts), start=1):
        warnings = []
        if LINE_BREAK_HYPHEN.search(texts[number - 1]):
            warnings.append(
                "Line-break hyphens normalized using document spellings; ambiguous hyphens kept. "
                "Inspect the PDF."
            )
        if not text:
            warnings.append("No extractable text; page may be blank or scanned. OCR is unsupported.")
        elif len(text) < 80:
            warnings.append("Low text content; inspect the page for missing text or images.")
        if "\ufffd" in text:
            warnings.append("Replacement characters found; extracted text may be incomplete.")
        # shortcut: table mentions flag layout risk; add structure parsing if table QA is needed.
        if re.search(r"\btable\s+\d", text, flags=re.IGNORECASE):
            warnings.append("Page mentions a table; inspect column reading order against the PDF.")
        pages.append(Page(
            document_hash=document_hash, filename=display_name,
            page_number=number, text=text, warnings=warnings,
        ))
    if not any(page.text for page in pages):
        raise ValueError("PDF has no extractable text; scanned PDFs require OCR, which is unsupported")
    return pages


def _repair_line_break_hyphens(texts: list[str]) -> list[str]:
    """Join only document-confirmed spellings; keep ambiguous hyphens instead of guessing."""
    unbroken = LINE_BREAK_HYPHEN.sub(" ", "\n".join(texts)).lower()
    words = set(re.findall(r"[a-z]+", unbroken))
    compounds = set(re.findall(r"[a-z]+(?:-[a-z]+)+", unbroken))

    def repair(match: re.Match) -> str:
        left, right = match.groups()
        pair = (left.lower(), right.lower())
        if "-".join(pair) in compounds or "".join(pair) not in words:
            return f"{left}-{right}"
        return left + right

    return [LINE_BREAK_HYPHEN.sub(repair, text) for text in texts]


def _inside_word(text: str, offsets: list[tuple[int, int]], index: int) -> bool:
    position = offsets[index][0]
    return 0 < position < len(text) and text[position - 1].isalnum() and text[position].isalnum()


def _word_start(text: str, offsets: list[tuple[int, int]], index: int, lower: int) -> int:
    """Move a token index back to its word's first token, staying above lower."""
    candidate = index
    while candidate > lower + 1 and _inside_word(text, offsets, candidate):
        candidate -= 1
    return index if _inside_word(text, offsets, candidate) else candidate


@lru_cache(maxsize=1)
def _load_tokenizer(model: str, revision: str, cache_dir: str) -> PreTrainedTokenizerFast:
    tokenizer = AutoTokenizer.from_pretrained(
        model, revision=revision, cache_dir=cache_dir, use_fast=True, trust_remote_code=False
    )
    if not tokenizer.is_fast:
        raise ValueError("Chunking requires a fast tokenizer with character offsets")
    return tokenizer


def chunk_pages(
    pages: list[Page], document_id: str, index_config_id: str,
    *, settings: Settings | None = None, tokenizer: PreTrainedTokenizerFast | None = None,
) -> list[Chunk]:
    settings = settings if settings is not None else load_settings()
    if not document_id.strip() or not index_config_id.strip():
        raise ValueError("Document and indexing configuration IDs must be nonempty")
    if not pages:
        return []
    if len({page.document_hash for page in pages}) != 1:
        raise ValueError("Pages must belong to one document")
    if tokenizer is None:
        tokenizer = _load_tokenizer(
            settings.embedding_model, settings.embedding_revision,
            str((settings.hf_home / "hub").resolve()),
        )
    if not tokenizer.is_fast:
        raise ValueError("Chunking requires a fast tokenizer with character offsets")
    if settings.chunk_tokens + tokenizer.num_special_tokens_to_add() > tokenizer.model_max_length:
        raise ValueError("Chunk token budget exceeds the embedding model's input limit")
    chunks = []
    for page in pages:
        offsets = tokenizer(
            page.text, add_special_tokens=False, return_offsets_mapping=True,
            truncation=False, verbose=False,
        )["offset_mapping"]
        if not offsets and page.text.strip():
            raise ValueError(f"Page {page.page_number} has text the embedding tokenizer cannot encode")
        token_ends = [end for _, end in offsets]
        start = 0
        ordinal = 0
        while start < len(offsets):
            end = min(start + settings.chunk_tokens, len(offsets))
            boundary = page.text.rfind("\n\n", offsets[start][0], offsets[end - 1][1])
            paragraph_end = bisect_right(token_ends, boundary)
            if paragraph_end - start >= max(settings.chunk_tokens // 2, settings.chunk_overlap + 1):
                end = paragraph_end
            if end < len(offsets):
                end = _word_start(page.text, offsets, end, start)
            start_char = 0 if start == 0 else offsets[start][0]
            while end > start:
                # Include characters the tokenizer normalizes away, including trailing accents.
                end_char = offsets[end][0] if end < len(offsets) else len(page.text)
                text = page.text[start_char:end_char].rstrip()
                end_char = start_char + len(text)
                if len(tokenizer.encode(text, add_special_tokens=False)) <= settings.chunk_tokens:
                    break
                end = _word_start(page.text, offsets, end - 1, start)
            if end == start:
                raise ValueError("A text span cannot fit the configured token budget")
            chunks.append(Chunk(
                chunk_id=str(uuid5(
                    NAMESPACE_URL, f"{page.document_hash}:{index_config_id}:{page.page_number}:{ordinal}"
                )),
                document_id=document_id, document_hash=page.document_hash,
                index_config_id=index_config_id, filename=page.filename, page_number=page.page_number,
                text=text, start_char=start_char, end_char=end_char,
            ))
            if end == len(offsets):
                break
            following = _word_start(
                page.text, offsets, max(start + 1, end - settings.chunk_overlap), start
            )
            # A word too long to back up into: shorten the overlap to the next word instead.
            while following < end and _inside_word(page.text, offsets, following):
                following += 1
            start = following
            ordinal += 1
    return chunks


def ingest_pdf(
    pdf_bytes: bytes, filename: str, *, index: "DocumentIndex | None" = None,
) -> DocumentRecord:
    from app.retrieval import get_index

    return (index if index is not None else get_index()).ingest_pdf(pdf_bytes, filename)
