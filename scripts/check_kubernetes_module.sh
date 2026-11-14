#!/usr/bin/env bash
# Verify the Kubernetes module: lint, unit tests, cluster access and live checks.
set -u

failure_count=0

run_check() {
    local check_name="$1"
    shift
    local check_output
    if check_output=$("$@" 2>&1); then
        echo "PASS  ${check_name}"
    else
        echo "FAIL  ${check_name}"
        echo "${check_output}" | tail -25 | sed 's/^/      /'
        failure_count=$((failure_count + 1))
    fi
}

run_check "ruff lint" uv run ruff check .
run_check "ruff format" uv run ruff format --check .
run_check "unit tests" uv run pytest -q
run_check "cluster reachable" kubectl --context kind-mlops get nodes
run_check "live kubernetes tools + rbac" uv run python -m scripts.live_check_kubernetes_tools

if [ "${failure_count}" -eq 0 ]; then
    echo "ALL CHECKS PASSED"
else
    echo "${failure_count} CHECK(S) FAILED"
    exit 1
fi
