# Technical specification

Status: Phases 0–1 passed: local dependencies/models are pinned, PDF extraction/chunking is verified, and one capped Groq Free request succeeded. Indexing, retrieval, cited generation, and UI sections remain implementation targets.

## Stack
- Python 3.11, FastAPI, Pydantic, Uvicorn: typed API and input validation.
- Streamlit: local demo interface; communicates with FastAPI instead of duplicating retrieval logic.
- PyMuPDF: page-level PDF text extraction. Review its license before distributing the application.
- sentence-transformers: embedding inference and cross-encoder scoring.
- Qdrant: local service with persistent storage; cosine similarity over normalized vectors.
- LLM: Groq Free plan, using the official `groq` Python SDK only for final answer generation. Set `GROQ_API_KEY` on the backend and `GROQ_MODEL` to an available free-plan model selected during setup. Never expose the key to Streamlit clients or commit it.
- Packaging: Docker Compose runs FastAPI, Streamlit, and Qdrant locally; named volumes persist PDFs, vectors, and model caches. Only the backend needs Groq credentials. Keep Qdrant internal and publish demo ports on localhost.
- Reproducibility: `uv` with a committed lockfile, pinned container versions, and recorded model revisions.
- pytest and Ruff; GitHub Actions runs lint and offline tests on pull requests and pushes.

## Model decision
Selected local models: `BAAI/bge-small-en-v1.5` for English embeddings and `cross-encoder/ms-marco-MiniLM-L6-v2` for reranking. These replace the larger BGE-M3 candidates to favor a laptop demo. Phase 0 verified compatibility, model revisions, token limits, and CPU smoke timing; revisions are pinned in settings. Retrieval/answer quality and end-to-end latency remain unmeasured. See [implementation.md](implementation.md) for evidence; inspect licenses before redistribution.

Use an initial 300-token target and 60-token overlap instead of the earlier 500–800 / 80–120 proposal. Reranking must accept the complete query/passage pair. Count with each model's tokenizer, reserve special/query tokens, and reject silent truncation. Validate query limits by tokens as well as characters. Smaller chunks may split evidence; tune only on development questions.

## Index contract
Start at a 300-token chunk target and 60-token overlap. Split within pages, favor paragraph boundaries, preserve raw source text, and skip empty pages with warnings. Token budgets use the embedding tokenizer, not word counts. Record low-text pages for manual inspection; OCR is out of scope.

Implemented contract: `extract_pages()` returns physical Page records including blank-page warnings; `chunk_pages()` emits only tokenizable text, with exact slices of whitespace-normalized page text and character offsets. It preserves tokenizer-ignored Unicode at slice edges, verifies actual re-encoded budgets, and rejects nonempty pages with no token offsets. `Page.storage_name` derives only from the validated document hash; supplied filenames are display basenames. `read_pdf_bytes()` caps binary reads, while complete multipart-body enforcement awaits Phase 6. Numbered-table mentions trigger a heuristic layout warning; this does not detect all tables or preserve table relationships.

Each Qdrant point stores `document_id`, `document_hash`, `filename`, `page_number` (one-based physical PDF page), `chunk_id`, `text`, and `index_config_id`. Point IDs are deterministic UUIDs derived from content hash, indexing configuration, page, and chunk ordinal. Filename is display metadata, never an identity or filesystem path.

Embedding dimension comes from the loaded model; an existing collection with a different dimension is an error. Changing models or chunk settings means deleting the collection and re-ingesting. Ready documents are listed in `documents.json` on the data volume, and a document is added only after all its chunks are written. On failure, that document's points are deleted, so a failed ingestion never becomes selectable. A full settings manifest that refuses incompatible reuse is a stretch goal (see [implementation.md](implementation.md#stretch-goals-only-after-the-release-checklist-passes)).

## Retrieval and generation
1. Validate query and require a nonempty set of ready document IDs.
2. Filter by document IDs and active indexing configuration inside Qdrant; retrieve 20 candidates initially.
3. Cross-encoder rerank candidates; keep up to 5 passages within the LLM token budget, including prompt/question/output reserves.
4. Assign request-local source IDs; provide text plus document/page metadata as untrusted evidence.
5. Make at most one successful Groq generation request per question; no query rewriting, answer-repair calls, or model-based grading. Request structured output supported by the selected model: answer, abstention flag, and cited source IDs. Validate structure and references locally; invalid output produces a generation error rather than an unchecked answer. A no-evidence query can abstain locally without calling Groq.

