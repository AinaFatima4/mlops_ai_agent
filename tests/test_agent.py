import io
import json
import logging
import time
from typing import Any

import httpx
import pytest

from agent.llm_client import (
    LlmResponse,
    LlmToolCall,
    LlmUnavailableError,
    OpenAiCompatibleChatModel,
    parse_chat_completion,
)
from agent.logging_config import JsonFormatter
from agent.orchestrator import MAXIMUM_STEPS, Agent
from agent.schemas import ToolStatus
from agent.tool_executor import ToolExecutor
from agent.tool_registry import ServiceProvider, ToolRegistry
from agent.tools.airflow_tools import AirflowTools
from agent.tools.errors import ServiceUnavailableError
from tests.test_kubernetes_tools import build_pod
from tests.test_kubernetes_tools import build_tools as build_kubernetes_tools

BEST_RUN_ID = "a" * 32
DATASET_MD5 = "b" * 32


class ScriptedChatModel:
    def __init__(self, responses: list[LlmResponse]) -> None:
        self.responses = list(responses)
        self.received_messages: list[list[dict[str, Any]]] = []

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LlmResponse:
        self.received_messages.append([dict(message) for message in messages])
        if not self.responses:
            return LlmResponse(content="(no more scripted responses)")
        return self.responses.pop(0)


def call_tool(name: str, arguments: dict[str, Any], call_id: str = "call_1") -> LlmResponse:
    return LlmResponse(content="", tool_calls=[LlmToolCall(call_id, name, json.dumps(arguments))])


class FakeMlflowTools:
    def find_best_run(self, experiment_name: str, metric: str, recent_run_limit: int) -> dict:
        return {
            "best_run": {
                "run_id": BEST_RUN_ID,
                "metrics": {"f1": 0.71},
                "provenance": {"dataset.md5": DATASET_MD5},
            },
            "warnings": ["Selected by f1 alone."],
        }


class FakeDvcTools:
    def find_version_by_hash(self, dataset_path: str, md5_hash: str) -> dict:
        return {"found": True, "version": {"version": "dataset-v2.0", "md5": md5_hash}}


class FakeAirflowApiClient:
    def __init__(self) -> None:
        self.posted_paths: list[str] = []

    def request(self, method: str, path: str, params=None, json_body=None) -> dict:
        if method == "POST":
            self.posted_paths.append(path)
            return {
                "dag_id": "adult_income_training",
                "dag_run_id": "manual__run",
                "state": "queued",
            }
        if path.endswith("/dagRuns"):
            return {
                "dag_runs": [
                    {"dag_id": "adult_income_training", "dag_run_id": "r1", "state": "success"}
                ]
            }
        return {"is_paused": False}


class SlowTools:
    def list_experiments(self) -> dict:
        time.sleep(1)
        return {"experiments": []}


def unavailable_factory() -> Any:
    raise ServiceUnavailableError("Agent kubeconfig not found")


@pytest.fixture
def services() -> dict[str, Any]:
    kubernetes_tools, _, kubernetes_apps_api = build_kubernetes_tools([build_pod("api-1")])
    airflow_api_client = FakeAirflowApiClient()
    return {
        "mlflow": FakeMlflowTools(),
        "dvc": FakeDvcTools(),
        "kubernetes": kubernetes_tools,
        "kubernetes_apps_api": kubernetes_apps_api,
        "airflow": AirflowTools(airflow_api_client),
        "airflow_api_client": airflow_api_client,
    }


def build_agent(
    responses: list[LlmResponse],
    services: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    timeout_seconds: float = 30,
) -> tuple[Agent, ScriptedChatModel]:
    factories = {
        name: (lambda service=service: service)
        for name, service in services.items()
        if name in {"mlflow", "dvc", "kubernetes", "airflow"}
    }
    factories.update(overrides or {})
    registry = ToolRegistry(ServiceProvider(factories))
    chat_model = ScriptedChatModel(responses)
    return Agent(chat_model, ToolExecutor(registry, timeout_seconds=timeout_seconds)), chat_model


def test_agent_selects_and_executes_requested_tool(services: dict) -> None:
    agent, chat_model = build_agent(
        [
            call_tool("mlflow_find_best_run", {"metric": "f1"}),
            LlmResponse(content="Best run found."),
        ],
        services,
    )
    response = agent.ask("Which run is best?")
    assert response.answer == "Best run found."
    assert [result.tool_name for result in response.tool_results] == ["mlflow_find_best_run"]
    assert response.tool_results[0].status == ToolStatus.SUCCESS
    tool_message = chat_model.received_messages[1][-1]
    assert tool_message["role"] == "tool" and BEST_RUN_ID in tool_message["content"]


