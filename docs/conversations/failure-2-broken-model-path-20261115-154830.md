# Agent failure-2-broken-model-path (20261115-154830 UTC)

## System evidence: pods while broken

`kubectl --context kind-mlops -n mlops-app get pods`

```
NAME                                READY   STATUS    RESTARTS   AGE
adult-income-api-646d56c894-66knn   0/1     Running   0          6s
adult-income-api-646d56c894-vm7hk   0/1     Running   0          6s
```

## User

Why is my prediction API unavailable?

## Agent

## Why Your Prediction API is Unavailable

### Facts
- **Kubernetes deployment state**: The `adult-income-api` deployment has 2 pods, both Running but neither Ready (0 ready replicas)
- **Pod health**: Both pods fail readiness probes with HTTP 503 errors
- **Root cause from logs**: Model failed to load from `/app/model-missing/MLmodel` - FileNotFoundError: No such file or directory
- **Service status**: The service has 0 ready endpoints (not serving traffic)
- **Recent training runs**: Last 3 Airflow DAG runs (`adult_income_training`) have FAILED, with `validate_data` task failing
- **Best model available**: gradient_boosting run (F1=0.718) using dataset-v2.0 (MD5: 06769c0a96e9ab07b8d9e2c1255a976b), quality gate passed
- **Dataset version**: Current DVC-tracked dataset is dataset-v2.0 with the same MD5 as the best MLflow run

### Uncertainties
- Whether any model was successfully registered in MLflow after the failed training runs
- The exact reason for `validate_data` task failures (data quality issue, missing file, or other error)
- Whether the deployment image tag `model-v2` corresponds to a valid model build

### Recommended Actions
1. **Investigate failed training**: Check why `validate_data` task is failing in recent Airflow runs - this prevents model registration and deployment
2. **Fix data validation**: Resolve whatever issue causes validate_data to fail (check data quality, file paths, or preprocessing)
3. **Re-run training pipeline**: Once validation passes, trigger a new DAG run to train models, register them, and deploy
4. **Verify deployment**: After successful training, confirm the new model is deployed and pods become Ready

The API is unavailable because recent training runs failed before completing, leaving no valid model file at `/app/model-missing/MLmodel`. The container starts but cannot load its model, causing 503 errors on all requests.

<details><summary>kubernetes_list_workloads: success (11 ms)</summary>

```json
{
  "namespace": "mlops-app",
  "deployments": [
    {
      "name": "adult-income-api",
      "desired_replicas": 2,
      "ready_replicas": 0,
      "available_replicas": 0,
      "updated_replicas": 2,
      "images": [
        "adult-income-api:model-v2"
      ]
    }
  ],
  "pods": [
    {
      "name": "adult-income-api-646d56c894-66knn",
      "phase": "Running",
      "ready": false,
      "restart_count": 0,
      "node": "mlops-control-plane",
      "images": [
        "docker.io/library/adult-income-api:model-v2"
      ],
      "created_at": "2026-11-15T15:48:30+00:00"
    },
    {
      "name": "adult-income-api-646d56c894-vm7hk",
      "phase": "Running",
      "ready": false,
      "restart_count": 0,
      "node": "mlops-control-plane",
      "images": [
        "docker.io/library/adult-income-api:model-v2"
      ],
      "created_at": "2026-11-15T15:48:30+00:00"
    }
  ]
}
```
</details>

<details><summary>kubernetes_find_unhealthy_pods: success (6 ms)</summary>

