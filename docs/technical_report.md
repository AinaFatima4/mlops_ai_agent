# Technical Report — Production-Ready MLOps AI Agent

**Course:** MLOps & Production AI Engineering, Fall 2026 · **Assignment 3** · Aina Fatima (23i-0613)

## 1. System architecture

The agent is a command-line chat backed by a local LLM (Ollama, `qwen3.5:9b`, fully on GPU) that
calls 26 structured tools against four real systems. Full diagrams, the training DAG, lineage flow
and safety layers are in [`architecture.md`](../architecture.md).

| Layer | Technology | Role |
|---|---|---|
| Data versioning | DVC 3 + SeaweedFS (S3-compatible) | Dataset versions `dataset-v1.0` (raw) and `dataset-v2.0` (cleaned) |
| Experiment tracking | MLflow 3.18 + PostgreSQL 17 + SeaweedFS | Runs, metrics, provenance tags, model registry |
| Orchestration | Airflow 3.4, LocalExecutor | DAG `adult_income_training`, 11 task instances |
| Serving | FastAPI on kind (Kubernetes 1.36) | 2 replicas, probes, resource limits, RBAC |
| Agent | Python, OpenAI-compatible tool calling, Pydantic | Orchestrator, tool executor, guards, JSON logs |
| CI | GitHub Actions + uv | Ruff lint/format and 127 pytest tests on every PR |

Key design choices:

- **SeaweedFS** for S3 storage: MinIO stopped publishing community images in October 2025.
- **PostgreSQL** backend for MLflow: concurrent writers (Airflow tasks, CLI, agent).
- **`@task.external_python`** in Airflow: isolates training packages without mounting the Docker socket.
- **Model baked into the image** (`adult-income-api:model-v<N>`): each image is one immutable model version.
- **Direct tool calling** instead of an agent framework: safety rules are enforced in code and are easy to test.
- **Local LLM**: no rate limits, no data leaves the machine, no quota risk during the demo.

## 2. Tool definitions and permissions

All tools return structured JSON. Inputs are Pydantic models with `extra="forbid"`.

| Service | Tool | Access | Guard |
|---|---|---|---|
| DVC | `dvc_list_tracked_datasets` | read | allowlisted `git ls-files` |
| DVC | `dvc_list_dataset_versions` | read | validated path |
| DVC | `dvc_get_current_dataset_version` | read | compares workspace file MD5 with committed pointer |
| DVC | `dvc_find_version_by_hash` | read | 32-hex MD5 only |
| DVC | `dvc_compare_dataset_versions` | read | version names `dataset-vX.Y` only |
| DVC | `dvc_check_data_changed` | read | `dvc status` |
| DVC | `dvc_get_reproduction_steps` | read | returns commands, never runs them |
| MLflow | `mlflow_list_experiments` | read | fail-fast client (no retries, 10 s timeout) |
| MLflow | `mlflow_list_runs` | read | limit 1–50 |
| MLflow | `mlflow_get_run_details` | read | 32-hex run ID |
| MLflow | `mlflow_find_best_run` | read | metric allowlist; runner-up and readiness warnings |
| MLflow | `mlflow_compare_runs` | read | 2–10 run IDs |
| MLflow | `mlflow_get_model_versions` | read | name allowlist pattern |
| Airflow | `airflow_list_dags` | read | includes DAG import errors |
| Airflow | `airflow_list_dag_runs` | read | — |
| Airflow | `airflow_get_dag_run_status` | read | validated run ID |
| Airflow | `airflow_trigger_dag` | **write** | approved DAG only, user confirmation, refuses paused DAG |
| Airflow | `airflow_wait_for_dag_run` | read | timeout ≤ 900 s |
| Airflow | `airflow_get_failed_tasks` | read | separates root-cause from `upstream_failed` |
| Airflow | `airflow_get_task_logs` | read | log tail, error lines, exception summary |
| Kubernetes | `kubernetes_list_workloads` | read | namespace `mlops-app` only |
| Kubernetes | `kubernetes_get_pod_details` | read | includes previous-container logs |
| Kubernetes | `kubernetes_inspect_services` | read | ready EndpointSlice count |
| Kubernetes | `kubernetes_find_unhealthy_pods` | read | CrashLoopBackOff, ImagePullBackOff, OOMKilled, not Ready |
| Kubernetes | `kubernetes_get_deployed_version` | read | image tag + API `/version` via service proxy |
| Kubernetes | `kubernetes_restart_deployment` | **write** | `mlops-app` only, user confirmation |

**Credentials.** The Airflow tools use a dedicated `mlops_agent` account (role `user`), not admin.
The Kubernetes tools use the `mlops-agent` ServiceAccount, whose Role allows reading pods, logs,
events, services, ConfigMaps and EndpointSlices, calling the API's `/version` through the service
proxy, and patching only the `adult-income-api` Deployment. The live check proves RBAC returns
**403 Forbidden** for listing `kube-system` pods, deleting the Deployment and reading Secrets, even
when the tool code is bypassed. No secrets are committed: `.env`, `.kube/`, the DVC local config
and the Airflow password file are git-ignored.

