import json

import httpx
import pytest

from agent.tools.airflow_tools import AirflowApiClient, AirflowTools
from agent.tools.errors import (
    ConfirmationRequiredError,
    InvalidToolInputError,
    ServiceUnavailableError,
    ToolPermissionError,
)

DAG_ID = "adult_income_training"
DAG_RUN_ID = "manual__2026-11-14T22:40:25.061356+00:00"
ENCODED_RUN_PATH = f"/api/v2/dags/{DAG_ID}/dagRuns/manual__2026-11-14T22%3A40%3A25.061356%2B00%3A00"


def build_dag_run(state: str, dag_run_id: str = DAG_RUN_ID) -> dict:
    return {
        "dag_id": DAG_ID,
        "dag_run_id": dag_run_id,
        "state": state,
        "run_type": "manual",
        "triggered_by": "rest_api",
        "start_date": None,
        "end_date": None,
        "duration": None,
    }


def build_task_instance(task_id: str, state: str, map_index: int = -1) -> dict:
    return {
        "task_id": task_id,
        "map_index": map_index,
        "state": state,
        "try_number": 1,
        "duration": 1.5,
    }


class FakeAirflowServer:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], httpx.Response | Exception] = {}
        self.received_requests: list[httpx.Request] = []
        self.issued_token_count = 0

    def add_route(self, method: str, path: str, response: httpx.Response | Exception) -> None:
        self.routes[(method, path)] = response

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.received_requests.append(request)
        if request.url.path == "/auth/token":
            self.issued_token_count += 1
            return httpx.Response(201, json={"access_token": f"token-{self.issued_token_count}"})
        route_response = self.routes.get(
            (request.method, request.url.raw_path.decode().split("?")[0])
        )
        if route_response is None:
            return httpx.Response(404, json={"detail": "not found"})
        if isinstance(route_response, Exception):
            raise route_response
        return route_response


@pytest.fixture
def fake_server() -> FakeAirflowServer:
    return FakeAirflowServer()


def build_tools(fake_server: FakeAirflowServer) -> AirflowTools:
    api_client = AirflowApiClient(
        "http://airflow.test",
        "mlops_agent",
        "secret",
        transport=httpx.MockTransport(fake_server.handle),
    )
    return AirflowTools(api_client, sleep_function=lambda seconds: None)


def test_requests_carry_bearer_token(fake_server: FakeAirflowServer) -> None:
    fake_server.add_route("GET", "/api/v2/dags", httpx.Response(200, json={"dags": []}))
    fake_server.add_route(
        "GET", "/api/v2/importErrors", httpx.Response(200, json={"import_errors": []})
    )
    build_tools(fake_server).list_dags()
    api_request = fake_server.received_requests[1]
    assert api_request.headers["Authorization"] == "Bearer token-1"