```json
{
  "namespace": "mlops-app",
  "total_pods": 2,
  "unhealthy_pods": [
    {
      "name": "adult-income-api-646d56c894-66knn",
      "phase": "Running",
      "problems": [
        "pod is not Ready"
      ]
    },
    {
      "name": "adult-income-api-646d56c894-vm7hk",
      "phase": "Running",
      "problems": [
        "pod is not Ready"
      ]
    }
  ],
  "all_healthy": false,
  "recent_warning_events": [
    {
      "type": "Warning",
      "reason": "Failed",
      "object": "Pod/adult-income-api-646d56c894-5fkh6",
      "message": "Error: services have not yet been read at least once, cannot construct envvars",
      "count": 1,
      "last_seen": "2026-11-15T15:27:54+00:00"
    },
    {
      "type": "Warning",
      "reason": "BackOff",
      "object": "Pod/adult-income-api-646d56c894-5fkh6",
      "message": "Back-off restarting failed container api in pod adult-income-api-646d56c894-5fkh6_mlops-app(699d9e51-082b-47fd-a8e8-6e17cd65b81e)",
      "count": 3,
      "last_seen": "2026-11-15T15:27:57+00:00"
    },
    {
      "type": "Warning",
      "reason": "Unhealthy",
      "object": "Pod/adult-income-api-646d56c894-66knn",
      "message": "Readiness probe failed: HTTP probe failed with statuscode: 503",
      "count": 1,
      "last_seen": "2026-11-15T15:48:36+00:00"
    },
    {
      "type": "Warning",
      "reason": "Failed",
      "object": "Pod/adult-income-api-646d56c894-v2qg7",
      "message": "Error: services have not yet been read at least once, cannot construct envvars",
      "count": 1,
      "last_seen": "2026-11-15T15:27:54+00:00"
    },
    {
      "type": "Warning",
      "reason": "BackOff",
      "object": "Pod/adult-income-api-646d56c894-v2qg7",
      "message": "Back-off restarting failed container api in pod adult-income-api-646d56c894-v2qg7_mlops-app(0b7acb5a-0beb-47de-8b32-cd68441d87d3)",
      "count": 3,
      "last_seen": "2026-11-15T15:27:58+00:00"
    },
    {
      "type": "Warning",
      "reason": "Unhealthy",
      "object": "Pod/adult-income-api-646d56c894-vm7hk",
      "message": "Readiness probe failed: HTTP probe failed with statuscode: 503",
      "count": 1,
      "last_seen": "2026-11-15T15:48:36+00:00"
    }
  ]
}
```
</details>

<details><summary>kubernetes_inspect_services: success (6 ms)</summary>

```json
{
  "namespace": "mlops-app",
  "services": [
    {
      "name": "adult-income-api",
      "type": "ClusterIP",
      "cluster_ip": "10.96.136.200",
      "selector": {
        "app.kubernetes.io/name": "adult-income-api"
      },
      "ports": [
        {
          "name": "http",
          "port": 80,
          "target_port": "http",
          "protocol": "TCP"
        }
      ],
      "ready_endpoints": 0,
      "has_ready_endpoints": false
    }
  ]
}
```
</details>

<details><summary>kubernetes_get_deployed_version: success (6 ms)</summary>

```json
{
  "deployment": "adult-income-api",
  "desired_images": [
    "adult-income-api:model-v2"
  ],
  "desired_image_tags": [
    "model-v2"
  ],
  "running_ready_images": [],
  "rollout_complete": false,
  "service_reported_version": {
    "available": false,
    "reason": "Kubernetes API returned 503: Service Unavailable"
  }
}
```
</details>

<details><summary>kubernetes_get_pod_details: success (15 ms)</summary>

