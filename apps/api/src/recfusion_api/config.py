import ipaddress
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RECFUSION_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = "development"
    app_name: str = "RecFusion API"
    debug: bool = False
    log_level: LogLevel = "INFO"
    synthetic_demo_enabled: bool = False
    synthetic_demo_max_concurrency: int = Field(default=2, ge=1, le=4)
    synthetic_demo_allowed_origin: str | None = None

    @model_validator(mode="after")
    def reject_production_debug(self) -> Self:
        if self.environment == "production" and self.debug:
            raise ValueError("Debug mode cannot be enabled in production.")
        if self.environment == "production" and self.synthetic_demo_enabled:
            raise ValueError(
                "The synthetic recommendation demo is unavailable in production."
            )
        if self.synthetic_demo_enabled and not _is_exact_loopback_http_origin(
            self.synthetic_demo_allowed_origin
        ):
            raise ValueError(
                "An exact loopback HTTP origin is required when the synthetic "
                "demo is enabled."
            )
        return self


def _is_exact_loopback_http_origin(origin: str | None) -> bool:
    if not origin or origin == "*" or any(character.isspace() for character in origin):
        return False
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1 <= port <= 65_535
        or parsed.hostname is None
    ):
        return False
    hostname = parsed.hostname.casefold()
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False
