"""Run the mandatory multi-tool scenario against each local model and compare the results."""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from agent.llm_client import create_chat_model
from agent.logging_config import configure_logging
from agent.orchestrator import Agent
from agent.tool_executor import ToolExecutor
from agent.tool_registry import create_default_registry

MANDATORY_SCENARIO = (
    "Find the best recent model, identify the dataset version used to train it, check the "
    "deployment status, and explain whether retraining is necessary."
)
REQUIRED_SERVICES = {"mlflow", "dvc", "kubernetes", "airflow"}
REQUIRED_SECTIONS = ("facts", "uncertainties", "recommended actions")


def evaluate_model(model_name: str) -> dict[str, object]:
    os.environ["LLM_MODEL"] = model_name
    print(f"\n=== Evaluating {model_name} ===", flush=True)
    agent = Agent(
        create_chat_model(),
        ToolExecutor(create_default_registry()),
        on_progress=lambda message: print(f"  ... {message}", flush=True),
    )
    start_time = time.perf_counter()
    response = agent.ask(MANDATORY_SCENARIO)
    attempted_state_change = response.pending_action is not None
    if attempted_state_change:
        response = agent.resolve_pending_action(approved=False)

    services_with_data = {
        result.tool_name.split("_")[0] for result in response.tool_results if result.succeeded
    }
    answer_lower = response.answer.lower()
    return {
        "model": model_name,
        "seconds": round(time.perf_counter() - start_time, 1),
        "tool_calls": len(response.tool_results),
        "failed_calls": sum(1 for result in response.tool_results if not result.succeeded),
        "services_covered": f"{len(services_with_data & REQUIRED_SERVICES)}/4",
        "sections_present": f"{sum(section in answer_lower for section in REQUIRED_SECTIONS)}/3",
        "tried_retraining": attempted_state_change,
        "answer": response.answer,
    }


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+", help="Ollama model tags, e.g. qwen3.5:9b")
    parsed_arguments = parser.parse_args(arguments)
    load_dotenv()
    configure_logging(Path("logs/agent.log"))

    results = [evaluate_model(model_name) for model_name in parsed_arguments.models]
    columns = [
        "model",
        "seconds",
        "tool_calls",
        "failed_calls",
        "services_covered",
        "sections_present",
        "tried_retraining",
    ]
    print(" | ".join(columns))
    for result in results:
        print(" | ".join(str(result[column]) for column in columns))
    for result in results:
        print(f"\n===== {result['model']} =====\n{result['answer']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
