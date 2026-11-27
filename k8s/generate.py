"""Generates k8s/base/*.yaml (committed). Re-run after changing a module list:  python k8s/generate.py
Every workload: probes, requests/limits (start values; TODO(human): set from `kubectl top` measurements),
non-root + read-only root FS, pinned image `registry/<module>:<sha>` (set by scripts/deploy.sh), RollingUpdate
maxUnavailable 0 / maxSurge 1, envFrom ConfigMaps/Secrets, no localhost."""

from __future__ import annotations

from pathlib import Path

import yaml

NS = "idea-validator"
BASE = Path(__file__).parent / "base"
TAG = "set-by-deploy"

# name: (replicas, extra env, volumes, resources override, tier)
SERVICES: dict[str, dict] = {
    "gateway": {"replicas": 2, "tier": "edge"},
    "profile": {},
    "orchestrator": {"cm": ["budgets"]},
    "tools": {"cm": ["tools-allowlist"]},
    "kb": {"data": True},
    "analyst": {"data": True},
    "ideation": {},
    "validators": {},
    "scorer": {"res": ({"cpu": "1", "memory": "2Gi"}, {"cpu": "2", "memory": "3Gi"}), "model": True},
    "verdict": {"replicas": 2, "cm": ["verdict-config"]},
    "critic": {},
    "agentops": {"traces": True},
    "ui": {"tier": "ui", "port": 8080, "probe": "/"},
}


def dump(name: str, docs: list[dict]) -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    (BASE / name).write_text("---\n".join(yaml.safe_dump(d, sort_keys=False) for d in docs))


def security() -> dict:
    return {
        "runAsNonRoot": True,
        "runAsUser": 10001,
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }


def container(name: str, cfg: dict) -> dict:
    port = cfg.get("port", 8000)
    req, lim = cfg.get("res", ({"cpu": "100m", "memory": "128Mi"}, {"cpu": "500m", "memory": "256Mi"}))
    env_from = [
        {"configMapRef": {"name": "service-urls"}},
        {"configMapRef": {"name": "common-config"}},
        {"secretRef": {"name": "app-secrets", "optional": True}},
    ]
    env_from += [{"configMapRef": {"name": c}} for c in cfg.get("cm", []) if c != "verdict-config" and c != "budgets"]
    mounts = [{"name": "tmp", "mountPath": "/tmp"}]
    if "verdict-config" in cfg.get("cm", []):
        mounts.append({"name": "verdict-config", "mountPath": "/config/verdict.yaml", "subPath": "verdict.yaml"})
    if "budgets" in cfg.get("cm", []):
        mounts.append({"name": "budgets", "mountPath": "/config/budgets.yaml", "subPath": "budgets.yaml"})
    if cfg.get("data"):
        mounts.append({"name": "snapshot", "mountPath": "/data/snapshot", "readOnly": True})
    if cfg.get("traces"):
        mounts.append({"name": "traces", "mountPath": "/traces"})
    if cfg.get("model"):
        mounts.append({"name": "models", "mountPath": "/models", "readOnly": True})
    probe = cfg.get("probe")
    c = {
        "name": name,
        "image": f"registry/{name}:{TAG}",
        "ports": [{"containerPort": port}],
        "envFrom": env_from,
        "readinessProbe": {"httpGet": {"path": probe or "/ready", "port": port}, "periodSeconds": 10},
        "livenessProbe": {
            "httpGet": {"path": probe or "/health", "port": port},
            "periodSeconds": 20,
            "initialDelaySeconds": 10,
        },
        "resources": {"requests": req, "limits": lim},
        "securityContext": security(),
        "volumeMounts": mounts,
    }
    if name == "ui":
        c["env"] = [{"name": "API_BASE_URL", "value": "/api"}]
        c["securityContext"]["runAsUser"] = 101
        c["volumeMounts"] = [
            {"name": "tmp", "mountPath": "/tmp"},
            {"name": "nginx-conf", "mountPath": "/usr/share/nginx/html/runtime"},
        ]
    if name == "scorer":
        c["env"] = [{"name": "SCORER_BACKEND", "value": "rule"}, {"name": "MODEL_PATH", "value": "/models/scorer.gguf"}]
    return c