```json
{
  "name": "adult-income-api-646d56c894-66knn",
  "phase": "Running",
  "ready": false,
  "restart_count": 0,
  "node": "mlops-control-plane",
  "images": [
    "docker.io/library/adult-income-api:model-v2"
  ],
  "created_at": "2026-11-15T15:48:30+00:00",
  "containers": [
    {
      "name": "api",
      "ready": false,
      "restart_count": 0,
      "current": {
        "state": "running",
        "started_at": "2026-11-15T15:48:31+00:00"
      },
      "previous": null
    }
  ],
  "conditions": [
    {
      "type": "PodReadyToStartContainers",
      "status": "True",
      "reason": null
    },
    {
      "type": "Initialized",
      "status": "True",
      "reason": null
    },
    {
      "type": "Ready",
      "status": "False",
      "reason": "ContainersNotReady"
    },
    {
      "type": "ContainersReady",
      "status": "False",
      "reason": "ContainersNotReady"
    },
    {
      "type": "PodScheduled",
      "status": "True",
      "reason": null
    }
  ],
  "problems": [
    "pod is not Ready"
  ],
  "events": [
    {
      "type": "Normal",
      "reason": "Scheduled",
      "object": "Pod/adult-income-api-646d56c894-66knn",
      "message": "Successfully assigned mlops-app/adult-income-api-646d56c894-66knn to mlops-control-plane",
      "count": null,
      "last_seen": "2026-11-15T15:48:30.767708+00:00"
    },
    {
      "type": "Normal",
      "reason": "Pulled",
      "object": "Pod/adult-income-api-646d56c894-66knn",
      "message": "Container image \"adult-income-api:model-v2\" already present on machine and can be accessed by the pod",
      "count": 1,
      "last_seen": "2026-11-15T15:48:31+00:00"
    },
    {
      "type": "Normal",
      "reason": "Created",
      "object": "Pod/adult-income-api-646d56c894-66knn",
      "message": "Container created",
      "count": 1,
      "last_seen": "2026-11-15T15:48:31+00:00"
    },
    {
      "type": "Normal",
      "reason": "Started",
      "object": "Pod/adult-income-api-646d56c894-66knn",
      "message": "Container started",
      "count": 1,
      "last_seen": "2026-11-15T15:48:31+00:00"
    },
    {
      "type": "Warning",
      "reason": "Unhealthy",
      "object": "Pod/adult-income-api-646d56c894-66knn",
      "message": "Readiness probe failed: HTTP probe failed with statuscode: 503",
      "count": 2,
      "last_seen": "2026-11-15T15:48:41+00:00"
    }
  ],
  "current_logs": [
    "INFO:     Started server process [1]",
    "INFO:     Waiting for application startup.",
    "2026-11-15 15:48:35,011 ERROR adult_income_api Model failed to load from /app/model-missing: FileNotFoundError: [Errno 2] No such file or directory: '/app/model-missing/MLmodel'",
    "INFO:     Application startup complete.",
    "INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)",
    "INFO:     10.244.0.1:43496 - \"GET /ready HTTP/1.1\" 503 Service Unavailable",
    "INFO:     10.244.0.1:55896 - \"GET /health HTTP/1.1\" 200 OK",
    "INFO:     10.244.0.1:55902 - \"GET /ready HTTP/1.1\" 503 Service Unavailable"
  ],
  "previous_logs": null
}
```
</details>

<details><summary>airflow_list_dag_runs: success (33 ms)</summary>

```json
{
  "dag_id": "adult_income_training",
  "dag_runs": [
    {
      "dag_id": "adult_income_training",
      "dag_run_id": "manual__2026-11-15T15:46:02.946055+00:00",
      "state": "failed",
      "run_type": "manual",
      "triggered_by": "rest_api",
      "start_date": "2026-11-15T15:46:03.787113Z",
      "end_date": "2026-11-15T15:47:14.062774Z",
      "duration_seconds": 70.275661
    },
    {
      "dag_id": "adult_income_training",
      "dag_run_id": "manual__2026-11-15T15:29:09.188499+00:00",
      "state": "failed",
      "run_type": "manual",
      "triggered_by": "rest_api",
      "start_date": "2026-11-15T15:29:09.627139Z",
      "end_date": "2026-11-15T15:30:24.191648Z",
      "duration_seconds": 74.564509
    },
    {
      "dag_id": "adult_income_training",
      "dag_run_id": "manual__2026-11-15T00:28:43.681510+00:00",
      "state": "failed",
      "run_type": "manual",
      "triggered_by": "rest_api",
      "start_date": "2026-11-15T00:28:43.878765Z",
      "end_date": "2026-11-15T00:29:55.315593Z",
      "duration_seconds": 71.436828
    },
    {
      "dag_id": "adult_income_training",
      "dag_run_id": "manual__2026-11-15T00:08:05.905401+00:00",
      "state": "success",
      "run_type": "manual",
      "triggered_by": "rest_api",
      "start_date": "2026-11-15T00:08:06.305691Z",
      "end_date": "2026-11-15T00:08:31.275144Z",
      "duration_seconds": 24.969453
    },
    {
      "dag_id": "adult_income_training",
      "dag_run_id": "manual__2026-11-14T23:57:31.980064+00:00",
      "state": "success",
      "run_type": "manual",
      "triggered_by": "rest_api",
      "start_date": "2026-11-14T23:57:32.758485Z",
      "end_date": "2026-11-14T23:57:59.505134Z",
      "duration_seconds": 26.746649
    }
  ]
}
```
</details>