## 3. Evidence from DVC, MLflow, Airflow and Kubernetes

### DVC

| Version | Rows | MD5 | Size |
|---|---|---|---|
| `dataset-v1.0` (raw UCI Adult) | 32,561 | `910d8ebecaaa49bd45cc3f208dc755bb` | 4,007,022 B |
| `dataset-v2.0` (cleaned) | 30,162 | `06769c0a96e9ab07b8d9e2c1255a976b` | 3,328,203 B |

Reproducible checkout was demonstrated by switching the pointer to `dataset-v1.0`, running
`dvc checkout` (32,562 lines), and switching back (30,163 lines).

![DVC reproducible checkout](../screenshots/01-dvc-checkout.png)

### MLflow

Best run per model type on `dataset-v2.0` (test split 20 %, stratified, seed 42):

| Model | F1 | Precision | Recall | ROC-AUC | Accuracy | Quality gate |
|---|---|---|---|---|---|---|
| Gradient boosting | 0.7176 | 0.6208 | 0.8502 | 0.9233 | 0.8334 | passed |
| Random forest | 0.6921 | — | — | — | — | passed |
| Logistic regression | 0.6791 | — | — | — | — | passed |

Registered model `adult-income-classifier` version 2 (`@candidate`, run
`930195a0314e4405b412ac21fb2f1a56`) is the deployed model.

![MLflow runs](../screenshots/02-mlflow-runs.png)
![MLflow registered model](../screenshots/03-mlflow-model-registry.png)

### Airflow

Run `manual__2026-11-15T00:08:05.905401+00:00` succeeded in about 25 s with all 11 task instances
successful (3 mapped `train_model` and 3 mapped `evaluate_model` tasks).

![Airflow DAG graph](../screenshots/04-airflow-dag-success.png)

### Kubernetes

Deployment `adult-income-api` runs image `adult-income-api:model-v2` with 2/2 ready replicas,
2 ready endpoints behind the ClusterIP Service, and `/version` reporting model version 2 trained
on `dataset-v2.0`.

![Kubernetes resources](../screenshots/05-kubernetes-resources.png)
![FastAPI docs](../screenshots/06-fastapi-predict.png)

## 4. Five tested agent conversations

Full transcripts with every tool's JSON output are in [`docs/conversations/`](conversations/).

| # | Scenario | Question | Tools called | Outcome |
|---|---|---|---|---|
| 1 | Dataset provenance | Which dataset version trained the best model, and how to reproduce it? | `mlflow_find_best_run`, `dvc_get_reproduction_steps` | `dataset-v2.0`, MD5, exact `git checkout` + `dvc pull` commands |
| 2 | Model selection | Compare the last five runs and recommend a candidate. Production-ready? | `mlflow_list_experiments`, `mlflow_list_runs`, `mlflow_compare_runs`, `kubernetes_get_deployed_version`, `mlflow_get_run_details` | Gradient boosting (F1 0.7176) with quality-gate and `git.dirty` caveats |
| 3 | Pipeline execution | Trigger the training pipeline and report the result. | `airflow_trigger_dag` (after approval), `airflow_wait_for_dag_run` | Run succeeded, 11/11 tasks with durations |
| 4 | Deployment diagnosis | Is the prediction API healthy? | `kubernetes_find_unhealthy_pods`, `kubernetes_inspect_services`, `kubernetes_get_deployed_version` | 2 healthy pods, 2 ready endpoints, `model-v2` |
| 5 | Multi-tool reasoning | Best recent model, its dataset, deployment status, retraining needed? | 7 calls across MLflow, DVC, Kubernetes and Airflow | No retraining: same dataset, identical metrics, gates passed, recent runs succeeded |

Safety checks in the same sessions: restarting `coredns` in `kube-system` returned
`permission_denied` with no API call; restarting `adult-income-api` paused for confirmation and was
not executed after the user answered `n`.

## 5. Failure investigations

Both failures are injected and restored by `scripts/run_failure_scenarios.py`; transcripts are
saved as `docs/conversations/failure-1-*.md` and `failure-2-*.md`.

### Failure 1 — corrupted dataset (data and workflow layers)

- **Injection:** `data/adult.csv` truncated to 500 rows (validation requires at least 1,000).
- **Symptom:** DAG run fails; `validate_data` fails on all 3 attempts; every downstream task is
  `upstream_failed`; no model is registered.
- **Agent evidence path:** `airflow_wait_for_dag_run` → `airflow_get_task_logs` (`DataValidationError:
  only 500 rows, need at least 1000`) → `dvc_get_current_dataset_version`
  (`workspace_matches_committed_version: false`).
