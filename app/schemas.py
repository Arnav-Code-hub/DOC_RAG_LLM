from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    qdrant: Literal["ready", "unavailable"]
    generation: Literal["not_configured", "configured_not_verified"]


class Page(BaseModel):
    document_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    filename: str
    page_number: int = Field(gt=0)
    text: str
    warnings: list[str] = Field(default_factory=list)

    @property
    def storage_name(self) -> str:
        return f"{self.document_hash}.pdf"


class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    document_hash: str
    index_config_id: str
    filename: str
    page_number: int = Field(gt=0)
    text: str
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
