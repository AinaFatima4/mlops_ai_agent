"""Structured JSON logging with secret redaction."""

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

SECRET_NAME_MARKERS = ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "ACCESS_KEY")
MINIMUM_SECRET_LENGTH = 6
REDACTED = "***REDACTED***"


def collect_secret_values() -> set[str]:
    return {
        value
        for name, value in os.environ.items()
        if any(marker in name.upper() for marker in SECRET_NAME_MARKERS)
        and len(value) >= MINIMUM_SECRET_LENGTH
    }


def redact(text: str, secret_values: set[str]) -> str:
    for secret_value in secret_values:
        text = text.replace(secret_value, REDACTED)
    return text


class JsonFormatter(logging.Formatter):
    def __init__(self, secret_values: set[str]) -> None:
        super().__init__()
        self.secret_values = secret_values

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        log_entry.update(getattr(record, "structured_fields", {}))
        return redact(json.dumps(log_entry, default=str), self.secret_values)


def configure_logging(log_file: Path, level: str = "INFO") -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter(collect_secret_values()))
    root_logger = logging.getLogger()
    root_logger.handlers = [file_handler]
    root_logger.setLevel(level)
    # HTTP client libraries log every request at INFO; keep the agent log focused on tool calls
    for noisy_logger_name in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy_logger_name).setLevel(logging.WARNING)
