"""Run the DVC tools against this repository and assert the expected real results."""

import sys
from pathlib import Path

from agent.tools.command_runner import CommandNotAllowedError
from agent.tools.dvc_tools import create_dvc_tools

DATASET_PATH = "data/adult.csv"
EXPECTED_VERSIONS = ["dataset-v1.0", "dataset-v2.0"]


def main() -> int:
    dvc_tools = create_dvc_tools(Path.cwd())

    tracked_paths = [
        dataset["dataset_path"] for dataset in dvc_tools.list_tracked_datasets()["datasets"]
    ]
    assert DATASET_PATH in tracked_paths, f"{DATASET_PATH} not tracked: {tracked_paths}"

    version_names = [
        version["version"] for version in dvc_tools.list_dataset_versions(DATASET_PATH)["versions"]
    ]
    assert version_names == EXPECTED_VERSIONS, f"Unexpected versions: {version_names}"

    current_version = dvc_tools.get_current_dataset_version(DATASET_PATH)
    assert current_version["version"] == "dataset-v2.0", f"Current version: {current_version}"

    change_status = dvc_tools.check_data_changed()
    assert change_status["has_changes"] is False, f"Workspace has changes: {change_status}"

    comparison = dvc_tools.compare_dataset_versions(DATASET_PATH, *EXPECTED_VERSIONS)
    assert comparison["content_changed"] is True, "v1 and v2 should differ"

    try:
        dvc_tools.command_runner.run(["dvc", "push"])
    except CommandNotAllowedError:
        pass
    else:
        raise AssertionError("dvc push was not blocked")

    print(f"Versions: {version_names}, current: {current_version['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
