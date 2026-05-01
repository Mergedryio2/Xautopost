from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="XAUTOPOST_", env_file=None)

    port: int = 8765
    token: str = ""
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".xautopost")


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