Candidate counts are initial settings, not measured optima. Similarity and reranker scores are not calibrated probabilities. Tune any evidence cutoff on development questions; absence of a cutoff does not justify answering unsupported questions. Prompt instructions plus human evaluation establish support checks; reference validation cannot establish semantic truth.

## Free-quota generation policy
- Select `GROQ_MODEL` after checking current availability, free-plan eligibility, context/output limits, and the account's request/token quotas. Record the model ID and limit snapshot with the evaluation; do not hard-code a permanent free-model promise.
- Keep extraction, embedding, reranking, and Qdrant on the laptop. Send only the question, instructions, source metadata, and selected passages to Groq; no full-PDF uploads or accumulated chat history.
- Planning target: approximately 2,000 total input tokens/request, including instructions and question; reduce passage count/text at chunk boundaries to fit. Start with a 300-output-token cap and adjust within quota/model limits. Use the generation tokenizer when available, a conservative estimate otherwise, and record actual usage. For reasoning models, verify how reasoning tokens count toward output and quota budgets.
- Twenty generated answers at that input target imply about 40,000 input tokens plus up to 6,000 output tokens, before retries, reasoning overhead, development, and repeated runs. This is a budgeting estimate, not measured usage or guaranteed quota availability.
- Serialize requests. Pace evaluation against remaining request/token budgets and reset headers; check all applicable minute/day limits and shared organization usage. Pause/resume the run when daily quota is unavailable; never mark unanswered rows as completed evaluation.
- On HTTP 429, honor `Retry-After`. Proposed retry policy: at most two retries after the initial attempt, at most 30 seconds total waiting; absent a header, use short exponential backoff with jitter. If reset exceeds that budget, return an actionable quota/rate-limit error immediately. Disable SDK automatic retries so they cannot multiply this budget. Do not automatically retry authentication errors, malformed output, or ambiguous timeouts.
- UI distinguishes temporary rate limiting from confirmed exhausted daily quota; show reset/retry guidance when supplied. Never label quota failures as evidence-based abstentions, switch providers/models automatically, or enable a paid plan.
- Confirm Free-plan account status manually; the application configuration cannot prove the account has not been upgraded. Electricity, hardware, internet, and downloads remain outside API-cost estimates.

Verified account/model snapshot (2026-10-27): user-supplied billing evidence shows Free as the current $0 plan; the organization screenshot lists `openai/gpt-oss-120b` at 30 requests/minute, 1,000/day, 8,000 tokens/minute, and 200,000/day. One 300-token-capped request succeeded with 111 total tokens, including 23 reasoning tokens within 33 completion tokens. Response headers confirmed requests/day and tokens/minute. Project overrides and shared usage can reduce available capacity; recheck before evaluation. `GROQ_FREE_CONFIRMED` records external confirmation and does not query billing. Full evidence and environment constraints are in [implementation.md](implementation.md).

Provider references: [Groq quickstart](https://console.groq.com/docs/quickstart), [supported models](https://console.groq.com/docs/models), [rate limits](https://console.groq.com/docs/rate-limits), and [billing FAQ](https://console.groq.com/docs/billing-faqs). Public documentation checked 2026-10-27; the dated account evidence above is separate from these public references.

## Proposed API
- `GET /health`: service readiness and dependency failures without secrets.
- `POST /documents`: synchronous, bounded single-PDF ingestion; returns ready document metadata or a clear failure.
- `GET /documents`: ready documents and ingestion status.
- `POST /chat`: `{question, document_ids}`; returns `{answer, abstained, sources}`. Each source includes source ID, document ID, filename, page number, and excerpt. Dependency/quota failures return structured non-success errors with a stable code and retry guidance, rather than `abstained=true`.

Initial limits: 20 MiB/PDF, 200 pages/PDF, 2,000 characters/question, 10 selected documents/query. Validate PDF content, encrypted/unreadable files, page counts, and model/service timeouts. Use generated storage names, serialize ingestion in the demo, and bind services to localhost. These limits bound the demo; they are not a production security boundary for hostile PDFs.

## Configuration and persistence
Planned settings: Qdrant URL/collection, embedding/reranker model IDs and revisions, `GROQ_API_KEY`, `GROQ_MODEL`, chunk target/overlap, candidate/final counts, and timeout/token limits. Use the SDK's Groq endpoint; no generic provider fallback. Provide a secret-free `.env.example`; ignore `.env`, uploaded PDFs, local vectors, and caches. Persist uploaded files and Qdrant data outside source control. Avoid logging passages or credentials by default.
