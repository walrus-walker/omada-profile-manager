from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Omada Open API
    OMADA_BASE_URL: str = ""
    OMADA_CONTROLLER_ID: str = ""
    OMADA_CLIENT_ID: str = ""
    OMADA_CLIENT_SECRET: str = ""
    OMADA_SITE_ID: str = ""
    OMADA_VERIFY_SSL: bool = False
    OMADA_UI_USERNAME: str = ""
    OMADA_UI_PASSWORD: str = ""

    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8095
    APP_ADMIN_PIN: str = "changeme"
    APP_SECRET_KEY: str = "changeme-please-set-a-real-secret-key"
    DATABASE_PATH: str = "/data/net-profile-manager.db"

    # Optional
    DISCORD_WEBHOOK_URL: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
