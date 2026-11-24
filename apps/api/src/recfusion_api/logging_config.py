import json
import logging
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for field in (
            "request_id",
            "http_method",
            "route",
            "status_code",
            "error_code",
            "error_type",
        ):
            value = getattr(record, field, None)
            if value is not None:
                entry[field] = value
        return json.dumps(entry, separators=(",", ":"))


def get_api_logger() -> logging.Logger:
    return logging.getLogger("recfusion.api")


def configure_logging(level: str) -> None:
    logger = get_api_logger()
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
