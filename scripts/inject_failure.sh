#!/usr/bin/env bash
# Inject or undo the two demonstration failures.
# Usage: ./scripts/inject_failure.sh {bad-data|restore-data|bad-model-path|restore-model-path}
set -euo pipefail

DATASET_PATH="data/adult.csv"
TRUNCATED_ROW_COUNT=500
NAMESPACE="mlops-app"
DEPLOYMENT_NAME="adult-income-api"
CONFIGMAP_NAME="adult-income-api-config"
BROKEN_MODEL_PATH="/app/model-missing"
context="kind-mlops"

inject_bad_data() {
    # Keep the header plus the first rows only, so validation fails on the row count
    head -n "$((TRUNCATED_ROW_COUNT + 1))" "${DATASET_PATH}" > "${DATASET_PATH}.truncated"
    mv "${DATASET_PATH}.truncated" "${DATASET_PATH}"
    echo "Injected: ${DATASET_PATH} now has $(($(wc -l < "${DATASET_PATH}") - 1)) data rows"
}

restore_data() {
    uv run dvc checkout --force "${DATASET_PATH}.dvc"
    echo "Restored: ${DATASET_PATH} has $(($(wc -l < "${DATASET_PATH}") - 1)) data rows"
}

recreate_pods() {
    kubectl --context "${context}" -n "${NAMESPACE}" delete pod \
        -l "app.kubernetes.io/name=${DEPLOYMENT_NAME}" --wait=false
}

inject_bad_model_path() {
    kubectl --context "${context}" -n "${NAMESPACE}" patch configmap "${CONFIGMAP_NAME}" \
        --type merge -p "{\"data\":{\"MODEL_PATH\":\"${BROKEN_MODEL_PATH}\"}}"
    recreate_pods
    echo "Injected: MODEL_PATH=${BROKEN_MODEL_PATH}; pods are being recreated"
}

restore_model_path() {
    kubectl --context "${context}" apply -k kubernetes/
    recreate_pods
    kubectl --context "${context}" -n "${NAMESPACE}" rollout status "deployment/${DEPLOYMENT_NAME}" \
        --timeout=120s
    echo "Restored: ConfigMap re-applied from kubernetes/configmap.yaml"
}

case "${1:-}" in
    bad-data) inject_bad_data ;;
    restore-data) restore_data ;;
    bad-model-path) inject_bad_model_path ;;
    restore-model-path) restore_model_path ;;
    *)
        echo "Usage: $0 {bad-data|restore-data|bad-model-path|restore-model-path}" >&2
        exit 1
        ;;
esac
