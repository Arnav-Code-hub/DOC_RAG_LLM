# Product requirements

Status: planned MVP; documentation created 2026-10-27. No application, evaluation results, or deployment is claimed complete.

## Objective
Build a PDF document question-answering demo in two working days. Users select indexed documents, ask a question, receive an evidence-grounded answer with document/page citations, or receive an explicit abstention when evidence is insufficient.

## Scope
- Local, single-user demo with a small fixed corpus of text-based, primarily English PDFs.
- Parse pages with PyMuPDF; create overlapping chunks; embed with a sentence-transformers-compatible model; persist vectors and provenance in Qdrant.
- Run extraction, embeddings, reranking, and Qdrant locally; use Groq Free only for final answer generation with bounded evidence.
- FastAPI backend and Streamlit interface with ingestion status, document selection, answers, and source excerpts.
- At least 20 labeled evaluation questions, Python tests, and GitHub Actions CI.
- Deliver a GitHub repository with reproducible setup and clear README, a Docker Compose demo, and `eval/report.md` with metrics, error analysis, failure cases, and bias/ethical risks. A three-minute video is optional.

## Corpus
Three NIST policy/framework publications, downloaded from official sources. The NIST Technical Series reuse policy permits reuse subject to its terms, attribution, and any third-party rights; do not assume every embedded item is unrestricted merely because a document is government-published. Notice pages and the [NIST policy](https://www.nist.gov/open/license) were reviewed in Phase 0; source details are retained in `corpus/manifest.json` and `corpus/README.md`.

| ID | Document | Source URL |
|---|---|---|
| `nist-ai-rmf` | NIST AI 100-1, AI Risk Management Framework 1.0 | https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf |
| `nist-genai-profile` | NIST AI 600-1, Generative AI Profile | https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf |
| `nist-csf-2` | NIST CSWP 29, Cybersecurity Framework 2.0 | https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf |

All three URLs returned `application/pdf` when checked on 2026-10-27. PDFs are not committed. `scripts/fetch_corpus.py` downloads them and checks them against the SHA-256 hashes in `corpus/manifest.json`. In Phase 0, record those hashes and the actual page counts, and read each document's notice page to confirm the reuse terms. The two AI documents overlap in topic, which gives realistic cross-document distractors. Cybersecurity Framework 2.0 can supply "answerable only from an unselected document" test cases.

Non-goals: OCR, reliable table/figure interpretation, public hosting, authentication, multiple tenants, agents, query decomposition, and fine-tuning. Scanned or unusable PDFs must produce a clear unsupported-input warning.

## User requirements
1. Ingest valid PDFs and see which documents succeeded or failed.
2. Ask questions only against explicitly selected, successfully indexed documents.
3. Inspect filename, one-based PDF page number, and passage text behind each citation.
4. Receive a clear abstention for unsupported questions; partial answers identify missing information.
5. See actionable upload, indexing, model, and network errors without stack traces or secrets.
6. See rate-limit/quota errors with retry guidance; never trigger a paid fallback or plan upgrade.

## Acceptance criteria — targets, not measured results
- Re-ingesting an unchanged PDF creates no duplicate chunks, and a failed ingestion never appears as a selectable document.
- Every chunk retains document identity, content hash, page number, chunk ID, text, and indexing configuration identity. Chunks stay within one page.
- Out-of-scope documents never appear in retrieval or citations for a selected-document query.
- Every substantive answer claim has supporting citations; every citation resolves to supplied evidence. Citation existence alone does not prove support: inspect support manually.
- Run at least 20 questions: at least 14 answerable and 6 unanswerable. Label expected source pages or expected abstention before running the final evaluation.
- Release target: at least 12/14 answerable questions correct and grounded, at least 5/6 unanswerable questions correctly refused, and no invalid citation references. If the dataset grows, report counts and rates separately for each group.
- Report retrieval page recall at candidate and final-context stages, answer correctness, citation support, abstention outcomes, and latency. Publish actual failures; targets do not become results by declaration.
- Python tests and CI pass; a fresh local setup and end-to-end demonstration are recorded.
- Verify local Compose startup, persistent storage, and secret-free configuration. Publish actual repository/setup evidence; public hosting is optional because the Dockerized app satisfies the demo requirement.
- A stubbed 429 response surfaces as a rate-limit error, never as an abstention; no paid/model fallback is possible. Final evaluation runs sequentially with manual grading and records token usage, interruptions, and completed/attempted counts separately.

## Constraints and risks
Two days assumes readable PDFs, available model downloads, a usable LLM endpoint, and adequate local hardware. Model choice and latency require a setup-time smoke test. Poor extraction, silent model truncation, and evidence-free answers are release blockers. External LLM use requires permission to send the selected document excerpts to that provider.

The API-cost target is zero on a confirmed Groq Free account, not a guarantee of unlimited availability. Select the generation model and pacing against actual account limits. Budget roughly 40,000 input tokens plus output for one 20-question run; development/retries/reasoning may add usage. If quota is exhausted, pause and record the incomplete run rather than bypass limits or change billing plans.

## Milestones
- Day 1: working page extraction, deterministic indexing, filtered retrieval, and saved evidence inspection.
- Day 2: reranking, grounded generation, Streamlit integration, evaluation, tests, CI, and reproducible demo instructions.

See [implementation.md](implementation.md) for timeboxes, completion gates, and the stretch items deferred from the core build.
