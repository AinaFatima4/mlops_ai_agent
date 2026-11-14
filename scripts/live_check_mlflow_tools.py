"""Run the MLflow tools against the live server and assert the expected real results."""

import sys
from pathlib import Path

from agent.tools.dvc_tools import create_dvc_tools
from agent.tools.mlflow_tools import create_mlflow_tools

EXPERIMENT_NAME = "adult-income"
DATASET_PATH = "data/adult.csv"
EXPECTED_MODEL_TYPES = {"logistic_regression", "random_forest", "gradient_boosting"}


def main() -> int:
    mlflow_tools = create_mlflow_tools()
    dvc_tools = create_dvc_tools(Path.cwd())

    experiment_names = [
        experiment["name"] for experiment in mlflow_tools.list_experiments()["experiments"]
    ]
    assert EXPERIMENT_NAME in experiment_names, f"Missing experiment: {experiment_names}"

    runs = mlflow_tools.list_runs(EXPERIMENT_NAME, limit=10)["runs"]
    logged_model_types = {run["provenance"].get("model.type") for run in runs}
    assert EXPECTED_MODEL_TYPES <= logged_model_types, f"Model types: {logged_model_types}"

    best = mlflow_tools.find_best_run(EXPERIMENT_NAME, metric="f1")
    best_run = best["best_run"]
    assert best_run is not None, "No best run found"

    recorded_md5 = best_run["provenance"]["dataset.md5"]
    resolved_version = dvc_tools.find_version_by_hash(DATASET_PATH, recorded_md5)
    assert resolved_version["found"], f"MD5 {recorded_md5} does not match any DVC tag"
    assert best_run["provenance"]["dataset.version"] == resolved_version["version"]["version"]

    details = mlflow_tools.get_run_details(best_run["run_id"])
    assert details["datasets"], "Run has no logged dataset input"

    model_versions = mlflow_tools.get_model_versions()
    assert model_versions["registered"], "Model is not registered"
    all_aliases = [alias for version in model_versions["versions"] for alias in version["aliases"]]
    assert "candidate" in all_aliases, f"No candidate alias: {all_aliases}"

    print(
        f"Best run {best_run['run_id']} f1={best_run['metrics']['f1']:.3f} "
        f"trained on {resolved_version['version']['version']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
