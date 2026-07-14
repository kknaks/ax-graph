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
    # qmd 사이드카 (Graph RAG 2단 retriever 1단 후보 발굴, AXKG-WORK-008).
    # 비우면 NullQmdClient → keyword+edge 폴백만 동작(로컬/테스트 기본).
    # 배포: "http://qmd:8181/mcp" (qmd mcp --http). ::1 바인딩 우회는 사이드카 proxy 소관.
    axkg_qmd_mcp_url: str = ""
    # 리랭크 기본 off — CPU-only에서 LLM 리랭크는 60s+ (PLAN-013-T-006 C-1 실측). GPU 배포 시 on.
    axkg_qmd_rerank_default: bool = False
    # 1단 하이브리드 후보(시드) 개수(top_k). 2단 그래프 확장의 시드 집합.
    axkg_qmd_top_k: int = 12


settings = Settings()
