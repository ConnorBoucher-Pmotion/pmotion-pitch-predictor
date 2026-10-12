"""Idempotent pitch persistence: game_pk + at_bat_index + pitch_number."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Pitch, PlateAppearance, Player
from app.mlb.live_provider import ParsedPitch

logger = logging.getLogger(__name__)


class PitchEventService:
    def upsert_pitch(self, session: Session, parsed: ParsedPitch) -> tuple[Pitch, bool]:
        """Insert pitch if new. Returns (row, created)."""
        existing = session.scalar(
            select(Pitch).where(
                Pitch.game_pk == parsed.game_pk,
                Pitch.at_bat_index == parsed.at_bat_index,
                Pitch.pitch_number == parsed.pitch_number,
            )
        )
        if existing:
            return existing, False

        self._ensure_pa(session, parsed)
        self._ensure_player(session, parsed.pitcher_id, parsed.pitcher_name)
        self._ensure_player(session, parsed.batter_id, parsed.batter_name)

        row = Pitch(
            game_pk=parsed.game_pk,
            at_bat_index=parsed.at_bat_index,
            pitch_number=parsed.pitch_number,
            pitch_number_in_game=parsed.pitch_number_in_game,
            pitcher_id=parsed.pitcher_id,
            batter_id=parsed.batter_id,
            pitcher_name=parsed.pitcher_name,
            batter_name=parsed.batter_name,
            pitch_type=parsed.pitch_type,
            pitch_name=parsed.pitch_name,
            balls=parsed.balls,
            strikes=parsed.strikes,
            outs=parsed.outs,
            inning=parsed.inning,
            inning_half=parsed.inning_half,
            stand=parsed.stand,
            p_throws=parsed.p_throws,
            on_1b=parsed.on_1b,
            on_2b=parsed.on_2b,
            on_3b=parsed.on_3b,
            home_score=parsed.home_score,
            away_score=parsed.away_score,
            description=parsed.description,
            release_speed=parsed.release_speed,
            release_spin_rate=parsed.release_spin_rate,
            plate_x=parsed.plate_x,
            plate_z=parsed.plate_z,
        )
        session.add(row)
        session.flush()
        logger.info(
            "Stored pitch game=%s ab=%s n=%s type=%s",
            parsed.game_pk,
            parsed.at_bat_index,
            parsed.pitch_number,
            parsed.pitch_type,
        )
        return row, True

    def list_pitches(self, session: Session, game_pk: int) -> list[Pitch]:
        return list(
            session.scalars(
                select(Pitch).where(Pitch.game_pk == game_pk).order_by(Pitch.pitch_number_in_game, Pitch.id)
            ).all()
        )

    def _ensure_pa(self, session: Session, parsed: ParsedPitch) -> None:
        existing = session.scalar(
            select(PlateAppearance).where(
                PlateAppearance.game_pk == parsed.game_pk,
                PlateAppearance.at_bat_index == parsed.at_bat_index,
            )
        )
        if existing:
            return
        session.add(
            PlateAppearance(
                game_pk=parsed.game_pk,
                at_bat_index=parsed.at_bat_index,
                pitcher_id=parsed.pitcher_id,
                batter_id=parsed.batter_id,
                pitcher_name=parsed.pitcher_name,
                batter_name=parsed.batter_name,
                inning=parsed.inning,
                inning_half=parsed.inning_half,
            )
        )

    def _ensure_player(self, session: Session, player_id: Optional[int], name: Optional[str]) -> None:
        if not player_id:
            return
        row = session.get(Player, player_id)
        if row is None:
            session.add(Player(id=player_id, full_name=name or f"Player {player_id}"))
        elif name and row.full_name.startswith("Player "):
            row.full_name = name
