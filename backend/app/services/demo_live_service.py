"""Explicitly labeled historical demo through the live worker pipeline.

NEVER used as silent fake live data. data_label is always labeled_historical_demo.
Useful offseason / when today's games are Scheduled only.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Optional

from app.database.models import Game
from app.database.session import session_scope
from app.mlb.live_provider import LiveGameState, MLBLiveGameProvider, ParsedPitch
from app.services.live_prediction_service import LivePredictionService
from app.services.pitch_event_service import PitchEventService
from app.services.schedule_service import ScheduleService

logger = logging.getLogger(__name__)

DEMO_LABEL = "labeled_historical_demo"


class LabeledHistoricalDemoRunner:
    """Feeds a completed game's pitches one-by-one through predict→resolve timing."""

    def __init__(
        self,
        *,
        pitch_events: PitchEventService,
        predictions: LivePredictionService,
        schedule: ScheduleService,
        provider: Optional[MLBLiveGameProvider] = None,
        step_delay_sec: float = 1.5,
    ) -> None:
        self.provider = provider or MLBLiveGameProvider()
        self.pitch_events = pitch_events
        self.predictions = predictions
        self.schedule = schedule
        self.step_delay_sec = step_delay_sec
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.game_pk: Optional[int] = None
        self.index = 0
        self.total = 0
        self.last_snapshot: Optional[dict[str, Any]] = None
        self.running = False

    def start(self, game_pk: int) -> dict[str, Any]:
        self.stop()
        state = self.provider.get_live_game_state(game_pk)
        if not state.pitches:
            raise RuntimeError(
                f"No pitches in feed for game_pk={game_pk}. "
                "Pick a completed game with pitch data. This demo is labeled_historical_demo — not live."
            )
        self.game_pk = game_pk
        self.index = 0
        self.total = len(state.pitches)
        self._all_pitches = state.pitches
        self._base_state = state
        self._stop.clear()
        self.running = True

        with session_scope() as session:
            self.schedule.upsert_from_live_state(session, state)
            game = session.get(Game, game_pk)
            if game is None:
                raise RuntimeError(f"Failed to upsert game {game_pk}")
            game.data_label = DEMO_LABEL
            game.worker_active = True
            game.status = "Demo (labeled historical)"
            game.abstract_state = "Demo"

        self._thread = threading.Thread(target=self._loop, name=f"demo-{game_pk}", daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self.running = False
        if self.game_pk:
            with session_scope() as session:
                game = session.get(Game, self.game_pk)
                if game:
                    game.worker_active = False

    def _loop(self) -> None:
        assert self.game_pk is not None
        try:
            while self.index < self.total and not self._stop.is_set():
                self.step_once()
                self._stop.wait(self.step_delay_sec)
        finally:
            self.running = False
            with session_scope() as session:
                game = session.get(Game, self.game_pk)
                if game:
                    game.worker_active = False
                    game.status = "Demo complete (labeled historical)"

    def step_once(self) -> dict[str, Any]:
        """Predict next (actual still unknown) → then reveal pitch → resolve."""
        assert self.game_pk is not None
        pitches_so_far = self._all_pitches[: self.index]
        upcoming = self._all_pitches[self.index] if self.index < self.total else None

        # Build a synthetic live state with only pitches revealed so far
        partial = self._make_partial_state(pitches_so_far, upcoming)

        with session_scope() as session:
            self.schedule.upsert_from_live_state(session, partial)
            game = session.get(Game, self.game_pk)
            if game:
                game.data_label = DEMO_LABEL
                game.status = "Demo (labeled historical)"
                game.abstract_state = "Live"  # so predict path runs; UI shows data_label
                game.worker_active = True

            resolved = None
            # PREDICT before revealing upcoming pitch
            if upcoming is not None:
                # Force matchup target to upcoming pitch key
                partial.current_matchup = {
                    "pitcher_id": upcoming.pitcher_id,
                    "pitcher_name": upcoming.pitcher_name,
                    "batter_id": upcoming.batter_id,
                    "batter_name": upcoming.batter_name,
                    "stand": upcoming.stand,
                    "p_throws": upcoming.p_throws,
                    "at_bat_index": upcoming.at_bat_index,
                    "pitch_number_next": upcoming.pitch_number,
                }
                partial.balls = upcoming.balls
                partial.strikes = upcoming.strikes
                partial.outs = upcoming.outs
                partial.inning = upcoming.inning
                partial.inning_half = upcoming.inning_half
                partial.pitcher_id = upcoming.pitcher_id
                partial.pitcher_name = upcoming.pitcher_name
                partial.batter_id = upcoming.batter_id
                partial.batter_name = upcoming.batter_name
                partial.on_1b = upcoming.on_1b
                partial.on_2b = upcoming.on_2b
                partial.on_3b = upcoming.on_3b
                partial.abstract_state = "Live"
                pred = self.predictions.create_next_prediction(
                    session, state=partial, data_label=DEMO_LABEL
                )
                assert pred is not None
                assert pred.actual_pitch_type is None
                assert pred.prediction_created_at is not None
                created_at = pred.prediction_created_at

                # Small delay so timestamps differ clearly
                time.sleep(0.05)

                # Reveal actual pitch
                pitch_row, _ = self.pitch_events.upsert_pitch(session, upcoming)
                resolved = self.predictions.resolve_with_pitch(session, pitch_row.id, upcoming)
                assert resolved is not None
                assert resolved.resolved_at is not None
                assert created_at <= resolved.resolved_at
                assert resolved.actual_pitch_type == upcoming.pitch_type

            open_pred = self.predictions.open_prediction(session, self.game_pk)
            accuracy = self.predictions.accuracy_summary(session, self.game_pk)
            self.index += 1
            snap = {
                "mode": "labeled_historical_demo",
                "data_label": DEMO_LABEL,
                "warning": "NOT live MLB — explicitly labeled historical demo for timing proof.",
                "game_pk": self.game_pk,
                "index": self.index,
                "total": self.total,
                "home_score": partial.home_score,
                "away_score": partial.away_score,
                "inning": partial.inning,
                "inning_half": partial.inning_half,
                "pitcher_name": partial.pitcher_name,
                "batter_name": partial.batter_name,
                "open_prediction": LivePredictionService.serialize(open_pred) if open_pred else None,
                "last_resolved": LivePredictionService.serialize(resolved) if resolved else None,
                "accuracy": accuracy,
                "running": self.running and self.index < self.total,
            }
            self.last_snapshot = snap
            return snap

    def _make_partial_state(
        self, pitches: list[ParsedPitch], upcoming: Optional[ParsedPitch]
    ) -> LiveGameState:
        base = self._base_state
        last = pitches[-1] if pitches else upcoming
        return LiveGameState(
            game_pk=base.game_pk,
            status="Demo (labeled historical)",
            abstract_state="Live",
            home_team_id=base.home_team_id,
            away_team_id=base.away_team_id,
            home_team_name=base.home_team_name,
            away_team_name=base.away_team_name,
            home_score=last.home_score if last else 0,
            away_score=last.away_score if last else 0,
            inning=last.inning if last else 1,
            inning_half=last.inning_half if last else "Top",
            outs=last.outs if last else 0,
            balls=last.balls if last else 0,
            strikes=last.strikes if last else 0,
            pitcher_id=last.pitcher_id if last else None,
            pitcher_name=last.pitcher_name if last else None,
            batter_id=last.batter_id if last else None,
            batter_name=last.batter_name if last else None,
            on_1b=last.on_1b if last else False,
            on_2b=last.on_2b if last else False,
            on_3b=last.on_3b if last else False,
            pitches=list(pitches),
            current_matchup=None,
            venue=base.venue,
            game_date=base.game_date,
            data_label=DEMO_LABEL,
        )

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "game_pk": self.game_pk,
            "index": self.index,
            "total": self.total,
            "data_label": DEMO_LABEL,
            "last_snapshot": self.last_snapshot,
            "warning": "NOT live MLB — labeled_historical_demo only.",
        }
