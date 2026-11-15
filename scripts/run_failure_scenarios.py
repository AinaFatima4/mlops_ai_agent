"""Inject each demonstration failure, let the agent diagnose it, save the evidence, then restore."""

import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from agent.llm_client import create_chat_model
from agent.logging_config import configure_logging
from agent.main import TRANSCRIPT_DIRECTORY, TranscriptWriter, format_evidence
from agent.orchestrator import Agent, AgentResponse
from agent.tool_executor import ToolExecutor
from agent.tool_registry import create_default_registry

INJECT_SCRIPT = "./scripts/inject_failure.sh"
KUBECTL = ["kubectl", "--context", "kind-mlops", "-n", "mlops-app"]
POD_SELECTOR = "app.kubernetes.io/name=adult-income-api"
UNREADY_WAIT_SECONDS = 90


def run_command(arguments: list[str]) -> str:
    completed_process = subprocess.run(arguments, capture_output=True, text=True, check=False)
    return (completed_process.stdout + completed_process.stderr).strip()


def create_agent() -> Agent:
    return Agent(
        create_chat_model(),
        ToolExecutor(create_default_registry()),
        on_progress=lambda message: print(f"  ... {message}", flush=True),
    )


def ask_and_record(
    agent: Agent, transcript: TranscriptWriter, question: str, approve_actions: bool
) -> AgentResponse:
    print(f"\nYou: {question}", flush=True)
    transcript.record("User", question)
    response = agent.ask(question)
    while True:
        print(f"\nAgent: {response.answer}\n\n{format_evidence(response)}\n", flush=True)
        transcript.record("Agent", response.answer, response)
        if response.pending_action is None:
            return response
        decision = "Approved" if approve_actions else "Declined"
        transcript.record("User", f"{decision} (scripted answer at the confirmation prompt)")
        response = agent.resolve_pending_action(approve_actions)


def record_system_evidence(transcript: TranscriptWriter, title: str, command: list[str]) -> None:
    output = run_command(command)
    print(f"\n[{title}]\n{output}\n", flush=True)
    transcript.record(f"System evidence: {title}", f"`{' '.join(command)}`\n\n```\n{output}\n```")


def wait_until_pods_unready() -> None:
    deadline = time.monotonic() + UNREADY_WAIT_SECONDS
    while time.monotonic() < deadline:
        ready_states = run_command(
            [
                *KUBECTL,
                "get",
                "pods",
                "-l",
                POD_SELECTOR,
                "-o",
                "jsonpath={.items[*].status.containerStatuses[*].ready}",
            ]
        ).split()
        if ready_states and "true" not in ready_states:
            return
        time.sleep(5)


def run_data_failure_scenario() -> Path:
    transcript = TranscriptWriter(TRANSCRIPT_DIRECTORY, name="failure-1-corrupted-dataset")
    print(run_command([INJECT_SCRIPT, "bad-data"]))
    try:
        record_system_evidence(
            transcript, "dataset row count after injection", ["wc", "-l", "data/adult.csv"]
        )
        agent = create_agent()
        ask_and_record(
            agent,
            transcript,
            "Trigger the model training pipeline and report whether execution succeeded.",
            approve_actions=True,
        )
        agent.reset()
        ask_and_record(
            agent,
            transcript,
            "The training pipeline failed. Find the root cause and tell me how to fix it.",
            approve_actions=False,
        )
    finally:
        print(run_command([INJECT_SCRIPT, "restore-data"]))
        record_system_evidence(
            transcript, "dvc status after restore", ["uv", "run", "dvc", "status"]
        )
    return transcript.path


def run_deployment_failure_scenario() -> Path:
    transcript = TranscriptWriter(TRANSCRIPT_DIRECTORY, name="failure-2-broken-model-path")
    print(run_command([INJECT_SCRIPT, "bad-model-path"]))
    try:
        wait_until_pods_unready()
        record_system_evidence(transcript, "pods while broken", [*KUBECTL, "get", "pods"])
        agent = create_agent()
        ask_and_record(
            agent, transcript, "Why is my prediction API unavailable?", approve_actions=False
        )
    finally:
        print(run_command([INJECT_SCRIPT, "restore-model-path"]))
        record_system_evidence(transcript, "pods after restore", [*KUBECTL, "get", "pods"])
    return transcript.path


def main() -> int:
    load_dotenv()
    configure_logging(Path("logs/agent.log"))
    print("=== Failure 1: corrupted dataset ===", flush=True)
    first_transcript = run_data_failure_scenario()
    print("\n=== Failure 2: broken model path ===", flush=True)
    second_transcript = run_deployment_failure_scenario()
    print(f"\nTranscripts saved:\n  {first_transcript}\n  {second_transcript}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
