# Idea Validator — Idea Generator with Go / No-Go

CS4032 Software Construction and Development, semester project (FAST-NUCES).

An interactive multi-agent system that helps a student choose a project. It collects ideas from public sources,
maps niches and trends, proposes ideas that fit the student's profile (**Discover**), and validates an idea
(**Validate**) into **GO / PIVOT / NO-GO / INSUFFICIENT EVIDENCE** with evidence, gates, six scores, weights,
confidence, stability and "what would make this GO".

> **Decision support, not a prediction of success.** The verdict comes from a deterministic, unit-tested engine
> (M11), never from a language model.

## Modules

| Module | Folder | What it does |
|---|---|---|
| M1 UI + API gateway | `services/ui`, `services/gateway` | the only entrance; JWT, rate limits, input validation, SSE live events |
| M2 Profile/session/cache | `services/profile` | Postgres (Alembic) + Redis; layered `routes → services → repositories` |
| M3 Orchestrator | `services/orchestrator` | Validate + Discover as explicit state machines; budgets, retries, timeouts |
| M4 Scouts | `services/scouts` | HN, GitHub, Product Hunt, YC, Reddit — internet **only through M5** |
| M5 Tool layer | `services/tools` | allow-list, robots.txt, rate limit, cache, **sanitiser** |
| M6 Knowledge base | `services/kb` | hybrid BM25 + vector search, RRF fusion, rerank, card-id citations |
| M6i Ingestion | `jobs/ingestion` | normalise, dedupe (canonical URL + near-dup merge), idempotent upsert, snapshot |
| M7 Analyst | `services/analyst` | named niches, monthly series, rising/flat/saturated, gaps |
| M8 Ideation | `services/ideation` | Ideator, Gap Analyst, Skeptic, suggest_change |
| M9 Validators | `services/validators` | 4 parallel scorers → 6 dimensions; computed features; abstain without evidence |
| M10 Scorer | `services/scorer` | fine-tuned GGUF / hosted / rule backends; validate → retry once → fallback |
| M10t Fine-tuning | `jobs/finetune` | dataset, human review tool, group split, QLoRA notebook, merge+quantise, comparison |
| M11 Verdict engine | `services/verdict` | plain deterministic code, rules in a ConfigMap |
| M12 Critic | `services/critic` | claim check, injection defence, input rail, approval policy |
| M13 AgenticOps | `services/agentops`, `jobs/evaluation` | traces + replay, registry, eval harness, drift, dashboard |
| M14 Platform | `.github/`, `Jenkinsfile`, `k8s/` | GitHub Actions, Jenkins, Docker, Kubernetes |

Architecture walkthrough: [docs/architecture.md](docs/architecture.md). Live status: [PROGRESS.md](PROGRESS.md).

## Quick start (local, development only)

Prerequisites: Docker 24+, Python 3.12, Node 20.

```bash
cp .env.example .env          # then fill POSTGRES_PASSWORD, JWT_SECRET, INTERNAL_TOKEN (and LLM_* if you have a key)
./scripts/dev_up.sh           # builds every image, starts compose, loads the card snapshot
```

UI: http://localhost:8080 · API: http://localhost:8000/docs. docker-compose is for development only; the target is Kubernetes.

Without an LLM key the system still runs end to end: the scorer uses the transparent `rule` backend and M8 uses
templates (`model: "rule"` / `"template"` is shown on the card).

## Tests

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
PYTHON=.venv/bin/python ./scripts/test_all.sh      # every module, recorded responses, no network
.venv/bin/pytest services/verdict -q               # the verdict engine incl. the worked example (§9.6)
.venv/bin/pytest eval/retrieval -q                 # retrieval quality gate
(cd services/ui && npm ci && npm test -- --run)    # UI component tests
```

## Kubernetes (kind + Calico, which enforces NetworkPolicy)

```bash
docker run -d --restart=always -p 127.0.0.1:5001:5000 --network bridge --name kind-registry registry:2
kind create cluster --name iv --config k8s/kind-config.yaml
docker network connect kind kind-registry
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.29.1/manifests/calico.yaml
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.0/deploy/static/provider/kind/deploy.yaml
kubectl apply -f k8s/base/namespace.yaml
kubectl -n idea-validator create secret generic app-secrets \
  --from-literal=POSTGRES_PASSWORD=... --from-literal=JWT_SECRET=... --from-literal=INTERNAL_TOKEN=... \
  --from-literal=LLM_API_KEY=... --from-literal=LLM_BASE_URL=... --from-literal=HOSTED_MODEL=... \
  --from-literal=GITHUB_TOKEN=... --from-literal=PRODUCTHUNT_TOKEN=...
TAG=$(git rev-parse --short HEAD) REGISTRY=localhost:5001
./scripts/build_images.sh $TAG && ./scripts/push_images.sh $TAG && ./scripts/deploy.sh $TAG
./scripts/smoke_test.sh
./scripts/netpol_test.sh                          # non-M5 pod blocked, M5 reaches the internet
```

Useful commands:

```bash
kubectl get pods -n idea-validator
kubectl logs deploy/verdict -n idea-validator
kubectl top pods -n idea-validator                # measure, then set requests/limits (docs/report/resources.md)
kubectl rollout status deploy/gateway -n idea-validator
kubectl rollout undo deploy/gateway -n idea-validator
kubectl apply -f k8s/base/jobs/eval-job.yaml      # evaluation harness as a Job
```

Rollout/rollback demo: set `BAD_RELEASE=true` on the gateway (its `/ready` then returns 503). With
`maxUnavailable: 0` the old pods keep serving; then `kubectl rollout undo deploy/gateway`.

Manifests are generated (`python k8s/generate.py`) and committed; CI fails if they are out of date.

## Data, ingestion, replay, evaluation

```bash
docker compose run --rm scouts python -m src.main --source hn     # scouts write raw items (through M5)
docker compose --profile jobs run --rm ingestion                   # dedupe + upsert + snapshot
python scripts/replay_run.py --trace traces/<run_id>.jsonl         # replay a run without network/model
python eval/retrieval/metrics.py                                   # 4-configuration retrieval table
python jobs/evaluation/src/harness.py --gateway http://localhost:8000
```

## Data ethics

- Official APIs first (HN Algolia/Firebase, GitHub REST, Product Hunt API, Reddit API); no HTML scraping where an API exists.
- Every request goes through M5: per-domain rate limits, robots.txt, a clear User-Agent, caching, back-off.
- No logins, no private data. Cards keep only name, public text and the public URL; emails/usernames are stripped.
- Sources are credited: every card keeps its source + URL and the verdict card links to them.
- Fetched text is **data, never instructions**: sanitised in M5, wrapped in `<<<DATA … DATA>>>`, checked again in M12.
- A card snapshot (`data/snapshot/cards.jsonl.gz`) keeps the system working when websites are down.

## Repository settings (human, day 1)

Protect `main`: no direct pushes, PRs only, 1 approving review from the other member, dismiss stale approvals,
required status checks = every job in `.github/workflows/pr-checks.yml` (lint-type, unit-tests, ui-tests,
retrieval-gate, docker (all matrix entries), manifests, secrets).

## Troubleshooting

- `profile` not ready → Postgres password mismatch between `.env` / Secret and the existing volume.
- Every verdict is INSUFFICIENT_EVIDENCE → the KB is empty; run ingestion (`kubectl -n idea-validator get pvc card-snapshot`).
- NetworkPolicy test passes for verdict *and* fails for tools → your CNI does not enforce policies (use Calico).
- 429 from the gateway → rate limits (`RATE_USER_PER_MIN`, `RATE_AUTH_IP_PER_MIN`).
