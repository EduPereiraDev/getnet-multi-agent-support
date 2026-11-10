import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_mode: Literal["auto", "llm", "offline"] = "auto"
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5-5"
    router_model: str = "claude-haiku-5-5"
    llm_timeout_s: float = 30.0
    llm_max_tool_iterations: int = 5

    rag_top_k: int = 4
    rag_min_score: float = 0.08
    index_dir: Path = DATA_DIR / "index"
    ingest_online: bool = False

    escalation_confidence: float = 0.45
    rate_limit_per_minute: int = 30
    expose_docs: bool = True
    log_level: str = "INFO"

    @property
    def resolved_mode(self) -> Literal["llm", "offline"]:
        if self.llm_mode != "auto":
            return self.llm_mode
        has_credential = bool(self.anthropic_api_key or os.getenv("ANTHROPIC_AUTH_TOKEN"))
        return "llm" if has_credential else "offline"


@lru_cache
def get_settings() -> Settings:
    return Settings()
