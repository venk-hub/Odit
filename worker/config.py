from pydantic_settings import BaseSettings
from functools import lru_cache


class WorkerSettings(BaseSettings):
    DATABASE_URL: str = "postgresql://odit:odit_local_pass@localhost:5432/odit"
    DATA_DIR: str = "/data"
    PROXY_HOST: str = "proxy"
    PROXY_PORT: int = 8080
    LOG_LEVEL: str = "INFO"
    WORKER_POLL_INTERVAL: int = 5  # seconds
    USE_PROXY: bool = True
    ANTHROPIC_API_KEY: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> WorkerSettings:
    return WorkerSettings()
