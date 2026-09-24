from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    ENVIRONMENT: Literal["development", "production", "test"] = "development"
    DATABASE_URL: str = "postgresql://coastworks:local-only@127.0.0.1:55432/coastworks"
    APP_ORIGIN: str = "http://localhost:8000"
    PUBLIC_API_ORIGIN: str = ""
    EMBEDDED_WORKER: bool = False
    SECRET_KEY: str = "development-only-change-before-deploy-0123456789"
    LLM_PROVIDER: Literal["gemini", "openai"] = "gemini"
    LLM_MODEL: str = "gemini-2.5-flash"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 900
    RAG_MAX_TOKENS: int = 2400
    RAG_THINKING_BUDGET: int | None = 256
    EMBEDDINGS_PROVIDER: Literal["gemini", "openai"] = "gemini"
    EMBEDDINGS_MODEL: str = "gemini-embedding-001"
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GEMINI_USE_VERTEX_AI: bool = False
    GOOGLE_CLOUD_PROJECT: str = ""
    GOOGLE_CLOUD_LOCATION: str = "europe-west1"
    CLOUDFLARE_ACCOUNT_ID: str = ""
    CLOUDFLARE_API_TOKEN: str = ""
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_STARTTLS: bool = False
    EMAIL_FROM: str = "Coastworks <hello@localhost>"
    CRAWL_PAGES: int = 8
    CRAWL_SECONDS: int = 110
    KNOWLEDGE_PAGES: int = 500
    KNOWLEDGE_SECONDS: int = 1200
    KNOWLEDGE_CHUNKS: int = 12000
    PREVIEW_CHUNKS: int = 300
    EMBEDDING_BATCH_SIZE: int = 64
    RETRIEVAL_CANDIDATES: int = 32
    RERANK_CANDIDATES: int = 24
    ANSWER_CHUNKS: int = 8
    PREVIEW_HOURS: int = 24
    GLOBAL_CRAWLS_PER_DAY: int = 100
    GLOBAL_MESSAGES_PER_DAY: int = 2000
    MIN_RELEVANCE: float = 0.45

    @model_validator(mode="after")
    def production_contract(self):
        if not 1 <= self.CRAWL_PAGES <= 100 or not 10 <= self.CRAWL_SECONDS <= 180:
            raise ValueError("Crawl budget outside supported bounds")
        if not (1 <= self.KNOWLEDGE_PAGES <= 10000 and 60 <= self.KNOWLEDGE_SECONDS <= 7200):
            raise ValueError("Knowledge crawl budget outside supported bounds")
        if not (1 <= self.PREVIEW_CHUNKS <= self.KNOWLEDGE_CHUNKS <= 100000):
            raise ValueError("Invalid index budgets")
        if not (
            1 <= self.ANSWER_CHUNKS <= 12
            and self.ANSWER_CHUNKS <= self.RERANK_CANDIDATES <= self.RETRIEVAL_CANDIDATES <= 100
        ):
            raise ValueError("Invalid retrieval budgets")
        if not 512 <= self.RAG_MAX_TOKENS <= 8192:
            raise ValueError("Invalid structured answer token budget")
        if self.RAG_THINKING_BUDGET is not None and not -1 <= self.RAG_THINKING_BUDGET <= 32768:
            raise ValueError("Invalid thinking budget")
        if not 1 <= self.EMBEDDING_BATCH_SIZE <= 128:
            raise ValueError("Invalid embedding batch size")
        if self.ENVIRONMENT == "production":
            if not self.APP_ORIGIN.startswith("https://") or len(self.SECRET_KEY) < 40:
                raise ValueError("Production requires HTTPS and a long random SECRET_KEY")
            if self.PUBLIC_API_ORIGIN and not self.PUBLIC_API_ORIGIN.startswith("https://"):
                raise ValueError("Production PUBLIC_API_ORIGIN must use HTTPS")
            if "development" in self.SECRET_KEY or "localhost" in self.EMAIL_FROM:
                raise ValueError("Development credentials are forbidden in production")
            if not self.SMTP_HOST or not self.SMTP_STARTTLS:
                raise ValueError("Production requires authenticated TLS email delivery")
            if not self.SMTP_USERNAME or not self.SMTP_PASSWORD:
                raise ValueError("Production requires SMTP credentials")
        return self


@lru_cache
def get_settings():
    return Settings()


settings = get_settings()
