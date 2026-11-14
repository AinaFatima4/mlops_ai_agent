from pathlib import Path

import pytest

from agent.tools.command_runner import CommandFailedError, CommandResult

V1_MD5 = "910d8ebecaaa49bd45cc3f208dc755bb"
V2_MD5 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def build_pointer_text(md5_hash: str, size_bytes: int) -> str:
    return f"outs:\n- md5: {md5_hash}\n  size: {size_bytes}\n  hash: md5\n  path: adult.csv\n"


class FakeCommandRunner:
    def __init__(self, responses: dict[tuple[str, ...], str | Exception]) -> None:
        self.responses = responses
        self.executed_commands: list[tuple[str, ...]] = []

    def run(self, arguments: list[str]) -> CommandResult:
        command = tuple(arguments)
        self.executed_commands.append(command)
        if command not in self.responses:
            raise CommandFailedError(command, 128, "no fake response configured")
        response = self.responses[command]
        if isinstance(response, Exception):
            raise response
        return CommandResult(command=command, standard_output=response, standard_error="")


@pytest.fixture
def repository_with_dataset(tmp_path: Path) -> Path:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    (data_directory / "adult.csv.dvc").write_text(
        build_pointer_text(V2_MD5, 3500000), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def version_history_responses() -> dict[tuple[str, ...], str]:
    return {
        ("git", "ls-files", "*.dvc"): "data/adult.csv.dvc\n",
        (
            "git",
            "tag",
            "--list",
            "dataset-v*",
            "--sort=creatordate",
        ): "dataset-v1.0\ndataset-v2.0\n",
        ("git", "show", "dataset-v1.0:data/adult.csv.dvc"): build_pointer_text(V1_MD5, 4007022),
        ("git", "show", "dataset-v2.0:data/adult.csv.dvc"): build_pointer_text(V2_MD5, 3500000),
        ("git", "rev-list", "-n", "1", "dataset-v1.0"): "1111111\n",
        ("git", "rev-list", "-n", "1", "dataset-v2.0"): "2222222\n",
        ("git", "log", "-1", "--format=%cI", "dataset-v1.0"): "2026-11-14T16:58:00-05:00\n",
        ("git", "log", "-1", "--format=%cI", "dataset-v2.0"): "2026-11-14T17:04:00-05:00\n",
        ("git", "log", "-1", "--format=%H", "--", "data/adult.csv.dvc"): "2222222\n",
    }
