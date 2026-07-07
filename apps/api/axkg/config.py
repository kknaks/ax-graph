"""환경 설정 (40-architecture/system README Configuration 표)."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    axkg_database_url: str = "postgresql+psycopg://axkg:axkg@localhost:5432/axkg"
    axkg_markdown_root: str = "data/documents"
    axkg_open_kknaks_base_url: str = "http://localhost:8080"
    axkg_auth_token_ttl_days: int = 30
    axkg_default_provider: str = "claude"
    axkg_redis_url: str = ""
    axkg_slack_signing_secret: str = ""
    axkg_slack_bot_token: str = ""
    # 콤마 구분 허용 origin 목록 (CORS)
    axkg_cors_origins: str = "http://localhost:3000"


settings = Settings()
