#!/usr/bin/env bash
# Verify the DVC module: lint, unit tests and live checks against this repository.
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
        echo "${check_output}" | sed 's/^/      /'
        failure_count=$((failure_count + 1))
    fi
}

run_check "ruff lint" uv run ruff check .
run_check "ruff format" uv run ruff format --check .
run_check "unit tests" uv run pytest -q tests/test_command_runner.py tests/test_dvc_tools.py
run_check "live dvc tools" uv run python -m scripts.live_check_dvc_tools

if [ "${failure_count}" -eq 0 ]; then
    echo "ALL CHECKS PASSED"
else
    echo "${failure_count} CHECK(S) FAILED"
    exit 1
fi