<details><summary>mlflow_list_experiments: success (126 ms)</summary>

```json
{
  "experiments": [
    {
      "experiment_id": "1",
      "name": "adult-income",
      "creation_time": "2026-11-14T22:31:17.513000+00:00"
    },
    {
      "experiment_id": "0",
      "name": "Default",
      "creation_time": "2026-11-14T22:31:15.154000+00:00"
    }
  ]
}
```
</details>

<details><summary>airflow_get_failed_tasks: success (30 ms)</summary>

```json
{
  "dag_id": "adult_income_training",
  "dag_run_id": "manual__2026-11-15T15:46:02.946055+00:00",
  "failed_tasks": [
    {
      "task_id": "validate_data",
      "map_index": -1,
      "state": "failed",
      "try_number": 3,
      "duration_seconds": 1.663161
    }
  ],
  "blocked_tasks": [
    {
      "task_id": "preprocess",
      "map_index": -1,
      "state": "upstream_failed",
      "try_number": 0,
      "duration_seconds": 0.0
    },
    {
      "task_id": "evaluate_model",
      "map_index": -1,
      "state": "upstream_failed",
      "try_number": 0,
      "duration_seconds": 0.0
    },
    {
      "task_id": "collect_evaluation_results",
      "map_index": -1,
      "state": "upstream_failed",
      "try_number": 0,
      "duration_seconds": 0.0
    },
    {
      "task_id": "quality_gate",
      "map_index": -1,
      "state": "upstream_failed",
      "try_number": 0,
      "duration_seconds": 0.0
    },
    {
      "task_id": "register_candidate",
      "map_index": -1,
      "state": "upstream_failed",
      "try_number": 0,
      "duration_seconds": 0.0
    },
    {
      "task_id": "train_model",
      "map_index": 0,
      "state": "upstream_failed",
      "try_number": 0,
      "duration_seconds": 0.0
    },
    {
      "task_id": "train_model",
      "map_index": 1,
      "state": "upstream_failed",
      "try_number": 0,
      "duration_seconds": 0.0
    },
    {
      "task_id": "train_model",
      "map_index": 2,
      "state": "upstream_failed",
      "try_number": 0,
      "duration_seconds": 0.0
    }
  ]
}
```
</details>

<details><summary>mlflow_list_runs: success (167 ms)</summary>

