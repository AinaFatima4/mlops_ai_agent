# Agent failure-1-corrupted-dataset (20261115-154553 UTC)

## System evidence: dataset row count after injection

`wc -l data/adult.csv`

```
501 data/adult.csv
```

## User

Trigger the model training pipeline and report whether execution succeeded.

## Agent

Before I continue, please confirm: trigger a new run of Airflow DAG 'adult_income_training'

<details><summary>airflow_list_dags: success (48 ms)</summary>

```json
{
  "dags": [
    {
      "dag_id": "adult_income_training",
      "is_paused": false,
      "tags": [
        "mlops",
        "training"
      ],
      "trigger_approved": true
    }
  ],
  "import_errors": []
}
```
</details>

## User

Approved (scripted answer at the confirmation prompt)

## Agent

## Model Training Pipeline Execution Result: **FAILED**

### Root Cause Analysis

The training pipeline failed due to a **data validation error**:

1. **Failed Task**: `validate_data` (after 3 retry attempts)
2. **Error Message**: "only 500 rows, need at least 1000"
3. **Root Issue**: The workspace file `data/adult.csv` does NOT match the committed DVC version

### Evidence from Systems

| System | Finding |
|--------|---------|
| **Airflow** | DAG run `manual__2026-11-15T15:46:02.946055+00:00` failed with 8 upstream_failed tasks and 1 failed task (validate_data) |
| **DVC Workspace** | File MD5 mismatch: committed `06769c0a96e9ab07b8d9e2c1255a976b` vs workspace `4e621ca43aa9af8d8d11947488e44044` |
| **DVC File Size** | Committed: 3,328,203 bytes vs Workspace: 55,417 bytes (only 501 lines) |
| **Deployed Model** | Using `dataset-v2.0` (MD5: 06769c0a96e9ab07b8d9e2c1255a976b) |

### Facts
- The workspace file has been modified/corrupted and no longer matches the committed DVC version `dataset-v2.0`
- The dataset currently in the workspace only contains 500 data rows (plus header), far below the required 1000 minimum
- Available tagged versions: `dataset-v1.0` (4,007,022 bytes) and `dataset-v2.0` (3,328,203 bytes)

### Uncertainties
- What caused the workspace file to be modified? (manual edit, corrupted download, or other issue?)
- Whether restoring with `dvc checkout` will recover the original committed version

### Recommended Actions
1. **Restore the dataset** to its committed version:
   ```bash
   dvc checkout data/adult.csv.dvc
   ```
2. **Verify restoration** by checking that workspace matches committed version
3. **Re-trigger the training pipeline** after confirming the file is restored
4. If the issue persists, investigate whether the DVC remote storage has integrity issues or if a different dataset file was accidentally placed in the workspace

<details><summary>airflow_list_dags: success (48 ms)</summary>

```json
{
  "dags": [
    {
      "dag_id": "adult_income_training",
      "is_paused": false,
      "tags": [
        "mlops",
        "training"
      ],
      "trigger_approved": true
    }
  ],
  "import_errors": []
}
```
</details>

<details><summary>airflow_trigger_dag: success (46 ms)</summary>

```json
{
  "dag_id": "adult_income_training",
  "dag_run_id": "manual__2026-11-15T15:46:02.946055+00:00",
  "state": "queued",
  "run_type": "manual",
  "triggered_by": "rest_api",
  "start_date": null,
  "end_date": null,
  "duration_seconds": null
}
```
</details>

<details><summary>airflow_wait_for_dag_run: success (70250 ms)</summary>

```json
{
  "dag_id": "adult_income_training",
  "dag_run_id": "manual__2026-11-15T15:46:02.946055+00:00",
  "state": "failed",
  "run_type": "manual",
  "triggered_by": "rest_api",
  "start_date": "2026-11-15T15:46:03.787113Z",
  "end_date": "2026-11-15T15:47:14.062774Z",
  "duration_seconds": 70.275661,
  "task_state_counts": {
    "upstream_failed": 8,
    "failed": 1
  },
  "tasks": [
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
      "task_id": "validate_data",
      "map_index": -1,
      "state": "failed",
      "try_number": 3,
      "duration_seconds": 1.663161
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
  ],
  "finished": true,
  "waited_seconds": 70
}
```
</details>

<details><summary>airflow_get_failed_tasks: success (20 ms)</summary>

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

