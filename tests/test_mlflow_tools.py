from pathlib import Path
from types import SimpleNamespace

import pytest
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from agent.tools.errors import InvalidToolInputError, ServiceUnavailableError
from agent.tools.mlflow_tools import MlflowTools, create_mlflow_tools

EXPERIMENT_NAME = "adult-income-test"
MODEL_NAME = "adult-income-classifier"


def log_run(
    client: MlflowClient, experiment_id: str, metrics: dict[str, float], tags: dict[str, str]
) -> str:
    run = client.create_run(experiment_id, run_name=tags.get("model.type", "run"), tags=tags)
    for metric_name, metric_value in metrics.items():
        client.log_metric(run.info.run_id, metric_name, metric_value)
    client.log_param(run.info.run_id, "model_type", tags.get("model.type", "unknown"))
    client.set_terminated(run.info.run_id, status="FINISHED")
    return run.info.run_id


@pytest.fixture(scope="module")
def populated_tracking_store(tmp_path_factory: pytest.TempPathFactory) -> dict:
    store_path = tmp_path_factory.mktemp("mlflow")
    tracking_uri = f"sqlite:///{store_path / 'mlflow.db'}"
    client = MlflowClient(tracking_uri=tracking_uri, registry_uri=tracking_uri)
    experiment_id = client.create_experiment(
        EXPERIMENT_NAME, artifact_location=(store_path / "artifacts").as_uri()
    )
    base_tags = {"dataset.version": "dataset-v2.0", "git.dirty": "false"}
    strong_run_id = log_run(
        client,
        experiment_id,
        {"f1": 0.72, "recall": 0.80, "precision": 0.65, "roc_auc": 0.92, "accuracy": 0.85},
        {**base_tags, "model.type": "logistic_regression", "quality_gate.passed": "true"},
    )
    close_run_id = log_run(
        client,
        experiment_id,
        {"f1": 0.715, "recall": 0.55, "precision": 0.90, "roc_auc": 0.93, "accuracy": 0.86},
        {**base_tags, "model.type": "random_forest", "quality_gate.passed": "false"},
    )
    client.create_registered_model(MODEL_NAME)
    model_version = client.create_model_version(
        MODEL_NAME, source=(store_path / "model").as_uri(), run_id=strong_run_id
    )
    client.set_registered_model_alias(MODEL_NAME, "candidate", model_version.version)
    return {
        "tools": MlflowTools(client),
        "strong_run_id": strong_run_id,
        "close_run_id": close_run_id,
    }


def test_list_experiments_includes_created_experiment(populated_tracking_store: dict) -> None:
    experiment_names = [
        experiment["name"]
        for experiment in populated_tracking_store["tools"].list_experiments()["experiments"]
    ]
    assert EXPERIMENT_NAME in experiment_names


def test_list_runs_returns_metrics_and_provenance(populated_tracking_store: dict) -> None:
    runs = populated_tracking_store["tools"].list_runs(EXPERIMENT_NAME)["runs"]
    assert len(runs) == 2
    assert all(run["provenance"]["dataset.version"] == "dataset-v2.0" for run in runs)


def test_best_run_is_selected_by_metric_with_readiness_warnings(
    populated_tracking_store: dict,
) -> None:
    result = populated_tracking_store["tools"].find_best_run(EXPERIMENT_NAME, metric="f1")
    assert result["best_run"]["run_id"] == populated_tracking_store["strong_run_id"]
    assert any("Selected by f1 alone" in warning for warning in result["warnings"])
    assert any("may not be meaningful" in warning for warning in result["warnings"])


def test_best_run_by_precision_warns_about_failed_gate_and_low_recall(
    populated_tracking_store: dict,
) -> None:
    result = populated_tracking_store["tools"].find_best_run(EXPERIMENT_NAME, metric="precision")
    assert result["best_run"]["run_id"] == populated_tracking_store["close_run_id"]
    assert any("did not pass the quality gate" in warning for warning in result["warnings"])
    assert any("Recall" in warning for warning in result["warnings"])


def test_compare_runs_identifies_best_per_metric(populated_tracking_store: dict) -> None:
    tools = populated_tracking_store["tools"]
    result = tools.compare_runs(
        [populated_tracking_store["strong_run_id"], populated_tracking_store["close_run_id"]]
    )
    assert result["best_run_by_metric"]["f1"] == populated_tracking_store["strong_run_id"]
    assert result["best_run_by_metric"]["precision"] == populated_tracking_store["close_run_id"]
    assert result["same_dataset_version"] is True
    assert "model_type" in result["differing_parameters"]


def test_model_versions_include_aliases(populated_tracking_store: dict) -> None:
    result = populated_tracking_store["tools"].get_model_versions(MODEL_NAME)
    assert result["registered"] is True
    assert result["versions"][0]["aliases"] == ["candidate"]


def test_unknown_run_raises_invalid_input(populated_tracking_store: dict) -> None:
    with pytest.raises(InvalidToolInputError):
        populated_tracking_store["tools"].get_run_details("0" * 32)


@pytest.mark.parametrize(
    ("method_name", "arguments"),
    [
        ("get_run_details", ["not-a-run-id"]),
        ("find_best_run", [EXPERIMENT_NAME, "made_up_metric"]),
        ("list_runs", ["name' OR '1'='1"]),
        ("compare_runs", [["a" * 32]]),
    ],
)
def test_invalid_inputs_are_rejected(
    populated_tracking_store: dict, method_name: str, arguments: list
) -> None:
    with pytest.raises(InvalidToolInputError):
        getattr(populated_tracking_store["tools"], method_name)(*arguments)


def test_unreachable_server_raises_service_unavailable() -> None:
    tools = create_mlflow_tools("http://127.0.0.1:9")
    with pytest.raises(ServiceUnavailableError):
        tools.list_experiments()


def test_server_error_is_wrapped_as_service_unavailable() -> None:
    def failing_search(*arguments, **keyword_arguments):
        raise MlflowException("internal error", error_code="INTERNAL_ERROR")

    tools = MlflowTools(SimpleNamespace(search_experiments=failing_search))
    with pytest.raises(ServiceUnavailableError):
        tools.list_experiments()


def test_experiment_artifacts_stay_out_of_project_root() -> None:
    assert not Path("mlruns").exists()
