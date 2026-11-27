# M10t — Fine-tuning pipeline

Goal: a **cheaper, faster, more consistent** 1.5B scorer that follows the rubric format and the evidence rule —
not a smarter model than the hosted one.

| Step | Who | Command |
|---|---|---|
| 1. Build ≥ 300 candidates (all dims, all levels; tuning-set ideas excluded) | agent/script | `python jobs/finetune/build_dataset.py --kb http://localhost:8000 --n 360` |
| 2. Draft labels with the hosted model (`checked: false`) | script | `python jobs/finetune/label_with_hosted.py` |
| 3. Hand-check ≥ 60 | **HUMAN** | `python jobs/finetune/review_tool.py --member "Member 1"` → http://127.0.0.1:8765 |
| 4. Group-aware 80/20 split by idea; checked → test | script | `python jobs/finetune/split.py` (writes `data/train.jsonl`, `data/test.jsonl`, `dataset_card.md`) |
| 5. Train QLoRA on Qwen2.5-1.5B-Instruct | **HUMAN on Colab/Kaggle** | open `train_colab.ipynb` (settings in `settings.yaml`) |
| 6. Merge + GGUF Q4_K_M | human | `python merge_and_quantize.py --adapter out/scorer-lora --llama-cpp ~/llama.cpp --out out/scorer-q4_k_m.gguf` |
| 7. Upload weights as a GitHub Release asset (never commit) | human | `gh release create model-v1 out/scorer-q4_k_m.gguf` |
| 8. Import into the cluster | human | set `MODEL_URL`, `kubectl apply -f k8s/base/jobs/model-import-job.yaml`, set `SCORER_BACKEND=gguf` |
| 9. Compare base vs fine-tuned vs hosted | human runs | `python compare_models.py --scorer-base … --scorer-ft … --scorer-hosted …` |

Rules: the agent never sets `checked: true`; tuning-set ideas (`eval/labelled/ideas.yaml`) never enter training
(tested in `tests/test_finetune.py`); `settings.yaml` + the dataset hash are committed; weights are not.
