"""Apache Airflow workflow tools using the authenticated Airflow 3 REST API."""

import os
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from agent.tools.errors import (
    ConfirmationRequiredError,
    InvalidToolInputError,
    ServiceUnavailableError,
    ToolPermissionError,
)

DEFAULT_AIRFLOW_URL = "http://localhost:8080"
APPROVED_TRIGGER_DAG_IDS = frozenset({"adult_income_training"})
IDENTIFIER_REGEX = re.compile(r"^[A-Za-z0-9_.\-]{1,250}$")
DAG_RUN_ID_REGEX = re.compile(r"^[A-Za-z0-9_.:+\-]{1,250}$")
REQUEST_TIMEOUT_SECONDS = 15
MAXIMUM_LIST_LIMIT = 50
MAXIMUM_LOG_LINES = 200
MAXIMUM_WAIT_SECONDS = 900
FAILED_TASK_STATES = {"failed", "upstream_failed"}
TERMINAL_RUN_STATES = {"success", "failed"}
AUTHENTICATION_FAILURE_CODES = {401, 403}


def validate_identifier(value: str, field_name: str) -> str:
    if not IDENTIFIER_REGEX.match(value):
        raise InvalidToolInputError(f"Invalid {field_name}: {value!r}")
    return value


def validate_dag_run_id(dag_run_id: str) -> str:
    if not DAG_RUN_ID_REGEX.match(dag_run_id):
        raise InvalidToolInputError(f"Invalid DAG run ID: {dag_run_id!r}")
    return dag_run_id


def encode_path_segment(value: str) -> str:
    return quote(value, safe="")


def extract_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return str(body)[:300]


class AirflowApiClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.http_client = httpx.Client(
            base_url=base_url, timeout=timeout_seconds, transport=transport
        )
        self.access_token: str | None = None

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        for attempt_number in range(2):
            if self.access_token is None:
                self._authenticate()
            response = self._send(
                method,
                path,
                params=params,
                json=json_body,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Accept": "application/json",
                },
            )
            # An expired token is rejected; get a fresh one and retry once
            if response.status_code in AUTHENTICATION_FAILURE_CODES and attempt_number == 0:
                self.access_token = None
                continue
            return self._parse_response(response)
        raise ServiceUnavailableError("Airflow request could not be authenticated")

    def _authenticate(self) -> None:
        response = self._send(
            "POST", "/auth/token", json={"username": self.username, "password": self.password}
        )
        if response.status_code not in (200, 201):
            raise ServiceUnavailableError(
                f"Airflow authentication failed with HTTP {response.status_code}"
            )
        self.access_token = response.json()["access_token"]

    def _send(self, method: str, path: str, **request_options: Any) -> httpx.Response:
        try:
            return self.http_client.request(method, path, **request_options)
        except httpx.TimeoutException as error:
            raise ServiceUnavailableError(f"Airflow request timed out: {method} {path}") from error
        except httpx.HTTPError as error:
            raise ServiceUnavailableError(f"Airflow is unreachable: {error}") from error

    @staticmethod
    def _parse_response(response: httpx.Response) -> Any:
        if response.status_code == 404:
            raise InvalidToolInputError(f"Not found in Airflow: {extract_error_detail(response)}")
        if response.status_code in AUTHENTICATION_FAILURE_CODES:
            raise ToolPermissionError(
                f"Airflow denied the request: {extract_error_detail(response)}"
            )
        if response.status_code >= 400:
            raise ServiceUnavailableError(
                f"Airflow returned HTTP {response.status_code}: {extract_error_detail(response)}"
            )
        return response.json()


def format_log_entry(entry: Any) -> str:
    if isinstance(entry, str):
        return entry
    parts = [
        entry.get("timestamp", ""),
        entry.get("level", "").upper(),
        str(entry.get("event", "")),
    ]
    return " ".join(part for part in parts if part)


def summarize_exceptions(log_entries: list[Any]) -> list[dict[str, str]]:
    exceptions = []
    for entry in log_entries:
        if not isinstance(entry, dict):
            continue
        for error_detail in entry.get("error_detail") or []:
            exceptions.append(
                {
                    "type": str(error_detail.get("exc_type", "")),
                    "message": str(error_detail.get("exc_value", ""))[:500],
                }
            )
    return exceptions


def is_error_line(entry: Any) -> bool:
    if isinstance(entry, dict):
        return entry.get("level") in ("error", "critical") or "Traceback" in str(
            entry.get("event", "")
        )
    return "ERROR" in entry or "Traceback" in entry


