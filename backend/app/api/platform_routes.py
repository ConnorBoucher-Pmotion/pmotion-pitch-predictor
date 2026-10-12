"""Milestone 1 platform API: scoreboard, live games, pitchers, accuracy."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.database.models import Game, Pitch, Prediction
from app.database.session import session_scope
from app.services.accuracy_service import AccuracyService
from app.services.live_prediction_service import LivePredictionService
from app.services.schedule_service import ScheduleService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _orch(request: Request):
    return request.app.state.orchestrator


def _demo(request: Request):
    return request.app.state.demo_runner


def _http_error(exc: Exception, code: str = "error", status: int = 400) -> HTTPException:
    logger.exception("API error (%s): %s", code, exc)
    return HTTPException(status_code=status, detail={"detail": str(exc), "code": code})


@router.get("/schedule/today")
def schedule_today(
    request: Request,
    day: Optional[str] = Query(None, description="YYYY-MM-DD; default UTC today"),
    refresh: bool = True,
) -> dict[str, Any]:
    try:
        d = date.fromisoformat(day) if day else datetime.now(timezone.utc).date()
        orch = _orch(request)
        with session_scope() as session:
            if refresh:
                cards = orch.schedule.sync_day(session, d)
            else:
                cards = orch.schedule.list_day(session, d)
        workers = orch.worker_status()
        return {
            "date": d.isoformat(),
            "games": cards,
            "live_workers": list((workers.get("active") or {}).keys()),
            "data_label": "mlb_schedule",
            "note": "Backend auto-discovers LIVE games and starts LiveGameWorkers — no UI button required.",
        }
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "schedule_today_failed") from exc


@router.get("/games")
def list_games(
    request: Request,
    day: Optional[str] = Query(None),
) -> dict[str, Any]:
    return schedule_today(request, day=day, refresh=True)


@router.get("/games/{game_pk}")
def get_game(request: Request, game_pk: int) -> dict[str, Any]:
    try:
        orch = _orch(request)
        # Prefer live worker snapshot
        wstatus = orch.worker_status(game_pk)
        with session_scope() as session:
            game = session.get(Game, game_pk)
            pitches = list(
                session.scalars(
                    select(Pitch)
                    .where(Pitch.game_pk == game_pk)
                    .order_by(Pitch.pitch_number_in_game.nulls_last(), Pitch.id)
                ).all()
            )
            open_pred = session.scalar(
                select(Prediction)
                .where(Prediction.game_pk == game_pk, Prediction.resolved_at.is_(None))
                .order_by(Prediction.prediction_created_at.desc())
            )
            recent_preds = list(
                session.scalars(
                    select(Prediction)
                    .where(Prediction.game_pk == game_pk)
                    .order_by(Prediction.prediction_created_at.desc())
                    .limit(30)
                ).all()
            )
            accuracy = AccuracyService().summary(session, game_pk=game_pk)

            # If no DB game yet, pull from MLB
            if game is None:
                try:
                    state = orch.provider.get_live_game_state(game_pk)
                    orch.schedule.upsert_from_live_state(session, state)
                    game = session.get(Game, game_pk)
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(
                        f"Game {game_pk} not found locally and MLB feed failed: {exc}. "
                        "Never silently faking live data."
                    ) from exc

            card = ScheduleService.game_to_card(game) if game else {"game_pk": game_pk}
            live_feed = None
            try:
                st = orch.provider.get_live_game_state(game_pk)
                live_feed = {
                    "status": st.status,
                    "abstract_state": st.abstract_state,
                    "home_score": st.home_score,
                    "away_score": st.away_score,
                    "inning": st.inning,
                    "inning_half": st.inning_half,
                    "balls": st.balls,
                    "strikes": st.strikes,
                    "outs": st.outs,
                    "pitcher_id": st.pitcher_id,
                    "pitcher_name": st.pitcher_name,
                    "batter_id": st.batter_id,
                    "batter_name": st.batter_name,
                    "runners": {"on_1b": st.on_1b, "on_2b": st.on_2b, "on_3b": st.on_3b},
                    "current_matchup": st.current_matchup,
                    "feed_pitch_count": len(st.pitches),
                    "data_label": st.data_label,
                }
            except Exception as exc:  # noqa: BLE001
                live_feed = {"error": str(exc), "data_label": "mlb_feed_error"}

            return {
                "game": card,
                "live": live_feed,
                "worker": wstatus,
                "open_prediction": LivePredictionService.serialize(open_pred) if open_pred else None,
                "predictions": [LivePredictionService.serialize(p) for p in recent_preds],
                "pitches": [
                    {
                        "id": p.id,
                        "at_bat_index": p.at_bat_index,
                        "pitch_number": p.pitch_number,
                        "pitch_number_in_game": p.pitch_number_in_game,
                        "pitch_type": p.pitch_type,
                        "pitch_name": p.pitch_name,
                        "pitcher_name": p.pitcher_name,
                        "batter_name": p.batter_name,
                        "balls": p.balls,
                        "strikes": p.strikes,
                        "outs": p.outs,
                        "inning": p.inning,
                        "inning_half": p.inning_half,
                        "description": p.description,
                        "created_at": p.created_at.isoformat() if p.created_at else None,
                    }
                    for p in pitches[-40:]
                ],
                "accuracy": accuracy,
                "data_label": (live_feed or {}).get("data_label") or card.get("data_label"),
            }
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "game_detail_failed") from exc


@router.post("/games/{game_pk}/track")
def track_game(request: Request, game_pk: int) -> dict[str, Any]:
    """Force-start a LiveGameWorker (normally auto-started when status is LIVE)."""
    try:
        return {"worker": _orch(request).force_track(game_pk), "note": "Worker attached"}
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "track_failed") from exc


@router.get("/workers")
def workers(request: Request) -> dict[str, Any]:
    return _orch(request).worker_status()


@router.get("/pitchers")
def pitchers(
    request: Request,
    team_id: Optional[int] = None,
    q: Optional[str] = None,
    sync: bool = False,
) -> dict[str, Any]:
    try:
        orch = _orch(request)
        with session_scope() as session:
            if sync or not orch.roster_synced:
                orch.roster.sync_all_pitchers(session)
                orch.roster_synced = True
            rows = orch.roster.list_pitchers(session, team_id=team_id, q=q, limit=500)
        return {"pitchers": rows, "count": len(rows), "data_label": "mlb_roster"}
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "pitchers_failed") from exc


@router.get("/accuracy")
def accuracy(
    request: Request,
    game_pk: Optional[int] = None,
    pitcher_id: Optional[int] = None,
) -> dict[str, Any]:
    try:
        with session_scope() as session:
            return AccuracyService().summary(session, game_pk=game_pk, pitcher_id=pitcher_id)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "accuracy_failed") from exc


@router.get("/predictions/timing-proof")
def timing_proof(request: Request, game_pk: Optional[int] = None, limit: int = 20) -> dict[str, Any]:
    """Return predictions proving prediction_created_at precedes actual/resolve."""
    try:
        with session_scope() as session:
            q = select(Prediction).order_by(Prediction.prediction_created_at.desc()).limit(limit)
            if game_pk is not None:
                q = q.where(Prediction.game_pk == game_pk)
            rows = list(session.scalars(q).all())
            items = []
            for p in rows:
                ok = (
                    p.prediction_created_at is not None
                    and (
                        p.resolved_at is None
                        or p.prediction_created_at <= p.resolved_at
                    )
                )
                items.append(
                    {
                        **LivePredictionService.serialize(p),
                        "proof_ok": ok,
                    }
                )
            return {
                "count": len(items),
                "all_proof_ok": all(i["proof_ok"] for i in items) if items else True,
                "items": items,
                "rule": "prediction_created_at must be set while actual_pitch_type is null; resolve only later.",
            }
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "timing_proof_failed") from exc


class DemoStartRequest(BaseModel):
    game_pk: int = Field(description="Completed MLB game_pk with pitch data")
    step_delay_sec: float = 1.2


@router.post("/demo/historical-live")
def demo_start(request: Request, body: DemoStartRequest) -> dict[str, Any]:
    """Start explicitly labeled historical demo (NOT silent fake live)."""
    try:
        runner = _demo(request)
        runner.step_delay_sec = body.step_delay_sec
        return runner.start(body.game_pk)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc, "demo_start_failed") from exc


@router.get("/demo/historical-live")
def demo_status(request: Request) -> dict[str, Any]:
    return _demo(request).status()


@router.post("/demo/historical-live/stop")
def demo_stop(request: Request) -> dict[str, Any]:
    _demo(request).stop()
    return {"stopped": True, "data_label": "labeled_historical_demo"}
