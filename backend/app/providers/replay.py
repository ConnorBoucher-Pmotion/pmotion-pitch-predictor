"""Mock live provider that replays one historical game pitch-by-pitch."""

from __future__ import annotations

import logging
from typing import Optional

from app.providers.base import HistoricalPitchProvider, LiveGameProvider
from app.schema.pitch import PitchRecord

logger = logging.getLogger(__name__)


class ReplayLiveProvider(LiveGameProvider):
    """Labeled mock/replay feed — never presented as true live data."""

    def __init__(self, historical: HistoricalPitchProvider) -> None:
        self.historical = historical
        self._pitches: list[PitchRecord] = []
        self._index = 0
        self._game_pk: Optional[int] = None
        self._pitcher_id: Optional[int] = None

    def start_game(self, game_pk: int, pitcher_id: int) -> None:
        self._pitches = self.historical.get_game_pitches(game_pk, pitcher_id)
        self._index = 0
        self._game_pk = game_pk
        self._pitcher_id = pitcher_id
        logger.info(
            "Replay started game_pk=%s pitcher_id=%s pitches=%d (data_label=%s)",
            game_pk,
            pitcher_id,
            len(self._pitches),
            self.data_label(),
        )

    def current_index(self) -> int:
        return self._index

    def total_pitches(self) -> int:
        return len(self._pitches)

    def peek_situation(self) -> Optional[PitchRecord]:
        if self._index >= len(self._pitches):
            return None
        return self._pitches[self._index]

    def reveal_actual(self) -> Optional[PitchRecord]:
        return self.peek_situation()

    def advance(self) -> Optional[PitchRecord]:
        if self._index < len(self._pitches) - 1:
            self._index += 1
            return self.peek_situation()
        if self._index < len(self._pitches):
            self._index = len(self._pitches)
        return None

    def step_back(self) -> Optional[PitchRecord]:
        if self._index > 0:
            self._index -= 1
        return self.peek_situation()

    def reset(self) -> None:
        self._index = 0

    def data_label(self) -> str:
        return "replayed_historical"

    def all_pitches(self) -> list[PitchRecord]:
        return list(self._pitches)
