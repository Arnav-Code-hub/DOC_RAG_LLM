# PDF RAG Chatbot Implementation Plan

> For agentic workers: implement task by task using the executing-plans skill. Checkboxes record verified progress; Phases 0–2 are complete and Phases 3–9 remain pending. This document does not authorize publishing or spending beyond the user's stated scope.

**Goal:** Deliver a reproducible Dockerized PDF chatbot, a GitHub repository, and an honest evaluation report within two focused working days where hardware and free quotas permit.

**Architecture:** Streamlit calls FastAPI. The backend extracts page text, creates chunks, embeds locally, searches Qdrant, reranks locally, and sends selected evidence to Groq Free for one final answer. Source provenance and citation validation remain in application code; humans grade evaluation outputs.

**Tech stack:** Python 3.11, FastAPI/Pydantic/Uvicorn, Streamlit, PyMuPDF, sentence-transformers, Qdrant, Groq Python SDK, Docker Compose, uv, pytest, Ruff, GitHub Actions.

**Specifications:** [PRD.md](PRD.md), [TECHspec.md](TECHspec.md), [workflow.md](workflow.md), and [rules.md](rules.md). Read these alongside this plan. Status as of 2026-10-27: Phases 0–2 passed, including the Groq readiness gate, extraction/chunking, persistent indexing, and selected-document dense search. Phases 3–9 remain pending. Checkboxes record verified progress only, not quality evaluation or full application readiness.

