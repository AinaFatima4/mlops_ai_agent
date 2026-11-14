#!/usr/bin/env bash
# Create the local kind cluster used for the inference service, if it does not exist yet.
set -euo pipefail

CLUSTER_NAME="mlops"

if kind get clusters | grep -qx "${CLUSTER_NAME}"; then
    echo "Cluster ${CLUSTER_NAME} already exists"
else
    kind create cluster --name "${CLUSTER_NAME}" --wait 120s
fi
kubectl --context "kind-${CLUSTER_NAME}" get nodes
