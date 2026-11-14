"""DVC data management tools: dataset discovery, versions, comparison and change detection."""

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from agent.tools.command_runner import CommandFailedError, CommandRunner
from agent.tools.errors import InvalidToolInputError

DATASET_TAG_PATTERN = "dataset-v*"
VERSION_NAME_REGEX = re.compile(r"^dataset-v\d+\.\d+$")
MD5_HASH_REGEX = re.compile(r"^[0-9a-f]{32}$")
DVC_ALLOWED_COMMAND_PREFIXES = frozenset(
    {
        ("git", "ls-files"),
        ("git", "tag", "--list"),
        ("git", "rev-list"),
        ("git", "show"),
        ("git", "log"),
        ("dvc", "status"),
        ("dvc", "diff"),
    }
)


def validate_dataset_path(dataset_path: str) -> str:
    pure_path = PurePosixPath(dataset_path)
    if (
        not dataset_path
        or pure_path.is_absolute()
        or ".." in pure_path.parts
        or dataset_path.startswith("-")
    ):
        raise InvalidToolInputError(f"Invalid dataset path: {dataset_path!r}")
    return str(pure_path)


def validate_version_name(version_name: str) -> str:
    if not VERSION_NAME_REGEX.match(version_name):
        raise InvalidToolInputError(
            f"Invalid version name: {version_name!r}. Expected format like 'dataset-v1.0'"
        )
    return version_name


def parse_pointer_file(pointer_text: str) -> dict[str, Any]:
    pointer_content = yaml.safe_load(pointer_text)
    first_output = pointer_content["outs"][0]
    return {"md5": first_output["md5"], "size_bytes": first_output.get("size")}


