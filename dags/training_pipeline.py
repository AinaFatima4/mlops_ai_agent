"""Adult Income training pipeline: validate, preprocess, train, evaluate, quality gate, register."""

from datetime import datetime, timedelta

from airflow.sdk import dag, task

DAG_ID = "adult_income_training"
TRAINING_PYTHON = "/opt/training-venv/bin/python"
PROJECT_DIRECTORY = "/opt/project"
DATA_PATH = "data/adult.csv"
MODEL_TYPES = ["logistic_regression", "random_forest", "gradient_boosting"]

DEFAULT_TASK_ARGUMENTS = {
    "owner": "mlops",
    "retries": 2,
    "retry_delay": timedelta(seconds=30),
    "execution_timeout": timedelta(minutes=30),
}


@task.external_python(python=TRAINING_PYTHON, expect_airflow=False)
def validate_data(project_directory: str, data_path: str) -> dict:
    import logging
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, project_directory)
    os.chdir(project_directory)
    from training.train import load_dataset, validate_dataset

    logging.basicConfig(level=logging.INFO)
    dataset = load_dataset(Path(data_path))
    validate_dataset(dataset)
    logging.info("Validation passed: %d rows, %d columns", len(dataset), len(dataset.columns))
    return {"row_count": len(dataset), "column_count": len(dataset.columns)}


@task.external_python(python=TRAINING_PYTHON, expect_airflow=False)
def preprocess(project_directory: str, data_path: str, validation_summary: dict) -> dict:
    import logging
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, project_directory)
    os.chdir(project_directory)
    from training.train import build_provenance, load_dataset, split_dataset

    logging.basicConfig(level=logging.INFO)
    dataset = load_dataset(Path(data_path))
    train_features, test_features, train_target, test_target = split_dataset(dataset)
    provenance = build_provenance(Path(data_path))
    logging.info(
        "Split %d rows into %d train / %d test; positive rate train=%.3f test=%.3f",
        validation_summary["row_count"],
        len(train_features),
        len(test_features),
        train_target.mean(),
        test_target.mean(),
    )
    logging.info("Provenance: %s", provenance.as_tags())
    return provenance.as_tags()


@task.external_python(python=TRAINING_PYTHON, expect_airflow=False)
def train_model(project_directory: str, data_path: str, model_type: str, provenance: dict) -> str:
    import logging
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, project_directory)
    os.chdir(project_directory)
    import mlflow

    from training.train import (
        DEFAULT_EXPERIMENT_NAME,
        DatasetProvenance,
        fit_and_log_model,
        load_dataset,
    )

    logging.basicConfig(level=logging.INFO)
    mlflow.set_experiment(DEFAULT_EXPERIMENT_NAME)
    dataset_provenance = DatasetProvenance(
        path=provenance["dataset.path"],
        md5=provenance["dataset.md5"],
        version=provenance["dataset.version"],
        git_commit=provenance["git.commit"],
        git_dirty=provenance["git.dirty"] == "true",
    )
    run_id, model_uri = fit_and_log_model(
        model_type, load_dataset(Path(data_path)), dataset_provenance
    )
    logging.info("Trained %s: run_id=%s model_uri=%s", model_type, run_id, model_uri)
    return run_id


@task.external_python(python=TRAINING_PYTHON, expect_airflow=False)
def evaluate_model(project_directory: str, data_path: str, mlflow_run_id: str) -> dict:
    import logging
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, project_directory)
    os.chdir(project_directory)
    from training.train import evaluate_logged_run, load_dataset

    logging.basicConfig(level=logging.INFO)
    result = evaluate_logged_run(mlflow_run_id, load_dataset(Path(data_path)))
    logging.info(
        "Evaluated run %s: %s quality_gate_passed=%s",
        mlflow_run_id,
        result.metrics,
        result.quality_gate_passed,
    )
    return result.as_dict()


@task
def collect_evaluation_results(evaluation_results: list[dict]) -> list[dict]:
    # Mapped task outputs arrive as a lazy sequence; turn them into a plain list for the next task
    return list(evaluation_results)


@task.external_python(python=TRAINING_PYTHON, expect_airflow=False)
def quality_gate(project_directory: str, evaluation_results: list[dict]) -> dict:
    import logging
    import sys

    sys.path.insert(0, project_directory)
    from training.train import TrainingResult, select_best_passing_result

    logging.basicConfig(level=logging.INFO)
    results = [TrainingResult(**result) for result in evaluation_results]
    for result in results:
        logging.info(
            "%s run=%s passed=%s metrics=%s",
            result.model_type,
            result.run_id,
            result.quality_gate_passed,
            result.metrics,
        )
    best_result = select_best_passing_result(results)
    if best_result is None:
        raise RuntimeError("Quality gate failed: no model met the thresholds; nothing promoted")
    logging.info("Quality gate passed. Best run: %s", best_result.run_id)
    return best_result.as_dict()


@task.external_python(python=TRAINING_PYTHON, expect_airflow=False)
def register_candidate(project_directory: str, best_result: dict, provenance: dict) -> dict:
    import logging
    import sys

    sys.path.insert(0, project_directory)
    from training.train import TrainingResult, register_model_version

    logging.basicConfig(level=logging.INFO)
    registration = register_model_version(
        TrainingResult(**best_result), provenance["dataset.version"]
    )
    logging.info("Registered candidate: %s", registration)
    return registration


@dag(
    dag_id=DAG_ID,
    description="Validate, train, evaluate and register Adult Income classifiers",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=DEFAULT_TASK_ARGUMENTS,
    tags=["mlops", "training"],
)
def adult_income_training():
    validation_summary = validate_data(PROJECT_DIRECTORY, DATA_PATH)
    provenance = preprocess(PROJECT_DIRECTORY, DATA_PATH, validation_summary)
    mlflow_run_ids = train_model.partial(
        project_directory=PROJECT_DIRECTORY, data_path=DATA_PATH, provenance=provenance
    ).expand(model_type=MODEL_TYPES)
    evaluation_results = evaluate_model.partial(
        project_directory=PROJECT_DIRECTORY, data_path=DATA_PATH
    ).expand(mlflow_run_id=mlflow_run_ids)
    collected_results = collect_evaluation_results(evaluation_results)
    best_result = quality_gate(PROJECT_DIRECTORY, collected_results)
    register_candidate(PROJECT_DIRECTORY, best_result, provenance)


adult_income_training()
