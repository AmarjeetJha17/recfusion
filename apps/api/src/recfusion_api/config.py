from typing import Literal, Self

from pydantic import model_validator
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

    @model_validator(mode="after")
    def reject_production_debug(self) -> Self:
        if self.environment == "production" and self.debug:
            raise ValueError("Debug mode cannot be enabled in production.")
        return self