- **Root cause:** the workspace file was modified after the last DVC commit; the committed
  `dataset-v2.0` is intact.
- **Resolution:** `dvc checkout data/adult.csv.dvc` restores the committed version; re-trigger the DAG.

### Failure 2 — broken model path (infrastructure layer)

- **Injection:** ConfigMap `MODEL_PATH` set to `/app/model-missing` and pods recreated.
- **Symptom:** both pods `0/1` Ready, Service has 0 ready endpoints, the API is unavailable.
  Liveness stays healthy, so pods do not crash-loop and keep their logs.
- **Agent evidence path:** `kubernetes_find_unhealthy_pods` (not Ready, readiness-probe warning
  events) → `kubernetes_get_pod_details` (log: `Model failed to load from /app/model-missing:
  FileNotFoundError`) → `kubernetes_inspect_services` (0 ready endpoints).
- **Root cause:** the ConfigMap points the API at a model directory that does not exist in the image.
- **Resolution:** re-apply `kubernetes/configmap.yaml` and restart the pods.

### Unexpected failures found while testing the agent

| Symptom | Root cause | Fix |
|---|---|---|
| MLflow container restart loop | SQLAlchemy 2.1 defaults `postgresql://` to psycopg 3, image had psycopg2 | `postgresql+psycopg://` and psycopg 3 |
| `rollout_complete: false` on a healthy rollout | Runtime reports `docker.io/library/<image>`, manifest says `<image>` | Normalise image names; also compare replica counts |
| Empty agent answer after successful tools | Model returned no text content after its tool calls | One retry with a nudge, then a code-built tool summary |
| Answer cut off mid-table | Conversation history filled the 16K context | Oldest turns trimmed automatically; `finish_reason: length` flagged |
| Claims about systems not queried | Model reused earlier turns' evidence | Per-question coverage guard |
| Wrong root cause for a corrupted dataset | DVC tool read the committed pointer, not the file on disk | Tool now hashes the workspace file and reports mismatches |

## 6. Testing, reliability and safety

127 pytest tests run in CI with every external system mocked (MLflow uses a temporary SQLite
store; DVC, Airflow, Kubernetes and the LLM are fakes).

| Requirement | Tests |
|---|---|
| Successful tool selection and execution | `test_agent_selects_and_executes_requested_tool`, `test_multi_tool_request_gathers_evidence_from_all_four_services` |
| Tool timeouts | `test_slow_tool_times_out_as_unavailable`, `test_command_timeout_raises_timeout_error`, `test_timeout_becomes_service_unavailable` |
| Invalid requests | `test_unknown_tool_is_reported_back_as_invalid_input`, `test_invalid_inputs_are_rejected`, `test_malformed_*` |
| Service failures | `test_unreachable_*`, `test_server_error_is_wrapped_as_service_unavailable`, `test_llm_http_error_raises_unavailable` |
| No invented results | `test_agent_does_not_present_results_from_an_unavailable_tool` |
| Unauthorized Kubernetes changes rejected | `test_unauthorized_kubernetes_namespace_is_rejected`, `test_other_namespaces_are_rejected_before_any_api_call`, `test_model_cannot_confirm_its_own_state_change` |
| Structured logs without secrets | `test_structured_log_records_tool_call_without_secrets` |
| Retraining not automatic | `test_retraining_is_not_started_without_confirmation`, `test_declined_action_is_never_executed` |

Each tool call is logged as one JSON line in `logs/agent.log` with `request_id`, `tool`,
`status`, `duration_ms`, `confirmed` and `error`; secret values are replaced by `***REDACTED***`.

## 7. Known limitations and proposed improvements

| Limitation | Improvement |
|---|---|
| A 9B local model follows long instructions inconsistently; code guards compensate | Larger model or structured planning step; evaluate answers automatically on a fixed question set |
| The coverage guard detects required systems by keywords | Let the model output a declared plan, validated against the question |
| No drift or performance monitoring, so retraining advice cannot use degradation data | Log prediction distributions from the API and compare them with training data |
| Training is deterministic on the same data, so repeated runs give identical metrics | Hyperparameter search per run; record seeds as parameters |
| Kubernetes token expires after 24 hours and is refreshed manually | Short-lived tokens issued automatically per agent session |
| Single-node kind, single SeaweedFS node, LocalExecutor | Managed Kubernetes, replicated object storage, CeleryExecutor or KubernetesExecutor |
| FastAPI and MLflow have no authentication | Add API keys or OIDC at an ingress; enable MLflow authentication |
| Secrets live in a local `.env` file | External secret manager (for example Vault) with Kubernetes Secrets |
| Model is baked into the image; promotion needs a rebuild | GitOps promotion (Argo CD) triggered by registry alias changes |
