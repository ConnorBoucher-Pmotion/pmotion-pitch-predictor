"""FastAPI entrypoint — live MLB pitch intelligence platform (Milestone 1)."""

from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.platform_routes import router as platform_router
from app.api.routes import router
from app.config import get_settings
from app.database.session import init_db
from app.services.demo_live_service import LabeledHistoricalDemoRunner
from app.services.live_prediction_service import LivePredictionService
from app.services.pitch_event_service import PitchEventService
from app.services.predictor_service import PredictorService
from app.services.schedule_service import ScheduleService
from app.workers.schedule_orchestrator import ScheduleOrchestrator


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
        title="PMotion Pitch Intelligence Platform",
        description=(
            "Live MLB pitch intelligence — schedule discovery, simultaneous game workers, "
            "Postgres pitch/prediction storage with pre-pitch timing proof."
        ),
        version="0.2.0-m1",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(platform_router)
    app.state.settings = settings
    app.state.service = PredictorService(settings)

    @app.on_event("startup")
    def _startup() -> None:
        log = logging.getLogger(__name__)
        try:
            init_db()
            log.info("PostgreSQL schema ready (%s)", settings.database_url.split("@")[-1])
        except Exception as exc:  # noqa: BLE001
            log.error("Database init failed: %s", exc)
            raise

        predictor: PredictorService = app.state.service
        orch = ScheduleOrchestrator(
            predictor=predictor,
            poll_interval_sec=settings.schedule_poll_interval_sec,
            live_poll_interval_sec=settings.live_poll_interval_sec,
        )
        app.state.orchestrator = orch
        app.state.demo_runner = LabeledHistoricalDemoRunner(
            pitch_events=PitchEventService(),
            predictions=LivePredictionService(predictor),
            schedule=ScheduleService(orch.provider),
            provider=orch.provider,
        )

        try:
            predictor.get_tendencies(settings.default_pitcher_id)
        except Exception as exc:  # noqa: BLE001
            log.error("Predictor warmup failed: %s", exc)

        if settings.auto_start_workers:
            orch.start()
            log.info("ScheduleOrchestrator running — auto LiveGameWorkers enabled")
        else:
            log.warning("AUTO_START_WORKERS=false — schedule discovery idle")

    @app.on_event("shutdown")
    def _shutdown() -> None:
        orch = getattr(app.state, "orchestrator", None)
        if orch:
            orch.stop()
        demo = getattr(app.state, "demo_runner", None)
        if demo:
            demo.stop()

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, reload=True)
