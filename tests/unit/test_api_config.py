from pathlib import Path

import pytest
from pydantic import ValidationError

from recfusion_api.config import Settings


def test_settings_read_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECFUSION_ENVIRONMENT", "test")
    monkeypatch.setenv("RECFUSION_APP_NAME", "RecFusion Test")
    monkeypatch.setenv("RECFUSION_DEBUG", "true")
    monkeypatch.setenv("RECFUSION_LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.environment == "test"
    assert settings.app_name == "RecFusion Test"
    assert settings.debug is True
    assert settings.log_level == "DEBUG"


def test_example_environment_file_uses_non_secret_defaults() -> None:
    example_path = Path(__file__).parents[2] / ".env.example"

    settings = Settings(_env_file=example_path)

    assert settings.environment == "development"
    assert settings.app_name == "RecFusion API"
    assert settings.debug is False
    assert settings.log_level == "INFO"


def test_production_debug_mode_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Debug mode cannot be enabled"):
        Settings(environment="production", debug=True)
