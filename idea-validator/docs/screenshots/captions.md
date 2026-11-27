# Screenshots (§27) — TODO(human): take each, save as NN-name.png, write a one-line caption

| # | File | How to produce | Caption |
|---|---|---|---|
| 1 | 01-protected-main.png | GitHub → Settings → Branches; and a PR showing the required checks | |
| 2 | 02-merge-conflict.png | two branches edit `config/verdict.yaml` thresholds; resolve in the PR | |
| 3 | 03-actions-green.png / 03-actions-red.png | a PR that breaks a verdict test on purpose, then the fix | |
| 4 | 04-jenkins-green.png / 04-jenkins-red.png | smoke test against a broken build (`BAD_RELEASE=true`) | |
| 5 | 05-pods.png | `kubectl get pods -n idea-validator` | |
| 6 | 06-rollout.png / 06-rollback.png | `kubectl rollout status deploy/gateway`, `kubectl rollout undo deploy/gateway` | |
| 7 | 07-netpol.png | `./scripts/netpol_test.sh` | |
| 8 | 08-ui-*.png | profile; Discover results; verdict card; challenge result; what-if v2; INSUFFICIENT EVIDENCE card | |
| 9 | 09-trace.png / 09-dashboard.png / 09-drift.png | `GET /runs/{id}/trace`, Grafana (or M13 `/dashboard`), `GET /drift/latest` | |
| 10 | 10-retrieval.png / 10-finetune.png | `python eval/retrieval/metrics.py`, `compare_models.py` output | |