<details><summary>airflow_get_task_logs: success (26 ms)</summary>

```json
{
  "dag_id": "adult_income_training",
  "dag_run_id": "manual__2026-11-15T15:46:02.946055+00:00",
  "task_id": "validate_data",
  "map_index": -1,
  "try_number": 3,
  "exceptions": [
    {
      "type": "AirflowException",
      "message": "Process returned non-zero exit status 1.\nonly 500 rows, need at least 1000"
    }
  ],
  "error_lines": [
    "2026-11-15T15:47:09.816566Z INFO Traceback (most recent call last):",
    "2026-11-15T15:47:10.005517Z ERROR Task failed with exception"
  ],
  "last_lines": [
    "::group::Log message source details",
    "/opt/airflow/logs/dag_id=adult_income_training/run_id=manual__2026-11-15T15:46:02.946055+00:00/task_id=validate_data/attempt=3.log",
    "::endgroup::",
    "2026-11-15T15:47:08.352697Z INFO ::group::Pre Execute",
    "2026-11-15T15:47:08.368656Z INFO DAG bundles loaded: dags-folder",
    "2026-11-15T15:47:08.369488Z INFO Filling up the DagBag from /opt/airflow/dags/training_pipeline.py",
    "2026-11-15T15:47:08.389689Z INFO Worker startup parse complete",
    "2026-11-15T15:47:08.408260Z INFO ::endgroup::",
    "2026-11-15T15:47:08.447895Z INFO Use 'pickle' as serializer.",
    "2026-11-15T15:47:08.458186Z INFO Executing cmd: /opt/training-venv/bin/python /tmp/venv-call_h7q4sx6/script.py /tmp/venv-call_h7q4sx6/script.in /tmp/venv-call_h7q4sx6/script.out /tmp/venv-call_h7q4sx6/string_args.txt /tmp/venv-call_h7q4sx6/termination.log /tmp/venv-call_h7q4sx6/airflow_context.json",
    "2026-11-15T15:47:08.458625Z INFO Output:",
    "2026-11-15T15:47:09.816566Z INFO Traceback (most recent call last):",
    "2026-11-15T15:47:09.816709Z INFO   File \"/tmp/venv-call_h7q4sx6/script.py\", line 60, in <module>",
    "2026-11-15T15:47:09.816796Z INFO     res = validate_data(*arg_dict[\"args\"], **arg_dict[\"kwargs\"])",
    "2026-11-15T15:47:09.816855Z INFO           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^",
    "2026-11-15T15:47:09.816906Z INFO   File \"/tmp/venv-call_h7q4sx6/script.py\", line 35, in validate_data",
    "2026-11-15T15:47:09.816941Z INFO     validate_dataset(dataset)",
    "2026-11-15T15:47:09.816990Z INFO   File \"/opt/project/training/train.py\", line 183, in validate_dataset",
    "2026-11-15T15:47:09.817030Z INFO     raise DataValidationError(\"; \".join(problems))",
    "2026-11-15T15:47:09.817074Z INFO training.train.DataValidationError: only 500 rows, need at least 1000",
    "2026-11-15T15:47:10.005517Z ERROR Task failed with exception",
    "2026-11-15T15:47:10.006582Z INFO ::group::Post Execute",
    "2026-11-15T15:47:10.008392Z INFO ::endgroup::"
  ]
}
```
</details>

<details><summary>dvc_get_current_dataset_version: success (23 ms)</summary>

```json
{
  "dataset_path": "data/adult.csv",
  "committed_version": "dataset-v2.0",
  "committed_md5": "06769c0a96e9ab07b8d9e2c1255a976b",
  "committed_size_bytes": 3328203,
  "last_pointer_commit": "20f0e1015f83c816debfd6a5b1129a3c540501a4",
  "is_tagged_version": true,
  "workspace_file": {
    "exists": true,
    "md5": "4e621ca43aa9af8d8d11947488e44044",
    "size_bytes": 55417,
    "line_count": 501
  },
  "workspace_matches_committed_version": false,
  "warning": "The file at data/adult.csv does not match the committed version (dataset-v2.0). It was modified, replaced or deleted after the last DVC commit. Restore it with 'dvc checkout data/adult.csv.dvc' or record a new version with 'dvc add'."
}
```
</details>

<details><summary>dvc_list_dataset_versions: success (9 ms)</summary>

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

<details><summary>kubernetes_get_deployed_version: success (470 ms)</summary>

