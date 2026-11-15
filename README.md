# Production-Ready MLOps AI Agent

A conversational agent that answers operational questions about a machine-learning system by
calling tools against **DVC**, **MLflow**, **Apache Airflow** and **Kubernetes**, and grounds
every claim in those tool results. The model is an Adult Income classifier served by a FastAPI
application on a local kind cluster.

See [architecture.md](architecture.md) for the design and
[docs/technical_report.md](docs/technical_report.md) for evidence and evaluation.

## Repository layout

| Path | Purpose |
|---|---|
| `agent/` | CLI, orchestrator, LLM client, tool registry/executor, logging, schemas |
| `agent/tools/` | DVC, MLflow, Airflow and Kubernetes tools plus the safe command runner |
| `api/` | FastAPI inference service (`/health`, `/ready`, `/version`, `/predict`) |
| `dags/training_pipeline.py` | Airflow DAG: validate → preprocess → train → evaluate → gate → register |
| `training/train.py` | Training, evaluation, provenance tagging and model registration |
| `kubernetes/` | Namespace, RBAC, ConfigMap, Deployment, Service, Kustomization |
| `docker/`, `Dockerfile`, `docker-compose.yml` | MLflow, Airflow and API images; local services |
| `scripts/` | Setup, deployment, live checks, failure injection and scenario runners |
| `tests/` | 127 pytest tests; all external systems are mocked |
| `docs/conversations/` | Recorded agent conversations with tool evidence |

## 1. Prerequisites

Tested on Windows 11 + WSL2 (Ubuntu 24.04), 32 GB RAM, NVIDIA RTX 4080 Laptop GPU (12 GB).

| Tool | Version | Install |
|---|---|---|
| Docker Engine + Compose plugin | Compose v5.7 | Docker apt repository inside WSL |
| uv | 0.13 | `curl -LsSf https://astral.sh/uv/install.sh \| sudo env UV_INSTALL_DIR=/usr/local/bin sh` |
| kind, kubectl | v0.32.0, v1.36.1 | `./scripts/install_kubernetes_tools.sh` (checksums verified) |
| Ollama + `qwen3.5:9b` | latest | `curl -fsSL https://ollama.com/install.sh \| sh` then `ollama pull qwen3.5:9b` |

## 2. Installation

```bash
git clone git@github.com:AinaFatima4/mlops_ai_agent.git
cd mlops_ai_agent
uv sync --locked
source .venv/bin/activate
```

## 3. Environment configuration

All secrets live in `.env`, which is git-ignored. `.env.example` lists every variable.

```bash
cp .env.example .env
sed -i "s/^SEAWEEDFS_ACCESS_KEY=.*/SEAWEEDFS_ACCESS_KEY=$(openssl rand -hex 10)/" .env
sed -i "s/^SEAWEEDFS_SECRET_KEY=.*/SEAWEEDFS_SECRET_KEY=$(openssl rand -hex 24)/" .env
sed -i "s/^MLFLOW_POSTGRES_PASSWORD=.*/MLFLOW_POSTGRES_PASSWORD=$(openssl rand -hex 16)/" .env
sed -i '/^AIRFLOW_/d' .env
./scripts/setup_airflow_secrets.sh
```

`setup_airflow_secrets.sh` generates the Airflow database password, JWT secret and the admin and
`mlops_agent` passwords, and writes `airflow/simple_auth_manager_passwords.json` (git-ignored).

To give Ollama enough context for 26 tool schemas:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_CONTEXT_LENGTH=16384"\n' | sudo tee /etc/systemd/system/ollama.service.d/override.conf
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

## 4. Launching each service

### Storage, MLflow and Airflow

```bash
docker compose up -d --build
docker exec -i seaweedfs weed shell <<< "s3.bucket.create -name dvc-storage"
docker exec -i seaweedfs weed shell <<< "s3.bucket.create -name mlflow-artifacts"
docker compose ps
```

| Service | URL |
|---|---|
| MLflow UI | http://localhost:5000 (switch to **Model training** mode) |
| Airflow UI | http://localhost:8080 (user `admin`, password `AIRFLOW_ADMIN_PASSWORD` in `.env`) |
| SeaweedFS S3 | http://localhost:8333 |

### DVC

```bash
set -a; source .env; set +a
dvc remote modify --local seaweedfs access_key_id "$SEAWEEDFS_ACCESS_KEY"
dvc remote modify --local seaweedfs secret_access_key "$SEAWEEDFS_SECRET_KEY"
dvc pull
```

On a machine without access to the original storage, rebuild the versions instead:
`python scripts/download_dataset.py` (v1.0), then `python scripts/clean_dataset.py` (v2.0).

Reproduce any dataset version:

```bash
git checkout dataset-v1.0 -- data/adult.csv.dvc && dvc checkout
git checkout main -- data/adult.csv.dvc && dvc checkout
```

### Training

Either trigger the Airflow DAG `adult_income_training` (UI, API or the agent), or run locally:

```bash
uv run python -m training.train --register
```

### Kubernetes deployment

```bash
./scripts/setup_kind_cluster.sh
./scripts/deploy_api.sh
kubectl -n mlops-app get deploy,pods,svc,configmap
kubectl -n mlops-app port-forward svc/adult-income-api 8000:80   # then open http://localhost:8000/docs
```

`deploy_api.sh` exports `adult-income-classifier@candidate`, builds `adult-income-api:model-v<N>`,
loads it into kind, applies `kubernetes/` with Kustomize and writes the agent's restricted
kubeconfig to `.kube/mlops-agent.kubeconfig` (git-ignored, token valid for 24 hours; refresh with
`./scripts/create_agent_kubeconfig.sh`).

## 5. Running the tests

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

GitHub Actions (`.github/workflows/ci.yml`) runs the same lint and test jobs on every pull request
and push to `main`. Live end-to-end checks against the running services:

```bash
./scripts/check_dvc_module.sh
./scripts/check_mlflow_module.sh
./scripts/check_airflow_module.sh
./scripts/check_kubernetes_module.sh
./scripts/check_agent_module.sh
```

## 6. Using the agent

```bash
uv run python -m agent.main --save-transcript
```

Type a question, `reset` to clear the context, or `exit`. State-changing actions (triggering the
DAG, restarting the Deployment) stop at `Approve this action? [y/N]`. Every answer ends with an
evidence list of the tools called and their status; JSON logs are written to `logs/agent.log`.

Example questions:

- Which dataset version was used to train the best model by F1, and how would I reproduce it?
- Compare the last five training runs and recommend the best candidate. Is it production-ready?
- Trigger the model training pipeline and report whether execution succeeded.
- Is my prediction API healthy? Check the pods, the service endpoints and the deployed model version.
- Find the best recent model, identify the dataset version used to train it, check the deployment
  status, and explain whether retraining is necessary.

Switch LLM provider by editing `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY` in `.env`; any
OpenAI-compatible endpoint works.

## 7. Failure demonstrations

```bash
uv run python -m scripts.run_failure_scenarios
```

Injects a corrupted dataset and a broken model path in turn, lets the agent diagnose each one,
saves both transcripts to `docs/conversations/`, and always restores the system afterwards.
