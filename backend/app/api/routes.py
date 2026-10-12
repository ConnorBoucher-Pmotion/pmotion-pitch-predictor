"""FastAPI routes for prediction, tendencies, replay, live, and ML."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.schema.pitch import SituationInput

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class PredictRequest(BaseModel):
    situation: SituationInput
    weights: Optional[dict[str, float]] = None
    model: Optional[str] = Field(default=None, description="ml | baseline | null=prefer config")


class ReplayStartRequest(BaseModel):
    game_pk: int
    pitcher_id: Optional[int] = None


class ReplayControlRequest(BaseModel):
    action: str = Field(description="start|pause|next|previous|reveal|reset|set_speed")
    speed: Optional[float] = None


class LiveStartRequest(BaseModel):
    game_pk: int
    pitcher_id: Optional[int] = None


class LiveControlRequest(BaseModel):
    action: str = Field(description="refresh|stop|start_polling|log_current")


def _svc(request: Request):
    return request.app.state.service


def _http_error(exc: Exception, code: str = "error", status: int = 400) -> HTTPException:
    logger.exception("API error (%s): %s", code, exc)
    return HTTPException(status_code=status, detail={"detail": str(exc), "code": code})


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pmotion-pitch-predictor"}


@router.get("/config")
def get_config(request: Request) -> dict[str, Any]:
    s = request.app.state.settings
    return {
        "default_pitcher_id": s.default_pitcher_id,
        "default_pitcher_name": s.default_pitcher_name,
        "default_start_date": s.default_start_date,
        "default_end_date": s.default_end_date,
        "default_game_pk": s.default_game_pk,
        "use_sample_data": s.use_sample_data,
        "dodgers_starter_ids": s.dodgers_starter_id_list,
        "dodgers_team_id": s.dodgers_team_id,
        "prefer_ml_predictions": s.prefer_ml_predictions,
        "data_label_note": (
            "Sample data is an explicit fallback only. Live uses MLB Stats API; "
            "replay is labeled replayed_historical."
        ),
    }


@router.get("/pitchers/starters")
def list_starters(request: Request) -> dict[str, Any]:
    try:
        return {
            "starters": _svc(request).list_starters(),
            "use_sample_data": request.app.state.settings.use_sample_data,
        }
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "starters_failed") from exc


@router.post("/data/warm-starters")
def warm_starters(request: Request, force_refresh: bool = False) -> dict[str, Any]:
    try:
        return _svc(request).warm_dodgers_starters(force_refresh=force_refresh)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "warm_failed") from exc


@router.get("/pitchers/{pitcher_id}/pitches")
def get_pitches(
    request: Request,
    pitcher_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict[str, Any]:
    try:
        pitches = _svc(request).load_pitches(pitcher_id, start_date, end_date)
        label = "sample" if request.app.state.settings.use_sample_data else "historical"
        return {
            "pitcher_id": pitcher_id,
            "count": len(pitches),
            "data_label": label,
            "pitches": [p.model_dump() for p in pitches[:25]],
            "truncated": len(pitches) > 25,
        }
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "data_load_failed") from exc


@router.get("/pitchers/{pitcher_id}/tendencies")
def get_tendencies(request: Request, pitcher_id: int) -> dict[str, Any]:
    try:
        t = _svc(request).get_tendencies(pitcher_id)
        return {"data_label": "historical_tendencies", **t.model_dump()}
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "tendency_failed") from exc


@router.get("/pitchers/{pitcher_id}/games")
def list_games(request: Request, pitcher_id: int) -> dict[str, Any]:
    try:
        games = _svc(request).list_games(pitcher_id)
        return {"pitcher_id": pitcher_id, "games": games, "data_label": "historical"}
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "games_failed") from exc


@router.post("/predict")
def predict(request: Request, body: PredictRequest) -> dict[str, Any]:
    try:
        result = _svc(request).predict_situation(
            body.situation, weights=body.weights, model=body.model
        )
        return result.model_dump()
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "predict_failed") from exc


@router.post("/replay/start")
def replay_start(request: Request, body: ReplayStartRequest) -> dict[str, Any]:
    try:
        return _svc(request).start_replay(body.game_pk, body.pitcher_id)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "replay_start_failed") from exc


@router.get("/replay/state")
def replay_state(request: Request) -> dict[str, Any]:
    try:
        return _svc(request).replay_state()
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "replay_state_failed") from exc


@router.post("/replay/control")
def replay_control(request: Request, body: ReplayControlRequest) -> dict[str, Any]:
    try:
        return _svc(request).replay_control(body.action, body.speed)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "replay_control_failed") from exc


@router.get("/replay/evaluate")
def replay_evaluate(
    request: Request,
    game_pk: int = Query(...),
    pitcher_id: Optional[int] = None,
) -> dict[str, Any]:
    try:
        return _svc(request).game_evaluation(game_pk, pitcher_id)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "evaluate_failed") from exc


@router.post("/live/start")
def live_start(request: Request, body: LiveStartRequest) -> dict[str, Any]:
    try:
        return _svc(request).start_live(body.game_pk, body.pitcher_id)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "live_start_failed") from exc


@router.get("/live/state")
def live_state(request: Request) -> dict[str, Any]:
    try:
        return _svc(request).live_state()
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "live_state_failed") from exc


@router.post("/live/control")
def live_control(request: Request, body: LiveControlRequest) -> dict[str, Any]:
    try:
        return _svc(request).live_control(body.action)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "live_control_failed") from exc


@router.get("/live/schedule")
def live_schedule(
    date: str = Query(..., description="YYYY-MM-DD"),
    team_id: int = Query(119, description="MLB team id (Dodgers=119)"),
) -> dict[str, Any]:
    try:
        from app.providers.mlb_live import MlbLiveGameProvider

        games = MlbLiveGameProvider.find_team_games(team_id, date)
        return {"date": date, "team_id": team_id, "games": games, "data_label": "mlb_schedule"}
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "schedule_failed") from exc


@router.get("/model/performance")
def model_performance(request: Request, pitcher_id: Optional[int] = None) -> dict[str, Any]:
    try:
        return _svc(request).model_performance(pitcher_id)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "performance_failed") from exc


@router.post("/model/train")
def model_train(request: Request, pitcher_id: Optional[int] = None) -> dict[str, Any]:
    try:
        pid = pitcher_id or request.app.state.settings.default_pitcher_id
        return _svc(request).ensure_ml(pid)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "train_failed") from exc


@router.get("/logs/predictions")
def prediction_logs(request: Request, limit: int = 50) -> dict[str, Any]:
    try:
        store = _svc(request).logs
        return {"summary": store.summary(), "recent": store.recent(limit)}
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "logs_failed") from exc
