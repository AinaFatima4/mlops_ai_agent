"""Validate, run and time tool calls, turning every outcome into a structured ToolResult."""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from pydantic import ValidationError

from agent.schemas import ToolResult, ToolStatus
from agent.tool_registry import ToolRegistry
from agent.tools.command_runner import (
    CommandFailedError,
    CommandNotAllowedError,
    CommandTimeoutError,
)
from agent.tools.errors import (
    ConfirmationRequiredError,
    InvalidToolInputError,
    ServiceUnavailableError,
    ToolPermissionError,
)

logger = logging.getLogger("agent.tools")

DEFAULT_TOOL_TIMEOUT_SECONDS = 120
WAITING_TOOL_TIMEOUT_SECONDS = 960
WAITING_TOOLS = {"airflow_wait_for_dag_run"}


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
    ) -> None:
        self.registry = registry
        self.timeout_seconds = timeout_seconds
        self.thread_pool = ThreadPoolExecutor(max_workers=4)

    def execute(
        self, tool_name: str, arguments_json: str, request_id: str, confirmed: bool = False
    ) -> ToolResult:
        start_time = time.perf_counter()
        status, data, error = self._run(tool_name, arguments_json, confirmed)
        result = ToolResult(
            tool_name=tool_name,
            status=status,
            request_id=request_id,
            duration_ms=round((time.perf_counter() - start_time) * 1000, 1),
            data=data,
            error=error,
        )
        logger.info(
            "tool_call",
            extra={
                "structured_fields": {
                    "event": "tool_call",
                    "request_id": request_id,
                    "tool": tool_name,
                    "status": result.status.value,
                    "duration_ms": result.duration_ms,
                    "confirmed": confirmed,
                    "error": error,
                }
            },
        )
        return result

    def _run(
        self, tool_name: str, arguments_json: str, confirmed: bool
    ) -> tuple[ToolStatus, dict | None, str | None]:
        definition = self.registry.get_definition(tool_name)
        if definition is None:
            return ToolStatus.INVALID_INPUT, None, f"Unknown tool: {tool_name}"
        try:
            raw_arguments = json.loads(arguments_json or "{}")
            validated_input = definition.input_model.model_validate(raw_arguments)
        except (json.JSONDecodeError, ValidationError) as error:
            return ToolStatus.INVALID_INPUT, None, f"Invalid arguments: {error}"

        timeout = (
            WAITING_TOOL_TIMEOUT_SECONDS if tool_name in WAITING_TOOLS else self.timeout_seconds
        )
        future = self.thread_pool.submit(self.registry.call, definition, validated_input, confirmed)
        try:
            return ToolStatus.SUCCESS, future.result(timeout=timeout), None
        except FutureTimeoutError:
            return ToolStatus.UNAVAILABLE, None, f"Tool timed out after {timeout} seconds"
        except ConfirmationRequiredError as error:
            return ToolStatus.CONFIRMATION_REQUIRED, None, error.action_description
        except (ToolPermissionError, CommandNotAllowedError) as error:
            return ToolStatus.PERMISSION_DENIED, None, str(error)
        except InvalidToolInputError as error:
            return ToolStatus.INVALID_INPUT, None, str(error)
        except (ServiceUnavailableError, CommandTimeoutError, CommandFailedError) as error:
            return ToolStatus.UNAVAILABLE, None, str(error)
        except Exception as error:
            logger.exception("Unexpected tool failure in %s", tool_name)
            return ToolStatus.ERROR, None, f"{type(error).__name__}: {error}"