def volumes(cfg: dict, name: str) -> list[dict]:
    v = [{"name": "tmp", "emptyDir": {}}]
    if "verdict-config" in cfg.get("cm", []):
        v.append({"name": "verdict-config", "configMap": {"name": "verdict-config"}})
    if "budgets" in cfg.get("cm", []):
        v.append({"name": "budgets", "configMap": {"name": "budgets"}})
    if cfg.get("data"):
        v.append({"name": "snapshot", "persistentVolumeClaim": {"claimName": "card-snapshot"}})
    if cfg.get("traces"):
        v.append({"name": "traces", "persistentVolumeClaim": {"claimName": "agentops-traces"}})
    if cfg.get("model"):
        v.append({"name": "models", "persistentVolumeClaim": {"claimName": "scorer-models"}})
    if name == "ui":
        v.append({"name": "nginx-conf", "emptyDir": {}})
    return v


def deployment(name: str, cfg: dict) -> list[dict]:
    labels = {"app": name, "tier": cfg.get("tier", "internal")}
    dep = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": NS, "labels": labels},
        "spec": {
            "replicas": cfg.get("replicas", 1),
            "strategy": {"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}},
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {
                    "labels": labels,
                    "annotations": {"prometheus.io/scrape": "true", "prometheus.io/port": str(cfg.get("port", 8000))},
                },
                "spec": {
                    "automountServiceAccountToken": False,
                    "containers": [container(name, cfg)],
                    "volumes": volumes(cfg, name),
                },
            },
        },
    }
    svc = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": NS},
        "spec": {
            "selector": {"app": name},
            "ports": [{"port": cfg.get("port", 8000) if name != "ui" else 80, "targetPort": cfg.get("port", 8000)}],
        },
    }
    return [dep, svc]


def statefulset(
    name: str,
    image: str,
    port: int,
    env: list[dict],
    mount: str,
    size: str,
    args: list[str] | None = None,
    probe: dict | None = None,
    user: int = 999,
) -> list[dict]:
    c = {
        "name": name,
        "image": image,
        "ports": [{"containerPort": port}],
        "env": env,
        "volumeMounts": [{"name": "data", "mountPath": mount}],
        "resources": {"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"cpu": "1", "memory": "1Gi"}},
        "securityContext": {"runAsNonRoot": True, "runAsUser": user, "allowPrivilegeEscalation": False},
    }
    if args:
        c["args"] = args
    if probe:
        c["readinessProbe"] = probe
        c["livenessProbe"] = probe
    ss = {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {"name": name, "namespace": NS},
        "spec": {
            "serviceName": name,
            "replicas": 1,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name, "tier": "data"}},
                "spec": {"securityContext": {"fsGroup": user}, "containers": [c]},
            },
            "volumeClaimTemplates": [
                {
                    "metadata": {"name": "data"},
                    "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": size}}},
                }
            ],
        },
    }
    svc = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": NS},
        "spec": {"clusterIP": "None", "selector": {"app": name}, "ports": [{"port": port}]},
    }
    return [ss, svc]


def job_spec(
    name: str,
    image: str,
    args: list[str],
    app: str,
    mounts: list[dict] | None = None,
    vols: list[dict] | None = None,
    env_from: bool = True,
) -> dict:
    c = {
        "name": name,
        "image": f"registry/{image}:{TAG}",
        "args": args,
        "envFrom": [
            {"configMapRef": {"name": "service-urls"}},
            {"configMapRef": {"name": "common-config"}},
            {"secretRef": {"name": "app-secrets", "optional": True}},
        ]
        if env_from
        else [],
        "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "500m", "memory": "512Mi"}},
        "securityContext": security(),
        "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}, *(mounts or [])],
    }
    return {
        "metadata": {"labels": {"app": app, "tier": "internal"}},
        "spec": {
            "restartPolicy": "OnFailure",
            "containers": [c],
            "volumes": [{"name": "tmp", "emptyDir": {}}, *(vols or [])],
        },
    }


