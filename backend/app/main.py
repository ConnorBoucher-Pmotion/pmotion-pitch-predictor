"""FastAPI entrypoint for PMotion Pitch Prediction Engine."""

from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.services.predictor_service import PredictorService


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="PMotion Pitch Prediction Engine",
        description="Next-pitch probability POC — baseline tendencies + historical replay.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.state.settings = settings
    app.state.service = PredictorService(settings)

    @app.on_event("startup")
    def _warmup() -> None:
        logging.getLogger(__name__).info(
            "Warming default pitcher %s (%s)",
            settings.default_pitcher_id,
            settings.default_pitcher_name,
        )
        try:
            app.state.service.get_tendencies(settings.default_pitcher_id)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).error("Startup warmup failed: %s", exc)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, reload=True)
