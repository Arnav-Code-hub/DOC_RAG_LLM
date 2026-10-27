# Research notes and evidence status

Status: research backlog, not a verified literature review. Paper claims from the supplied conversation remain unverified. Groq operational documentation was checked on 2026-10-27. Phases 0–1 verified local model smoke behavior, account access, dated Free-plan/quota evidence, and one capped generation request; see [implementation.md](implementation.md). Full application performance and answer-quality evaluation remain unmeasured.

## What the conversation actually supports
The project brief requires PDF ingestion, embeddings/vector retrieval, cited answers, and at least 20 evaluation questions including unanswerable ones. The chosen MVP adds page-aware extraction, cross-encoder reranking, and explicit abstention. These are implementation hypotheses to evaluate on the selected corpus, not proof of high accuracy.

The earlier assistant mentioned these 2026 studies without recoverable titles, authors, DOI/arXiv identifiers, or usable paper URLs in the supplied preview:
- A September regulatory-document study allegedly comparing 3 parsers, 3 chunkers, and 5 embedding models across 800 questions.
- A policy-document study allegedly reporting faithfulness of 0.347, 0.621, and 0.797 for successive systems.
- A September scientific-QA study allegedly favoring reranking and late-interaction retrieval.
- A page-aware PDF study allegedly comparing BM25, hybrid retrieval, reranking, and decomposition.

All four are **unverified and currently unidentifiable from the supplied material**. Do not cite them as established papers, repeat their numbers as evidence, or invent titles/links. The cached preview contains broken citation placeholders, not usable references. There are no identifiable paper links to preserve from that preview.

## Verification procedure
For each candidate paper, obtain its exact title, authors, publication date, and primary publisher/arXiv URL. Read its methods and limitations, record dataset/domain, baselines, evaluation definition, hardware, cost, and code availability. Confirm that a 2026 date refers to the relevant publication/version. Reject comparisons whose metrics or corpora differ. Record verified citations here only after this work is done.

## Engineering hypotheses to test
- Extraction quality and correct page provenance are prerequisites; retrieval cannot recover missing text.
- Initial chunk target: 300 tokens, overlap 60, bounded to pages, replacing the earlier 600/100 proposal for the smaller local embedding/reranker models. Tune with development questions, not asserted universal optima.
- Retrieve 20 and rerank to at most 5. Compare candidate-page recall with final-context recall to detect whether reranking loses necessary evidence.
- A stronger reranker can improve ordering but adds latency and cannot retrieve a passage absent from the candidate set.
- Score thresholds need corpus-specific tuning. Citation validation detects unknown IDs; human review must determine whether sources support claims.
- Unsupported, ambiguous, misleading, and conflicting-evidence questions expose failures that answerable questions alone miss.

## Minimal experiments
1. Inspect extracted text and page metadata on representative normal, blank, multi-column, and table-heavy pages.
2. On development questions, compare dense retrieval alone with dense retrieval plus reranking using the same candidate pool.
3. Inspect candidate and final page recall, grounded correctness, abstention, median and p95 latency, and model/provider costs where available.
4. Freeze one configuration, then run the separate final evaluation with at least 20 questions. With such a small sample, report raw counts and failures alongside rates; do not claim broad benchmark superiority.

BM25/hybrid search, query decomposition, OCR, and agentic retrieval are deferred until measured failures justify them. No experiment has been run or result recorded yet.

## Free-quota operational sources
- [Groq quickstart](https://console.groq.com/docs/quickstart): official Python SDK and environment-key setup.
- [Supported models](https://console.groq.com/docs/models): check current generation models and output capabilities before setting `GROQ_MODEL`.
- [Rate limits](https://console.groq.com/docs/rate-limits): account-specific organization limits, request/token windows, HTTP 429 responses, and retry/reset headers.
- [Billing FAQ](https://console.groq.com/docs/billing-faqs): Free versus paid Developer tier. Keep the account on Free; no automatic upgrade or paid fallback is planned.

The supplied [community free-plan link](https://community.groq.com/t/do-i-get-charged-for-anything-on-the-groq-free-plan/832) redirected to the Groq homepage when checked, so it is not treated as verified billing evidence. Official references replace it; no universal or permanent quota is assumed.

Planning arithmetic only: 20 generation requests × approximately 2,000 total input tokens ≈ 40,000 input tokens, plus up to 6,000 output tokens at an initial 300-token cap. Actual tokenization, reasoning, retries, development, and repeated evaluations change consumption. Manual grading uses no extra LLM calls; sequential execution still needs token-aware pacing. A free quota may require spreading runs across reset windows.

The planned `eval/report.md` must discuss English-model coverage bias, poor table/scanned-page coverage, confidential excerpts sent to Groq, prompt injection, misleading citations, and overreliance on generated answers. Record mitigations and residual failures; do not claim a small test set proves fairness or safety.
