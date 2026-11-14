"""MLflow experiment intelligence tools built on MlflowClient."""

import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from mlflow import MlflowClient
from mlflow.entities import ViewType
from mlflow.exceptions import MlflowException

from agent.tools.errors import InvalidToolInputError, ServiceUnavailableError

DEFAULT_TRACKING_URI = "http://localhost:5000"
DEFAULT_REGISTERED_MODEL_NAME = "adult-income-classifier"
SUPPORTED_METRICS = ("f1", "precision", "recall", "roc_auc", "accuracy")
PROVENANCE_TAG_KEYS = (
    "model.type",
    "dataset.path",
    "dataset.md5",
    "dataset.version",
    "git.commit",
    "git.dirty",
    "quality_gate.passed",
    "quality_gate.failures",
    "model.uri",
)
RUN_ID_REGEX = re.compile(r"^[0-9a-f]{32}$")
NAME_REGEX = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")
MAXIMUM_RESULTS = 50
MINIMUM_COMPARED_RUNS = 2
MAXIMUM_COMPARED_RUNS = 10
LOW_RECALL_THRESHOLD = 0.6
CLOSE_SCORE_MARGIN = 0.01
NOT_FOUND_ERROR_CODES = {"RESOURCE_DOES_NOT_EXIST", "NOT_FOUND"}

ReturnType = TypeVar("ReturnType")


def format_timestamp(milliseconds: int | None) -> str | None:
    if milliseconds is None:
        return None
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC).isoformat()


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_REGEX.match(run_id):
        raise InvalidToolInputError(f"Invalid run ID: {run_id!r}")
    return run_id


def validate_name(name: str, field_name: str) -> str:
    if not NAME_REGEX.match(name):
        raise InvalidToolInputError(f"Invalid {field_name}: {name!r}")
    return name


def validate_metric(metric: str) -> str:
    if metric not in SUPPORTED_METRICS:
        raise InvalidToolInputError(
            f"Unsupported metric {metric!r}. Supported: {', '.join(SUPPORTED_METRICS)}"
        )
    return metric


def validate_result_limit(limit: int) -> int:
    if not 1 <= limit <= MAXIMUM_RESULTS:
        raise InvalidToolInputError(f"Limit must be between 1 and {MAXIMUM_RESULTS}")
    return limit


def summarize_run(run: Any) -> dict[str, Any]:
    return {
        "run_id": run.info.run_id,
        "run_name": run.info.run_name,
        "status": run.info.status,
        "start_time": format_timestamp(run.info.start_time),
        "metrics": {
            metric_name: run.data.metrics[metric_name]
            for metric_name in SUPPORTED_METRICS
            if metric_name in run.data.metrics
        },
        "provenance": {
            tag_key: run.data.tags[tag_key]
            for tag_key in PROVENANCE_TAG_KEYS
            if tag_key in run.data.tags
        },
    }