class DvcTools:
    def __init__(self, repository_path: Path, command_runner: CommandRunner) -> None:
        self.repository_path = repository_path
        self.command_runner = command_runner

    def list_tracked_datasets(self) -> dict[str, Any]:
        listing = self.command_runner.run(["git", "ls-files", "*.dvc"]).standard_output
        datasets = []
        for pointer_file in listing.splitlines():
            pointer_path = self.repository_path / pointer_file
            pointer_info = parse_pointer_file(pointer_path.read_text(encoding="utf-8"))
            datasets.append(
                {
                    "dataset_path": pointer_file.removesuffix(".dvc"),
                    "pointer_file": pointer_file,
                    **pointer_info,
                }
            )
        return {"datasets": datasets}

    def list_dataset_versions(self, dataset_path: str) -> dict[str, Any]:
        dataset_path = validate_dataset_path(dataset_path)
        pointer_file = f"{dataset_path}.dvc"
        tag_listing = self.command_runner.run(
            ["git", "tag", "--list", DATASET_TAG_PATTERN, "--sort=creatordate"]
        ).standard_output

        versions = []
        for version_name in tag_listing.splitlines():
            try:
                pointer_text = self.command_runner.run(
                    ["git", "show", f"{version_name}:{pointer_file}"]
                ).standard_output
            except CommandFailedError:
                # This tag does not contain this dataset
                continue
            git_commit = self.command_runner.run(
                ["git", "rev-list", "-n", "1", version_name]
            ).standard_output.strip()
            created_at = self.command_runner.run(
                ["git", "log", "-1", "--format=%cI", version_name]
            ).standard_output.strip()
            versions.append(
                {
                    "version": version_name,
                    "git_commit": git_commit,
                    "created_at": created_at,
                    **parse_pointer_file(pointer_text),
                }
            )
        return {"dataset_path": dataset_path, "versions": versions}

    def get_current_dataset_version(self, dataset_path: str) -> dict[str, Any]:
        dataset_path = validate_dataset_path(dataset_path)
        pointer_file = f"{dataset_path}.dvc"
        pointer_path = self.repository_path / pointer_file
        if not pointer_path.exists():
            raise InvalidToolInputError(f"Dataset is not tracked by DVC: {dataset_path}")

        current_pointer = parse_pointer_file(pointer_path.read_text(encoding="utf-8"))
        last_commit = self.command_runner.run(
            ["git", "log", "-1", "--format=%H", "--", pointer_file]
        ).standard_output.strip()
        matching_version = self._find_version_by_md5(dataset_path, current_pointer["md5"])
        return {
            "dataset_path": dataset_path,
            "version": matching_version["version"] if matching_version else None,
            "md5": current_pointer["md5"],
            "size_bytes": current_pointer["size_bytes"],
            "last_pointer_commit": last_commit,
            "is_tagged_version": matching_version is not None,
        }

    def find_version_by_hash(self, dataset_path: str, md5_hash: str) -> dict[str, Any]:
        dataset_path = validate_dataset_path(dataset_path)
        if not MD5_HASH_REGEX.match(md5_hash):
            raise InvalidToolInputError(f"Invalid MD5 hash: {md5_hash!r}")
        matching_version = self._find_version_by_md5(dataset_path, md5_hash)
        return {
            "dataset_path": dataset_path,
            "md5": md5_hash,
            "found": matching_version is not None,
            "version": matching_version,
        }

    def compare_dataset_versions(
        self, dataset_path: str, version_a: str, version_b: str
    ) -> dict[str, Any]:
        dataset_path = validate_dataset_path(dataset_path)
        validate_version_name(version_a)
        validate_version_name(version_b)
        versions_by_name = {
            version["version"]: version
            for version in self.list_dataset_versions(dataset_path)["versions"]
        }
        for version_name in (version_a, version_b):
            if version_name not in versions_by_name:
                raise InvalidToolInputError(f"Unknown dataset version: {version_name}")

        diff_output = self.command_runner.run(
            ["dvc", "diff", "--json", version_a, version_b, "--targets", dataset_path]
        ).standard_output
        diff_result = json.loads(diff_output) if diff_output.strip() else {}

        first_version = versions_by_name[version_a]
        second_version = versions_by_name[version_b]
        size_difference = None
        if first_version["size_bytes"] is not None and second_version["size_bytes"] is not None:
            size_difference = second_version["size_bytes"] - first_version["size_bytes"]
        return {
            "dataset_path": dataset_path,
            "version_a": first_version,
            "version_b": second_version,
            "content_changed": first_version["md5"] != second_version["md5"],
            "size_difference_bytes": size_difference,
            "dvc_diff": diff_result,
        }

    def check_data_changed(self) -> dict[str, Any]:
        status_output = self.command_runner.run(["dvc", "status", "--json"]).standard_output
        status_result = json.loads(status_output) if status_output.strip() else {}

        changed_files = []
        for stage_name, stage_entries in status_result.items():
            for entry in stage_entries:
                if isinstance(entry, str):
                    changed_files.append({"path": stage_name, "change": entry})
                    continue
                for changed_paths in entry.values():
                    for changed_path, change_type in changed_paths.items():
                        changed_files.append({"path": changed_path, "change": change_type})
        return {"has_changes": bool(changed_files), "changed_files": changed_files}

    def get_reproduction_steps(self, dataset_path: str, version: str) -> dict[str, Any]:
        dataset_path = validate_dataset_path(dataset_path)
        validate_version_name(version)
        known_versions = {
            listed_version["version"]
            for listed_version in self.list_dataset_versions(dataset_path)["versions"]
        }
        if version not in known_versions:
            raise InvalidToolInputError(f"Unknown dataset version: {version}")

        pointer_file = f"{dataset_path}.dvc"
        return {
            "dataset_path": dataset_path,
            "version": version,
            "steps": [
                f"git checkout {version} -- {pointer_file}",
                f"dvc pull {pointer_file}",
            ],
            "restore_latest_steps": [
                f"git checkout main -- {pointer_file}",
                f"dvc checkout {pointer_file}",
            ],
            "explanation": (
                "The first command restores the DVC pointer file recorded at the version tag. "
                "dvc pull then downloads the matching data from the remote if it is not "
                "already cached, and places it in the workspace."
            ),
        }

    def _find_version_by_md5(self, dataset_path: str, md5_hash: str) -> dict[str, Any] | None:
        for version in self.list_dataset_versions(dataset_path)["versions"]:
            if version["md5"] == md5_hash:
                return version
        return None


def create_dvc_tools(repository_path: Path) -> DvcTools:
    command_runner = CommandRunner(repository_path, DVC_ALLOWED_COMMAND_PREFIXES)
    return DvcTools(repository_path, command_runner)