def test_multi_tool_request_gathers_evidence_from_all_four_services(services: dict) -> None:
    agent, _ = build_agent(
        [
            call_tool("mlflow_find_best_run", {}),
            call_tool("dvc_find_version_by_hash", {"md5_hash": DATASET_MD5}),
            call_tool("kubernetes_get_deployed_version", {}),
            call_tool("airflow_list_dag_runs", {}),
            LlmResponse(content="Facts: ... Uncertainties: ... Recommended actions: ..."),
        ],
        services,
    )
    response = agent.ask("Find the best model, its dataset, deployment and retraining need.")
    assert [result.tool_name.split("_")[0] for result in response.tool_results] == [
        "mlflow",
        "dvc",
        "kubernetes",
        "airflow",
    ]
    assert all(result.succeeded for result in response.tool_results)
    assert services["airflow_api_client"].posted_paths == []


def test_unknown_tool_is_reported_back_as_invalid_input(services: dict) -> None:
    agent, _ = build_agent(
        [call_tool("delete_cluster", {}), LlmResponse(content="That tool does not exist.")],
        services,
    )
    response = agent.ask("Delete everything")
    assert response.tool_results[0].status == ToolStatus.INVALID_INPUT


def test_model_cannot_confirm_its_own_state_change(services: dict) -> None:
    agent, _ = build_agent(
        [
            call_tool("kubernetes_restart_deployment", {"confirmed": True}),
            LlmResponse(content="Rejected."),
        ],
        services,
    )
    response = agent.ask("Restart the API")
    assert response.tool_results[0].status == ToolStatus.INVALID_INPUT
    assert services["kubernetes_apps_api"].patches == []


def test_unauthorized_kubernetes_namespace_is_rejected(services: dict) -> None:
    agent, _ = build_agent(
        [
            call_tool("kubernetes_restart_deployment", {"namespace": "kube-system"}),
            LlmResponse(content="Not allowed."),
        ],
        services,
    )
    response = agent.ask("Restart coredns in kube-system")
    assert response.tool_results[0].status == ToolStatus.PERMISSION_DENIED
    assert response.pending_action is None
    assert services["kubernetes_apps_api"].patches == []


def test_restart_waits_for_user_approval_before_running(services: dict) -> None:
    agent, _ = build_agent(
        [call_tool("kubernetes_restart_deployment", {}), LlmResponse(content="Restarted.")],
        services,
    )
    response = agent.ask("Restart the prediction API")
    assert response.pending_action is not None
    assert services["kubernetes_apps_api"].patches == []

    final_response = agent.resolve_pending_action(approved=True)
    assert len(services["kubernetes_apps_api"].patches) == 1
    assert final_response.answer == "Restarted."


def test_declined_action_is_never_executed(services: dict) -> None:
    agent, chat_model = build_agent(
        [
            call_tool("kubernetes_restart_deployment", {}),
            LlmResponse(content="Okay, not restarted."),
        ],
        services,
    )
    agent.ask("Restart the prediction API")
    agent.resolve_pending_action(approved=False)
    assert services["kubernetes_apps_api"].patches == []
    assert "declined" in chat_model.received_messages[-1][-1]["content"]


def test_retraining_is_not_started_without_confirmation(services: dict) -> None:
    agent, _ = build_agent([call_tool("airflow_trigger_dag", {})], services)
    response = agent.ask("Is retraining necessary?")
    assert response.pending_action is not None
    assert services["airflow_api_client"].posted_paths == []


def test_new_question_after_pending_action_counts_as_declined(services: dict) -> None:
    agent, chat_model = build_agent(
        [call_tool("airflow_trigger_dag", {}), LlmResponse(content="Sure.")], services
    )
    agent.ask("Retrain")
    agent.ask("Actually, just list the experiments")
    abandoned_message = chat_model.received_messages[-1][-2]
    assert abandoned_message["role"] == "tool" and "declined" in abandoned_message["content"]
    assert services["airflow_api_client"].posted_paths == []


def test_agent_does_not_present_results_from_an_unavailable_tool(services: dict) -> None:
    agent, chat_model = build_agent(
        [
            call_tool("kubernetes_find_unhealthy_pods", {}),
            LlmResponse(content="All pods are healthy."),
        ],
        services,
        overrides={"kubernetes": unavailable_factory},
    )
    response = agent.ask("Is the API healthy?")
    assert response.tool_results[0].status == ToolStatus.UNAVAILABLE
    tool_message = json.loads(chat_model.received_messages[1][-1]["content"])
    assert "data" not in tool_message
    assert "Do not state any result" in tool_message["instruction"]
    assert "Unverified" in response.answer
    assert "kubernetes_find_unhealthy_pods" in response.answer


def test_slow_tool_times_out_as_unavailable(services: dict) -> None:
    agent, _ = build_agent(
        [call_tool("mlflow_list_experiments", {}), LlmResponse(content="Timed out.")],
        services,
        overrides={"mlflow": SlowTools},
        timeout_seconds=0.1,
    )
    response = agent.ask("List experiments")
    assert response.tool_results[0].status == ToolStatus.UNAVAILABLE
    assert "timed out" in response.tool_results[0].error