def main() -> None:
    (BASE / "files").mkdir(parents=True, exist_ok=True)
    for f in ("verdict.yaml", "budgets.yaml"):  # kustomize cannot read outside k8s/; CI checks these copies are in sync
        (BASE / "files" / f).write_text((Path(__file__).parents[1] / "config" / f).read_text())
    dump("namespace.yaml", [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NS}}])
    urls = {f"{k.upper()}_URL": f"http://{k}:8000" for k in SERVICES if k not in ("ui",)}
    urls |= {
        "REDIS_URL": "redis://redis:6379/0",
        "QDRANT_URL": "http://qdrant:6333",
        "POSTGRES_HOST": "postgres",
        "GATEWAY_URL": "http://gateway:8000",
    }
    dump(
        "configmaps.yaml",
        [
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "service-urls", "namespace": NS},
                "data": urls,
            },
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "common-config", "namespace": NS},
                "data": {
                    "ENV": "test",
                    "LOG_LEVEL": "INFO",
                    "LLM_MODE": "live",
                    "POSTGRES_DB": "ideas",
                    "POSTGRES_USER": "ideas",
                    "POSTGRES_PORT": "5432",
                    "KB_SNAPSHOT": "/data/snapshot/cards.jsonl.gz",
                    "TRACE_DIR": "/traces",
                    "DRIFT_DIR": "/traces/drift",
                    "UI_ORIGIN": "",
                    "BUDGET_MAX_PAGES": "30",
                },
            },
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "tools-allowlist", "namespace": NS},
                "data": {
                    "ALLOWED_DOMAINS": "hacker-news.firebaseio.com,hn.algolia.com,api.github.com,api.producthunt.com,"
                    "www.ycombinator.com,oauth.reddit.com,www.reddit.com"
                },
            },
        ],
    )
    dump(
        "secrets.example.yaml",
        [
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "app-secrets", "namespace": NS},
                "type": "Opaque",
                "stringData": {
                    k: "CHANGE_ME"
                    for k in (
                        "POSTGRES_PASSWORD",
                        "JWT_SECRET",
                        "INTERNAL_TOKEN",
                        "LLM_API_KEY",
                        "LLM_BASE_URL",
                        "HOSTED_MODEL",
                        "GITHUB_TOKEN",
                        "PRODUCTHUNT_TOKEN",
                        "REDDIT_CLIENT_ID",
                        "REDDIT_CLIENT_SECRET",
                    )
                },
            }
        ],
    )
    docs: list[dict] = []
    for n, cfg in SERVICES.items():
        docs += deployment(n, cfg)
    dump("deployments.yaml", docs)
    pw = {
        "name": "POSTGRES_PASSWORD",
        "valueFrom": {"secretKeyRef": {"name": "app-secrets", "key": "POSTGRES_PASSWORD"}},
    }
    dump(
        "statefulsets.yaml",
        [
            *statefulset(
                "postgres",
                "postgres:16.4-alpine",
                5432,
                [
                    {"name": "POSTGRES_DB", "value": "ideas"},
                    {"name": "POSTGRES_USER", "value": "ideas"},
                    pw,
                    {"name": "PGDATA", "value": "/var/lib/postgresql/data/pgdata"},
                ],
                "/var/lib/postgresql/data",
                "2Gi",
                probe={"exec": {"command": ["pg_isready", "-U", "ideas"]}, "periodSeconds": 10},
                user=70,
            ),
            *statefulset(
                "redis",
                "redis:7.4.1-alpine",
                6379,
                [],
                "/data",
                "1Gi",
                probe={"exec": {"command": ["redis-cli", "ping"]}, "periodSeconds": 10},
            ),
            *statefulset(
                "qdrant",
                "qdrant/qdrant:v1.12.4",
                6333,
                [],
                "/qdrant/storage",
                "2Gi",
                probe={"httpGet": {"path": "/readyz", "port": 6333}, "periodSeconds": 10},
                user=1000,
            ),
        ],
    )
    pvc = lambda n, s, mode="ReadWriteOnce": {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",  # noqa: E731
        "metadata": {"name": n, "namespace": NS},
        "spec": {"accessModes": [mode], "resources": {"requests": {"storage": s}}},
    }
    dump(
        "pvcs.yaml",
        [
            pvc("agentops-traces", "1Gi"),
            pvc("card-snapshot", "1Gi"),
            pvc("scout-raw", "1Gi"),
            pvc("scorer-models", "3Gi"),
        ],
    )
    raw_m = [{"name": "raw", "mountPath": "/data/raw"}]
    raw_v = [{"name": "raw", "persistentVolumeClaim": {"claimName": "scout-raw"}}]
    snap_m = [{"name": "snapshot", "mountPath": "/data/snapshot"}]
    snap_v = [{"name": "snapshot", "persistentVolumeClaim": {"claimName": "card-snapshot"}}]
    crons = []
    for src, sched in (
        ("hn", "0 */6 * * *"),
        ("github", "30 1 * * *"),
        ("producthunt", "0 2 * * *"),
        ("yc", "0 3 * * 0"),
    ):
        crons.append(
            {
                "apiVersion": "batch/v1",
                "kind": "CronJob",
                "metadata": {"name": f"scout-{src}", "namespace": NS},
                "spec": {
                    "schedule": sched,
                    "concurrencyPolicy": "Forbid",
                    "jobTemplate": {
                        "spec": {
                            "template": job_spec(
                                "scout", "scouts", ["python", "-m", "src.main", "--source", src], "scouts", raw_m, raw_v
                            )
                        }
                    },
                },
            }
        )
    crons.append(
        {
            "apiVersion": "batch/v1",
            "kind": "CronJob",
            "metadata": {"name": "ingestion", "namespace": NS},
            "spec": {
                "schedule": "0 4 * * *",
                "concurrencyPolicy": "Forbid",
                "jobTemplate": {
                    "spec": {
                        "template": job_spec(
                            "ingestion",
                            "ingestion",
                            ["python", "-m", "src.ingest"],
                            "ingestion",
                            raw_m + snap_m,
                            raw_v + snap_v,
                        )
                    }
                },
            },
        }
    )
    crons.append(
        {
            "apiVersion": "batch/v1",
            "kind": "CronJob",
            "metadata": {"name": "analyst-recompute", "namespace": NS},
            "spec": {
                "schedule": "30 4 * * *",
                "jobTemplate": {
                    "spec": {
                        "template": job_spec(
                            "recompute",
                            "evaluation",
                            [
                                "python",
                                "-c",
                                "import httpx,os;[httpx.post(os.environ[k]+p,timeout=60) for k,p in "
                                "(('KB_URL','/reload'),('ANALYST_URL','/recompute'))]",
                            ],
                            "recompute",
                        )
                    }
                },
            },
        }
    )
    dump("cronjobs.yaml", crons)
    (BASE / "jobs").mkdir(exist_ok=True)
    (BASE / "jobs" / "eval-job.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "metadata": {"name": "eval-job", "namespace": NS},
                "spec": {
                    "backoffLimit": 0,
                    "ttlSecondsAfterFinished": 86400,
                    "template": job_spec("eval", "evaluation", ["python", "-m", "src.harness"], "evaluation"),
                },
            },
            sort_keys=False,
        )
    )
    imp = job_spec(
        "model-import",
        "evaluation",
        [
            "python",
            "-c",
            "import os,urllib.request;urllib.request.urlretrieve(os.environ['MODEL_URL'],'/models/scorer.gguf')",
        ],
        "model-import",
        [{"name": "models", "mountPath": "/models"}],
        [{"name": "models", "persistentVolumeClaim": {"claimName": "scorer-models"}}],
    )
    (BASE / "jobs" / "model-import-job.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "metadata": {"name": "model-import", "namespace": NS},
                "spec": {"backoffLimit": 1, "template": imp},
            },
            sort_keys=False,
        )
    )
    dump(
        "ingress.yaml",
        [
            {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "Ingress",
                "metadata": {
                    "name": "idea-validator",
                    "namespace": NS,
                    "annotations": {
                        "nginx.ingress.kubernetes.io/use-regex": "true",
                        "nginx.ingress.kubernetes.io/rewrite-target": "/$2",
                    },
                },
                "spec": {
                    "ingressClassName": "nginx",
                    "rules": [
                        {
                            "http": {
                                "paths": [
                                    {
                                        "path": "/api(/|$)(.*)",
                                        "pathType": "ImplementationSpecific",
                                        "backend": {"service": {"name": "gateway", "port": {"number": 8000}}},
                                    },
                                    {
                                        "path": "/()(.*)",
                                        "pathType": "ImplementationSpecific",
                                        "backend": {"service": {"name": "ui", "port": {"number": 80}}},
                                    },
                                ]
                            }
                        }
                    ],
                },
            }
        ],
    )
    dump(
        "hpa.yaml",
        [
            {
                "apiVersion": "autoscaling/v2",
                "kind": "HorizontalPodAutoscaler",
                "metadata": {"name": "gateway", "namespace": NS},
                "spec": {
                    "scaleTargetRef": {"apiVersion": "apps/v1", "kind": "Deployment", "name": "gateway"},
                    "minReplicas": 2,
                    "maxReplicas": 5,
                    "metrics": [
                        {
                            "type": "Resource",
                            "resource": {"name": "cpu", "target": {"type": "Utilization", "averageUtilization": 70}},
                        }
                    ],
                },
            }
        ],
    )
    np = lambda n, spec: {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",  # noqa: E731
        "metadata": {"name": n, "namespace": NS},
        "spec": spec,
    }
    not_ui = {"matchExpressions": [{"key": "tier", "operator": "NotIn", "values": ["ui"]}]}
    (BASE / "networkpolicies").mkdir(exist_ok=True)
    pols = {
        "default-deny.yaml": np("default-deny", {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}),
        "allow-dns.yaml": np(
            "allow-dns",
            {
                "podSelector": {},
                "policyTypes": ["Egress"],
                "egress": [
                    {
                        "to": [
                            {
                                "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
                                "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                            }
                        ],
                        "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}],
                    }
                ],
            },
        ),
        "allow-intra-namespace.yaml": np(
            "allow-intra-namespace",
            {
                "podSelector": not_ui,
                "policyTypes": ["Egress", "Ingress"],
                "egress": [{"to": [{"podSelector": not_ui}]}],
                "ingress": [
                    {
                        "from": [
                            {"podSelector": {"matchLabels": {"tier": "internal"}}},
                            {"podSelector": {"matchLabels": {"tier": "edge"}}},
                            {"podSelector": {"matchLabels": {"tier": "data"}}},
                        ]
                    }
                ],
            },
        ),
        "allow-ui-to-gateway.yaml": np(
            "allow-ui-to-gateway",
            {
                "podSelector": {"matchLabels": {"tier": "ui"}},
                "policyTypes": ["Egress", "Ingress"],
                "egress": [{"to": [{"podSelector": {"matchLabels": {"app": "gateway"}}}], "ports": [{"port": 8000}]}],
                "ingress": [
                    {"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ingress-nginx"}}}]}
                ],
            },
        ),
        "allow-ingress-to-gateway.yaml": np(
            "allow-ingress-to-gateway",
            {
                "podSelector": {"matchLabels": {"app": "gateway"}},
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [
                            {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ingress-nginx"}}},
                            {"podSelector": {"matchLabels": {"tier": "ui"}}},
                        ]
                    }
                ],
            },
        ),
        "allow-tools-internet.yaml": np(
            "allow-tools-internet",
            {
                "podSelector": {"matchLabels": {"app": "tools"}},
                "policyTypes": ["Egress"],
                "egress": [
                    {
                        "to": [
                            {
                                "ipBlock": {
                                    "cidr": "0.0.0.0/0",
                                    "except": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
                                }
                            }
                        ],
                        "ports": [{"protocol": "TCP", "port": 443}, {"protocol": "TCP", "port": 80}],
                    }
                ],
            },
        ),
        "allow-model-import.yaml": np(
            "allow-model-import",
            {
                "podSelector": {"matchLabels": {"app": "model-import"}},
                "policyTypes": ["Egress"],
                "egress": [
                    {
                        "to": [
                            {
                                "ipBlock": {
                                    "cidr": "0.0.0.0/0",
                                    "except": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
                                }
                            }
                        ],
                        "ports": [{"protocol": "TCP", "port": 443}],
                    }
                ],
            },
        ),
        "allow-prometheus-scrape.yaml": np(
            "allow-prometheus-scrape",
            {
                "podSelector": {},
                "policyTypes": ["Ingress"],
                "ingress": [
                    {"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "monitoring"}}}]}
                ],
            },
        ),
    }
    for f, d in pols.items():
        (BASE / "networkpolicies" / f).write_text(yaml.safe_dump(d, sort_keys=False))
    resources = [
        "namespace.yaml",
        "configmaps.yaml",
        "deployments.yaml",
        "statefulsets.yaml",
        "pvcs.yaml",
        "cronjobs.yaml",
        "ingress.yaml",
        "hpa.yaml",
        *[f"networkpolicies/{f}" for f in pols],
    ]
    (BASE / "kustomization.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "kustomize.config.k8s.io/v1beta1",
                "kind": "Kustomization",
                "namespace": NS,
                "resources": resources,
                "configMapGenerator": [
                    {"name": "verdict-config", "files": ["verdict.yaml=files/verdict.yaml"]},
                    {"name": "budgets", "files": ["budgets.yaml=files/budgets.yaml"]},
                ],
                "generatorOptions": {"disableNameSuffixHash": True},
            },
            sort_keys=False,
        )
    )
    ov = Path(__file__).parent / "overlays" / "test"
    ov.mkdir(parents=True, exist_ok=True)
    mods = [*SERVICES, "scouts", "ingestion", "evaluation"]
    (ov / "kustomization.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "kustomize.config.k8s.io/v1beta1",
                "kind": "Kustomization",
                "resources": ["../../base"],
                "images": [{"name": f"registry/{m}", "newName": f"localhost:5001/{m}", "newTag": "dev"} for m in mods],
            },
            sort_keys=False,
        )
    )


if __name__ == "__main__":
    main()
