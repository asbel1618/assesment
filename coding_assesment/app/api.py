"""Application factory."""

from fastapi import FastAPI

from app.routers import query


def create_app() -> FastAPI:
    app = FastAPI(title="coding_assesment")
    app.include_router(query.router)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"message": "Hello, World"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
