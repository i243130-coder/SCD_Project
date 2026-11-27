# Idea Generator with Go / No-Go — Report (DRAFT)

> Draft prepared by the coding agent. **TODO(human):** review, edit, fill every `TODO(human)` with numbers from real
> runs (PROGRESS.md → "Measured numbers"), export to PDF ≤ 10 pages excluding screenshots.

## 1. Summary and changes from the given architecture
- 15 modules, one image each (16 images incl. the evaluation job); Kubernetes namespace `idea-validator`.
- Changes: `learning` is scored by the Feasibility scorer (decision 0002); hand-written state machines instead of an
  agent framework (0001); kind + Calico (0003); hybrid search with RRF + reranking (0004, provisional);
  the KB currently serves from an in-memory index loaded from the card snapshot (Postgres/Qdrant backends planned).
- Internal what-if/challenge endpoints are `POST /ideas/{id}/whatif|challenge` on M3.

## 2. Modules and architecture figure
See `docs/architecture.md` (mermaid figure; TODO(human): export to PNG and place here).

## 3. Verdict design
Gates (evidence ≥ 3 sources on ≥ 2 platforms → feasibility hours → risk blocker → duplicate with differentiation < 3.0),
goal-preset weights (sum 100), T_go = 70, T_no = 50, floor = 1.5 on the first five dimensions, confidence
0.7 × mean + 0.3 × min(1, sources/5) with a 0.5 minimum, challenge −0.5/−0.1 per accepted objection (max −1.0),
14-run sensitivity, smallest-change what-if preferring a stable GO.

Worked example (unit test `test_worked_example`): portfolio weights, scores 3.5/2.0/3.0/4.0/3.5/4.5 → 70.5 → GO;
feasibility weight −20 % → 69.87 → PIVOT ⇒ **GO, BORDERLINE**; competition 2.0 → 3.0 → 73.5, still GO at 73.07.

TODO(human): one worked example from a real run; before/after confusion matrices from `eval/tune.py`; false-GO count.

## 4. Knowledge base
TODO(human): sources and card counts per source (ingestion count table), ≥ 20 confirmed queries.
Provisional retrieval table (synthetic fixture, proposed queries — replace with real numbers):

| Configuration | Recall@5 | Recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|
| vector | 0.947 | 0.987 | 0.980 | 0.959 |
| keyword | 0.987 | 0.987 | 1.000 | 0.980 |
| hybrid | 0.987 | 0.987 | 1.000 | 0.979 |
| hybrid + rerank | 0.973 | 0.987 | 0.980 | 0.964 |

## 5. Fine-tuning
Pipeline in `jobs/finetune` (QLoRA r=16, α=32, lr 2e-4, Qwen2.5-1.5B-Instruct, GGUF Q4_K_M).
TODO(human): dataset counts, hand-checked count, split, comparison table (base / fine-tuned / hosted), one case where
fine-tuning did not help.

## 6. AgenticOps results
Tracing per step (TraceRecord), replay (`scripts/replay_run.py` reproduced a 25-record trace's decisions exactly),
budgets in `config/budgets.yaml`, behaviour tests (invalid JSON, timeout, empty source, poisoned page, budget,
debate rounds). TODO(human): trace screenshot, eval harness results, drift report, dashboard metrics.

## 7. Platform
GitHub Actions on every PR (lint/type, unit, UI, retrieval gate, docker + Trivy, kubeconform, gitleaks); Jenkins
(build → push → deploy → smoke → nightly eval). TODO(human): how requests/limits were measured (`kubectl top` output
in `docs/report/resources.md`), HPA load test, NetworkPolicy test result, rollout/rollback.

## 8. Known limits and next steps
See PROGRESS.md "Known issues". Decision support, not a prediction of success.
