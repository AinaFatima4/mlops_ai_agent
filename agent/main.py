"""Command-line chat interface for the MLOps agent."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from agent.llm_client import create_chat_model
from agent.logging_config import configure_logging
from agent.orchestrator import Agent, AgentResponse
from agent.tool_executor import ToolExecutor
from agent.tool_registry import create_default_registry

LOG_FILE = Path("logs/agent.log")
TRANSCRIPT_DIRECTORY = Path("docs/conversations")
EXIT_COMMANDS = {"exit", "quit"}
STATUS_SYMBOLS = {"success": "OK", "confirmation_required": "WAIT"}


def format_evidence(response: AgentResponse) -> str:
    if not response.tool_results:
        return "Evidence: no tools were called"
    lines = [f"Evidence (request {response.request_id}):"]
    for result in response.tool_results:
        symbol = STATUS_SYMBOLS.get(result.status.value, result.status.value.upper())
        lines.append(f"  [{symbol}] {result.tool_name} ({result.duration_ms:.0f} ms)")
    return "\n".join(lines)


class TranscriptWriter:
    def __init__(self, directory: Path, name: str = "conversation") -> None:
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self.path = directory / f"{name}-{timestamp}.md"
        self.path.write_text(f"# Agent {name} ({timestamp} UTC)\n", encoding="utf-8")

    def record(self, speaker: str, text: str, response: AgentResponse | None = None) -> None:
        sections = [f"\n## {speaker}\n\n{text}\n"]
        if response is not None:
            for result in response.tool_results:
                evidence = result.data if result.succeeded else {"error": result.error}
                sections.append(
                    f"\n<details><summary>{result.tool_name}: {result.status.value} "
                    f"({result.duration_ms:.0f} ms)</summary>\n\n```json\n"
                    f"{json.dumps(evidence, indent=2, default=str)[:4000]}\n```\n</details>\n"
                )
        with self.path.open("a", encoding="utf-8") as transcript_file:
            transcript_file.write("".join(sections))


def handle_response(
    agent: Agent, response: AgentResponse, transcript: TranscriptWriter | None
) -> AgentResponse:
    while True:
        print(f"\nAgent: {response.answer}\n\n{format_evidence(response)}\n")
        if transcript:
            transcript.record("Agent", response.answer, response)
        if response.pending_action is None:
            return response
        approval = input("Approve this action? [y/N]: ").strip().lower() == "y"
        if transcript:
            transcript.record("User", "Approved" if approval else "Declined")
        response = agent.resolve_pending_action(approval)


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", help="Ask one question and exit")
    parser.add_argument("--save-transcript", action="store_true", help="Save to docs/conversations")
    parsed_arguments = parser.parse_args(arguments)

    load_dotenv()
    configure_logging(LOG_FILE)
    agent = Agent(
        create_chat_model(),
        ToolExecutor(create_default_registry()),
        on_progress=lambda message: print(f"  ... {message}", flush=True),
    )
    transcript = (
        TranscriptWriter(TRANSCRIPT_DIRECTORY) if parsed_arguments.save_transcript else None
    )

    if parsed_arguments.question:
        if transcript:
            transcript.record("User", parsed_arguments.question)
        handle_response(agent, agent.ask(parsed_arguments.question), transcript)
        return 0

    print("MLOps agent ready. Type a question, 'reset' to clear context, or 'exit' to quit.")
    while True:
        try:
            user_message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user_message:
            continue
        if user_message.lower() in EXIT_COMMANDS:
            return 0
        if user_message.lower() == "reset":
            agent.reset()
            print("Context cleared.")
            continue
        if transcript:
            transcript.record("User", user_message)
        handle_response(agent, agent.ask(user_message), transcript)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
