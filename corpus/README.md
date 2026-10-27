# Reproducible NIST corpus

Phase 0 downloaded three unmodified official PDFs on 2026-10-27. `manifest.json` records source URLs, SHA-256 hashes, byte sizes, and actual physical page counts: AI 100-1 has 48 pages, AI 600-1 has 64, and CSWP 29 has 32. Local PDFs are ignored by Git and Docker build contexts.

Run `uv run python -m scripts.fetch_corpus` from the project root to download missing files or verify existing copies. It refuses changed hashes/page counts and preserves existing files on mismatch. `--record-hashes` is for initial recording only; it does not override an existing hash pin. If a download was interrupted, inspect and remove only that incomplete cached PDF before retrying. The script is single-process; concurrent downloads are unsupported.

Initial bytes were fetched through Windows HTTPS because the project's newly installed Python executable was denied outbound sockets in this environment. The Python script then recorded and reverified all three files. Its download branch is covered by controlled offline tests; a direct Python-network download remains environment-dependent.

## Reuse review
Reviewed physical notice pages 2–3 of AI 100-1, page 3 of AI 600-1 (which links to NIST copyright/use statements), and the opening notices/acknowledgments of CSWP 29. Also checked the [NIST Technical Series policy](https://www.nist.gov/open/license#nist-technical-series-publications) on 2026-10-27. That policy grants reuse rights for NIST-authored works while preserving third-party rights and attribution requirements. These are source/reuse checks, not a legal opinion or proof of ownership of every referenced illustration.

For reproduced passages include document title, publication identifier, NIST attribution, and the policy's requested acknowledgment: “Republished courtesy of the National Institute of Standards and Technology.” Do not imply NIST endorsement of this chatbot.

- NIST (2023), *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*, NIST AI 100-1, [DOI](https://doi.org/10.6028/NIST.AI.100-1).
- NIST (2024), *Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile*, NIST AI 600-1, [DOI](https://doi.org/10.6028/NIST.AI.600-1).
- NIST (2024), *The NIST Cybersecurity Framework (CSF) 2.0*, NIST CSWP 29, [DOI](https://doi.org/10.6028/NIST.CSWP.29).

The corpus contains 144 physical PDF pages in total. That does not change the per-file 200-page application limit. No question-answering quality evaluation has been run yet.
