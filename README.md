# PDF Document RAG Chatbot

Repository: [Arnav-Code-hub/DOC_RAG_LLM](https://github.com/Arnav-Code-hub/DOC_RAG_LLM).

A prototype for asking questions about a selected set of PDFs and receiving evidence-grounded answers with document/page citations. When the documents cannot support an answer, the chatbot should say so.

**Current status:** Phases 0–2 are complete: local setup, extraction/chunking, persistent Qdrant indexing, and document-filtered dense search are verified. Document-chat endpoints, reranking, UI, CI, and answer-quality evaluation remain pending.

## Planned capabilities
- Extract text page by page with PyMuPDF and retain physical PDF page numbers.
- Start with 300-token chunks and 60-token overlap, checked against both local models' tokenizers; this replaces the original larger-chunk proposal.
- Embed with sentence-transformers and store vectors plus source metadata in Qdrant.
- Retrieve 20 candidates locally, rerank to up to 5, and use Groq Free only for final answer generation from bounded evidence.
- Show answers, source excerpts, and explicit abstentions in Streamlit through a FastAPI backend.
- Evaluate at least 20 labeled questions, including at least 6 unanswerable questions.
- Run Python tests and lint checks in GitHub Actions.
- Package backend, UI, and Qdrant with Docker Compose and publish an evaluation report covering errors and ethical risks.

## Intended use
Local, single-user exploration of a small corpus of text-based, primarily English PDFs such as syllabi, policy documents, or research papers. The evaluation corpus is three public-domain NIST publications: the AI Risk Management Framework (AI 100-1), the Generative AI Profile (AI 600-1), and the Cybersecurity Framework 2.0 (CSWP 29). `scripts/fetch_corpus.py` downloads them and verifies pinned hashes; see [docs/PRD.md](docs/PRD.md#corpus). OCR, reliable table/figure interpretation, public hosting, and multi-user access are outside the initial scope. External LLM use may send selected excerpts to the configured provider; confirm document permissions first.

## Planned stack
Python 3.11, PyMuPDF, sentence-transformers (`BAAI/bge-small-en-v1.5` embeddings and `cross-encoder/ms-marco-MiniLM-L6-v2` reranking), local Qdrant, Groq's official Python SDK, FastAPI, Streamlit, Docker Compose, `uv`/lockfile, pytest, Ruff, and GitHub Actions. Local models are pinned and CPU smoke-tested; retrieval/answer quality is unmeasured. See [docs/TECHspec.md](docs/TECHspec.md) for compatibility checks and configuration.

## Groq Free usage plan
Extraction, embeddings, reranking, and vector storage stay on your laptop. Only the final question, instructions, and selected passages go to Groq. Configure backend-only `GROQ_API_KEY` and a `GROQ_MODEL` selected after checking current availability and your Free-account limits. No exact generation model or quota is promised permanently.

Use at most one successful generation request per question, approximately 2,000 total input tokens, and an initial 300-output-token cap. No-evidence queries can abstain without a request. Twenty generated answers imply approximately 40,000 input tokens plus up to 6,000 output tokens before retries, reasoning overhead, development, and repeat runs. These are estimates, not measured consumption.

Run evaluation sequentially with request/token-aware pacing and manual grading. Honor bounded 429 retry handling; display temporary rate limiting or confirmed quota exhaustion with reset guidance. Save progress and resume after quota resets. Never switch to a paid provider/model or upgrade the account automatically; confirm the account remains on Free. Consult [Groq rate limits](https://console.groq.com/docs/rate-limits) and [billing FAQ](https://console.groq.com/docs/billing-faqs), checked 2026-10-27.

Verified setup snapshot (2026-10-27): the supplied billing screenshot shows **Free, $0, Current Plan**. For configured model `openai/gpt-oss-120b`, the organization screenshot shows 30 requests/minute, 1,000/day, 8,000 tokens/minute, and 200,000/day. A single successful 300-token-capped request consumed 78 prompt + 33 completion = 111 tokens, with 23 reasoning tokens included in the completion count. Response headers confirmed the requests/day and tokens/minute limits. Recheck project overrides, shared usage, and current limits before evaluation; this smoke check establishes access, not answer quality.

## Documentation
- [docs/PRD.md](docs/PRD.md): goals, scope, corpus, acceptance criteria, and risks.
- [docs/TECHspec.md](docs/TECHspec.md): stack, index contract, APIs, and model constraints.
- [docs/workflow.md](docs/workflow.md): ingestion, answers, failures, and evaluation flow.
- [docs/Design.md](docs/Design.md): intentionally empty, reserved for later.
- [docs/implementation.md](docs/implementation.md): milestones, checks, stretch goals, and release evidence.
- [docs/research.md](docs/research.md): hypotheses and explicitly unverified research claims.
- [docs/rules.md](docs/rules.md): engineering and evidence standards.

## Setup and evaluation
Phase 0 developer setup (run from the project root with Python 3.11 and `uv` installed):

```powershell
uv sync --frozen
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv run python -m scripts.fetch_corpus
uv run pytest -q
uv run ruff check .
uv run python -m scripts.smoke_models
uv run python -m scripts.smoke_ingest
```

The corpus fetch verifies pinned hashes and physical page counts. The model smoke command explicitly downloads pinned models and runs assertions; it makes no Groq calls. In this Windows session, the Python executable's outbound sockets were denied, so the corpus/model snapshots were fetched through Windows HTTPS and Python model inference was verified offline. This is an environment limitation, not a completed live-download check. On a similarly restricted machine, use an approved network/runtime or prepopulate the cache rather than disabling TLS verification.

The ingestion smoke uses cached tokenizers and verifies all three PDFs without network/API requests. Current checks: 63 offline tests pass; 144 corpus pages yield 453 chunks with source coverage and token budgets checked. These are implementation checks, not answer-accuracy results. Complex table layouts still require inspection, and scanned PDFs need OCR outside the MVP. Full multipart upload limits will be enforced when the API upload route is implemented in Phase 6.

For the local uv bootstrap used in this workspace, `.tools/bin/uv.exe` and project-local Python under `.runtime/python/` are ignored setup artifacts, not committed dependencies. The checked-in `uv.lock` is the reproducible dependency specification. Offline tests use synthetic PDFs and stubs, without model downloads or Groq credentials. If Windows restricts its default temporary folder, pass a fresh project-local `--basetemp .cache/pytest-local` to pytest.

Create your own Groq Free account, save its key and an available model ID in the ignored `.env`, and set `GROQ_FREE_CONFIRMED=true` only after confirming the plan. Then explicitly run `uv run python -m scripts.smoke_groq` for one capped request with SDK retries disabled. The workspace's request passed on 2026-10-27; rerunning the command consumes quota. The script prints usage and allowlisted rate-limit headers without the key or answer text. The flag records confirmation outside the API; it cannot independently inspect account billing.

Initial container commands are `docker compose build backend` and `docker compose up -d`. The skeleton currently includes Qdrant and the health-only backend; there is no Streamlit UI/chat endpoint yet. Visit `http://localhost:8000/health` after startup. Its generation field reports configuration only, not verified Groq access or full application readiness.

On a network with a private TLS issuer, supply an already trusted CA bundle as a build secret: `docker build --secret id=build_ca,src=<trusted-ca-bundle.pem> -t gdgragchatbot-backend .`. The optional secret is used for dependency installation only and is not copied into the image. Keep local trust bundles ignored; never disable certificate verification. Full container verification is recorded in the Phase 0 checklist in [docs/implementation.md](docs/implementation.md#phase-0--prove-prerequisites-and-establish-the-runnable-skeleton-day-1-1h).

The successful Groq check on this restricted network used the container runtime with a read-only trusted bundle: `docker compose run --rm --no-deps -v "<absolute-CA-bundle-path>:/trusted-ca.pem:ro" -e SSL_CERT_FILE=/trusted-ca.pem backend /app/.venv/bin/python -m scripts.smoke_groq`. This runtime mount is separate from the build secret and is needed here for outbound TLS. The running health-only service has not been configured for generation traffic yet.

Target complete-demo workflow: fetch the corpus, configure backend-only Groq environment variables (each reviewer needs their own Free key), then `docker compose up --build`. The full PDF/chat/UI flow remains planned. Model downloads and internet access for Groq are required; the finished demo will not be an offline app.

## Local index
Phase 2 exposes Python entry points `app.ingest.ingest_pdf`, `app.retrieval.list_documents`, and `app.retrieval.search`. The shared `DocumentIndex` loads the embedding model once, serializes ingestion, stores original PDFs under hash-derived names, and atomically publishes `documents.json` after vector writes. Repeating the same bytes returns the existing record. Runtime document IDs are full SHA-256 hashes; corpus manifest IDs are readable aliases.

Search requires explicitly selected ready document IDs and applies document/configuration filters inside Qdrant. It preserves passage text, offsets, physical pages, and dense scores. Missing/unknown selections fail; incompatible vector dimensions, distance, changed indexing settings, and stale/corrupt ready registries fail explicitly. Changing models/chunk settings requires rebuilding the collection and ready registry together. Dense scores are not answer-confidence probabilities.

`uv run python -m scripts.smoke_index` is an explicit integration check requiring a reachable Qdrant service, the downloaded corpus, and cached/downloadable embedding weights. It checks actual embeddings, duplicate ingestion, selected-document filtering, and a deliberately failed vector write; it makes no Groq requests. Run again with `--verify-only` after restart to check persisted records and vectors without ingestion. The local Compose service keeps Qdrant internal, so run this smoke inside the backend container. Multiple writer processes and crash reconciliation are outside the current single-process contract.

Verified PowerShell commands after the earlier corpus/model setup and backend build:

```powershell
docker compose up -d --wait --wait-timeout 45 backend
$modelMount = (Join-Path (Get-Location).Path '.cache/huggingface') + ':/models:ro'
$corpusMount = (Join-Path (Get-Location).Path 'corpus/pdfs') + ':/app/corpus/pdfs:ro'
docker compose run --rm --no-deps -v $modelMount -v $corpusMount -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e OMP_NUM_THREADS=2 -e MKL_NUM_THREADS=2 backend /app/.venv/bin/python -m scripts.smoke_index
```

These commands mount the cached weights and source corpus read-only; application data and vectors persist on Compose volumes. To repeat the persistence check, restart Qdrant with `docker compose restart qdrant`, run the `up --wait` command above, then append `--verify-only` to the smoke command. On 2026-10-27, all three PDFs produced 453 unique 384-dimensional vectors (143/213/97 chunks), and ready records, original PDF hashes, vector counts, and filtered searches passed after restart. A fresh source review reported no findings. This is index verification, not a retrieval-quality or answer-accuracy result.

No evaluation has run. Planned release targets include at least 12/14 answerable questions correct and grounded, at least 5/6 unanswerable questions refused, and zero invalid citation references. Publish actual counts, latency, source-support judgments, and failures before claiming accuracy.

The repository is published at the link above. The complete Dockerized FastAPI/Streamlit/Qdrant demo and `eval/report.md` remain pending; the report will cover metrics, error analysis, failure examples, token usage, quota interruptions, and bias/ethical risks. A three-minute video is optional.

## Repository layout
This `README.md` is the landing page, and specifications live in `docs/`. `app/ingest.py` exposes ingestion; `app/retrieval.py` owns the persistent index and filtered dense search. Typed records live in `app/schemas.py`; `scripts/` contains explicit corpus/model/ingestion/index smoke checks. Reranking, answers, UI, and evaluation data/report remain pending. `docs/Design.md` remains empty.

Project licensing has not been selected. Verify document, library, and model licenses before redistribution.
