import hashlib
from pathlib import Path

import pytest

from agent.tools.command_runner import CommandTimeoutError
from agent.tools.dvc_tools import DvcTools, InvalidToolInputError
from tests.conftest import V1_MD5, V2_MD5, FakeCommandRunner


def build_dvc_tools(repository_path: Path, responses: dict) -> DvcTools:
    return DvcTools(repository_path, FakeCommandRunner(responses))


def test_list_tracked_datasets_reads_pointer_files(
    repository_with_dataset: Path, version_history_responses: dict
) -> None:
    dvc_tools = build_dvc_tools(repository_with_dataset, version_history_responses)
    result = dvc_tools.list_tracked_datasets()
    assert result["datasets"] == [
        {
            "dataset_path": "data/adult.csv",
            "pointer_file": "data/adult.csv.dvc",
            "md5": V2_MD5,
            "size_bytes": 3500000,
        }
    ]


def test_list_dataset_versions_returns_versions_in_order(
    repository_with_dataset: Path, version_history_responses: dict
) -> None:
    dvc_tools = build_dvc_tools(repository_with_dataset, version_history_responses)
    versions = dvc_tools.list_dataset_versions("data/adult.csv")["versions"]
    assert [version["version"] for version in versions] == ["dataset-v1.0", "dataset-v2.0"]
    assert versions[0]["md5"] == V1_MD5
    assert versions[0]["git_commit"] == "1111111"


def test_current_version_matches_tag_by_hash(
    repository_with_dataset: Path, version_history_responses: dict
) -> None:
    dvc_tools = build_dvc_tools(repository_with_dataset, version_history_responses)
    result = dvc_tools.get_current_dataset_version("data/adult.csv")
    assert result["committed_version"] == "dataset-v2.0"
    assert result["is_tagged_version"] is True
    assert result["last_pointer_commit"] == "2222222"


def test_current_version_is_none_when_workspace_hash_is_untagged(
    repository_with_dataset: Path, version_history_responses: dict
) -> None:
    pointer_path = repository_with_dataset / "data" / "adult.csv.dvc"
    pointer_path.write_text(pointer_path.read_text().replace(V2_MD5, "b" * 32))
    dvc_tools = build_dvc_tools(repository_with_dataset, version_history_responses)
    result = dvc_tools.get_current_dataset_version("data/adult.csv")
    assert result["committed_version"] is None
    assert result["is_tagged_version"] is False


def test_find_version_by_hash_returns_matching_tag(
    repository_with_dataset: Path, version_history_responses: dict
) -> None:
    dvc_tools = build_dvc_tools(repository_with_dataset, version_history_responses)
    result = dvc_tools.find_version_by_hash("data/adult.csv", V1_MD5)
    assert result["found"] is True
    assert result["version"]["version"] == "dataset-v1.0"


def test_compare_versions_reports_content_and_size_change(
    repository_with_dataset: Path, version_history_responses: dict
) -> None:
    diff_command = (
        "dvc",
        "diff",
        "--json",
        "dataset-v1.0",
        "dataset-v2.0",
        "--targets",
        "data/adult.csv",
    )
    responses = {
        **version_history_responses,
        diff_command: '{"modified": [{"path": "data/adult.csv"}]}',
    }
    dvc_tools = build_dvc_tools(repository_with_dataset, responses)
    result = dvc_tools.compare_dataset_versions("data/adult.csv", "dataset-v1.0", "dataset-v2.0")
    assert result["content_changed"] is True
    assert result["size_difference_bytes"] == 3500000 - 4007022
    assert result["dvc_diff"]["modified"][0]["path"] == "data/adult.csv"


def test_compare_with_unknown_version_raises(
    repository_with_dataset: Path, version_history_responses: dict
) -> None:
    dvc_tools = build_dvc_tools(repository_with_dataset, version_history_responses)
    with pytest.raises(InvalidToolInputError):
        dvc_tools.compare_dataset_versions("data/adult.csv", "dataset-v1.0", "dataset-v9.0")


