#!/usr/bin/env bash
# Export the candidate model, build the API image, load it into kind and roll it out.
set -euo pipefail

CLUSTER_NAME="mlops"
NAMESPACE="mlops-app"
DEPLOYMENT_NAME="adult-income-api"
context="kind-${CLUSTER_NAME}"

set -a
source .env
set +a

image_tag=$(uv run python -m scripts.export_model --output build/model | tail -n 1)
image="${DEPLOYMENT_NAME}:${image_tag}"
echo "Building ${image}"

docker build --tag "${image}" .
kind load docker-image "${image}" --name "${CLUSTER_NAME}"

sed -i "s/newTag: .*/newTag: ${image_tag}/" kubernetes/kustomization.yaml
kubectl --context "${context}" apply -k kubernetes/
kubectl --context "${context}" -n "${NAMESPACE}" rollout status "deployment/${DEPLOYMENT_NAME}" \
    --timeout=180s

./scripts/create_agent_kubeconfig.sh
echo "Deployed ${image}"
