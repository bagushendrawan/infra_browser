from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BrowserSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BROWSER_", env_file=".env", extra="ignore"
    )
    max_tabs: int = Field(default=5, ge=1)
    timeout_seconds: float = Field(default=30, gt=0)
    viewport_width: int = Field(default=1280, ge=1)
    viewport_height: int = Field(default=720, ge=1)
