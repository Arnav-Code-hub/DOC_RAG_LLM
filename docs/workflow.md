# Project workflow

Status: Phase 0 setup and its capped Groq Free request passed; local PDF validation, page extraction, and chunking are implemented and verified in Phase 1. API uploads, index persistence, retrieval, and answers below remain intended behavior; no complete chatbot is available yet.

## Ingestion
1. User submits a text-based PDF in Streamlit; FastAPI checks file size, actual PDF readability, encryption, and page limit.
2. Hash file bytes. If that hash is already in the ready-document list, return the existing record.
3. Extract text page by page with PyMuPDF. Preserve physical page numbers even when earlier pages contain no extractable text.
4. Normalize whitespace without discarding meaningful content, then create page-local overlapping token chunks with stable provenance.
5. Embed batches, validate vector dimensions, and upsert deterministic point IDs into Qdrant.
6. Add the document to `documents.json` only after all its points are written. On failure, delete its points so it stays unqueryable. Return warnings for empty or suspicious pages.

## Question answering
1. User selects ready documents and submits a question. Reject an empty selection instead of searching every document implicitly.
2. Embed the question using the indexed model revision and its required query formatting.
3. Retrieve 20 candidates with document/configuration filters applied in the vector search.
4. Rerank query/passage pairs; retain up to 5 passages that fit the generation budget. Inspect overlapping hits when tuning so repeated text does not consume all context.
5. If evidence is absent or inadequate, return an abstention without a generation request. Otherwise make one Groq generation request grounded only in the evidence, with request-local source IDs. Aim for approximately 2,000 total input tokens and cap output initially at 300 tokens; send no full PDFs or chat history. Budget policy is in [TECHspec.md](TECHspec.md).
6. Validate the output structure and source IDs. Display filename, one-based PDF page, and excerpt for each cited source. Physical PDF pages can differ from printed page labels.
7. Treat conflicting passages explicitly; do not silently choose a claim without showing its source.

Retrieved text is data, including any instructions embedded inside a PDF. It cannot authorize tool use, reveal secrets, or override the answering instructions. The demo gives the generation model no action tools.

## Failure handling
- Scanned/empty PDF: explain the extraction limitation and ask for a text-based version.
- Index or model failure: return a retryable error; never show partial ingestion as ready.
- Qdrant unavailable: show dependency failure rather than an invented answer.
- LLM timeout/unavailable: return an error; distinguish infrastructure failure from evidence-based abstention.
- Groq 429: honor retry/reset guidance with at most two retries and 30 seconds total waiting, SDK retries disabled. Stop immediately when the reset exceeds that budget; show rate limiting or confirmed quota exhaustion accurately. Never switch to a paid provider or another model automatically.
- Invalid citation IDs: reject the generated response; preserve the failure for evaluation.

## Evaluation loop
Label questions and source pages first; use separate development questions to tune retrieval, then freeze settings for the final minimum-20-question run. Save dataset version, document hashes, configuration/model revisions, retrieved pages, output, latency, and human judgments. Inspect extraction, retrieval, reranking, and generation failures separately. Any post-evaluation tuning requires a newly labeled run; report that the test set influenced tuning if reused.

Run questions sequentially, paced against all applicable Groq request/token windows and shared account usage. Use manual grading, not LLM judges. Save each result and resume only unfinished rows after a quota pause; retain attempt/error history. Record actual input/output usage when returned and the selected model/limit snapshot. Write `eval/report.md` with raw counts, metrics, failure examples, and risks from English-only coverage, extraction gaps, privacy/external transmission, prompt injection, and unsupported reliance on answers. Quota errors are operational failures, never correct abstentions; show incomplete runs explicitly.