```json
{
  "experiment_name": "adult-income",
  "runs": [
    {
      "run_id": "1c26db8e1e5e4ed1b509f382a353c6aa",
      "run_name": "logistic_regression-20261115-000812",
      "status": "FINISHED",
      "start_time": "2026-11-15T00:08:12.453000+00:00",
      "metrics": {
        "f1": 0.6790799561883899,
        "precision": 0.5767441860465117,
        "recall": 0.8255659121171771,
        "roc_auc": 0.901927276542334,
        "accuracy": 0.8057351234874855
      },
      "provenance": {
        "model.type": "logistic_regression",
        "dataset.path": "data/adult.csv",
        "dataset.md5": "06769c0a96e9ab07b8d9e2c1255a976b",
        "dataset.version": "dataset-v2.0",
        "git.commit": "2eba9ca905e4f9fe206c5afef10bd3c5037bac97",
        "git.dirty": "false",
        "quality_gate.passed": "true",
        "quality_gate.failures": "none",
        "model.uri": "models:/m-db34c76f97444bf98a0651f0d5334245"
      }
    },
    {
      "run_id": "87c961f206124924bcb23e7cae714ffe",
      "run_name": "random_forest-20261115-000812",
      "status": "FINISHED",
      "start_time": "2026-11-15T00:08:12.450000+00:00",
      "metrics": {
        "f1": 0.6921215380478624,
        "precision": 0.5805142083897158,
        "recall": 0.8568575233022636,
        "roc_auc": 0.9135305063711123,
        "accuracy": 0.8102105088678933
      },
      "provenance": {
        "model.type": "random_forest",
        "dataset.path": "data/adult.csv",
        "dataset.md5": "06769c0a96e9ab07b8d9e2c1255a976b",
        "dataset.version": "dataset-v2.0",
        "git.commit": "2eba9ca905e4f9fe206c5afef10bd3c5037bac97",
        "git.dirty": "false",
        "quality_gate.passed": "true",
        "quality_gate.failures": "none",
        "model.uri": "models:/m-6a278d9c70fe4428ac1b4e23b34da834"
      }
    },
    {
      "run_id": "6abf2cea17604e538859f9c565d9354c",
      "run_name": "gradient_boosting-20261115-000812",
      "status": "FINISHED",
      "start_time": "2026-11-15T00:08:12.417000+00:00",
      "metrics": {
        "f1": 0.7176173082326496,
        "precision": 0.6208070004861449,
        "recall": 0.8501997336884154,
        "roc_auc": 0.9233298440305151,
        "accuracy": 0.8334162108403779
      },
      "provenance": {
        "model.type": "gradient_boosting",
        "dataset.path": "data/adult.csv",
        "dataset.md5": "06769c0a96e9ab07b8d9e2c1255a976b",
        "dataset.version": "dataset-v2.0",
        "git.commit": "2eba9ca905e4f9fe206c5afef10bd3c5037bac97",
        "git.dirty": "false",
        "quality_gate.passed": "true",
        "quality_gate.failures": "none",
        "model.uri": "models:/m-e33962178bc74463807fce06302181a6"
      }
    },
    {
      "run_id": "868de00cd13a4005bbcef4c0304c18c1",
      "run_name": "logistic_regression-20261114-235743",
      "status": "FINISHED",
      "start_time": "2026-11-14T23:57:43.564000+00:00",
      "metrics": {
        "f1": 0.6790799561883899,
        "precision": 0.5767441860465117,
        "recall": 0.8255659121171771,
        "roc_auc": 0.901927276542334,
        "accuracy": 0.8057351234874855
      },
      "provenance": {
        "model.type": "logistic_regression",
        "dataset.path": "data/adult.csv",
        "dataset.md5": "06769c0a96e9ab07b8d9e2c1255a976b",
        "dataset.version": "dataset-v2.0",
        "git.commit": "4c72dd142e9e5980be0b0ba21cc1be0318ec2e70",
        "git.dirty": "true",
        "quality_gate.passed": "true",
        "quality_gate.failures": "none",
        "model.uri": "models:/m-fd634771d02640d4a8661bc675600c88"
      }
    },
    {
      "run_id": "0a8ce8d63e534a998b43adb0232bf990",
      "run_name": "random_forest-20261114-235743",
      "status": "FINISHED",
      "start_time": "2026-11-14T23:57:43.146000+00:00",
      "metrics": {
        "f1": 0.6921215380478624,
        "precision": 0.5805142083897158,
        "recall": 0.8568575233022636,
        "roc_auc": 0.9135305063711123,
        "accuracy": 0.8102105088678933
      },
      "prove
```
</details>

<details><summary>mlflow_find_best_run: success (76 ms)</summary>

