"""Run an allowlist of read-only git and dvc commands without a shell."""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 30
BLOCKED_ARGUMENT_PREFIXES = ("--output", "--exec", "--upload-pack")


class CommandNotAllowedError(Exception):
    """Raised when a command is not on the approved list."""


class CommandTimeoutError(Exception):
    """Raised when a command runs longer than its timeout."""


class CommandFailedError(Exception):
    """Raised when a command exits with a non-zero status."""

    def __init__(self, command: tuple[str, ...], return_code: int, error_output: str) -> None:
        self.command = command
        self.return_code = return_code
        self.error_output = error_output
        super().__init__(
            f"Command {' '.join(command)} failed with exit code {return_code}: {error_output}"
        )


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    standard_output: str
    standard_error: str


class CommandRunner:
    def __init__(
        self,
        working_directory: Path,
        allowed_command_prefixes: frozenset[tuple[str, ...]],
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.working_directory = working_directory
        self.allowed_command_prefixes = allowed_command_prefixes
        self.timeout_seconds = timeout_seconds

    def is_allowed(self, arguments: list[str]) -> bool:
        for argument in arguments:
            if argument.startswith(BLOCKED_ARGUMENT_PREFIXES):
                return False
        for prefix in self.allowed_command_prefixes:
            if tuple(arguments[: len(prefix)]) == prefix:
                return True
        return False

    def run(self, arguments: list[str]) -> CommandResult:
        command = tuple(arguments)
        if not self.is_allowed(arguments):
            raise CommandNotAllowedError(f"Command is not approved: {' '.join(command)}")

        executable_arguments = self._resolve_executable(arguments)
        try:
            completed_process = subprocess.run(
                executable_arguments,
                cwd=self.working_directory,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise CommandTimeoutError(
                f"Command {' '.join(command)} timed out after {self.timeout_seconds} seconds"
            ) from error
        except FileNotFoundError as error:
            raise CommandFailedError(
                command, -1, f"Executable not found: {arguments[0]}"
            ) from error

        if completed_process.returncode != 0:
            raise CommandFailedError(
                command, completed_process.returncode, completed_process.stderr.strip()
            )
        return CommandResult(
            command=command,
            standard_output=completed_process.stdout,
            standard_error=completed_process.stderr,
        )

    @staticmethod
    def _resolve_executable(arguments: list[str]) -> list[str]:
        # Run dvc through the current interpreter so it always uses the project's .venv
        if arguments[0] == "dvc":
            return [sys.executable, "-m", "dvc", *arguments[1:]]
        return arguments
