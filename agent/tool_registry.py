"""Registry mapping tool names to validated handlers on the DVC, MLflow, Airflow and k8s tools."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from agent import schemas

ToolFactory = Callable[[], Any]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    service: str
    method_name: str
    changes_state: bool = False

    def as_function_schema(self) -> dict[str, Any]:
        parameters = self.input_model.model_json_schema()
        parameters.pop("title", None)
        for property_schema in parameters.get("properties", {}).values():
            property_schema.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


TOOL_DEFINITIONS = [
    ToolDefinition(
        "dvc_list_tracked_datasets",
        "List datasets tracked by DVC with their current MD5 hash and size.",
        schemas.NoInput,
        "dvc",
        "list_tracked_datasets",
    ),
    ToolDefinition(
        "dvc_list_dataset_versions",
        "List tagged dataset versions (git tags dataset-v*) with commit, MD5 and size.",
        schemas.DatasetPathInput,
        "dvc",
        "list_dataset_versions",
    ),
    ToolDefinition(
        "dvc_get_current_dataset_version",
        "Get the dataset version currently in the workspace and its git commit.",
        schemas.DatasetPathInput,
        "dvc",
        "get_current_dataset_version",
    ),
    ToolDefinition(
        "dvc_find_version_by_hash",
        "Resolve an MD5 hash (for example the dataset.md5 tag of an MLflow run) to a DVC version.",
        schemas.DatasetHashInput,
        "dvc",
        "find_version_by_hash",
    ),
    ToolDefinition(
        "dvc_compare_dataset_versions",
        "Compare two dataset versions: content change, size difference and dvc diff.",
        schemas.CompareDatasetVersionsInput,
        "dvc",
        "compare_dataset_versions",
    ),
    ToolDefinition(
        "dvc_check_data_changed",
        "Check whether DVC-tracked data differs from what is committed (dvc status).",
        schemas.NoInput,
        "dvc",
        "check_data_changed",
    ),
    ToolDefinition(
        "dvc_get_reproduction_steps",
        "Explain the exact commands to restore a previous dataset version. Does not run them.",
        schemas.DatasetVersionInput,
        "dvc",
        "get_reproduction_steps",
    ),
    ToolDefinition(
        "mlflow_list_experiments",
        "List MLflow experiments.",
        schemas.NoInput,
        "mlflow",
        "list_experiments",
    ),
    ToolDefinition(
        "mlflow_list_runs",
        "List recent runs of an experiment with metrics and provenance tags.",
        schemas.ExperimentRunsInput,
        "mlflow",
        "list_runs",
    ),
    ToolDefinition(
        "mlflow_get_run_details",
        "Get parameters, metrics, dataset inputs and provenance of one run.",
        schemas.RunIdInput,
        "mlflow",
        "get_run_details",
    ),
    ToolDefinition(
        "mlflow_find_best_run",
        "Find the best recent run by a metric, with runner-up and production-readiness warnings.",
        schemas.BestRunInput,
        "mlflow",
        "find_best_run",
    ),
    ToolDefinition(
        "mlflow_compare_runs",
        "Compare 2 to 10 runs: best run per metric, differing parameters, dataset versions.",
        schemas.CompareRunsInput,
        "mlflow",
        "compare_runs",
    ),
    ToolDefinition(
        "mlflow_get_model_versions",
        "List registered model versions and their aliases.",
        schemas.ModelVersionsInput,
        "mlflow",
        "get_model_versions",
    ),
    ToolDefinition(
        "airflow_list_dags",
        "List Airflow DAGs, whether triggering is approved, and DAG import errors.",
        schemas.NoInput,
        "airflow",
        "list_dags",
    ),
    ToolDefinition(
        "airflow_list_dag_runs",
        "List the most recent runs of a DAG with their states.",
        schemas.DagRunsInput,
        "airflow",
        "list_dag_runs",
    ),
    ToolDefinition(
        "airflow_get_dag_run_status",
        "Get the state of one DAG run and of every task in it.",
        schemas.DagRunInput,
        "airflow",
        "get_dag_run_status",
    ),
    ToolDefinition(
        "airflow_trigger_dag",
        "Start a new run of an approved DAG (retrains models). Requires user confirmation.",
        schemas.TriggerDagInput,
        "airflow",
        "trigger_dag",
        changes_state=True,
    ),
    ToolDefinition(
        "airflow_wait_for_dag_run",
        "Wait until a DAG run succeeds or fails, then return its final status.",
        schemas.WaitForDagRunInput,
        "airflow",
        "wait_for_dag_run",
    ),
    ToolDefinition(
        "airflow_get_failed_tasks",
        "List failed tasks (root causes) and blocked upstream_failed tasks of a DAG run.",
        schemas.FailedTasksInput,
        "airflow",
        "get_failed_tasks",
    ),
    ToolDefinition(
        "airflow_get_task_logs",
        "Get the log tail, error lines and exceptions of one task attempt.",
        schemas.TaskLogsInput,
        "airflow",
        "get_task_logs",
    ),
    ToolDefinition(
        "kubernetes_list_workloads",
        "List Deployments and Pods in the approved namespace.",
        schemas.NamespaceInput,
        "kubernetes",
        "list_workloads",
    ),
    ToolDefinition(
        "kubernetes_get_pod_details",
        "Get a pod's container states, conditions, events, current and previous logs.",
        schemas.PodDetailsInput,
        "kubernetes",
        "get_pod_details",
    ),
    ToolDefinition(
        "kubernetes_inspect_services",
        "Inspect Services: type, ports, selector and number of ready endpoints.",
        schemas.NamespaceInput,
        "kubernetes",
        "inspect_services",
    ),
    ToolDefinition(
        "kubernetes_find_unhealthy_pods",
        "Find pods that are not Ready, restarting, crash-looping or OOMKilled, plus warnings.",
        schemas.NamespaceInput,
        "kubernetes",
        "find_unhealthy_pods",
    ),
    ToolDefinition(
        "kubernetes_get_deployed_version",
        "Report the deployed image tag and the model version the API itself reports.",
        schemas.DeploymentInput,
        "kubernetes",
        "get_deployed_version",
    ),
    ToolDefinition(
        "kubernetes_restart_deployment",
        "Rolling restart of a Deployment in the approved namespace. Requires user confirmation.",
        schemas.DeploymentInput,
        "kubernetes",
        "restart_deployment",
        changes_state=True,
    ),
]


class ServiceProvider:
    """Creates each service tool object on first use, so one missing service never blocks others."""

    def __init__(self, factories: dict[str, ToolFactory]) -> None:
        self.factories = factories
        self.instances: dict[str, Any] = {}

    def get(self, service: str) -> Any:
        if service not in self.instances:
            self.instances[service] = self.factories[service]()
        return self.instances[service]


class ToolRegistry:
    def __init__(
        self,
        service_provider: ServiceProvider,
        definitions: list[ToolDefinition] = TOOL_DEFINITIONS,
    ) -> None:
        self.service_provider = service_provider
        self.definitions = {definition.name: definition for definition in definitions}

    def function_schemas(self) -> list[dict[str, Any]]:
        return [definition.as_function_schema() for definition in self.definitions.values()]

    def get_definition(self, tool_name: str) -> ToolDefinition | None:
        return self.definitions.get(tool_name)

    def call(
        self, definition: ToolDefinition, validated_input: BaseModel, confirmed: bool
    ) -> dict[str, Any]:
        service_tools = self.service_provider.get(definition.service)
        method = getattr(service_tools, definition.method_name)
        arguments = validated_input.model_dump()
        if definition.changes_state:
            arguments["confirmed"] = confirmed
        return method(**arguments)


def create_default_registry() -> ToolRegistry:
    from pathlib import Path

    from agent.tools.airflow_tools import create_airflow_tools
    from agent.tools.dvc_tools import create_dvc_tools
    from agent.tools.kubernetes_tools import create_kubernetes_tools
    from agent.tools.mlflow_tools import create_mlflow_tools

    return ToolRegistry(
        ServiceProvider(
            {
                "dvc": lambda: create_dvc_tools(Path.cwd()),
                "mlflow": create_mlflow_tools,
                "airflow": create_airflow_tools,
                "kubernetes": create_kubernetes_tools,
            }
        )
    )