def test_check_data_changed_detects_modified_file(repository_with_dataset: Path) -> None:
    responses = {
        ("dvc", "status", "--json"): (
            '{"data/adult.csv.dvc": [{"changed outs": {"data/adult.csv": "modified"}}]}'
        )
    }
    dvc_tools = build_dvc_tools(repository_with_dataset, responses)
    result = dvc_tools.check_data_changed()
    assert result == {
        "has_changes": True,
        "changed_files": [{"path": "data/adult.csv", "change": "modified"}],
    }


def test_check_data_changed_reports_clean_workspace(repository_with_dataset: Path) -> None:
    dvc_tools = build_dvc_tools(repository_with_dataset, {("dvc", "status", "--json"): "{}"})
    assert dvc_tools.check_data_changed() == {"has_changes": False, "changed_files": []}


def test_reproduction_steps_reference_the_version_tag(
    repository_with_dataset: Path, version_history_responses: dict
) -> None:
    dvc_tools = build_dvc_tools(repository_with_dataset, version_history_responses)
    result = dvc_tools.get_reproduction_steps("data/adult.csv", "dataset-v1.0")
    assert result["steps"] == [
        "git checkout dataset-v1.0 -- data/adult.csv.dvc",
        "dvc pull data/adult.csv.dvc",
    ]


@pytest.mark.parametrize("dataset_path", ["../etc/passwd", "/etc/passwd", "-rf", ""])
def test_unsafe_dataset_paths_are_rejected(
    repository_with_dataset: Path, dataset_path: str
) -> None:
    dvc_tools = build_dvc_tools(repository_with_dataset, {})
    with pytest.raises(InvalidToolInputError):
        dvc_tools.list_dataset_versions(dataset_path)


@pytest.mark.parametrize("version_name", ["v1", "dataset-v1.0; rm -rf /", "--all"])
def test_malformed_version_names_are_rejected(
    repository_with_dataset: Path, version_name: str
) -> None:
    dvc_tools = build_dvc_tools(repository_with_dataset, {})
    with pytest.raises(InvalidToolInputError):
        dvc_tools.get_reproduction_steps("data/adult.csv", version_name)


def test_timeout_from_runner_propagates(repository_with_dataset: Path) -> None:
    responses = {("dvc", "status", "--json"): CommandTimeoutError("timed out")}
    dvc_tools = build_dvc_tools(repository_with_dataset, responses)
    with pytest.raises(CommandTimeoutError):
        dvc_tools.check_data_changed()


def test_modified_workspace_file_is_reported_even_when_pointer_is_tagged(
    repository_with_dataset: Path, version_history_responses: dict
) -> None:
    (repository_with_dataset / "data" / "adult.csv").write_text("header\nrow\n", encoding="utf-8")
    dvc_tools = build_dvc_tools(repository_with_dataset, version_history_responses)
    result = dvc_tools.get_current_dataset_version("data/adult.csv")
    assert result["committed_version"] == "dataset-v2.0"
    assert result["workspace_matches_committed_version"] is False
    assert result["workspace_file"]["line_count"] == 2
    assert "does not match the committed version" in result["warning"]


def test_unmodified_workspace_file_matches_committed_version(
    repository_with_dataset: Path, version_history_responses: dict
) -> None:
    data_file = repository_with_dataset / "data" / "adult.csv"
    data_file.write_text("header\nrow\n", encoding="utf-8")
    pointer_file = repository_with_dataset / "data" / "adult.csv.dvc"
    actual_md5 = hashlib.md5(data_file.read_bytes()).hexdigest()
    pointer_file.write_text(pointer_file.read_text().replace(V2_MD5, actual_md5))
    responses = {
        **version_history_responses,
        ("git", "show", "dataset-v2.0:data/adult.csv.dvc"): pointer_file.read_text(),
    }
    dvc_tools = build_dvc_tools(repository_with_dataset, responses)
    result = dvc_tools.get_current_dataset_version("data/adult.csv")
    assert result["committed_version"] == "dataset-v2.0"
    assert result["workspace_matches_committed_version"] is True
    assert "warning" not in result
