"""Train, evaluate and log Adult Income classifiers to MLflow with dataset provenance."""

import argparse
import hashlib
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import mlflow
import mlflow.data
import mlflow.sklearn
import pandas as pd
from mlflow import MlflowClient
from mlflow.models import infer_signature
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from agent.tools.command_runner import CommandFailedError, CommandTimeoutError
from agent.tools.dvc_tools import create_dvc_tools
from agent.tools.errors import InvalidToolInputError

logger = logging.getLogger(__name__)

DEFAULT_TRACKING_URI = "http://localhost:5000"
DEFAULT_DATA_PATH = Path("data/adult.csv")
DEFAULT_EXPERIMENT_NAME = "adult-income"
REGISTERED_MODEL_NAME = "adult-income-classifier"
CANDIDATE_ALIAS = "candidate"
UNKNOWN_VALUE = "unknown"

TARGET_COLUMN = "income"
POSITIVE_LABEL = ">50K"
ALLOWED_LABELS = {">50K", "<=50K"}
NUMERIC_COLUMNS = [
    "age",
    "fnlwgt",
    "education_num",
    "capital_gain",
    "capital_loss",
    "hours_per_week",
]
CATEGORICAL_COLUMNS = [
    "workclass",
    "education",
    "marital_status",
    "occupation",
    "relationship",
    "race",
    "sex",
    "native_country",
]
FEATURE_COLUMNS = NUMERIC_COLUMNS + CATEGORICAL_COLUMNS
MINIMUM_ROW_COUNT = 1000
TEST_SIZE = 0.2
RANDOM_STATE = 42
MODEL_TYPES = ("logistic_regression", "random_forest", "gradient_boosting")
QUALITY_GATE_THRESHOLDS = {"f1": 0.60, "recall": 0.60, "roc_auc": 0.85}
# skops refuses to save or load types not listed here; these are our own trained models
SKOPS_TRUSTED_TYPES = [
    "numpy.dtype",
    "sklearn.tree._tree.Tree",
    "sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor",
]


class DataValidationError(Exception):
    """Raised when the dataset does not meet the training requirements."""


@dataclass(frozen=True)
class DatasetProvenance:
    path: str
    md5: str
    version: str
    git_commit: str
    git_dirty: bool

    def as_tags(self) -> dict[str, str]:
        return {
            "dataset.path": self.path,
            "dataset.md5": self.md5,
            "dataset.version": self.version,
            "git.commit": self.git_commit,
            "git.dirty": str(self.git_dirty).lower(),
        }


@dataclass(frozen=True)
class TrainingResult:
    run_id: str
    model_type: str
    metrics: dict[str, float]
    model_uri: str
    quality_gate_passed: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def compute_file_md5(file_path: Path) -> str:
    md5_digest = hashlib.md5()
    with file_path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            md5_digest.update(chunk)
    return md5_digest.hexdigest()


def resolve_dataset_version(data_path: Path, md5_hash: str) -> str:
    try:
        lookup = create_dvc_tools(Path.cwd()).find_version_by_hash(data_path.as_posix(), md5_hash)
    except (CommandFailedError, CommandTimeoutError, InvalidToolInputError, OSError) as error:
        logger.warning("Could not resolve dataset version: %s", error)
        return UNKNOWN_VALUE
    if not lookup["found"]:
        return UNKNOWN_VALUE
    return lookup["version"]["version"]


def read_git_state() -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()
        uncommitted_changes = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError) as error:
        logger.warning("Could not read git state: %s", error)
        return UNKNOWN_VALUE, False
    return commit, bool(uncommitted_changes)


def build_provenance(data_path: Path) -> DatasetProvenance:
    md5_hash = compute_file_md5(data_path)
    git_commit, git_dirty = read_git_state()
    return DatasetProvenance(
        path=data_path.as_posix(),
        md5=md5_hash,
        version=resolve_dataset_version(data_path, md5_hash),
        git_commit=git_commit,
        git_dirty=git_dirty,
    )


def load_dataset(data_path: Path) -> pd.DataFrame:
    # skipinitialspace and na_values let the raw v1 file load as well as the cleaned v2 file
    dataset = pd.read_csv(data_path, skipinitialspace=True, na_values="?")
    for column in NUMERIC_COLUMNS:
        if column in dataset.columns:
            dataset[column] = dataset[column].astype("float64")
    return dataset


