#!/usr/bin/env bash
# Write a kubeconfig for the mlops-agent ServiceAccount, limited by RBAC to the mlops-app namespace.
set -euo pipefail

CLUSTER_NAME="mlops"
NAMESPACE="mlops-app"
SERVICE_ACCOUNT="mlops-agent"
TOKEN_DURATION="24h"
OUTPUT_PATH=".kube/mlops-agent.kubeconfig"
context="kind-${CLUSTER_NAME}"

server=$(kubectl config view --raw -o jsonpath="{.clusters[?(@.name==\"${context}\")].cluster.server}")
certificate_authority=$(kubectl config view --raw \
    -o jsonpath="{.clusters[?(@.name==\"${context}\")].cluster.certificate-authority-data}")
token=$(kubectl --context "${context}" -n "${NAMESPACE}" create token "${SERVICE_ACCOUNT}" \
    --duration="${TOKEN_DURATION}")

mkdir -p "$(dirname "${OUTPUT_PATH}")"
cat > "${OUTPUT_PATH}" << KUBECONFIG
apiVersion: v1
kind: Config
clusters:
  - name: ${context}
    cluster:
      server: ${server}
      certificate-authority-data: ${certificate_authority}
users:
  - name: ${SERVICE_ACCOUNT}
    user:
      token: ${token}
contexts:
  - name: ${SERVICE_ACCOUNT}@${context}
    context:
      cluster: ${context}
      user: ${SERVICE_ACCOUNT}
      namespace: ${NAMESPACE}
current-context: ${SERVICE_ACCOUNT}@${context}
KUBECONFIG
chmod 600 "${OUTPUT_PATH}"
echo "Agent kubeconfig written to ${OUTPUT_PATH} (token valid for ${TOKEN_DURATION})"
