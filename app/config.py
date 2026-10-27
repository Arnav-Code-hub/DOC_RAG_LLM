from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    groq_api_key: SecretStr | None = None
    groq_model: str = ""
    groq_free_confirmed: bool = False
    qdrant_url: AnyHttpUrl = "http://localhost:6333"
    qdrant_collection: str = "pdf_rag"
    data_dir: Path = Path("data")
    hf_home: Path = Path(".cache/huggingface")
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_revision: str = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    reranker_revision: str = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
    chunk_tokens: int = Field(default=300, gt=0)
    chunk_overlap: int = Field(default=60, ge=0)
    candidate_k: int = Field(default=20, gt=0)
    final_k: int = Field(default=5, gt=0)
    max_pdf_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_pages: int = Field(default=200, gt=0)
    max_question_chars: int = Field(default=2000, gt=0)
    max_documents: int = Field(default=10, gt=0)
    max_input_tokens: int = Field(default=2000, gt=0)
    max_output_tokens: int = Field(default=300, gt=0)

    @model_validator(mode="after")
    def validate_limits(self):
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("chunk_overlap must be smaller than chunk_tokens")
        if self.final_k > self.candidate_k:
            raise ValueError("final_k must not exceed candidate_k")
        return self

    @property
    def generation_configured(self) -> bool:
        return bool(
            self.groq_api_key
            and self.groq_api_key.get_secret_value().strip()
            and self.groq_model.strip()
        )


def load_settings() -> Settings:
    return Settings()