```json
{
  "metric": "f1",
  "runs_considered": 5,
  "best_run": {
    "run_id": "6abf2cea17604e538859f9c565d9354c",
    "run_name": "gradient_boosting-20261115-000812",
    "status": "FINISHED",
    "start_time": "2026-11-15T00:08:12.417000+00:00",
    "metrics": {
      "f1": 0.7176173082326496,
      "precision": 0.6208070004861449,
      "recall": 0.8501997336884154,
      "roc_auc": 0.9233298440305151,
      "accuracy": 0.8334162108403779
    },
    "provenance": {
      "model.type": "gradient_boosting",
      "dataset.path": "data/adult.csv",
      "dataset.md5": "06769c0a96e9ab07b8d9e2c1255a976b",
      "dataset.version": "dataset-v2.0",
      "git.commit": "2eba9ca905e4f9fe206c5afef10bd3c5037bac97",
      "git.dirty": "false",
      "quality_gate.passed": "true",
      "quality_gate.failures": "none",
      "model.uri": "models:/m-e33962178bc74463807fce06302181a6"
    }
  },
  "runner_up": {
    "run_id": "87c961f206124924bcb23e7cae714ffe",
    "run_name": "random_forest-20261115-000812",
    "status": "FINISHED",
    "start_time": "2026-11-15T00:08:12.450000+00:00",
    "metrics": {
      "f1": 0.6921215380478624,
      "precision": 0.5805142083897158,
      "recall": 0.8568575233022636,
      "roc_auc": 0.9135305063711123,
      "accuracy": 0.8102105088678933
    },
    "provenance": {
      "model.type": "random_forest",
      "dataset.path": "data/adult.csv",
      "dataset.md5": "06769c0a96e9ab07b8d9e2c1255a976b",
      "dataset.version": "dataset-v2.0",
      "git.commit": "2eba9ca905e4f9fe206c5afef10bd3c5037bac97",
      "git.dirty": "false",
      "quality_gate.passed": "true",
      "quality_gate.failures": "none",
      "model.uri": "models:/m-6a278d9c70fe4428ac1b4e23b34da834"
    }
  },
  "warnings": [
    "Selected by f1 alone. Production readiness also needs a passed quality gate, current training data and a healthy deployment."
  ]
}
```
</details>

<details><summary>dvc_list_tracked_datasets: success (13 ms)</summary>

```json
{
  "datasets": [
    {
      "dataset_path": "data/adult.csv",
      "pointer_file": "data/adult.csv.dvc",
      "md5": "06769c0a96e9ab07b8d9e2c1255a976b",
      "size_bytes": 3328203
    }
  ]
}
```
</details>

<details><summary>dvc_find_version_by_hash: success (13 ms)</summary>

```json
{
  "dataset_path": "data/adult.csv",
  "md5": "06769c0a96e9ab07b8d9e2c1255a976b",
  "found": true,
  "version": {
    "version": "dataset-v2.0",
    "git_commit": "20f0e1015f83c816debfd6a5b1129a3c540501a4",
    "created_at": "2026-11-14T17:04:27-05:00",
    "md5": "06769c0a96e9ab07b8d9e2c1255a976b",
    "size_bytes": 3328203
  }
}
```
</details>

<details><summary>dvc_list_dataset_versions: success (11 ms)</summary>

```json
{
  "dataset_path": "data/adult.csv",
  "versions": [
    {
      "version": "dataset-v1.0",
      "git_commit": "3ac5adf9a1e1f9e360e3aad7597a124a265cec08",
      "created_at": "2026-11-14T16:59:43-05:00",
      "md5": "910d8ebecaaa49bd45cc3f208dc755bb",
      "size_bytes": 4007022
    },
    {
      "version": "dataset-v2.0",
      "git_commit": "20f0e1015f83c816debfd6a5b1129a3c540501a4",
      "created_at": "2026-11-14T17:04:27-05:00",
      "md5": "06769c0a96e9ab07b8d9e2c1255a976b",
      "size_bytes": 3328203
    }
  ]
}
```
</details>

## System evidence: pods after restore

`kubectl --context kind-mlops -n mlops-app get pods`

```
NAME                                READY   STATUS    RESTARTS   AGE
adult-income-api-646d56c894-5wsrj   1/1     Running   0          6s
adult-income-api-646d56c894-xjtbl   1/1     Running   0          6s
```
