"""Agent loop: the LLM picks tools, the executor runs them, and answers rest on their results."""

import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent.llm_client import ChatModel, LlmToolCall, LlmUnavailableError
from agent.schemas import ToolResult, ToolStatus
from agent.tool_executor import ToolExecutor

MAXIMUM_STEPS = 12
MAXIMUM_TOOL_RESULT_CHARACTERS = 6000
# Roughly 4 characters per token; keeps history well inside a 16K-token context window
DEFAULT_HISTORY_CHARACTER_BUDGET = 24000
# Which systems a question needs evidence from, recognised by phrases in the question
SERVICE_TRIGGER_PHRASES = {
    "dvc": ("dataset", "data version", "dvc"),
    "mlflow": ("best model", "best recent model", "experiment", "training runs", "f1", "metric"),
    "kubernetes": ("deploy", "pod", "kubernetes", "endpoint", "prediction api"),
    "airflow": ("pipeline", "dag", "airflow"),
}
ALL_SERVICES_TRIGGER_PHRASES = ("retrain",)
TRUNCATED_ANSWER_NOTICE = (
    "\n\n[Answer cut off: the model reached its output or context limit. "
    "Type 'reset' and ask again.]"
)
EMPTY_ANSWER_NUDGE = (
    "You returned an empty answer. Write the final answer now in plain text, based only on "
    "the tool results above, ending with Facts, Uncertainties and Recommended actions."
)

SYSTEM_PROMPT = """You are an MLOps operations agent for the Adult Income classifier project.
You can call tools that query DVC, MLflow, Apache Airflow and Kubernetes.

Rules:
1. Every operational fact (versions, metrics, run states, pod health) must come from a tool
   result in this conversation. Never guess or fill in values from general knowledge.
2. If a tool returns status unavailable, error or permission_denied, say plainly which
   information could not be retrieved and treat it as unknown.
3. Call several tools when a question needs evidence from several systems. Connect them:
   an MLflow run's dataset.md5 tag can be resolved with dvc_find_version_by_hash.
4. Never start retraining or restart workloads unless the user explicitly asked for it.
   State-changing tools pause for the user's confirmation automatically.
5. Recommend retraining only with evidence: a failed quality gate, a newer dataset version
   than the one the deployed model used, a failed training run, or degradation results.
   The highest metric alone does not make a model production-ready.
6. End answers about system state with three short sections: Facts, Uncertainties,
   Recommended actions.
7. Only make claims about systems you queried in this conversation. Under Uncertainties,
   list relevant things you did not check (for example the deployment or recent Airflow
   runs) instead of writing "None". If you want to compare with the deployed model, call
   kubernetes_get_deployed_version first.
8. After the tool calls, always write a final answer in plain text; never reply empty.
9. To decide whether retraining is necessary, gather all of: the best run and its dataset
   (mlflow_find_best_run, then dvc_find_version_by_hash on its dataset.md5), the newest
   dataset version (dvc_get_current_dataset_version), the deployed model
   (kubernetes_get_deployed_version) and recent training runs (airflow_list_dag_runs).

10. When a pipeline fails on data, first check whether the dataset file in the workspace
    still matches its committed DVC version (dvc_get_current_dataset_version shows
    workspace_matches_committed_version; dvc_check_data_changed shows modified files).
    A modified workspace file is a different root cause from a bad tagged version.

"Best" means highest F1 unless the user names another metric.

Defaults: dataset data/adult.csv, experiment adult-income, registered model
adult-income-classifier, DAG adult_income_training, namespace mlops-app,
deployment adult-income-api."""


@dataclass
class PendingAction:
    tool_call: LlmToolCall
    description: str


@dataclass
class AgentResponse:
    request_id: str
    answer: str
    tool_results: list[ToolResult] = field(default_factory=list)
    pending_action: PendingAction | None = None

    @property
    def failed_tools(self) -> list[ToolResult]:
        return [
            result
            for result in self.tool_results
            if result.status in {ToolStatus.UNAVAILABLE, ToolStatus.ERROR}
        ]