def validate_dataset(dataset: pd.DataFrame, minimum_row_count: int = MINIMUM_ROW_COUNT) -> None:
    problems = []
    missing_columns = sorted(set(FEATURE_COLUMNS + [TARGET_COLUMN]) - set(dataset.columns))
    if missing_columns:
        problems.append(f"missing columns: {missing_columns}")
    if len(dataset) < minimum_row_count:
        problems.append(f"only {len(dataset)} rows, need at least {minimum_row_count}")
    if TARGET_COLUMN in dataset.columns:
        if dataset[TARGET_COLUMN].isna().any():
            problems.append("target column contains missing values")
        unexpected_labels = sorted(set(dataset[TARGET_COLUMN].dropna()) - ALLOWED_LABELS)
        if unexpected_labels:
            problems.append(f"unexpected target labels: {unexpected_labels}")
    if problems:
        raise DataValidationError("; ".join(problems))


def split_dataset(
    dataset: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    features = dataset[FEATURE_COLUMNS]
    target = (dataset[TARGET_COLUMN] == POSITIVE_LABEL).astype(int)
    return train_test_split(
        features, target, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=target
    )


def build_preprocessor() -> ColumnTransformer:
    numeric_pipeline = Pipeline(
        [("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]
    )
    categorical_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    return ColumnTransformer(
        [
            ("numeric", numeric_pipeline, NUMERIC_COLUMNS),
            ("categorical", categorical_pipeline, CATEGORICAL_COLUMNS),
        ]
    )


def build_model_pipeline(model_type: str) -> tuple[Pipeline, dict[str, object]]:
    if model_type == "logistic_regression":
        hyperparameters = {"C": 1.0, "max_iter": 1000, "class_weight": "balanced"}
        classifier = LogisticRegression(**hyperparameters)
    elif model_type == "random_forest":
        hyperparameters = {
            "n_estimators": 200,
            "max_depth": 16,
            "min_samples_leaf": 2,
            "class_weight": "balanced",
        }
        classifier = RandomForestClassifier(**hyperparameters, n_jobs=-1, random_state=RANDOM_STATE)
    elif model_type == "gradient_boosting":
        hyperparameters = {
            "max_iter": 300,
            "learning_rate": 0.1,
            "max_leaf_nodes": 31,
            "class_weight": "balanced",
        }
        classifier = HistGradientBoostingClassifier(**hyperparameters, random_state=RANDOM_STATE)
    else:
        raise ValueError(f"Unknown model type: {model_type}")
    pipeline = Pipeline([("preprocessor", build_preprocessor()), ("classifier", classifier)])
    return pipeline, hyperparameters


def evaluate_model(
    pipeline: Pipeline, test_features: pd.DataFrame, test_target: pd.Series
) -> dict[str, float]:
    predictions = pipeline.predict(test_features)
    positive_probabilities = pipeline.predict_proba(test_features)[:, 1]
    return {
        "f1": float(f1_score(test_target, predictions)),
        "precision": float(precision_score(test_target, predictions)),
        "recall": float(recall_score(test_target, predictions)),
        "roc_auc": float(roc_auc_score(test_target, positive_probabilities)),
        "accuracy": float(accuracy_score(test_target, predictions)),
    }


def check_quality_gate(metrics: dict[str, float]) -> tuple[bool, list[str]]:
    failures = [
        f"{metric_name} {metrics[metric_name]:.3f} < {threshold}"
        for metric_name, threshold in QUALITY_GATE_THRESHOLDS.items()
        if metrics[metric_name] < threshold
    ]
    return not failures, failures


def fit_and_log_model(
    model_type: str,
    dataset: pd.DataFrame,
    provenance: DatasetProvenance,
) -> tuple[str, str]:
    train_features, test_features, train_target, _ = split_dataset(dataset)
    pipeline, hyperparameters = build_model_pipeline(model_type)
    run_name = f"{model_type}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

    with mlflow.start_run(run_name=run_name) as run:
        mlflow.set_tags({**provenance.as_tags(), "model.type": model_type})
        mlflow.log_input(
            mlflow.data.from_pandas(
                dataset, source=provenance.path, name="adult-income", targets=TARGET_COLUMN
            ),
            context="training",
        )
        mlflow.log_params(
            {
                "model_type": model_type,
                **hyperparameters,
                "test_size": TEST_SIZE,
                "random_state": RANDOM_STATE,
                "row_count": len(dataset),
            }
        )

        training_start = time.perf_counter()
        pipeline.fit(train_features, train_target)
        mlflow.log_metric("training_seconds", time.perf_counter() - training_start)

        signature = infer_signature(test_features, pipeline.predict(test_features))
        model_info = mlflow.sklearn.log_model(
            pipeline,
            name="model",
            signature=signature,
            input_example=test_features.head(3),
            skops_trusted_types=SKOPS_TRUSTED_TYPES,
        )
        mlflow.set_tag("model.uri", model_info.model_uri)

    return run.info.run_id, model_info.model_uri


def evaluate_logged_run(run_id: str, dataset: pd.DataFrame) -> TrainingResult:
    client = MlflowClient()
    run = client.get_run(run_id)
    model_uri = run.data.tags["model.uri"]
    pipeline = mlflow.sklearn.load_model(model_uri)

    _, test_features, _, test_target = split_dataset(dataset)
    metrics = evaluate_model(pipeline, test_features, test_target)
    quality_gate_passed, quality_gate_failures = check_quality_gate(metrics)

    for metric_name, metric_value in metrics.items():
        client.log_metric(run_id, metric_name, metric_value)
    client.set_tag(run_id, "quality_gate.passed", str(quality_gate_passed).lower())
    client.set_tag(run_id, "quality_gate.failures", "; ".join(quality_gate_failures) or "none")

    return TrainingResult(
        run_id=run_id,
        model_type=run.data.tags["model.type"],
        metrics=metrics,
        model_uri=model_uri,
        quality_gate_passed=quality_gate_passed,
    )


def train_and_log_model(
    model_type: str,
    dataset: pd.DataFrame,
    provenance: DatasetProvenance,
) -> TrainingResult:
    run_id, _ = fit_and_log_model(model_type, dataset, provenance)
    return evaluate_logged_run(run_id, dataset)


def select_best_passing_result(results: list[TrainingResult]) -> TrainingResult | None:
    passing_results = [result for result in results if result.quality_gate_passed]
    if not passing_results:
        return None
    return max(passing_results, key=lambda result: result.metrics["f1"])


def register_model_version(result: TrainingResult, dataset_version: str) -> dict[str, str]:
    model_version = mlflow.register_model(
        result.model_uri,
        REGISTERED_MODEL_NAME,
        tags={"dataset.version": dataset_version, "source.run_id": result.run_id},
    )
    MlflowClient().set_registered_model_alias(
        REGISTERED_MODEL_NAME, CANDIDATE_ALIAS, model_version.version
    )
    return {
        "model_name": REGISTERED_MODEL_NAME,
        "version": str(model_version.version),
        "alias": CANDIDATE_ALIAS,
        "run_id": result.run_id,
    }


def register_best_model(
    results: list[TrainingResult], provenance: DatasetProvenance
) -> dict[str, str] | None:
    best_result = select_best_passing_result(results)
    if best_result is None:
        logger.warning("No model passed the quality gate; nothing registered")
        return None
    return register_model_version(best_result, provenance.version)


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--experiment-name", default=DEFAULT_EXPERIMENT_NAME)
    parser.add_argument("--model-type", choices=[*MODEL_TYPES, "all"], default="all")
    parser.add_argument(
        "--register", action="store_true", help="Register the best passing model as candidate"
    )
    return parser.parse_args(arguments)


def main(arguments: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parsed_arguments = parse_arguments(arguments)
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
    mlflow.set_experiment(parsed_arguments.experiment_name)

    dataset = load_dataset(parsed_arguments.data_path)
    validate_dataset(dataset)
    provenance = build_provenance(parsed_arguments.data_path)
    logger.info("Dataset %s version=%s", provenance.path, provenance.version)

    model_types = (
        MODEL_TYPES if parsed_arguments.model_type == "all" else [parsed_arguments.model_type]
    )
    results = [train_and_log_model(model_type, dataset, provenance) for model_type in model_types]

    for result in results:
        metrics_summary = ", ".join(f"{name}={value:.3f}" for name, value in result.metrics.items())
        gate_status = "PASSED" if result.quality_gate_passed else "FAILED"
        print(f"{result.model_type:<20} run={result.run_id} gate={gate_status} {metrics_summary}")

    if parsed_arguments.register:
        registration = register_best_model(results, provenance)
        print(f"Registered: {registration}" if registration else "No model registered")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
