import httpx
from fastapi import FastAPI, Response

from app.config import Settings, load_settings
from app.schemas import HealthResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    application = FastAPI(title="PDF RAG Chatbot", version="0.1.0")

    @application.get("/health", response_model=HealthResponse)
    def health(response: Response) -> HealthResponse:
        try:
            result = httpx.get(f"{str(settings.qdrant_url).rstrip('/')}/readyz", timeout=2)
            ready = result.status_code == 200
        except httpx.HTTPError:
            ready = False
        if not ready:
            response.status_code = 503
        return HealthResponse(
            status="ok" if ready else "degraded",
            qdrant="ready" if ready else "unavailable",
            generation=(
                "configured_not_verified" if settings.generation_configured else "not_configured"
            ),
        )

    return application


app = create_app()