def test_rejected_token_is_refreshed_once() -> None:
    issued_tokens: list[str] = []
    api_responses = iter(
        [
            httpx.Response(401, json={"detail": "expired"}),
            httpx.Response(200, json={"dag_runs": []}),
        ]
    )

    def handle_with_expired_token(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            issued_tokens.append(f"token-{len(issued_tokens) + 1}")
            return httpx.Response(201, json={"access_token": issued_tokens[-1]})
        return next(api_responses)

    api_client = AirflowApiClient(
        "http://airflow.test",
        "user",
        "secret",
        transport=httpx.MockTransport(handle_with_expired_token),
    )
    result = AirflowTools(api_client).list_dag_runs(DAG_ID)
    assert result["dag_runs"] == []
    assert issued_tokens == ["token-1", "token-2"]


def test_list_dags_includes_import_errors(fake_server: FakeAirflowServer) -> None:
    fake_server.add_route(
        "GET",
        "/api/v2/dags",
        httpx.Response(
            200,
            json={"dags": [{"dag_id": DAG_ID, "is_paused": False, "tags": [{"name": "mlops"}]}]},
        ),
    )
    fake_server.add_route(
        "GET",
        "/api/v2/importErrors",
        httpx.Response(
            200,
            json={
                "import_errors": [
                    {"filename": "broken.py", "stack_trace": "Traceback\nValueError: bad DAG\n"}
                ]
            },
        ),
    )
    result = build_tools(fake_server).list_dags()
    assert result["dags"][0]["trigger_approved"] is True
    assert result["import_errors"] == [{"file": "broken.py", "error": "ValueError: bad DAG"}]


def test_unapproved_dag_trigger_is_rejected_without_api_call(
    fake_server: FakeAirflowServer,
) -> None:
    with pytest.raises(ToolPermissionError):
        build_tools(fake_server).trigger_dag("delete_everything", confirmed=True)
    assert fake_server.received_requests == []


def test_trigger_without_confirmation_is_not_executed(fake_server: FakeAirflowServer) -> None:
    with pytest.raises(ConfirmationRequiredError):
        build_tools(fake_server).trigger_dag(DAG_ID)
    assert fake_server.received_requests == []


def test_confirmed_trigger_posts_new_run(fake_server: FakeAirflowServer) -> None:
    fake_server.add_route(
        "GET", f"/api/v2/dags/{DAG_ID}", httpx.Response(200, json={"is_paused": False})
    )
    fake_server.add_route(
        "POST", f"/api/v2/dags/{DAG_ID}/dagRuns", httpx.Response(200, json=build_dag_run("queued"))
    )
    result = build_tools(fake_server).trigger_dag(DAG_ID, confirmed=True)
    assert result["state"] == "queued"
    posted_body = json.loads(fake_server.received_requests[-1].content)
    assert posted_body["logical_date"] is None


def test_paused_dag_is_not_triggered(fake_server: FakeAirflowServer) -> None:
    fake_server.add_route(
        "GET", f"/api/v2/dags/{DAG_ID}", httpx.Response(200, json={"is_paused": True})
    )
    with pytest.raises(ServiceUnavailableError, match="paused"):
        build_tools(fake_server).trigger_dag(DAG_ID, confirmed=True)


def test_wait_for_dag_run_polls_until_terminal_state(fake_server: FakeAirflowServer) -> None:
    run_states = iter(["running", "running", "success"])

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(201, json={"access_token": "token"})
        if request.url.raw_path.decode().endswith("/taskInstances"):
            return httpx.Response(200, json={"task_instances": []})
        return httpx.Response(200, json=build_dag_run(next(run_states)))

    api_client = AirflowApiClient(
        "http://airflow.test", "user", "secret", transport=httpx.MockTransport(handle)
    )
    tools = AirflowTools(api_client, sleep_function=lambda seconds: None)
    result = tools.wait_for_dag_run(
        DAG_ID, DAG_RUN_ID, timeout_seconds=60, poll_interval_seconds=10
    )
    assert result["state"] == "success"
    assert result["finished"] is True
    assert result["waited_seconds"] == 20


def test_failed_tasks_separate_root_cause_from_blocked_tasks(
    fake_server: FakeAirflowServer,
) -> None:
    fake_server.add_route(
        "GET",
        f"{ENCODED_RUN_PATH}/taskInstances",
        httpx.Response(
            200,
            json={
                "task_instances": [
                    build_task_instance("validate_data", "success"),
                    build_task_instance("quality_gate", "failed"),
                    build_task_instance("register_candidate", "upstream_failed"),
                ]
            },
        ),
    )
    result = build_tools(fake_server).get_failed_tasks(DAG_ID, DAG_RUN_ID)
    assert [task["task_id"] for task in result["failed_tasks"]] == ["quality_gate"]
    assert [task["task_id"] for task in result["blocked_tasks"]] == ["register_candidate"]


def test_task_logs_extract_exceptions_and_error_lines(fake_server: FakeAirflowServer) -> None:
    fake_server.add_route(
        "GET",
        f"{ENCODED_RUN_PATH}/taskInstances/quality_gate/logs/2",
        httpx.Response(
            200,
            json={
                "content": [
                    {"timestamp": "t1", "level": "info", "event": "Starting"},
                    {
                        "timestamp": "t2",
                        "level": "error",
                        "event": "Task failed with exception",
                        "error_detail": [
                            {"exc_type": "RuntimeError", "exc_value": "Quality gate failed"}
                        ],
                    },
                ]
            },
        ),
    )
    result = build_tools(fake_server).get_task_logs(
        DAG_ID, DAG_RUN_ID, "quality_gate", try_number=2
    )
    assert result["exceptions"] == [{"type": "RuntimeError", "message": "Quality gate failed"}]
    assert result["error_lines"] == ["t2 ERROR Task failed with exception"]


def test_timeout_becomes_service_unavailable(fake_server: FakeAirflowServer) -> None:
    fake_server.add_route("GET", "/api/v2/dags", httpx.ReadTimeout("timed out"))
    with pytest.raises(ServiceUnavailableError, match="timed out"):
        build_tools(fake_server).list_dags()


def test_unreachable_server_becomes_service_unavailable() -> None:
    def refuse_connection(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    api_client = AirflowApiClient(
        "http://airflow.test", "user", "secret", transport=httpx.MockTransport(refuse_connection)
    )
    with pytest.raises(ServiceUnavailableError, match="unreachable"):
        AirflowTools(api_client).list_dags()


def test_wrong_credentials_raise_service_unavailable() -> None:
    def reject_login(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid credentials"})

    api_client = AirflowApiClient(
        "http://airflow.test", "user", "wrong", transport=httpx.MockTransport(reject_login)
    )
    with pytest.raises(ServiceUnavailableError, match="authentication failed"):
        AirflowTools(api_client).list_dags()


@pytest.mark.parametrize("dag_run_id", ["../../admin", "run id with spaces", "run;rm -rf /", ""])
def test_malformed_run_ids_are_rejected(fake_server: FakeAirflowServer, dag_run_id: str) -> None:
    with pytest.raises(InvalidToolInputError):
        build_tools(fake_server).get_dag_run_status(DAG_ID, dag_run_id)
