"""Structured inputs and outputs for every agent tool."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_DATASET_PATH = "data/adult.csv"
DEFAULT_EXPERIMENT_NAME = "adult-income"
DEFAULT_MODEL_NAME = "adult-income-classifier"
DEFAULT_DAG_ID = "adult_income_training"
DEFAULT_NAMESPACE = "mlops-app"
DEFAULT_DEPLOYMENT_NAME = "adult-income-api"


class ToolInput(BaseModel):
    # Unknown fields are rejected, so the model cannot slip in extra flags such as "confirmed"
    model_config = ConfigDict(extra="forbid")


class NoInput(ToolInput):
    pass


class DatasetPathInput(ToolInput):
    dataset_path: str = Field(DEFAULT_DATASET_PATH, description="DVC-tracked dataset path")


class DatasetVersionInput(DatasetPathInput):
    version: str = Field(description="Dataset version tag, for example dataset-v1.0")


class CompareDatasetVersionsInput(DatasetPathInput):
    version_a: str = Field(description="Older dataset version tag, for example dataset-v1.0")
    version_b: str = Field(description="Newer dataset version tag, for example dataset-v2.0")


class DatasetHashInput(DatasetPathInput):
    md5_hash: str = Field(description="32-character MD5 hash recorded on an MLflow run")


class ExperimentRunsInput(ToolInput):
    experiment_name: str = Field(DEFAULT_EXPERIMENT_NAME)
    limit: int = Field(10, ge=1, le=50)


class RunIdInput(ToolInput):
    run_id: str = Field(description="32-character MLflow run ID")


class BestRunInput(ToolInput):
    experiment_name: str = Field(DEFAULT_EXPERIMENT_NAME)
    metric: Literal["f1", "precision", "recall", "roc_auc", "accuracy"] = "f1"
    recent_run_limit: int = Field(20, ge=1, le=50)


class CompareRunsInput(ToolInput):
    run_ids: list[str] = Field(min_length=2, max_length=10)


class ModelVersionsInput(ToolInput):
    model_name: str = Field(DEFAULT_MODEL_NAME)


class DagRunsInput(ToolInput):
    dag_id: str = Field(DEFAULT_DAG_ID)
    limit: int = Field(5, ge=1, le=50)


class DagRunInput(ToolInput):
    dag_id: str = Field(DEFAULT_DAG_ID)
    dag_run_id: str = Field(description="Airflow DAG run ID, for example manual__2026-...")


class TriggerDagInput(ToolInput):
    dag_id: str = Field(DEFAULT_DAG_ID)


class WaitForDagRunInput(DagRunInput):
    timeout_seconds: int = Field(600, ge=10, le=900)


class FailedTasksInput(ToolInput):
    dag_id: str = Field(DEFAULT_DAG_ID)
    dag_run_id: str | None = Field(None, description="Leave empty to use the latest failed run")


class TaskLogsInput(DagRunInput):
    task_id: str
    map_index: int = Field(-1, description="Index of a mapped task, -1 for unmapped tasks")
    max_lines: int = Field(60, ge=1, le=200)


class NamespaceInput(ToolInput):
    namespace: str = Field(DEFAULT_NAMESPACE)


class PodDetailsInput(NamespaceInput):
    pod_name: str
    log_lines: int = Field(40, ge=1, le=200)


class DeploymentInput(NamespaceInput):
    deployment_name: str = Field(DEFAULT_DEPLOYMENT_NAME)


class ToolStatus(StrEnum):
    SUCCESS = "success"
    INVALID_INPUT = "invalid_input"
    PERMISSION_DENIED = "permission_denied"
    CONFIRMATION_REQUIRED = "confirmation_required"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class ToolResult(BaseModel):
    tool_name: str
    status: ToolStatus
    request_id: str
    duration_ms: float
    data: dict[str, Any] | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == ToolStatus.SUCCESS