```json
{
  "deployment": "adult-income-api",
  "desired_images": [
    "adult-income-api:model-v2"
  ],
  "desired_image_tags": [
    "model-v2"
  ],
  "running_ready_images": [
    "docker.io/library/adult-income-api:model-v2"
  ],
  "rollout_complete": true,
  "service_reported_version": {
    "available": true,
    "app_version": "1.0.0",
    "environment": "kind",
    "model_loaded": true,
    "model": {
      "model_name": "adult-income-classifier",
      "model_version": "2",
      "model_alias": "candidate",
      "run_id": "930195a0314e4405b412ac21fb2f1a56",
      "dataset_version": "dataset-v2.0",
      "exported_at": "2026-11-14T23:23:51.807473+00:00"
    }
  }
}
```
</details>

## User

The training pipeline failed. Find the root cause and tell me how to fix it.

## Agent

## Root Cause Analysis

The training pipeline failed because the `validate_data` task encountered an error: **"only 500 rows, need at least 1000"**.

### What happened:
- The workspace file `data/adult.csv` **does not match** its committed DVC version (dataset-v2.0)
- Workspace file: 554,17 bytes, 501 lines, MD5 `4e621ca43aa9af8d8d11947488e44044`
- Committed version (dataset-v2.0): 3,328,203 bytes, MD5 `06769c0a96e9ab07b8d9e2c1255a976b`
- The file was **modified** after the last DVC commit (not a bad tagged version)

### Why this matters:
The deployed model (`adult-income-api:model-v2`) uses dataset-v2.0, which is the correct version with sufficient rows. The pipeline failed because it's trying to train on a corrupted/modified workspace file instead of the committed dataset.

---

## How to Fix It

**Step 1: Restore the committed dataset version**
```bash
dvc checkout data/adult.csv.dvc
```

This will restore `data/adult.csv` to match the committed DVC version (dataset-v2.0).

**Step 2: Verify the fix**
```bash
dvc status
# Should show "working tree clean" or no changes
```

**Step 3: Re-trigger the training pipeline**
Once the data is restored, you can trigger a new run of the `adult_income_training` DAG.

---

## Facts
- Failed task: `validate_data` (root cause)
- Error message: "only 500 rows, need at least 1000"
- Workspace file does NOT match committed DVC version (dataset-v2.0)
- Deployed model uses dataset-v2.0 (correct version)

## Uncertainties
- Whether the workspace file was modified intentionally or accidentally
- What changes were made to the file (if any)

## Recommended actions
1. Run `dvc checkout data/adult.csv.dvc` to restore the committed dataset
2. Verify with `dvc status` that the workspace is clean
3. Trigger a new run of the `adult_income_training` DAG

<details><summary>airflow_list_dags: success (29 ms)</summary>

```json
{
  "dags": [
    {
      "dag_id": "adult_income_training",
      "is_paused": false,
      "tags": [
        "mlops",
        "training"
      ],
      "trigger_approved": true
    }
  ],
  "import_errors": []
}
```
</details>

<details><summary>dvc_check_data_changed: success (308 ms)</summary>

```json
{
  "has_changes": true,
  "changed_files": [
    {
      "path": "data/adult.csv",
      "change": "modified"
    }
  ]
}
```
</details>

<details><summary>airflow_list_dag_runs: success (31 ms)</summary>

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

<details><summary>airflow_get_failed_tasks: success (32 ms)</summary>

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

<details><summary>airflow_get_task_logs: success (18 ms)</summary>

