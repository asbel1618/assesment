"""Application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.routers import query

_INDEX_HTML = Path(__file__).parent / "static" / "index.html"


def create_app() -> FastAPI:
    app = FastAPI(title="coding_assesment")
    app.include_router(query.router)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"message": "Hello, World"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ui", include_in_schema=False)
    async def ui() -> FileResponse:
        return FileResponse(_INDEX_HTML, media_type="text/html")

    return app
