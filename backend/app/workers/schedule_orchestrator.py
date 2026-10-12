"""Discover today's games and auto-start LiveGameWorkers for LIVE games."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone
from typing import Any, Optional

from app.database.session import session_scope
from app.mlb.live_provider import MLBLiveGameProvider
from app.services.live_prediction_service import LivePredictionService
from app.services.pitch_event_service import PitchEventService
from app.services.predictor_service import PredictorService
from app.services.roster_service import RosterService
from app.services.schedule_service import ScheduleService
from app.workers.live_game_worker import LiveGameWorker

logger = logging.getLogger(__name__)


class ScheduleOrchestrator:
    """Background schedule discovery — no UI button required to track live games."""

    def __init__(
        self,
        *,
        predictor: PredictorService,
        poll_interval_sec: float = 20.0,
        live_poll_interval_sec: float = 3.0,
        provider: Optional[MLBLiveGameProvider] = None,
    ) -> None:
        self.provider = provider or MLBLiveGameProvider()
        self.schedule = ScheduleService(self.provider)
        self.pitch_events = PitchEventService()
        self.predictions = LivePredictionService(predictor)
        self.roster = RosterService(self.provider)
        self.poll_interval_sec = poll_interval_sec
        self.live_poll_interval_sec = live_poll_interval_sec
        self._workers: dict[int, LiveGameWorker] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_sync: Optional[dict[str, Any]] = None
        self.roster_synced = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="schedule-orchestrator", daemon=True)
        self._thread.start()
        logger.info("ScheduleOrchestrator started")

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            for w in list(self._workers.values()):
                w.stop()
            self._workers.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    def _loop(self) -> None:
        # Initial sync immediately
        try:
            self.sync_once()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Initial schedule sync failed: %s", exc)
        while not self._stop.wait(self.poll_interval_sec):
            try:
                self.sync_once()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Schedule sync failed: %s", exc)

    def sync_once(self, day: Optional[date] = None) -> dict[str, Any]:
        day = day or datetime.now(timezone.utc).date()
        with session_scope() as session:
            cards = self.schedule.sync_day(session, day)
            if not self.roster_synced:
                try:
                    self.roster.sync_all_pitchers(session)
                    self.roster_synced = True
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Roster sync deferred: %s", exc)

        live_pks: list[int] = []
        for card in cards:
            bucket = card.get("bucket")
            pk = int(card["game_pk"])
            if bucket == "Live":
                live_pks.append(pk)
                self.ensure_worker(pk)
            elif bucket == "Final":
                self.stop_worker(pk)

        # Also probe Scheduled games near start: if feed says Live, start worker
        for card in cards:
            if card.get("bucket") != "Scheduled":
                continue
            pk = int(card["game_pk"])
            try:
                state = self.provider.get_live_game_state(pk)
                if (state.abstract_state or "").lower() == "live":
                    live_pks.append(pk)
                    self.ensure_worker(pk)
            except Exception:  # noqa: BLE001
                continue

        # Stop workers for games no longer live
        with self._lock:
            for pk in list(self._workers.keys()):
                if pk not in live_pks:
                    # Keep polling briefly if worker still running until Final
                    w = self._workers[pk]
                    st = (w.last_state or {}).get("abstract_state", "")
                    if str(st).lower() == "final" or not w.running:
                        w.stop()
                        self._workers.pop(pk, None)

        result = {
            "date": day.isoformat(),
            "games": len(cards),
            "live_workers": list(self._workers.keys()),
            "cards": cards,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "data_label": "mlb_schedule",
        }
        self.last_sync = result
        logger.info(
            "Schedule sync date=%s games=%s live_workers=%s",
            day,
            len(cards),
            list(self._workers.keys()),
        )
        return result

    def ensure_worker(self, game_pk: int) -> LiveGameWorker:
        with self._lock:
            w = self._workers.get(game_pk)
            if w and w.running:
                return w
            w = LiveGameWorker(
                game_pk,
                provider=self.provider,
                pitch_events=self.pitch_events,
                predictions=self.predictions,
                schedule=self.schedule,
                poll_interval_sec=self.live_poll_interval_sec,
            )
            self._workers[game_pk] = w
            w.start()
            # Immediate poll so UI has state
            try:
                w.poll_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Initial poll failed game=%s: %s", game_pk, exc)
            return w

    def stop_worker(self, game_pk: int) -> None:
        with self._lock:
            w = self._workers.pop(game_pk, None)
            if w:
                w.stop()

    def worker_status(self, game_pk: Optional[int] = None) -> dict[str, Any]:
        with self._lock:
            if game_pk is not None:
                w = self._workers.get(game_pk)
                return w.status() if w else {"game_pk": game_pk, "running": False}
            return {
                "active": {str(k): v.status() for k, v in self._workers.items()},
                "last_sync": self.last_sync,
            }

    def force_track(self, game_pk: int) -> dict[str, Any]:
        """Explicitly attach a worker (e.g. for a live game discovered manually)."""
        w = self.ensure_worker(game_pk)
        return w.status()