def serialize_tool_result(result: ToolResult) -> str:
    payload: dict[str, Any] = {"status": result.status.value}
    if result.succeeded:
        payload["data"] = result.data
    else:
        payload["error"] = result.error
        payload["instruction"] = "No data was returned. Do not state any result from this tool."
    serialized = json.dumps(payload, default=str)
    if len(serialized) > MAXIMUM_TOOL_RESULT_CHARACTERS:
        serialized = serialized[:MAXIMUM_TOOL_RESULT_CHARACTERS] + '..."(truncated)"'
    return serialized


def required_services(user_message: str) -> set[str]:
    lowered_message = user_message.lower()
    if any(phrase in lowered_message for phrase in ALL_SERVICES_TRIGGER_PHRASES):
        return set(SERVICE_TRIGGER_PHRASES)
    return {
        service
        for service, phrases in SERVICE_TRIGGER_PHRASES.items()
        if any(phrase in lowered_message for phrase in phrases)
    }


def build_coverage_nudge(missing_services: set[str]) -> str:
    tool_prefixes = ", ".join(f"{service}_*" for service in sorted(missing_services))
    return (
        "Before answering, query these systems for this question, because earlier results in "
        f"the conversation may be outdated: {', '.join(sorted(missing_services))} "
        f"(tools {tool_prefixes}). Then write the final answer."
    )


def message_size(message: dict[str, Any]) -> int:
    return len(json.dumps(message, default=str))


def trim_history(messages: list[dict[str, Any]], character_budget: int) -> list[dict[str, Any]]:
    """Drop the oldest whole question-and-answer turns until the history fits the budget."""
    system_message, conversation = messages[0], messages[1:]
    turn_starts = [index for index, message in enumerate(conversation) if message["role"] == "user"]
    while (
        len(turn_starts) > 1
        and sum(message_size(message) for message in conversation) > character_budget
    ):
        # Remove everything before the second turn, so assistant/tool messages stay paired
        conversation = conversation[turn_starts[1] :]
        turn_starts = [
            index for index, message in enumerate(conversation) if message["role"] == "user"
        ]
    return [system_message, *conversation]


def build_fallback_answer(results: list[ToolResult]) -> str:
    lines = ["The language model did not write an answer. These are the tool results it received:"]
    lines.extend(f"- {result.tool_name}: {result.status.value}" for result in results)
    lines.append("Run the question again, or check logs/agent.log for details.")
    return "\n".join(lines)


def build_unverified_notice(failed_results: list[ToolResult]) -> str:
    lines = ["", "Unverified: these tools did not return data, so related facts are unknown:"]
    lines.extend(f"- {result.tool_name}: {result.error}" for result in failed_results)
    return "\n".join(lines)


ProgressCallback = Callable[[str], None]


def ignore_progress(message: str) -> None:
    return None


