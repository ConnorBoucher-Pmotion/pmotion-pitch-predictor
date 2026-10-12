"""Per-game live poller: detect pitches → resolve → predict next → save."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from app.database.session import session_scope
from app.mlb.live_provider import MLBLiveGameProvider
from app.services.live_prediction_service import LivePredictionService
from app.services.pitch_event_service import PitchEventService
from app.services.schedule_service import ScheduleService

logger = logging.getLogger(__name__)


class LiveGameWorker:
    """One worker per live game. Polls MLB feed every poll_interval_sec."""

    def __init__(
        self,
        game_pk: int,
        *,
        provider: MLBLiveGameProvider,
        pitch_events: PitchEventService,
        predictions: LivePredictionService,
        schedule: ScheduleService,
        poll_interval_sec: float = 3.0,
        data_label: str = "live_mlb_stats_api",
    ) -> None:
        self.game_pk = game_pk
        self.provider = provider
        self.pitch_events = pitch_events
        self.predictions = predictions
        self.schedule = schedule
        self.poll_interval_sec = poll_interval_sec
        self.data_label = data_label
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.last_error: Optional[str] = None
        self.last_state: Optional[dict[str, Any]] = None
        self.polls = 0
        self.new_pitches = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name=f"live-game-{self.game_pk}",
            daemon=True,
        )
        self._thread.start()
        logger.info("LiveGameWorker started game_pk=%s", self.game_pk)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        with session_scope() as session:
            game = self.schedule.get_game(session, self.game_pk)
            if game:
                game.worker_active = False
        logger.info("LiveGameWorker stopped game_pk=%s", self.game_pk)

    def _loop(self) -> None:
        with session_scope() as session:
            game = self.schedule.get_game(session, self.game_pk)
            if game:
                game.worker_active = True
        while not self._stop.wait(self.poll_interval_sec):
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                logger.exception("LiveGameWorker poll failed game=%s: %s", self.game_pk, exc)

    def poll_once(self) -> dict[str, Any]:
        state = self.provider.get_live_game_state(self.game_pk)
        self.polls += 1
        created_preds = 0
        resolved = 0
        new_pitches = 0

        with session_scope() as session:
            self.schedule.upsert_from_live_state(session, state)
            game = self.schedule.get_game(session, self.game_pk)
            if game:
                game.worker_active = True
                game.last_polled_at = datetime.now(timezone.utc)

            # 1) Persist any new pitches (idempotent)
            for parsed in state.pitches:
                pitch_row, created = self.pitch_events.upsert_pitch(session, parsed)
                if created:
                    new_pitches += 1
                    self.new_pitches += 1
                    # 2) Resolve prior prediction for this pitch key
                    pred = self.predictions.resolve_with_pitch(session, pitch_row.id, parsed)
                    if pred:
                        resolved += 1

            # 3) If game still live (or in progress), predict NEXT pitch before it arrives
            abstract = (state.abstract_state or "").lower()
            status_l = (state.status or "").lower()
            is_live = abstract == "live" or status_l in {"in progress", "manager challenge", "review"}
            if is_live:
                pred = self.predictions.create_next_prediction(
                    session, state=state, data_label=self.data_label
                )
                if pred and pred.actual_pitch_type is None and pred.resolved_at is None:
                    created_preds = 1

            # Stop condition: Final
            if abstract == "final" or status_l.startswith("final"):
                if game:
                    game.worker_active = False
                self._stop.set()

            open_pred = self.predictions.open_prediction(session, self.game_pk)
            accuracy = self.predictions.accuracy_summary(session, self.game_pk)
            snapshot = {
                "game_pk": self.game_pk,
                "status": state.status,
                "abstract_state": state.abstract_state,
                "home_score": state.home_score,
                "away_score": state.away_score,
                "inning": state.inning,
                "inning_half": state.inning_half,
                "count": {"balls": state.balls, "strikes": state.strikes, "outs": state.outs},
                "pitcher_id": state.pitcher_id,
                "pitcher_name": state.pitcher_name,
                "batter_id": state.batter_id,
                "batter_name": state.batter_name,
                "runners": {"on_1b": state.on_1b, "on_2b": state.on_2b, "on_3b": state.on_3b},
                "pitch_count_stored": len(state.pitches),
                "new_pitches_this_poll": new_pitches,
                "resolved_this_poll": resolved,
                "created_prediction": created_preds,
                "open_prediction": LivePredictionService.serialize(open_pred) if open_pred else None,
                "accuracy": accuracy,
                "current_matchup": state.current_matchup,
                "data_label": self.data_label,
                "polls": self.polls,
                "worker_running": self.running or not self._stop.is_set(),
                "last_error": self.last_error,
                "polled_at": datetime.now(timezone.utc).isoformat(),
            }
            self.last_state = snapshot
            self.last_error = None
            return snapshot

    def status(self) -> dict[str, Any]:
        return {
            "game_pk": self.game_pk,
            "running": self.running,
            "polls": self.polls,
            "new_pitches": self.new_pitches,
            "last_error": self.last_error,
            "last_state": self.last_state,
            "data_label": self.data_label,
        }
