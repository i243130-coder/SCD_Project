# 0004 — Hybrid search (BM25 + vector, RRF) with reranking for the knowledge base

- **Status:** Proposed — numbers below are from the **synthetic CI fixture** only. TODO(human): re-measure on the real
  KB with the human-confirmed queries and update this record before accepting it.
- **Context:** R-M6 requires hybrid search + reranking, measured on ≥ 20 hand-written queries.
- **Options:** (1) vector only, (2) keyword (BM25) only, (3) hybrid with RRF fusion, (4) hybrid + rerank.
- **Decision:** (4) hybrid + rerank is the configured default (`mode=hybrid_rerank`), gated in CI.
- **Why (measured 2026-11-27, `python eval/retrieval/metrics.py`, 25 proposed queries, 30 synthetic cards):**

  | Configuration | Recall@5 | Recall@10 | MRR | nDCG@10 |
  |---|---|---|---|---|
  | vector | 0.947 | 0.987 | 0.980 | 0.959 |
  | keyword | 0.987 | 0.987 | 1.000 | 0.980 |
  | hybrid | 0.987 | 0.987 | 1.000 | 0.979 |
  | hybrid_rerank | 0.973 | 0.987 | 0.980 | 0.964 |

  On this small fixture the dependency-free lexical reranker is slightly *worse* than plain hybrid. That is an honest
  finding, not a reason to drop reranking yet: the fixture is tiny and easy. Next step: switch the reranker to the
  fastembed cross-encoder (`RERANKER=crossencoder`) and re-measure on the real KB; if reranking still does not help,
  change the default to `hybrid` and record that here.
- **Cost:** one more ranking pass over the top 30 (~ms for the lexical reranker; more for a cross-encoder).
- **AI use:** Drafted by AI (Claude via Claude Code); numbers produced by running the script; TODO(human): review.