class Agent:
    def __init__(
        self,
        chat_model: ChatModel,
        tool_executor: ToolExecutor,
        on_progress: ProgressCallback = ignore_progress,
    ) -> None:
        self.chat_model = chat_model
        self.tool_executor = tool_executor
        self.on_progress = on_progress
        self.history_character_budget = int(
            os.environ.get("AGENT_HISTORY_CHARACTERS", DEFAULT_HISTORY_CHARACTER_BUDGET)
        )
        self.tool_schemas = tool_executor.registry.function_schemas()
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.pending_action: PendingAction | None = None
        self.current_required_services: set[str] = set()
        self.current_attempted_services: set[str] = set()
        self.current_request_id = ""
        self.current_results: list[ToolResult] = []

    def ask(self, user_message: str) -> AgentResponse:
        if self.pending_action is not None:
            # A new question replaces an unanswered confirmation, which counts as declined
            self._append_tool_message(
                self.pending_action.tool_call.call_id,
                json.dumps(
                    {"status": "declined", "error": "The user moved on without confirming."}
                ),
            )
            self.pending_action = None
        self.current_request_id = uuid.uuid4().hex[:12]
        self.current_results = []
        self.current_required_services = required_services(user_message)
        self.current_attempted_services: set[str] = set()
        self.messages.append({"role": "user", "content": user_message})
        self.messages = trim_history(self.messages, self.history_character_budget)
        return self._run_loop()

    def resolve_pending_action(self, approved: bool) -> AgentResponse:
        if self.pending_action is None:
            raise RuntimeError("There is no action waiting for confirmation")
        tool_call = self.pending_action.tool_call
        self.pending_action = None
        if approved:
            result = self.tool_executor.execute(
                tool_call.name, tool_call.arguments_json, self.current_request_id, confirmed=True
            )
            self.current_results.append(result)
            tool_message = serialize_tool_result(result)
        else:
            tool_message = json.dumps(
                {"status": "declined", "error": "The user declined. The action was not run."}
            )
        self._append_tool_message(tool_call.call_id, tool_message)
        return self._run_loop()

    def _missing_services(self) -> set[str]:
        # Attempts count too, so a declined or refused action is never asked for again
        return self.current_required_services - self.current_attempted_services

    def _append_tool_message(self, call_id: str, content: str) -> None:
        self.messages.append({"role": "tool", "tool_call_id": call_id, "content": content})

    def reset(self) -> None:
        self.messages = self.messages[:1]
        self.pending_action = None

    def _run_loop(self) -> AgentResponse:
        nudged_for_empty_answer = False
        nudged_for_coverage = False
        for step_number in range(1, MAXIMUM_STEPS + 1):
            self.on_progress(f"step {step_number}: waiting for the language model...")
            step_start = time.perf_counter()
            try:
                llm_response = self.chat_model.complete(self.messages, self.tool_schemas)
            except LlmUnavailableError as error:
                return self._finish(f"The language model is unavailable: {error}")
            self.on_progress(
                f"step {step_number}: model replied in {time.perf_counter() - step_start:.1f}s "
                f"with {len(llm_response.tool_calls)} tool call(s)"
            )
            self.messages.append(llm_response.as_assistant_message())

            if not llm_response.tool_calls:
                missing_services = self._missing_services()
                if missing_services and not nudged_for_coverage:
                    # Enforced in code: the answer must rest on evidence gathered for this question
                    nudged_for_coverage = True
                    self.on_progress(f"asking the model to also check: {sorted(missing_services)}")
                    self.messages.append(
                        {"role": "user", "content": build_coverage_nudge(missing_services)}
                    )
                    continue
                if llm_response.content:
                    answer = llm_response.content
                    if llm_response.finish_reason == "length":
                        answer += TRUNCATED_ANSWER_NOTICE
                    return self._finish(answer)
                if not nudged_for_empty_answer:
                    # Some models put their whole reply in hidden reasoning; ask once more
                    nudged_for_empty_answer = True
                    self.messages.append({"role": "user", "content": EMPTY_ANSWER_NUDGE})
                    continue
                return self._finish(build_fallback_answer(self.current_results))

            for position, tool_call in enumerate(llm_response.tool_calls):
                result = self.tool_executor.execute(
                    tool_call.name, tool_call.arguments_json, self.current_request_id
                )
                if result.status != ToolStatus.INVALID_INPUT:
                    self.current_attempted_services.add(result.tool_name.split("_", 1)[0])
                if result.status == ToolStatus.CONFIRMATION_REQUIRED:
                    self.pending_action = PendingAction(tool_call, result.error or tool_call.name)
                    for skipped_call in llm_response.tool_calls[position + 1 :]:
                        self._append_tool_message(
                            skipped_call.call_id,
                            json.dumps({"status": "skipped", "error": "Waiting for confirmation."}),
                        )
                    return self._finish(
                        f"Before I continue, please confirm: {self.pending_action.description}"
                    )
                self.on_progress(
                    f"  {result.tool_name} -> {result.status.value} ({result.duration_ms:.0f} ms)"
                )
                self.current_results.append(result)
                self._append_tool_message(tool_call.call_id, serialize_tool_result(result))
        return self._finish(
            f"I stopped after {MAXIMUM_STEPS} steps without a final answer. "
            "Please narrow the question."
        )

    def _finish(self, answer: str) -> AgentResponse:
        response = AgentResponse(
            request_id=self.current_request_id,
            answer=answer,
            tool_results=list(self.current_results),
            pending_action=self.pending_action,
        )
        # Added by code, not the model: the user always sees which evidence is missing
        if response.failed_tools and response.pending_action is None:
            response.answer += build_unverified_notice(response.failed_tools)
        return response