class AirflowTools:
    def __init__(
        self,
        api_client: AirflowApiClient,
        approved_trigger_dag_ids: frozenset[str] = APPROVED_TRIGGER_DAG_IDS,
        sleep_function: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_client = api_client
        self.approved_trigger_dag_ids = approved_trigger_dag_ids
        self.sleep_function = sleep_function

    def list_dags(self) -> dict[str, Any]:
        dags_response = self.api_client.request(
            "GET", "/api/v2/dags", params={"limit": MAXIMUM_LIST_LIMIT}
        )
        import_errors_response = self.api_client.request("GET", "/api/v2/importErrors")
        return {
            "dags": [
                {
                    "dag_id": dag["dag_id"],
                    "is_paused": dag["is_paused"],
                    "tags": [tag["name"] for tag in dag.get("tags", [])],
                    "trigger_approved": dag["dag_id"] in self.approved_trigger_dag_ids,
                }
                for dag in dags_response["dags"]
            ],
            "import_errors": [
                {
                    "file": import_error["filename"],
                    "error": import_error["stack_trace"].strip().splitlines()[-1],
                }
                for import_error in import_errors_response["import_errors"]
            ],
        }

    def list_dag_runs(self, dag_id: str, limit: int = 5) -> dict[str, Any]:
        validate_identifier(dag_id, "DAG ID")
        if not 1 <= limit <= MAXIMUM_LIST_LIMIT:
            raise InvalidToolInputError(f"Limit must be between 1 and {MAXIMUM_LIST_LIMIT}")
        response = self.api_client.request(
            "GET",
            f"/api/v2/dags/{dag_id}/dagRuns",
            params={"order_by": "-run_after", "limit": limit},
        )
        return {
            "dag_id": dag_id,
            "dag_runs": [self._summarize_run(run) for run in response["dag_runs"]],
        }

    def get_dag_run_status(self, dag_id: str, dag_run_id: str) -> dict[str, Any]:
        run_path = self._run_path(dag_id, dag_run_id)
        dag_run = self.api_client.request("GET", run_path)
        task_instances = self.api_client.request("GET", f"{run_path}/taskInstances")[
            "task_instances"
        ]
        state_counts: dict[str, int] = {}
        for task_instance in task_instances:
            task_state = task_instance["state"] or "none"
            state_counts[task_state] = state_counts.get(task_state, 0) + 1
        return {
            **self._summarize_run(dag_run),
            "task_state_counts": state_counts,
            "tasks": [self._summarize_task(task_instance) for task_instance in task_instances],
        }

    def trigger_dag(
        self, dag_id: str, confirmed: bool = False, conf: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        validate_identifier(dag_id, "DAG ID")
        if dag_id not in self.approved_trigger_dag_ids:
            raise ToolPermissionError(
                f"Triggering {dag_id!r} is not approved. "
                f"Approved DAGs: {sorted(self.approved_trigger_dag_ids)}"
            )
        if not confirmed:
            raise ConfirmationRequiredError(f"trigger a new run of Airflow DAG {dag_id!r}")

        dag = self.api_client.request("GET", f"/api/v2/dags/{dag_id}")
        if dag["is_paused"]:
            raise ServiceUnavailableError(
                f"DAG {dag_id!r} is paused, so a new run would never start. "
                "Unpausing is not something the agent is allowed to do."
            )
        dag_run = self.api_client.request(
            "POST",
            f"/api/v2/dags/{dag_id}/dagRuns",
            json_body={
                "logical_date": None,
                "conf": conf or {},
                "note": "Triggered by MLOps agent",
            },
        )
        return self._summarize_run(dag_run)

    def wait_for_dag_run(
        self,
        dag_id: str,
        dag_run_id: str,
        timeout_seconds: int = 600,
        poll_interval_seconds: int = 10,
    ) -> dict[str, Any]:
        if not 1 <= timeout_seconds <= MAXIMUM_WAIT_SECONDS:
            raise InvalidToolInputError(f"Timeout must be between 1 and {MAXIMUM_WAIT_SECONDS}")
        waited_seconds = 0
        while True:
            status = self.get_dag_run_status(dag_id, dag_run_id)
            if status["state"] in TERMINAL_RUN_STATES:
                return {**status, "finished": True, "waited_seconds": waited_seconds}
            if waited_seconds >= timeout_seconds:
                return {**status, "finished": False, "waited_seconds": waited_seconds}
            self.sleep_function(poll_interval_seconds)
            waited_seconds += poll_interval_seconds

    def get_failed_tasks(self, dag_id: str, dag_run_id: str | None = None) -> dict[str, Any]:
        validate_identifier(dag_id, "DAG ID")
        if dag_run_id is None:
            failed_runs = self.api_client.request(
                "GET",
                f"/api/v2/dags/{dag_id}/dagRuns",
                params={"state": "failed", "order_by": "-run_after", "limit": 1},
            )["dag_runs"]
            if not failed_runs:
                return {
                    "dag_id": dag_id,
                    "dag_run_id": None,
                    "failed_tasks": [],
                    "blocked_tasks": [],
                }
            dag_run_id = failed_runs[0]["dag_run_id"]

        task_instances = self.api_client.request(
            "GET", f"{self._run_path(dag_id, dag_run_id)}/taskInstances"
        )["task_instances"]
        failed_tasks = [
            self._summarize_task(task_instance)
            for task_instance in task_instances
            if task_instance["state"] == "failed"
        ]
        blocked_tasks = [
            self._summarize_task(task_instance)
            for task_instance in task_instances
            if task_instance["state"] == "upstream_failed"
        ]
        return {
            "dag_id": dag_id,
            "dag_run_id": dag_run_id,
            "failed_tasks": failed_tasks,
            "blocked_tasks": blocked_tasks,
        }

    def get_task_logs(
        self,
        dag_id: str,
        dag_run_id: str,
        task_id: str,
        try_number: int | None = None,
        map_index: int = -1,
        max_lines: int = 80,
    ) -> dict[str, Any]:
        validate_identifier(task_id, "task ID")
        if not 1 <= max_lines <= MAXIMUM_LOG_LINES:
            raise InvalidToolInputError(f"max_lines must be between 1 and {MAXIMUM_LOG_LINES}")
        task_path = f"{self._run_path(dag_id, dag_run_id)}/taskInstances/{task_id}"
        if try_number is None:
            instance_path = task_path if map_index == -1 else f"{task_path}/{map_index}"
            try_number = self.api_client.request("GET", instance_path)["try_number"]
        if try_number < 1:
            raise InvalidToolInputError(f"Task {task_id!r} has not run yet")

        log_response = self.api_client.request(
            "GET",
            f"{task_path}/logs/{try_number}",
            params={"full_content": "true", "map_index": map_index},
        )
        log_entries = log_response.get("content") or []
        if isinstance(log_entries, str):
            log_entries = log_entries.splitlines()
        return {
            "dag_id": dag_id,
            "dag_run_id": dag_run_id,
            "task_id": task_id,
            "map_index": map_index,
            "try_number": try_number,
            "exceptions": summarize_exceptions(log_entries),
            "error_lines": [
                format_log_entry(entry) for entry in log_entries if is_error_line(entry)
            ][-20:],
            "last_lines": [format_log_entry(entry) for entry in log_entries][-max_lines:],
        }

    def _run_path(self, dag_id: str, dag_run_id: str) -> str:
        validate_identifier(dag_id, "DAG ID")
        validate_dag_run_id(dag_run_id)
        return f"/api/v2/dags/{dag_id}/dagRuns/{encode_path_segment(dag_run_id)}"

    @staticmethod
    def _summarize_run(dag_run: dict[str, Any]) -> dict[str, Any]:
        return {
            "dag_id": dag_run["dag_id"],
            "dag_run_id": dag_run["dag_run_id"],
            "state": dag_run["state"],
            "run_type": dag_run.get("run_type"),
            "triggered_by": dag_run.get("triggered_by"),
            "start_date": dag_run.get("start_date"),
            "end_date": dag_run.get("end_date"),
            "duration_seconds": dag_run.get("duration"),
        }

    @staticmethod
    def _summarize_task(task_instance: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_id": task_instance["task_id"],
            "map_index": task_instance.get("map_index", -1),
            "state": task_instance["state"],
            "try_number": task_instance.get("try_number"),
            "duration_seconds": task_instance.get("duration"),
        }


def create_airflow_tools() -> AirflowTools:
    username = os.environ.get("AIRFLOW_AGENT_USERNAME")
    password = os.environ.get("AIRFLOW_AGENT_PASSWORD")
    if not username or not password:
        raise ServiceUnavailableError(
            "Airflow credentials are not configured (AIRFLOW_AGENT_USERNAME / PASSWORD)"
        )
    api_client = AirflowApiClient(
        os.environ.get("AIRFLOW_API_URL", DEFAULT_AIRFLOW_URL), username, password
    )
    return AirflowTools(api_client)
