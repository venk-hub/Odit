from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://odit:odit_local_pass@localhost:5432/odit"
    DATA_DIR: str = "/data"
    PROXY_HOST: str = "proxy"
    PROXY_PORT: int = 8080
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    POSTGRES_DB: str = "odit"
    POSTGRES_USER: str = "odit"
    POSTGRES_PASSWORD: str = "odit_local_pass"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