def test_unavailable_language_model_returns_clear_message(services: dict) -> None:
    class BrokenChatModel:
        def complete(self, messages, tools):
            raise LlmUnavailableError("connection refused")

    registry = ToolRegistry(ServiceProvider({}))
    agent = Agent(BrokenChatModel(), ToolExecutor(registry))
    response = agent.ask("Anything")
    assert "language model is unavailable" in response.answer


def test_agent_stops_after_maximum_steps(services: dict) -> None:
    looping_responses = [
        call_tool("mlflow_find_best_run", {}, call_id=f"call_{index}")
        for index in range(MAXIMUM_STEPS + 1)
    ]
    agent, _ = build_agent(looping_responses, services)
    response = agent.ask("Loop forever")
    assert f"stopped after {MAXIMUM_STEPS} steps" in response.answer


def test_structured_log_records_tool_call_without_secrets(services: dict) -> None:
    secret_value = "super-secret-password-123"

    class FailingMlflowTools:
        def find_best_run(self, **arguments: Any) -> dict:
            raise ServiceUnavailableError(f"login failed for password {secret_value}")

    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(JsonFormatter({secret_value}))
    tool_logger = logging.getLogger("agent.tools")
    tool_logger.addHandler(handler)
    tool_logger.setLevel(logging.INFO)
    try:
        agent, _ = build_agent(
            [call_tool("mlflow_find_best_run", {}), LlmResponse(content="Done.")],
            services,
            overrides={"mlflow": FailingMlflowTools},
        )
        response = agent.ask("Best run?")
    finally:
        tool_logger.removeHandler(handler)

    log_entry = json.loads(log_stream.getvalue().strip().splitlines()[-1])
    assert log_entry["request_id"] == response.request_id
    assert log_entry["tool"] == "mlflow_find_best_run"
    assert log_entry["status"] == "unavailable"
    assert isinstance(log_entry["duration_ms"], float)
    assert secret_value not in log_stream.getvalue()
    assert "***REDACTED***" in log_entry["error"]


def test_chat_completion_parsing_handles_string_and_object_arguments() -> None:
    body = {
        "choices": [
            {
                "message": {
                    "content": "<think>internal</think>Checking now.",
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "mlflow_list_runs", "arguments": "{}"}},
                        {"function": {"name": "dvc_check_data_changed", "arguments": {}}},
                    ],
                }
            }
        ]
    }
    response = parse_chat_completion(body)
    assert response.content == "Checking now."
    assert [call.name for call in response.tool_calls] == [
        "mlflow_list_runs",
        "dvc_check_data_changed",
    ]
    assert response.tool_calls[1].call_id == "call_1"
    assert response.tool_calls[1].arguments_json == "{}"


def test_llm_http_error_raises_unavailable() -> None:
    chat_model = OpenAiCompatibleChatModel(
        "http://llm.test/v1",
        "test-model",
        "key",
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="boom")),
    )
    with pytest.raises(LlmUnavailableError):
        chat_model.complete([{"role": "user", "content": "hi"}], [])


def test_empty_final_answer_is_retried_once(services: dict) -> None:
    agent, chat_model = build_agent(
        [
            call_tool("kubernetes_find_unhealthy_pods", {}),
            LlmResponse(content=""),
            LlmResponse(content="All pods are healthy."),
        ],
        services,
    )
    response = agent.ask("Is the API healthy?")
    assert response.answer == "All pods are healthy."
    assert "empty answer" in chat_model.received_messages[-1][-1]["content"]


def test_repeated_empty_answer_falls_back_to_tool_summary(services: dict) -> None:
    agent, _ = build_agent(
        [
            call_tool("kubernetes_find_unhealthy_pods", {}),
            LlmResponse(content=""),
            LlmResponse(content=""),
        ],
        services,
    )
    response = agent.ask("Is the API healthy?")
    assert "did not write an answer" in response.answer
    assert "kubernetes_find_unhealthy_pods: success" in response.answer


def test_old_turns_are_dropped_when_history_exceeds_budget(
    services: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_HISTORY_CHARACTERS", "1500")
    long_answer = "x" * 1000
    agent, chat_model = build_agent(
        [LlmResponse(content=long_answer), LlmResponse(content=long_answer), LlmResponse("ok")],
        services,
    )
    agent.ask("first question")
    agent.ask("second question")
    agent.ask("third question")
    final_request = chat_model.received_messages[-1]
    user_messages = [message["content"] for message in final_request if message["role"] == "user"]
    assert "first question" not in user_messages
    assert user_messages[-1] == "third question"
    assert final_request[0]["role"] == "system"


def test_cut_off_answer_is_flagged(services: dict) -> None:
    agent, _ = build_agent(
        [LlmResponse(content="Partial table | dataset-v2.0 (MD5: 0676", finish_reason="length")],
        services,
    )
    response = agent.ask("Long question")
    assert "Answer cut off" in response.answer
