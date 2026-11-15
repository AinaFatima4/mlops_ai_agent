from pathlib import Path

import pytest

import scripts.run_failure_scenarios as scenarios
from agent.llm_client import LlmResponse
from agent.orchestrator import Agent
from agent.tool_executor import ToolExecutor
from agent.tool_registry import ServiceProvider, ToolRegistry
from tests.test_agent import ScriptedChatModel


@pytest.fixture
def recorded_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[list[str]]:
    commands: list[list[str]] = []

    def fake_run_command(arguments: list[str]) -> str:
        commands.append(arguments)
        return "false false" if "jsonpath" in " ".join(arguments) else "ok"

    monkeypatch.setattr(scenarios, "run_command", fake_run_command)
    monkeypatch.setattr(scenarios, "TRANSCRIPT_DIRECTORY", tmp_path)
    return commands


def build_scripted_agent(answers: list[str]) -> Agent:
    registry = ToolRegistry(ServiceProvider({}))
    responses = [LlmResponse(content=answer) for answer in answers]
    return Agent(ScriptedChatModel(responses), ToolExecutor(registry))


def test_data_scenario_restores_data_and_saves_transcript(
    monkeypatch: pytest.MonkeyPatch, recorded_commands: list[list[str]]
) -> None:
    monkeypatch.setattr(
        scenarios, "create_agent", lambda: build_scripted_agent(["Run failed.", "Root cause."])
    )
    transcript_path = scenarios.run_data_failure_scenario()
    assert [scenarios.INJECT_SCRIPT, "bad-data"] in recorded_commands
    assert [scenarios.INJECT_SCRIPT, "restore-data"] in recorded_commands
    transcript_text = transcript_path.read_text()
    assert "Root cause." in transcript_text
    assert "dvc status after restore" in transcript_text


def test_deployment_scenario_restores_even_when_agent_crashes(
    monkeypatch: pytest.MonkeyPatch, recorded_commands: list[list[str]]
) -> None:
    def crashing_agent() -> Agent:
        raise RuntimeError("agent could not start")

    monkeypatch.setattr(scenarios, "create_agent", crashing_agent)
    with pytest.raises(RuntimeError):
        scenarios.run_deployment_failure_scenario()
    assert [scenarios.INJECT_SCRIPT, "restore-model-path"] in recorded_commands