class MlflowTools:
    def __init__(self, client: MlflowClient) -> None:
        self.client = client

    def list_experiments(self) -> dict[str, Any]:
        experiments = self._call(self.client.search_experiments, view_type=ViewType.ACTIVE_ONLY)
        return {
            "experiments": [
                {
                    "experiment_id": experiment.experiment_id,
                    "name": experiment.name,
                    "creation_time": format_timestamp(experiment.creation_time),
                }
                for experiment in experiments
            ]
        }

    def list_runs(self, experiment_name: str, limit: int = 10) -> dict[str, Any]:
        experiment = self._get_experiment(experiment_name)
        runs = self._call(
            self.client.search_runs,
            [experiment.experiment_id],
            order_by=["attributes.start_time DESC"],
            max_results=validate_result_limit(limit),
        )
        return {"experiment_name": experiment_name, "runs": [summarize_run(run) for run in runs]}

    def get_run_details(self, run_id: str) -> dict[str, Any]:
        run = self._get_run(validate_run_id(run_id))
        artifacts = self._call(self.client.list_artifacts, run_id)
        dataset_inputs = run.inputs.dataset_inputs if run.inputs else []
        return {
            **summarize_run(run),
            "end_time": format_timestamp(run.info.end_time),
            "all_metrics": dict(run.data.metrics),
            "parameters": dict(run.data.params),
            "artifacts": [artifact.path for artifact in artifacts],
            "datasets": [
                {
                    "name": dataset_input.dataset.name,
                    "digest": dataset_input.dataset.digest,
                    "source": dataset_input.dataset.source,
                }
                for dataset_input in dataset_inputs
            ],
        }

    def find_best_run(
        self, experiment_name: str, metric: str = "f1", recent_run_limit: int = 20
    ) -> dict[str, Any]:
        validate_metric(metric)
        experiment = self._get_experiment(experiment_name)
        runs = self._call(
            self.client.search_runs,
            [experiment.experiment_id],
            filter_string="attributes.status = 'FINISHED'",
            order_by=["attributes.start_time DESC"],
            max_results=validate_result_limit(recent_run_limit),
        )
        scored_runs = sorted(
            (run for run in runs if metric in run.data.metrics),
            key=lambda run: run.data.metrics[metric],
            reverse=True,
        )
        if not scored_runs:
            return {
                "metric": metric,
                "runs_considered": len(runs),
                "best_run": None,
                "runner_up": None,
                "warnings": [f"No finished runs in {experiment_name!r} recorded {metric}"],
            }

        best_run = scored_runs[0]
        runner_up = scored_runs[1] if len(scored_runs) > 1 else None
        return {
            "metric": metric,
            "runs_considered": len(runs),
            "best_run": summarize_run(best_run),
            "runner_up": summarize_run(runner_up) if runner_up else None,
            "warnings": self._production_readiness_warnings(best_run, runner_up, metric),
        }

    def compare_runs(self, run_ids: list[str]) -> dict[str, Any]:
        if not MINIMUM_COMPARED_RUNS <= len(run_ids) <= MAXIMUM_COMPARED_RUNS:
            raise InvalidToolInputError(
                f"Provide between {MINIMUM_COMPARED_RUNS} and {MAXIMUM_COMPARED_RUNS} run IDs"
            )
        runs = [self._get_run(validate_run_id(run_id)) for run_id in run_ids]

        best_run_by_metric = {}
        for metric_name in SUPPORTED_METRICS:
            runs_with_metric = [run for run in runs if metric_name in run.data.metrics]
            if runs_with_metric:
                best_run = max(runs_with_metric, key=lambda run: run.data.metrics[metric_name])
                best_run_by_metric[metric_name] = best_run.info.run_id

        all_parameter_names = sorted({name for run in runs for name in run.data.params})
        differing_parameters = {
            parameter_name: {run.info.run_id: run.data.params.get(parameter_name) for run in runs}
            for parameter_name in all_parameter_names
            if len({run.data.params.get(parameter_name) for run in runs}) > 1
        }
        dataset_versions = {run.data.tags.get("dataset.version", "unknown") for run in runs}
        return {
            "runs": [summarize_run(run) for run in runs],
            "best_run_by_metric": best_run_by_metric,
            "differing_parameters": differing_parameters,
            "same_dataset_version": len(dataset_versions) == 1,
            "dataset_versions": sorted(dataset_versions),
        }

    def get_model_versions(self, model_name: str = DEFAULT_REGISTERED_MODEL_NAME) -> dict[str, Any]:
        validate_name(model_name, "model name")
        model_versions = self._call(self.client.search_model_versions, f"name = '{model_name}'")
        if not model_versions:
            return {"model_name": model_name, "registered": False, "versions": []}

        # search_model_versions does not return aliases, so read them from the registered model
        registered_model = self._call(self.client.get_registered_model, model_name)
        aliases_by_version: dict[str, list[str]] = {}
        for alias_name, alias_version in registered_model.aliases.items():
            aliases_by_version.setdefault(str(alias_version), []).append(alias_name)
        return {
            "model_name": model_name,
            "registered": True,
            "versions": [
                {
                    "version": str(model_version.version),
                    "run_id": model_version.run_id,
                    "status": model_version.status,
                    "aliases": aliases_by_version.get(str(model_version.version), []),
                    "creation_time": format_timestamp(model_version.creation_timestamp),
                    "tags": dict(model_version.tags),
                }
                for model_version in sorted(
                    model_versions, key=lambda model_version: int(model_version.version)
                )
            ],
        }

    def _production_readiness_warnings(
        self, best_run: Any, runner_up: Any | None, metric: str
    ) -> list[str]:
        tags = best_run.data.tags
        metrics = best_run.data.metrics
        warnings = [
            f"Selected by {metric} alone. Production readiness also needs a passed quality "
            "gate, current training data and a healthy deployment."
        ]
        if tags.get("quality_gate.passed") != "true":
            warnings.append(
                f"Best run did not pass the quality gate: {tags.get('quality_gate.failures')}"
            )
        if metrics.get("recall", 1.0) < LOW_RECALL_THRESHOLD:
            warnings.append(f"Recall {metrics['recall']:.3f} is below {LOW_RECALL_THRESHOLD}")
        if runner_up and metrics[metric] - runner_up.data.metrics[metric] < CLOSE_SCORE_MARGIN:
            warnings.append(
                f"Runner-up {runner_up.info.run_id} is within {CLOSE_SCORE_MARGIN} on {metric}; "
                "the difference may not be meaningful"
            )
        if tags.get("git.dirty") == "true":
            warnings.append("Trained from code with uncommitted changes; not fully reproducible")
        if tags.get("dataset.version", "unknown") == "unknown":
            warnings.append("Training dataset version could not be resolved to a DVC tag")
        return warnings

    def _get_experiment(self, experiment_name: str) -> Any:
        validate_name(experiment_name, "experiment name")
        experiment = self._call(self.client.get_experiment_by_name, experiment_name)
        if experiment is None:
            raise InvalidToolInputError(f"Experiment not found: {experiment_name}")
        return experiment

    def _get_run(self, run_id: str) -> Any:
        return self._call(self.client.get_run, run_id)

    @staticmethod
    def _call(
        function: Callable[..., ReturnType], *arguments: Any, **keyword_arguments: Any
    ) -> ReturnType:
        try:
            return function(*arguments, **keyword_arguments)
        except MlflowException as error:
            if error.error_code in NOT_FOUND_ERROR_CODES:
                raise InvalidToolInputError(str(error.message)) from error
            raise ServiceUnavailableError(f"MLflow request failed: {error.message}") from error
        except OSError as error:
            raise ServiceUnavailableError(f"MLflow is unreachable: {error}") from error


def create_mlflow_tools(tracking_uri: str | None = None) -> MlflowTools:
    # Fail fast instead of retrying for minutes when the server is down
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "10")
    resolved_uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)
    return MlflowTools(MlflowClient(tracking_uri=resolved_uri, registry_uri=resolved_uri))
