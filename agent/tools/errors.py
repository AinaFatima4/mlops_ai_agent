"""Error types shared by all agent tools."""


class InvalidToolInputError(ValueError):
    """Raised when a tool receives an input that fails validation."""


class ServiceUnavailableError(Exception):
    """Raised when an external service cannot be reached or rejects a request."""
