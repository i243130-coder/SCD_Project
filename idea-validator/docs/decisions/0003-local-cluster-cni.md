# 0003 — Local Kubernetes: kind + Calico

- **Status:** Proposed (TODO(human): confirm after creating the cluster)
- **Context:** R-G18 requires NetworkPolicy to be *enforced*. kind's default CNI (kindnet) ignores NetworkPolicy.
- **Options:** (1) kind + Calico (disable default CNI), (2) minikube `--cni=calico`, (3) k3d (k3s enforces NetworkPolicy by default).
- **Decision:** (1) kind + Calico, with a local registry `kind-registry:5000`. Config in `k8s/kind-config.yaml`.
- **Why:** closest to upstream Kubernetes; Calico is a common production CNI; the local registry avoids pushing to the internet.
- **Cost:** a slightly longer cluster setup (Calico install, ~2 min).
- **AI use:** Drafted by AI (Claude via Claude Code); TODO(human): verify with `scripts/netpol_test.sh` and record the result.
