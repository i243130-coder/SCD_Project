# Jenkins LTS with docker CLI + kubectl + kustomize. Run with the host Docker socket mounted:
#   docker build -t iv-jenkins ci/jenkins
#   docker run -d --name jenkins -p 8081:8080 -v jenkins_home:/var/jenkins_home \
#     -v /var/run/docker.sock:/var/run/docker.sock --network kind iv-jenkins
# Credentials (never in the repo): kubeconfig-test (Secret file), registry (username/password), registry-url (text).
FROM jenkins/jenkins:2.479.2-lts-jdk17
USER root
RUN apt-get update && apt-get install -y --no-install-recommends docker.io curl openssl python3 \
 && curl -fsSLo /usr/local/bin/kubectl https://dl.k8s.io/release/v1.31.3/bin/linux/amd64/kubectl \
 && chmod +x /usr/local/bin/kubectl \
 && curl -fsSL https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv5.5.0/kustomize_v5.5.0_linux_amd64.tar.gz | tar xz -C /usr/local/bin \
 && rm -rf /var/lib/apt/lists/*
RUN jenkins-plugin-cli --plugins git workflow-aggregator credentials-binding timestamper
USER jenkins
