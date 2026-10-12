"""Provider interfaces — data retrieval stays separate from prediction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.schema.pitch import PitchRecord


class HistoricalPitchProvider(ABC):
    """Fetch historical pitch-by-pitch for a pitcher."""

    @abstractmethod
    def get_pitches(
        self,
        pitcher_id: int,
        start_date: str,
        end_date: str,
        *,
        force_refresh: bool = False,
    ) -> list[PitchRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_games(self, pitcher_id: int, start_date: str, end_date: str) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def get_game_pitches(self, game_pk: int, pitcher_id: Optional[int] = None) -> list[PitchRecord]:
        raise NotImplementedError


class LiveGameProvider(ABC):
    """Live or mock live game feed."""

    @abstractmethod
    def start_game(self, game_pk: int, pitcher_id: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def current_index(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def total_pitches(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def peek_situation(self) -> Optional[PitchRecord]:
        """Return the next pitch's pre-pitch context without revealing pitch_type for prediction use."""
        raise NotImplementedError

    @abstractmethod
    def reveal_actual(self) -> Optional[PitchRecord]:
        raise NotImplementedError

    @abstractmethod
    def advance(self) -> Optional[PitchRecord]:
        raise NotImplementedError

    @abstractmethod
    def step_back(self) -> Optional[PitchRecord]:
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def data_label(self) -> str:
        raise NotImplementedError
