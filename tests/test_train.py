import hashlib
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import pytest

from training.train import (
    MODEL_TYPES,
    DatasetProvenance,
    DataValidationError,
    check_quality_gate,
    compute_file_md5,
    load_dataset,
    train_and_log_model,
    validate_dataset,
)

SYNTHETIC_ROW_COUNT = 400


@pytest.fixture
def synthetic_dataset() -> pd.DataFrame:
    random_generator = np.random.default_rng(seed=7)
    row_count = SYNTHETIC_ROW_COUNT
    dataset = pd.DataFrame(
        {
            "age": random_generator.integers(18, 80, row_count).astype(float),
            "workclass": random_generator.choice(["Private", "State-gov"], row_count),
            "fnlwgt": random_generator.integers(10000, 400000, row_count).astype(float),
            "education": random_generator.choice(["Bachelors", "HS-grad"], row_count),
            "education_num": random_generator.integers(1, 16, row_count).astype(float),
            "marital_status": random_generator.choice(["Married", "Never-married"], row_count),
            "occupation": random_generator.choice(["Sales", "Tech-support"], row_count),
            "relationship": random_generator.choice(["Husband", "Own-child"], row_count),
            "race": random_generator.choice(["White", "Other"], row_count),
            "sex": random_generator.choice(["Male", "Female"], row_count),
            "capital_gain": random_generator.integers(0, 5000, row_count).astype(float),
            "capital_loss": random_generator.integers(0, 500, row_count).astype(float),
            "hours_per_week": random_generator.integers(10, 70, row_count).astype(float),
            "native_country": random_generator.choice(["United-States", "India"], row_count),
        }
    )
    signal = dataset["education_num"] + random_generator.normal(0, 2, row_count)
    dataset["income"] = np.where(signal > np.quantile(signal, 0.75), ">50K", "<=50K")
    return dataset


@pytest.fixture
def provenance() -> DatasetProvenance:
    return DatasetProvenance(
        path="data/adult.csv",
        md5="a" * 32,
        version="dataset-v2.0",
        git_commit="abc123",
        git_dirty=False,
    )


def test_validation_accepts_well_formed_dataset(synthetic_dataset: pd.DataFrame) -> None:
    validate_dataset(synthetic_dataset, minimum_row_count=100)


def test_validation_rejects_missing_column(synthetic_dataset: pd.DataFrame) -> None:
    with pytest.raises(DataValidationError, match="missing columns"):
        validate_dataset(synthetic_dataset.drop(columns=["age"]), minimum_row_count=100)


def test_validation_rejects_too_few_rows(synthetic_dataset: pd.DataFrame) -> None:
    with pytest.raises(DataValidationError, match="rows"):
        validate_dataset(synthetic_dataset.head(10), minimum_row_count=100)


def test_validation_rejects_unexpected_labels(synthetic_dataset: pd.DataFrame) -> None:
    synthetic_dataset.loc[0, "income"] = "maybe"
    with pytest.raises(DataValidationError, match="unexpected target labels"):
        validate_dataset(synthetic_dataset, minimum_row_count=100)


def test_quality_gate_reports_each_failed_threshold() -> None:
    passed, failures = check_quality_gate({"f1": 0.5, "recall": 0.9, "roc_auc": 0.7})
    assert passed is False
    assert len(failures) == 2


def test_quality_gate_passes_good_metrics() -> None:
    assert check_quality_gate({"f1": 0.7, "recall": 0.7, "roc_auc": 0.9}) == (True, [])


def test_file_md5_matches_hashlib(tmp_path: Path) -> None:
    data_file = tmp_path / "sample.csv"
    data_file.write_bytes(b"a,b\n1,2\n")
    assert compute_file_md5(data_file) == hashlib.md5(b"a,b\n1,2\n").hexdigest()


def test_raw_v1_format_loads_with_missing_values_as_nan(tmp_path: Path) -> None:
    raw_file = tmp_path / "adult.csv"
    raw_file.write_text("age,workclass,income\n39, ?, <=50K\n", encoding="utf-8")
    dataset = load_dataset(raw_file)
    assert dataset.loc[0, "workclass"] != dataset.loc[0, "workclass"]
    assert dataset.loc[0, "income"] == "<=50K"


@pytest.mark.parametrize("model_type", MODEL_TYPES)
def test_training_logs_metrics_and_provenance_to_mlflow(
    tmp_path: Path,
    synthetic_dataset: pd.DataFrame,
    provenance: DatasetProvenance,
    model_type: str,
) -> None:
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    experiment_id = mlflow.create_experiment(
        "test-training", artifact_location=(tmp_path / "artifacts").as_uri()
    )
    mlflow.set_experiment(experiment_id=experiment_id)

    result = train_and_log_model(model_type, synthetic_dataset, provenance)

    logged_run = mlflow.get_run(result.run_id)
    assert logged_run.data.tags["dataset.version"] == "dataset-v2.0"
    assert logged_run.data.tags["model.type"] == model_type
    assert set(result.metrics) == {"f1", "precision", "recall", "roc_auc", "accuracy"}
    assert logged_run.data.metrics["f1"] == pytest.approx(result.metrics["f1"])
    assert result.model_uri.startswith("models:/")
