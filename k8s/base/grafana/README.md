# Monitoring
Install kube-prometheus-stack into namespace `monitoring` (the `allow-prometheus-scrape` NetworkPolicy admits it):

    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm install mon prometheus-community/kube-prometheus-stack -n monitoring --create-namespace

Pods are annotated `prometheus.io/scrape: "true"` (port 8000, path `/metrics`). Import `dashboard.json` in Grafana
(Dashboards → Import). Panels: cost per verdict, latency per agent, cache hit rate, fallbacks, approvals, blocked
injections (+ blocked fetches, requests by status). Fallback without Grafana: `GET /dashboard` on agentops.
