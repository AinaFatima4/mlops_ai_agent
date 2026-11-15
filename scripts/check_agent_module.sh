#!/usr/bin/env bash
# Verify the agent module: lint, unit tests, LLM server and one real multi-tool question.
set -u

set -a
source .env
set +a

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
run_check "ollama reachable" curl -sf http://localhost:11434/api/tags
run_check "model ${LLM_MODEL} pulled" bash -c "ollama list | grep -q '${LLM_MODEL}'"

if [ "${failure_count}" -eq 0 ]; then
    echo "ALL CHECKS PASSED"
else
    echo "${failure_count} CHECK(S) FAILED"
    exit 1
fi
