"""Error types shared by all agent tools."""


class InvalidToolInputError(ValueError):
    """Raised when a tool receives an input that fails validation."""


class ServiceUnavailableError(Exception):
    """Raised when an external service cannot be reached or rejects a request."""


class ToolPermissionError(PermissionError):
    """Raised when an operation is outside what the agent is authorized to do."""


class ConfirmationRequiredError(Exception):
    """Raised when a state-changing operation needs explicit user confirmation first."""

    def __init__(self, action_description: str) -> None:
        self.action_description = action_description
        super().__init__(f"Confirmation required before: {action_description}")
