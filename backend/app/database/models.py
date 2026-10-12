"""SQLAlchemy models for Milestone 1 live platform."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # MLB team id
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    abbreviation: Mapped[Optional[str]] = mapped_column(String(16))
    league: Mapped[Optional[str]] = mapped_column(String(64))
    division: Mapped[Optional[str]] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # MLB player id
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    bat_side: Mapped[Optional[str]] = mapped_column(String(1))
    throw_hand: Mapped[Optional[str]] = mapped_column(String(1))
    primary_position: Mapped[Optional[str]] = mapped_column(String(8))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Pitcher(Base):
    __tablename__ = "pitchers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # MLB player id
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    throws: Mapped[Optional[str]] = mapped_column(String(1))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Roster(Base):
    __tablename__ = "rosters"
    __table_args__ = (UniqueConstraint("team_id", "player_id", "season", name="uq_roster_team_player_season"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[Optional[str]] = mapped_column(String(8))
    jersey_number: Mapped[Optional[str]] = mapped_column(String(8))
    status: Mapped[Optional[str]] = mapped_column(String(32))
    is_pitcher: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Game(Base):
    __tablename__ = "games"

    game_pk: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    game_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="Scheduled")
    abstract_state: Mapped[Optional[str]] = mapped_column(String(32))
    home_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    home_team_name: Mapped[Optional[str]] = mapped_column(String(128))
    away_team_name: Mapped[Optional[str]] = mapped_column(String(128))
    home_score: Mapped[Optional[int]] = mapped_column(Integer)
    away_score: Mapped[Optional[int]] = mapped_column(Integer)
    inning: Mapped[Optional[int]] = mapped_column(Integer)
    inning_half: Mapped[Optional[str]] = mapped_column(String(8))
    venue: Mapped[Optional[str]] = mapped_column(String(128))
    data_label: Mapped[str] = mapped_column(String(64), default="mlb_stats_api")
    worker_active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_polled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    pitches: Mapped[list["Pitch"]] = relationship(back_populates="game")
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="game")


class PlateAppearance(Base):
    __tablename__ = "plate_appearances"
    __table_args__ = (UniqueConstraint("game_pk", "at_bat_index", name="uq_pa_game_ab"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_pk: Mapped[int] = mapped_column(ForeignKey("games.game_pk"), nullable=False, index=True)
    at_bat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    pitcher_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    batter_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    pitcher_name: Mapped[Optional[str]] = mapped_column(String(128))
    batter_name: Mapped[Optional[str]] = mapped_column(String(128))
    inning: Mapped[Optional[int]] = mapped_column(Integer)
    inning_half: Mapped[Optional[str]] = mapped_column(String(8))
    result: Mapped[Optional[str]] = mapped_column(String(64))


class Pitch(Base):
    __tablename__ = "pitches"
    __table_args__ = (
        UniqueConstraint("game_pk", "at_bat_index", "pitch_number", name="uq_pitch_idempotent"),
        Index("ix_pitches_game_created", "game_pk", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_pk: Mapped[int] = mapped_column(ForeignKey("games.game_pk"), nullable=False, index=True)
    at_bat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    pitch_number: Mapped[int] = mapped_column(Integer, nullable=False)  # within PA
    pitch_number_in_game: Mapped[Optional[int]] = mapped_column(Integer)
    pitcher_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    batter_id: Mapped[Optional[int]] = mapped_column(Integer)
    pitcher_name: Mapped[Optional[str]] = mapped_column(String(128))
    batter_name: Mapped[Optional[str]] = mapped_column(String(128))
    pitch_type: Mapped[str] = mapped_column(String(8), nullable=False)
    pitch_name: Mapped[Optional[str]] = mapped_column(String(64))
    balls: Mapped[int] = mapped_column(Integer, default=0)
    strikes: Mapped[int] = mapped_column(Integer, default=0)
    outs: Mapped[int] = mapped_column(Integer, default=0)
    inning: Mapped[int] = mapped_column(Integer, default=1)
    inning_half: Mapped[Optional[str]] = mapped_column(String(8))
    stand: Mapped[Optional[str]] = mapped_column(String(1))
    p_throws: Mapped[Optional[str]] = mapped_column(String(1))
    on_1b: Mapped[bool] = mapped_column(Boolean, default=False)
    on_2b: Mapped[bool] = mapped_column(Boolean, default=False)
    on_3b: Mapped[bool] = mapped_column(Boolean, default=False)
    home_score: Mapped[Optional[int]] = mapped_column(Integer)
    away_score: Mapped[Optional[int]] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(Text)
    release_speed: Mapped[Optional[float]] = mapped_column(Float)
    release_spin_rate: Mapped[Optional[float]] = mapped_column(Float)
    plate_x: Mapped[Optional[float]] = mapped_column(Float)
    plate_z: Mapped[Optional[float]] = mapped_column(Float)
    raw_event: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    game: Mapped["Game"] = relationship(back_populates="pitches")


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Prediction(Base):
    """Next-pitch prediction stored BEFORE the actual pitch is known."""

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "game_pk",
            "at_bat_index",
            "pitch_number",
            "model_version",
            name="uq_prediction_target",
        ),
        Index("ix_predictions_timing", "game_pk", "prediction_created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_pk: Mapped[int] = mapped_column(ForeignKey("games.game_pk"), nullable=False, index=True)
    at_bat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    pitch_number: Mapped[int] = mapped_column(Integer, nullable=False)  # next pitch # in PA
    pitcher_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    batter_id: Mapped[Optional[int]] = mapped_column(Integer)
    situation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    probabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    top1_pitch_type: Mapped[str] = mapped_column(String(8), nullable=False)
    top2_pitch_type: Mapped[Optional[str]] = mapped_column(String(8))
    top3_pitch_type: Mapped[Optional[str]] = mapped_column(String(8))
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, default="baseline_v1")
    data_label: Mapped[str] = mapped_column(String(64), default="live_mlb_stats_api")
    # Timing proof: created before actual is known
    prediction_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actual_pitch_type: Mapped[Optional[str]] = mapped_column(String(8))
    actual_pitch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pitches.id"))
    top1_correct: Mapped[Optional[bool]] = mapped_column(Boolean)
    top2_correct: Mapped[Optional[bool]] = mapped_column(Boolean)
    top3_correct: Mapped[Optional[bool]] = mapped_column(Boolean)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    explanation: Mapped[Optional[str]] = mapped_column(Text)

    game: Mapped["Game"] = relationship(back_populates="predictions")


class PitcherProfile(Base):
    __tablename__ = "pitcher_profiles"

    pitcher_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pitcher_name: Mapped[str] = mapped_column(String(128), nullable=False)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    arsenal: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    sample_pitches: Mapped[int] = mapped_column(Integer, default=0)
    data_label: Mapped[Optional[str]] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