```json
{
  "dag_id": "adult_income_training",
  "dag_run_id": "manual__2026-11-15T15:46:02.946055+00:00",
  "task_id": "validate_data",
  "map_index": -1,
  "try_number": 3,
  "exceptions": [
    {
      "type": "AirflowException",
      "message": "Process returned non-zero exit status 1.\nonly 500 rows, need at least 1000"
    }
  ],
  "error_lines": [
    "2026-11-15T15:47:09.816566Z INFO Traceback (most recent call last):",
    "2026-11-15T15:47:10.005517Z ERROR Task failed with exception"
  ],
  "last_lines": [
    "::group::Log message source details",
    "/opt/airflow/logs/dag_id=adult_income_training/run_id=manual__2026-11-15T15:46:02.946055+00:00/task_id=validate_data/attempt=3.log",
    "::endgroup::",
    "2026-11-15T15:47:08.352697Z INFO ::group::Pre Execute",
    "2026-11-15T15:47:08.368656Z INFO DAG bundles loaded: dags-folder",
    "2026-11-15T15:47:08.369488Z INFO Filling up the DagBag from /opt/airflow/dags/training_pipeline.py",
    "2026-11-15T15:47:08.389689Z INFO Worker startup parse complete",
    "2026-11-15T15:47:08.408260Z INFO ::endgroup::",
    "2026-11-15T15:47:08.447895Z INFO Use 'pickle' as serializer.",
    "2026-11-15T15:47:08.458186Z INFO Executing cmd: /opt/training-venv/bin/python /tmp/venv-call_h7q4sx6/script.py /tmp/venv-call_h7q4sx6/script.in /tmp/venv-call_h7q4sx6/script.out /tmp/venv-call_h7q4sx6/string_args.txt /tmp/venv-call_h7q4sx6/termination.log /tmp/venv-call_h7q4sx6/airflow_context.json",
    "2026-11-15T15:47:08.458625Z INFO Output:",
    "2026-11-15T15:47:09.816566Z INFO Traceback (most recent call last):",
    "2026-11-15T15:47:09.816709Z INFO   File \"/tmp/venv-call_h7q4sx6/script.py\", line 60, in <module>",
    "2026-11-15T15:47:09.816796Z INFO     res = validate_data(*arg_dict[\"args\"], **arg_dict[\"kwargs\"])",
    "2026-11-15T15:47:09.816855Z INFO           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^",
    "2026-11-15T15:47:09.816906Z INFO   File \"/tmp/venv-call_h7q4sx6/script.py\", line 35, in validate_data",
    "2026-11-15T15:47:09.816941Z INFO     validate_dataset(dataset)",
    "2026-11-15T15:47:09.816990Z INFO   File \"/opt/project/training/train.py\", line 183, in validate_dataset",
    "2026-11-15T15:47:09.817030Z INFO     raise DataValidationError(\"; \".join(problems))",
    "2026-11-15T15:47:09.817074Z INFO training.train.DataValidationError: only 500 rows, need at least 1000",
    "2026-11-15T15:47:10.005517Z ERROR Task failed with exception",
    "2026-11-15T15:47:10.006582Z INFO ::group::Post Execute",
    "2026-11-15T15:47:10.008392Z INFO ::endgroup::"
  ]
}
```
</details>

<details><summary>kubernetes_get_deployed_version: success (8 ms)</summary>

```json
{
  "deployment": "adult-income-api",
  "desired_images": [
    "adult-income-api:model-v2"
  ],
  "desired_image_tags": [
    "model-v2"
  ],
  "running_ready_images": [
    "docker.io/library/adult-income-api:model-v2"
  ],
  "rollout_complete": true,
  "service_reported_version": {
    "available": true,
    "app_version": "1.0.0",
    "environment": "kind",
    "model_loaded": true,
    "model": {
      "model_name": "adult-income-classifier",
      "model_version": "2",
      "model_alias": "candidate",
      "run_id": "930195a0314e4405b412ac21fb2f1a56",
      "dataset_version": "dataset-v2.0",
      "exported_at": "2026-11-14T23:23:51.807473+00:00"
    }
  }
}
```
</details>

<details><summary>dvc_get_current_dataset_version: success (11 ms)</summary>

```json
{
  "dataset_path": "data/adult.csv",
  "committed_version": "dataset-v2.0",
  "committed_md5": "06769c0a96e9ab07b8d9e2c1255a976b",
  "committed_size_bytes": 3328203,
  "last_pointer_commit": "20f0e1015f83c816debfd6a5b1129a3c540501a4",
  "is_tagged_version": true,
  "workspace_file": {
    "exists": true,
    "md5": "4e621ca43aa9af8d8d11947488e44044",
    "size_bytes": 55417,
    "line_count": 501
  },
  "workspace_matches_committed_version": false,
  "warning": "The file at data/adult.csv does not match the committed version (dataset-v2.0). It was modified, replaced or deleted after the last DVC commit. Restore it with 'dvc checkout data/adult.csv.dvc' or record a new version with 'dvc add'."
}
```
</details>

<details><summary>dvc_list_dataset_versions: success (10 ms)</summary>

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

## System evidence: dvc status after restore

`uv run dvc status`

```
Data and pipelines are up to date.
```
