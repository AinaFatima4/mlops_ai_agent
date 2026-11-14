"""Run the Airflow tools against the live Airflow deployment and assert the real results."""

import sys

from agent.tools.airflow_tools import create_airflow_tools
from agent.tools.errors import ConfirmationRequiredError, ToolPermissionError

DAG_ID = "adult_income_training"
EXPECTED_SUCCESS_TASK_COUNT = 11


def main() -> int:
    airflow_tools = create_airflow_tools()

    dag_listing = airflow_tools.list_dags()
    dag_ids = [dag["dag_id"] for dag in dag_listing["dags"]]
    assert DAG_ID in dag_ids, f"{DAG_ID} not found; import errors: {dag_listing['import_errors']}"
    assert not dag_listing["import_errors"], f"Import errors: {dag_listing['import_errors']}"

    for blocked_call in (
        lambda: airflow_tools.trigger_dag("some_other_dag", confirmed=True),
        lambda: airflow_tools.trigger_dag(DAG_ID, confirmed=False),
    ):
        try:
            blocked_call()
        except (ToolPermissionError, ConfirmationRequiredError):
            pass
        else:
            raise AssertionError("A trigger that should have been blocked went through")

    triggered_run = airflow_tools.trigger_dag(DAG_ID, confirmed=True)
    print(f"Triggered {triggered_run['dag_run_id']}, waiting for it to finish...")
    final_status = airflow_tools.wait_for_dag_run(
        DAG_ID, triggered_run["dag_run_id"], timeout_seconds=900, poll_interval_seconds=10
    )
    assert final_status["finished"], (
        f"Run did not finish in time: {final_status['task_state_counts']}"
    )
    if final_status["state"] != "success":
        failed = airflow_tools.get_failed_tasks(DAG_ID, triggered_run["dag_run_id"])
        raise AssertionError(f"Run failed: {failed}")
    assert final_status["task_state_counts"] == {"success": EXPECTED_SUCCESS_TASK_COUNT}

    gate_logs = airflow_tools.get_task_logs(DAG_ID, triggered_run["dag_run_id"], "quality_gate")
    assert any("Quality gate passed" in line for line in gate_logs["last_lines"]), (
        "Gate log missing"
    )

    print(
        f"Run {triggered_run['dag_run_id']} succeeded in {final_status['duration_seconds']:.0f}s "
        f"with {EXPECTED_SUCCESS_TASK_COUNT} successful tasks"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