## Global constraints
- Single-user local demo; primarily English, text-based PDFs. No OCR, public hosting, agents, authentication, fine-tuning, or multi-tenant access in the MVP.
- Start with 300-token chunks and 60-token overlap, bounded to pages; check both embedding and reranker tokenizers and reject silent truncation.
- Local models: `BAAI/bge-small-en-v1.5` and `cross-encoder/ms-marco-MiniLM-L6-v2`, with revisions pinned after compatibility checks.
- Retrieve 20 candidates; rerank to at most 5; include fewer when the generation budget requires it.
- Groq Free only; backend-only `GROQ_API_KEY`, explicitly selected `GROQ_MODEL`, no automatic model/provider switch or paid upgrade.
- Approximately 2,000 total input tokens and an initial 300-output-token cap; actual model limits and reasoning overhead must be checked.
- At most two 429 retries after the first attempt, at most 30 seconds total waiting, SDK retries disabled. No automatic retry for ambiguous timeouts, authentication errors, or malformed output.
- Input limits: 20 MiB/PDF, 200 pages/PDF, 2,000 characters/question, and at most 10 selected documents/query, plus model-specific query token checks.
- At least 14 answerable plus 6 unanswerable final evaluation questions; separate development questions. No LLM judge calls.
- Corpus: the three NIST PDFs listed in [PRD.md](PRD.md#corpus), fetched by script and verified by hash.
- Layout: root `README.md` is the landing page; specifications live in `docs/`. Keep `docs/Design.md` completely empty.
- Build the core path first. Items under "Stretch goals" start only after the release checklist passes.

## Schedule and dependencies
Day 1: Phase 0 (1h), Phase 1 (2h), Phase 2 (1.5h), Phase 3 (1h), Phase 4 (1.5h).

Day 2: Phase 5 (1.5h), Phase 6 (1h), Phase 7 (1h), Phase 8 (2.5h), Phase 9 (1h).

Total: 14 focused hours plus a 2-hour buffer, which fits two 8-hour days. Model downloads and free-quota resets can extend elapsed time. Tests belong inside each phase's timebox. Begin Docker configuration in Phase 0; Phase 7 verifies the complete application rather than starting packaging from nothing.

Dependencies: ingestion precedes retrieval; retrieval precedes reranking and answers; a labeled dataset precedes final evaluation. The UI consumes the tested backend instead of implementing its own RAG pipeline.

## Planned file responsibilities
All paths below are relative to the project root and describe files to create, not files already present.

- `pyproject.toml`, `uv.lock`: runtime/development dependencies and locked environment.
- `.env.example`, `.gitignore`, `.dockerignore`: safe configuration and exclusion of secrets, PDFs, vectors, caches, and private evaluation outputs from build contexts/source control.
- `scripts/fetch_corpus.py`, `corpus/manifest.json`: download the NIST PDFs into an ignored `corpus/pdfs/` directory and verify each SHA-256 hash.
- `app/config.py`: validated settings and indexing configuration identity.
- `app/schemas.py`: shared Pydantic records for pages, chunks, passages, responses, and errors.
- `app/ingest.py`: PDF validation, extraction, chunking, deterministic IDs, and ingestion orchestration.
- `app/retrieval.py`: local model loading, Qdrant operations, ready-document list, filtered search, and reranking. Keep functions direct; split only if actual complexity warrants it.
- `app/answer.py`: evidence packing, Groq request, bounded quota handling, and output validation.
- `app/api.py`: FastAPI lifespan, endpoints, and stable HTTP error mapping.
- `ui.py`: Streamlit upload, selection, questions, citations, and error display.
- `tests/`: small synthetic fixtures and offline tests using model/provider stubs; explicit integration marker for live services.
- `eval/dev.jsonl`, `eval/questions.jsonl`: development/final labels with stable question IDs and expected evidence.
- `eval/run.py`, `eval/report.md`: resumable sequential runner and manually reviewed report.
- `Dockerfile`, `compose.yaml`: shared application image, backend/UI commands, local Qdrant, named volumes, health checks, and localhost ports.
- `.github/workflows/ci.yml`: locked install, lint, and offline tests without Groq credentials.

Do not add PostgreSQL, Redis, Celery, LangChain, LangGraph, or a second vector database. The ready-document list is a small JSON file (`documents.json`) on the data volume. A document is added to it only after all of its chunks are written, so a failed ingestion never becomes selectable.

## Review focus
- A PDF with text on pages 1 and 3 and a blank page 2 must retain physical page 3 citations. Test in Phase 1.
- A failed ingestion must not appear in the ready-document list. Test in Phase 2.
- Valid-looking source IDs can cite irrelevant text; local validation checks IDs, while Phase 8 human review checks claim support.
- A prompt-injection passage must remain evidence, never authorize actions or instruction changes. Exercise a stubbed prompt-construction test in Phase 5 and a development smoke question.

## Common test and checkpoint cycle
For each nontrivial task: write the named failing tests, run them and confirm the intended failure, implement only the required behavior, rerun the focused tests, then run the relevant existing suite. Use `uv run pytest <test-file> -q` and `uv run ruff check .`; these are planned commands until the project exists.

After a phase passes, inspect the diff and create a focused local commit if a Git repository exists and local commits are authorized. Stage explicit paths; exclude secrets and private data. No automatic push or publication is implied by a local checkpoint.

## Phase 0 — prove prerequisites and establish the runnable skeleton (Day 1, 1h)
**Files:** dependency/config files, `app/config.py`, `app/schemas.py`, minimal `app/api.py`, `Dockerfile`, `compose.yaml`, `tests/test_config.py`.

**Interfaces:** `load_settings() -> Settings`; FastAPI `app`; `GET /health`. Settings include model revisions, collection identity, limits, paths, and Groq key/model. Missing generation credentials must not prevent offline ingestion/tests; generation readiness reports the omission without exposing values.

- [x] Confirm Python, uv, Docker Desktop/Compose, and available RAM/disk.
- [x] Write `scripts/fetch_corpus.py`; download the three NIST PDFs, record their SHA-256 hashes and page counts in `corpus/manifest.json`, and confirm the reuse terms on each notice page. Ignore `corpus/pdfs/` in Git.
- [x] Download/load both local models; inspect a representative page and verify complete query/passage inputs fit. Measure smoke-test runtime, without claiming benchmark performance.
- [x] Manually confirm the Groq account is Free, select an available model, record account/model limits, and make one deliberately capped smoke request. Keep the key outside chat, Git, images, and logs. The readiness smoke uses plain text; cited structured answers and their validation belong to Phase 5.
- [x] Create dependencies and lockfile; add ignore files and placeholder environment values. The explicit model smoke loads each model once; backend process model loading belongs to the retrieval implementation, not the health-only skeleton. The backend uses one worker.
- [x] Start Qdrant and a minimal backend container; verify `/health` reports dependency readiness without generating text. Add named volumes now.
- [x] Test `test_missing_groq_key_allows_offline_mode` and `test_invalid_limits_rejected`: invalid overlap/size settings fail, absent key disables generation only, and errors reveal no secrets.

**Verified Phase 0 evidence:** Python 3.11.18, uv 0.13.6, Docker 29.7.2 / Compose 5.4.0; about 16 GiB RAM and 103 GiB free disk at setup. Corpus: 48/64/32 pages, all hashes reverified. Offline suite: 17 tests passed; Ruff passed. Native offline CPU model smoke: 384-dimensional normalized embedding, 302 embedding-input tokens and 314 reranker-pair tokens, model load 1.051s and combined inference 1.488s on one NIST page-3 passage. These timings are smoke observations, not retrieval/answer quality or a load benchmark. Starlette/sentence-transformers emit upstream deprecation warnings.

**Container evidence:** backend and Qdrant containers started; the live `/health` response was `{"status":"ok","qdrant":"ready","generation":"not_configured"}`. A disposable collection/point survived Qdrant restart on its named volume, then was deleted; the temporary localhost Qdrant mapping was removed. The initial build needed approximately nine minutes for image export/unpack in addition to dependency downloads; allow first-build time outside coding timeboxes.

**Groq gate passed 2026-10-27:** the key authenticated against the read-only model-list endpoint and selected model `openai/gpt-oss-120b` was available. The user then supplied billing evidence showing **Free, $0, Current Plan** and organization limits of **30 requests/minute, 1,000 requests/day, 8,000 tokens/minute, 200,000 tokens/day**. Only `GROQ_FREE_CONFIRMED` was changed to true in the ignored `.env`; the existing key/model were preserved. These limits are a dated snapshot, not a permanent promise; check project overrides and shared organization usage before evaluation.

Exactly **one** live `scripts/smoke_groq.py` generation request succeeded, with a **300-token maximum completion**, `finish_reason=stop`, **78 prompt tokens + 33 completion tokens = 111 total**, and **23 reasoning tokens within the 33 completion tokens**. SDK retries were disabled; no retry, model switch, or paid fallback occurred. Response headers confirmed 1,000 requests/day and 8,000 tokens/minute; remaining budgets were 999 requests and 7,622 tokens at that response. Those remaining values are transient. This was a readiness check, not a RAG evaluation or a structured-citation test.

**Final Phase 0–1 checks:** 41 offline tests passed, Ruff passed, and the 85-package lockfile passed offline validation. Docker Compose configuration validated, the rebuilt backend became healthy, and `/health` returned `{"status":"ok","qdrant":"ready","generation":"configured_not_verified"}`. The generation field intentionally describes configuration only; the separate smoke establishes live access. One new offline HTTP-transport regression verifies the smoke's application User-Agent, single capped request, and safe metadata output; it failed before the fix and passed afterward. The earlier 40-test suite, corpus/model checks, Qdrant restart persistence check, and image secret-exclusion check passed before the live request.

**Environment limitations:** direct project-Python networking is restricted in this session; pinned corpus/model files were fetched through Windows HTTPS, then verified/run locally. The Groq request succeeded from the rebuilt Linux container with an application User-Agent and a read-only trusted CA bundle mounted at runtime. Docker builds need the separate optional trusted-CA build secret described in the root README. No TLS verification was disabled, and the key was neither displayed nor baked into the image. The runtime trust mount must be configured for generation when Phase 5 is implemented on this network. Phase 0–1 checks originally ran without Git metadata. Git was subsequently initialized for the user's authorized publication to [Arnav-Code-hub/DOC_RAG_LLM](https://github.com/Arnav-Code-hub/DOC_RAG_LLM); local credentials, PDFs, model caches, and setup artifacts remain ignored.

**Gate:** one PDF page embeds locally; reranker scores a pair; Qdrant survives restart; one capped Groq request succeeds. If a prerequisite fails, resolve it before feature work. Quota/model availability is a blocker, not justification for a paid fallback.

## Phase 1 — extract and chunk with trustworthy provenance (Day 1, 2h)
**Files:** `app/ingest.py`, records in `app/schemas.py`, `tests/test_ingest.py`, and `scripts/smoke_ingest.py`.

**Interfaces:** `extract_pages(pdf_bytes: bytes, filename: str) -> list[Page]`; `chunk_pages(pages: list[Page], document_id: str, index_config_id: str) -> list[Chunk]`. `Page` carries one-based physical page number/text; `Chunk` carries deterministic ID, document/configuration identities, filename, page, and exact passage text.

- [x] Test rejection of oversize, unreadable, encrypted (including owner-encrypted files with an empty user password), and over-200-page inputs; do not trust filename extensions. `read_pdf_bytes()` bounds file reads to limit + 1. Whole multipart request-body enforcement remains in Phase 6 because no upload route exists yet.
- [x] Test blank-page preservation: a synthetic three-page PDF produces chunks on physical pages 1 and 3. Blank Page records retain warnings; all-empty extraction fails with an explicit OCR limitation.
- [x] Implement byte hashing, hash-derived storage names, page extraction, whitespace cleanup, and warnings for low/empty text, replacement characters, and numbered-table mentions. Storage names are available as metadata; actual persistence belongs to Phase 2.
- [x] Test deterministic UUID5 chunk IDs, maximum token budgets, page boundaries, progression, and trailing-text coverage. Source slices retain Unicode, including decomposed accents ignored by tokenizer normalization.
- [x] Implement paragraph-aware chunking with the 300/60 starting settings. Retain extracted headings/table text; numbered-table mentions explicitly request manual column-order inspection instead of claiming table reconstruction.

**Verified Phase 1 evidence (2026-10-27):** full offline suite 40 passed (23 ingestion cases plus 17 existing cases); Ruff passed. All 144 corpus pages passed pinned-tokenizer checks: AI RMF 143 chunks, GenAI Profile 213, CSF 97, total 453. Assertions checked source hashes, physical pages, exact normalized-text slices, all non-whitespace text coverage, unique IDs, and token budgets. Maximum embedding input was 302 tokens including specials; maximum reranker pair for the sample question was 312, below 512. Future arbitrary questions still require their own pair-length check in Phase 3. `scripts/smoke_ingest.py` uses cached tokenizers only, without Groq calls or model downloads.

**Visual inspection:** compared AI RMF physical page 6 (Executive Summary) and page 27 (GOVERN table; printed page 22) against rendered PDF pages. Narrative content/reading order matched. Table text survived, but column relationships interleave; the page now carries a layout-review warning. This heuristic only detects numbered-table mentions, not every complex layout. Printed page labels differ from physical citation numbers. Line-wrap hyphens remain as extracted; neither OCR nor reliable table interpretation is claimed.

**Review:** a fresh reviewer found decomposed combining accents could be dropped at source-range edges. Four regressions reproduced the issue before the fix; source ranges now cover tokenizer-ignored characters and non-tokenizable nonempty pages fail explicitly. The full suite and corpus checks passed after correction. No other Phase 1 defects were reported. HTTP upload protection and indexing remain later-phase work; Phase 1 makes no generation, retrieval-quality, or production-hostile-file-safety claim.

**Gate:** manually compare extracted passages against the original PDFs, including a multi-column or table-heavy page. If extraction is wrong, fix or flag it before indexing; retrieval cannot recover missing evidence.

## Phase 2 — persist a filtered Qdrant index (Day 1, 1.5h)
**Files:** `app/retrieval.py`, ingestion entry point in `app/ingest.py`, records in `app/schemas.py`, `tests/test_index.py`, and `scripts/smoke_index.py`.

**Interfaces:** `ingest_pdf(pdf_bytes: bytes, filename: str) -> DocumentRecord`; `list_documents() -> list[DocumentRecord]`; `search(question: str, document_ids: list[str], limit: int = 20) -> list[Passage]`. Records include document ID/hash, filename, page count, chunk count, and warnings.

- [x] Test `test_repeat_ingestion_is_idempotent`, `test_failed_ingestion_not_listed`, and `test_unselected_document_excluded` with stubs, plus one explicit local-Qdrant integration check.
- [x] Create the collection with the dimension of the loaded embedding model; fail with a clear error if an existing collection has a different dimension.
- [x] Serialize ingestion. If the document hash is already in `documents.json`, return the existing record. Otherwise delete leftover points for that document/configuration, upsert chunks with deterministic IDs, then atomically add the record to `documents.json`. On failure, attempt point/PDF cleanup and return the error; the document stays unready even if storage is unavailable during cleanup.
- [x] Search only document IDs present in `documents.json`, with document and active-configuration filters applied inside Qdrant. Never search all documents when the selection is missing or invalid. Passage metadata survives conversion into typed evidence.

**Verified Phase 2 evidence (2026-10-27):** 63 offline tests passed (22 index cases plus the 41-case baseline); Ruff passed and the backend image built successfully. Index cases cover named gates, partial upsert and atomic registry-replacement failures, physical page/offset provenance, config filtering, incompatible dimensions/distance, missing/corrupt/duplicate registries, query token limits, document limits, bad vectors, and concurrent use. A cold-start regression first failed with eight index/model instances; locked singleton construction now creates one.

The real `scripts/smoke_index.py` check used pinned BGE CPU weights and Qdrant 1.15.5: three NIST PDFs, 144 physical pages, 453 unique 384-dimensional vectors (143/213/97 chunks). Re-ingestion preserved point counts and records. Searches restricted to each selected document, plus a multi-document selection, returned only allowed metadata. An intentional server upsert followed by a simulated exception removed the partial document's points/PDF and preserved all ready documents. No Groq requests or answer grading occurred.

Qdrant was restarted and the rebuilt backend recreated. A separate `--verify-only` container reloaded the ready registry, checked stored PDF hashes and unchanged vector counts, and repeated filtered searches successfully without ingestion. Configuration ID: `799563acd1ba4ff04d7276495a82f003175dccdc7f6147a25fe00cb001ce2e8d`. Cached model/corpus mounts were read-only; PDFs, registry, vectors, and model artifacts stay outside Git.

**Post-audit fixes (2026-10-27, branch `fix/chunk-boundaries`):** chunk ends and overlap starts snap to word boundaries; oversized individual words can still be split to preserve coverage. Dehyphenation joins only spellings confirmed elsewhere in the document and preserves ambiguous/compound hyphens with page warnings. This avoids inventing spellings such as `longterm` or `costeffective`. Offline corpus check: 450 chunks (140/213/97), zero mid-word starts/ends, full source coverage and token budgets checked; 73 offline tests pass. Schema 2 rejects the earlier index. `scripts/reset_index.py` checks Qdrant connectivity and resolved paths before destructive work, refuses roots/redirected paths, and removes readiness first. Four additional regressions reproduced and now prevent compound corruption, local deletion during connection failure, unsafe redirected paths, and filesystem-root resets.

**Refreshed runtime evidence:** the audited image built successfully. Real BGE/Qdrant checks produced 450 unique 384-dimensional vectors in isolated collection `pdf_rag_audit_v2`, with data at `/data/audit-v2-verification`. Repeat ingestion, document filtering and intentional partial-write cleanup passed. After Qdrant restart and backend recreation, a separate `--verify-only` run preserved all ready records, PDF hashes, counts and filtered results without ingestion. Configuration ID: `c7643ed7f1b199c22ffffaa245db45976cebfd66d76f7b6a990427b853e42cb3`. The reset CLI separately refused absent confirmation, deleted only owned probe targets, preserved an unrelated file, and supported repeat reset. The original schema-1 `pdf_rag` collection retained 453 points and was not reset; using it with the new schema requires an explicit rebuild. No Groq requests were made.

**Review and limits:** the original Phase 2 fresh source review found no substantiated issues; subsequent audit changes and refreshed runtime evidence are recorded above. The reviewer did not independently rerun runtime checks. One cached index and one writer process are supported; cross-process writes, power-loss durability, complete corruption/orphan reconciliation, and sustained-load performance are not claimed. Retrieval relevance/reranking, citations, uploads, UI, CI, and final evaluation remain later phases. Commands are recorded in the root README. The original checkpoint was created on `codex/phase-2-index`; the user subsequently authorized merging and publishing Phase 2 with the audit fixes to `main`.

**Gate:** repeat ingestion creates no duplicate chunks; restart preserves ready documents; a simulated failed ingestion is not listed; selected-document search cannot return another document.

## Phase 3 — retrieve and rerank useful evidence (Day 1, 1h)
**Files:** `app/retrieval.py`, `tests/test_retrieval.py`.

**Interfaces:** `retrieve(question: str, document_ids: list[str]) -> list[Passage]` consumes ready document IDs and returns at most five reranked passages with scores/provenance. It composes Phase 2 `search` and local `CrossEncoder` scoring.

- [ ] Test descending reranker ordering, preservation of source IDs/page numbers, empty results, and rejection of overlong query/passage pairs under the actual tokenizers.
- [ ] Retrieve up to 20 filtered dense candidates, rerank in a batch, and retain up to 5. Load models once; use their documented query formatting. Record candidate and final page IDs for evaluation.
- [ ] Inspect overlapping hits; remove exact duplicate passages without adding an elaborate diversity algorithm. Do not treat raw reranker scores as probabilities.
- [ ] Inspect evidence for a few separate development questions. Introduce an evidence cutoff only if development data supports it; record that choice and its false-refusal trade-off.

**Gate:** a known answer page reaches the candidate set and final context for representative development questions. Diagnose extraction versus retrieval versus ranking before changing models.

## Phase 4 — freeze useful evaluation labels (Day 1, 1.5h)
**Files:** `eval/dev.jsonl`, `eval/questions.jsonl`, dataset schema checks in `tests/test_eval.py`.

**Interface:** each row contains `id`, `question`, `document_ids`, `answerable`, `expected_pages`, `reference_answer`, and `category`. `expected_pages` identifies document/page pairs; unanswerable rows use an empty list and explain the expected refusal in `reference_answer`.

- [ ] Prepare roughly 5 separate development questions; do not count them toward the final 20.
- [ ] Label at least 14 answerable final questions: direct facts, paraphrases, exact names/numbers, and questions requiring multiple passages where the corpus actually supports them.
- [ ] Label at least 6 unanswerable questions: absent facts, misleading premises, unsupported comparisons, and questions answerable only from unselected documents (for example, a Cybersecurity Framework question asked with only the two AI documents selected). Ensure they truly lack evidence in the selected corpus.
- [ ] Record source hashes and expected physical PDF pages before seeing final outputs. Validate unique IDs, valid document/page references, and required fields.
- [ ] Freeze final labels; tune on development questions only. If final results influence a fix, disclose reuse and label reruns as such.

**Gate:** every answerable reference can be justified from the selected PDF pages; no final question depends on external facts. A second human review is useful if available, but do not invent reviewer approval.

## Phase 5 — generate cited answers with bounded free-quota use (Day 2, 1.5h)
**Files:** `app/answer.py`, `app/schemas.py`, `tests/test_answer.py`.

**Interfaces:** `answer_question(question: str, document_ids: list[str]) -> ChatResponse`; `ChatResponse` has `answer`, `abstained`, and `sources`. Typed operational errors carry a stable code and optional `retry_after_seconds`; internal diagnostics retain usage, latency, and model/config identity for evaluation without returning secrets.

- [ ] Test no evidence yields local abstention and zero provider calls; valid source IDs resolve to exact supplied passages. Reject invented IDs, unparseable JSON, contradictory abstention/source fields, and factual answers without citations.
- [ ] Pack evidence within the approximate 2,000-total-input-token target, accounting for instructions/question/source metadata and generation-tokenizer differences. Reduce whole passages first; do not silently truncate the question. Set the initial 300-output-token cap and inspect the selected model's reasoning behavior.
- [ ] Construct a prompt that treats PDF text as untrusted evidence, requires abstention/partial-answer disclosure, and uses request-local citation IDs. Test that an injected passage remains inside the evidence block; this does not prove complete prompt-injection resistance.
- [ ] Make one generation call with the official Groq SDK and automatic retries disabled. Validate output locally; do not call again to repair malformed answers. Use no action tools.
- [ ] Implement the bounded 429 policy from [TECHspec.md](TECHspec.md). Test with a stub that a 429 becomes a structured rate-limit error (never an abstention) and that invalid credentials are not retried. No alternative provider/model path exists.

**Gate:** development questions produce inspectable citations or explicit abstentions; quota/network failures remain distinct operational errors. A citation-ID check is not a semantic faithfulness guarantee.

## Phase 6 — expose the complete flow through API and UI (Day 2, 1h)
**Files:** `app/api.py`, `ui.py`, `tests/test_api.py`.

**Interfaces:** `GET /health`; `POST /documents` (one bounded multipart PDF); `GET /documents`; `POST /chat` with `{question, document_ids}` returning Phase 5 `ChatResponse`. Map invalid input to 4xx, upstream rate limiting to 429, and dependency failures to explicit 5xx errors with sanitized bodies.

- [ ] Test upload limits before unbounded reads, empty/unknown selections, excessive document count, question character/token limits, and stable errors with FastAPI's test client plus dependency stubs.
- [ ] Connect endpoints directly to the tested services. Keep synchronous model work off the event loop using synchronous route functions or the framework's thread-pool support; serialize generation and ingestion for the single-user demo.
- [ ] Build Streamlit controls for upload/status, ready-document selection, question submission, answer/abstention, and expandable source excerpts with filenames/pages.
- [ ] UI sends no Groq key and invokes no model itself. Prevent accidental duplicate submission on Streamlit reruns; show rate-limit versus quota-exhaustion guidance only when the backend can distinguish them.
- [ ] Manually smoke-test upload → select → ask → inspect sources → unsupported question → simulated quota failure.

**Gate:** the full user flow works through Streamlit; restarting the backend does not erase the ready-document list. Preserve usable error messages and labels; UI polish is optional.

## Phase 7 — verify Docker and credential-free CI (Day 2, 1h)
**Files:** complete `Dockerfile`, `compose.yaml`, `.dockerignore`, `.github/workflows/ci.yml`.

- [ ] Finish the shared application image with separate FastAPI and Streamlit commands. Do not bake credentials or uploaded PDFs into image layers; pass Groq environment variables to the backend service only.
- [ ] Configure backend-to-Qdrant and UI-to-backend service names, health checks/readiness, named volumes, and localhost published ports. Keep Qdrant internal in the final Compose configuration.
- [ ] Run `docker compose config`, then `docker compose up --build`; verify both API readiness and UI flow after startup, and data persistence after restart. Confirm the model cache survives container recreation and explain first-run downloads.
- [ ] CI installs locked dependencies and runs `uv run ruff check .` and `uv run pytest -m "not integration" -q`. Register the integration marker; default CI has no key, no model downloads, and no paid requests.
- [ ] Inspect build context and tracked files for `.env`, PDFs, vectors, or caches before packaging/publication.

**Gate:** a clean local container build starts the complete application; lint/offline tests pass. Claim GitHub Actions success only after an actual remote run, not from a workflow file's existence.

## Phase 8 — run evaluation and write the required report (Day 2, 2.5h)
**Files:** `eval/run.py`, `eval/report.md`, `tests/test_eval.py`; saved run artifacts in an explicitly ignored directory unless reviewed and safe to publish.

**Interface:** `uv run python -m eval.run --dataset eval/questions.jsonl --output <run-directory> --resume`. Runner calls the same backend pipeline with diagnostics, not a separately reimplemented RAG system. Save a manifest with document hashes, dataset hash, model/config identity, limit snapshot, and timestamps.

- [ ] Write one JSONL record per question as it finishes, including errors. `--resume` skips question IDs that already have an answer or abstention and reruns the rest. Test this with stubs. Do not resume after changing the model or settings; start a new run directory instead.
- [ ] Freeze settings; check remaining quotas; run all final questions sequentially. Pace against applicable request/token windows and response headers; use a conservative allowance for in-flight output/reasoning. Pause if reset is unavailable or daily budget is insufficient.
- [ ] Manually mark correctness, grounding, citation support, and refusal behavior. No LLM grader calls. Record actual usage when available; mark missing usage unknown rather than zero.
- [ ] Compute retrieval evidence-page recall for answerable questions at candidate and final-context stages: expected pages retrieved divided by expected pages, averaged across answerable rows; disclose labeling limitations. Report answer-level supported correctness, claim/citation support judgments, refusal counts, false refusals, and operational failures separately.
- [ ] Report median/p95 latency with the sample size and calculation method. Separate service latency from quota waiting; with only 20 questions, p95 is unstable and not a load benchmark.
- [ ] Write `eval/report.md`: corpus/method, frozen configuration, raw numerator/denominator metrics, actual tokens, case-by-case failures, root-cause stage, attempted/completed counts, and limitations. Never exclude quota errors silently or count them as correct refusals.
- [ ] Discuss English/document-selection bias, scanned/table extraction gaps, privacy/external transmission, prompt injection, misleading citations, and inappropriate reliance for consequential decisions. Include mitigations and residual risks.

**Gate:** at least 20 completed labeled questions, with targets of at least 12/14 answerable correct and grounded, at least 5/6 unanswerable correctly refused, and zero invalid citation references. For larger sets, report subgroup rates and counts. If a target fails or quotas interrupt the run, publish the honest incomplete/failing outcome and prioritized fixes, not a passing claim.

## Phase 9 — repository delivery and optional video (Day 2, 1h)
**Files:** update root `README.md` and the populated `docs/` files from measured reality, and keep `docs/Design.md` empty.

- [ ] Replace planned-only setup text in `README.md` with commands verified from a fresh checkout/container build: fetching the corpus, environment variables (including that reviewers need their own free Groq key), first-run downloads, hardware observations, quota handling, evaluation reproduction, limitations, and license choices. Verify how GitHub renders it.
- [ ] Inspect tracked files and commit history for credentials/private PDFs; if a secret was committed, rotate it and remove it safely before publication. Confirm remote, account, repository visibility, and publication authorization before creating/pushing externally.
- [ ] Publish the repository when the destination and authorization are established. Verify the remote README, workflow result, Docker instructions, and evaluation report links. Record the actual repository URL only after creation.
- [ ] Optional video: about 20 seconds on scope, 40 seconds on upload/setup, 60 seconds on a cited answer/source inspection, 25 seconds on abstention, and 35 seconds on evaluation and limitations. Hide credentials and private text.

**Gate:** a reviewer can find the setup, run the Dockerized application, inspect the evaluation report, and understand limitations without reading chat history. Public deployment is not required when the Dockerized deliverable is provided.

## Release checklist and stopping rules
- [ ] Repository structure and verified setup are clear; publication destination is correct.
- [ ] Dockerized FastAPI, Streamlit, and local Qdrant run with persistent data.
- [ ] Page provenance, document filters, idempotence, and failed-ingestion exclusion pass checks.
- [ ] `scripts/fetch_corpus.py` reproduces the corpus with matching hashes.
- [ ] Local embedding/reranker context limits and generation budgets are respected.
- [ ] Grounded answer, source inspection, abstention, and quota-error flows are demonstrated.
- [ ] Offline tests/lint pass; actual remote CI status is recorded.
- [ ] At least 20 evaluation questions completed and honestly reported, including unmet targets if any.
- [ ] Error analysis, failure examples, bias/ethical risks, token usage, and quota limitations are published safely.
- [ ] `Design.md` remains empty; no credentials/private documents are tracked or baked into images.
- [ ] Optional video complete only after mandatory work.

## Stretch goals (only after the release checklist passes)
Removed from the core build to fit two days. Each one is useful but not required by the brief.
- Crash-safe indexing with per-document status records (indexing/failed/ready) stored in Qdrant, and a restart test after a mid-ingestion crash.
- A full indexing manifest (model revisions, tokenizer, chunk settings, parser version) that refuses to reuse a collection built under different settings.
- Retry-policy tests with a mock clock: at most three attempts, `Retry-After` honored, 30-second total wait cap.
- An evaluation runner that detects a changed dataset, model, or settings and refuses to resume.
- A retrieval ablation in the report: page recall with dense search alone versus dense search plus reranking. This needs no Groq calls.

If time slips, reduce corpus size and UI polish; defer the optional video and public hosting. Keep validation, citation checks, abstention, local reranking, Docker reproducibility, and the minimum evaluation set. If a required gate fails, label the release an incomplete prototype and state the blocker. Only checked milestones and their recorded evidence establish completed implementation.
