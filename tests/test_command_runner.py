import subprocess
from pathlib import Path

import pytest

from agent.tools.command_runner import (
    CommandFailedError,
    CommandNotAllowedError,
    CommandRunner,
    CommandTimeoutError,
)
from agent.tools.dvc_tools import DVC_ALLOWED_COMMAND_PREFIXES


@pytest.fixture
def command_runner(tmp_path: Path) -> CommandRunner:
    return CommandRunner(tmp_path, DVC_ALLOWED_COMMAND_PREFIXES, timeout_seconds=1)


@pytest.mark.parametrize(
    "arguments",
    [
        ["dvc", "push"],
        ["dvc", "gc", "--workspace"],
        ["git", "checkout", "dataset-v1.0"],
        ["git", "tag", "-a", "fake-tag"],
        ["git", "log", "--output=stolen.txt"],
        ["rm", "-rf", "/"],
        [],
    ],
)
def test_unapproved_commands_are_rejected(
    command_runner: CommandRunner, arguments: list[str]
) -> None:
    with pytest.raises(CommandNotAllowedError):
        command_runner.run(arguments)


def test_command_timeout_raises_timeout_error(
    command_runner: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_timeout(*arguments, **keyword_arguments):
        raise subprocess.TimeoutExpired(cmd="git log", timeout=1)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    with pytest.raises(CommandTimeoutError):
        command_runner.run(["git", "log", "-1"])


def test_non_zero_exit_raises_command_failed_error(command_runner: CommandRunner) -> None:
    # tmp_path is not a git repository, so git log fails
    with pytest.raises(CommandFailedError) as error_information:
        command_runner.run(["git", "log", "-1"])
    assert error_information.value.return_code != 0
