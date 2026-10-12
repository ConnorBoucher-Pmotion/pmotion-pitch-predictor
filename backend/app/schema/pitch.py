"""Standardized pitch schemas — no target leakage in feature views."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


PitchType = str  # e.g. FF, SI, SL, CU, CH, FC, FS, ST, KC, SV


class PitchRecord(BaseModel):
    """One historical or live pitch with context available BEFORE the pitch.

    Statcast outcome fields (velocity, spin, location) may be present for
    analysis of *past* pitches, but must never be used as features for the
    pitch currently being predicted.
    """

    game_pk: int
    game_date: str
    pitch_number_in_game: int
    pitcher_id: int
    pitcher_name: str
    batter_id: int
    batter_name: str
    pitch_type: PitchType
    pitch_name: Optional[str] = None
    pitch_number_in_pa: int
    balls: int = Field(ge=0, le=3)
    strikes: int = Field(ge=0, le=2)
    outs: int = Field(ge=0, le=2)
    inning: int = Field(ge=1)
    inning_topbot: Literal["Top", "Bot"]
    stand: Literal["L", "R"]  # batter stands
    p_throws: Literal["L", "R"]
    home_score: int = 0
    away_score: int = 0
    score_diff: int = 0  # pitcher team perspective when known; else home - away
    on_1b: bool = False
    on_2b: bool = False
    on_3b: bool = False
    previous_pitch_type: Optional[PitchType] = None
    previous_two_pitch_types: list[PitchType] = Field(default_factory=list)
    previous_pitch_result: Optional[str] = None
    times_through_order: int = 1
    pitcher_pitch_count: int = 0
    at_bat_number: Optional[int] = None
    description: Optional[str] = None
    events: Optional[str] = None
    # Statcast fields kept for later — NEVER for current-pitch features
    release_speed: Optional[float] = None
    release_spin_rate: Optional[float] = None
    pfx_x: Optional[float] = None
    pfx_z: Optional[float] = None
    plate_x: Optional[float] = None
    plate_z: Optional[float] = None
    zone: Optional[int] = None

    @property
    def count_key(self) -> str:
        return f"{self.balls}-{self.strikes}"

    @property
    def runners_state(self) -> str:
        if not self.on_1b and not self.on_2b and not self.on_3b:
            return "empty"
        if self.on_2b or self.on_3b:
            return "risp"
        return "on"


class SituationInput(BaseModel):
    """Manual situation for prediction — no upcoming pitch fields."""

    pitcher_id: int
    balls: int = Field(ge=0, le=3, default=0)
    strikes: int = Field(ge=0, le=2, default=0)
    outs: int = Field(ge=0, le=2, default=0)
    inning: int = Field(ge=1, default=1)
    stand: Literal["L", "R"] = "R"
    on_1b: bool = False
    on_2b: bool = False
    on_3b: bool = False
    previous_pitch_type: Optional[PitchType] = None
    previous_two_pitch_types: list[PitchType] = Field(default_factory=list)
    times_through_order: int = 1
    pitcher_pitch_count: int = 0


class PitchProbability(BaseModel):
    pitch_type: PitchType
    pitch_name: str
    probability: float
    why: list[str] = Field(default_factory=list)


class PredictionResult(BaseModel):
    pitcher_id: int
    pitcher_name: str
    situation: SituationInput
    probabilities: list[PitchProbability]
    top_pitch: PitchType
    top_probability: float
    baseline_most_common: PitchType
    baseline_most_common_rate: float
    explanation_summary: str
    data_label: str = "historical_tendencies"
    model: str = "weighted_baseline"


class TendencySlice(BaseModel):
    label: str
    sample_size: int
    rates: dict[str, float]


class PitcherTendencies(BaseModel):
    pitcher_id: int
    pitcher_name: str
    pitch_count: int
    arsenal: dict[str, float]
    by_strikes: dict[str, dict[str, float]]
    by_count: dict[str, dict[str, float]]
    vs_hand: dict[str, dict[str, float]]
    by_runners: dict[str, dict[str, float]]
    by_inning: dict[str, dict[str, float]]
    by_tto: dict[str, dict[str, float]]
    after_pitch: dict[str, dict[str, float]]
    sequences_2: dict[str, dict[str, float]]
    sequences_3: dict[str, dict[str, float]]
    pitch_names: dict[str, str]


class ReplayStepResult(BaseModel):
    index: int
    situation: SituationInput
    prediction: PredictionResult
    actual_pitch_type: Optional[PitchType] = None
    correct: Optional[bool] = None
    revealed: bool = False


class ReplayAccuracy(BaseModel):
    total_revealed: int
    correct: int
    accuracy: float
    most_common_baseline_correct: int
    most_common_baseline_accuracy: float
    beats_most_common: bool
    by_pitch_type: dict[str, dict[str, Any]]


class ApiError(BaseModel):
    detail: str
    code: str
    data_label: Optional[str] = None
