"""Discover and persist today's MLB schedule."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Game, Team
from app.mlb.live_provider import MLBLiveGameProvider

logger = logging.getLogger(__name__)


class ScheduleService:
    def __init__(self, provider: Optional[MLBLiveGameProvider] = None) -> None:
        self.provider = provider or MLBLiveGameProvider()

    def sync_day(self, session: Session, day: Optional[date] = None) -> list[dict[str, Any]]:
        day = day or datetime.now(timezone.utc).date()
        games = self.provider.get_todays_games(day)
        out: list[dict[str, Any]] = []
        for g in games:
            self._upsert_teams(session, g)
        session.flush()  # ensure teams exist before game FKs
        for g in games:
            row = self._upsert_game(session, g)
            out.append(self.game_to_card(row, g))
        session.flush()
        return out

    def list_day(self, session: Session, day: Optional[date] = None) -> list[dict[str, Any]]:
        day = day or datetime.now(timezone.utc).date()
        rows = session.scalars(select(Game).where(Game.game_date == day).order_by(Game.game_pk)).all()
        if not rows:
            return self.sync_day(session, day)
        return [self.game_to_card(r) for r in rows]

    def get_game(self, session: Session, game_pk: int) -> Optional[Game]:
        return session.get(Game, game_pk)

    def upsert_from_live_state(self, session: Session, state: Any) -> Game:
        self._upsert_teams(
            session,
            {
                "home_team_id": state.home_team_id,
                "home_team_name": state.home_team_name,
                "away_team_id": state.away_team_id,
                "away_team_name": state.away_team_name,
            },
        )
        session.flush()
        game = session.get(Game, state.game_pk)
        if game is None:
            game = Game(
                game_pk=state.game_pk,
                game_date=date.fromisoformat(state.game_date),
                status=state.status,
            )
            session.add(game)
        game.status = state.status
        game.abstract_state = state.abstract_state
        game.home_team_id = state.home_team_id
        game.away_team_id = state.away_team_id
        game.home_team_name = state.home_team_name
        game.away_team_name = state.away_team_name
        game.home_score = state.home_score
        game.away_score = state.away_score
        game.inning = state.inning
        game.inning_half = state.inning_half
        game.venue = state.venue
        game.data_label = getattr(state, "data_label", "live_mlb_stats_api")
        game.last_polled_at = datetime.now(timezone.utc)
        session.flush()
        return game

    def _upsert_teams(self, session: Session, g: dict[str, Any]) -> None:
        for tid, name in (
            (g.get("home_team_id"), g.get("home_team_name")),
            (g.get("away_team_id"), g.get("away_team_name")),
        ):
            if not tid:
                continue
            team = session.get(Team, tid)
            if team is None:
                session.add(Team(id=int(tid), name=name or f"Team {tid}"))
            elif name:
                team.name = name

    def _upsert_game(self, session: Session, g: dict[str, Any]) -> Game:
        game = session.get(Game, int(g["game_pk"]))
        if game is None:
            game = Game(
                game_pk=int(g["game_pk"]),
                game_date=date.fromisoformat(str(g["game_date"])[:10]),
                status=g.get("status") or "Scheduled",
            )
            session.add(game)
        game.status = g.get("status") or game.status
        game.abstract_state = g.get("abstract_state")
        game.home_team_id = g.get("home_team_id")
        game.away_team_id = g.get("away_team_id")
        game.home_team_name = g.get("home_team_name")
        game.away_team_name = g.get("away_team_name")
        game.home_score = g.get("home_score")
        game.away_score = g.get("away_score")
        game.inning = g.get("inning")
        game.inning_half = g.get("inning_half")
        game.venue = g.get("venue")
        game.data_label = g.get("data_label") or "mlb_schedule"
        return game

    @staticmethod
    def game_to_card(game: Game, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        abstract = (game.abstract_state or "").lower()
        status = game.status or ""
        if abstract == "live" or status.lower() in {"in progress", "manager challenge", "review"}:
            bucket = "Live"
        elif abstract == "final" or status.lower().startswith("final"):
            bucket = "Final"
        else:
            bucket = "Scheduled"
        card = {
            "game_pk": game.game_pk,
            "game_date": game.game_date.isoformat() if game.game_date else None,
            "status": game.status,
            "abstract_state": game.abstract_state,
            "bucket": bucket,
            "home_team_id": game.home_team_id,
            "away_team_id": game.away_team_id,
            "home_team_name": game.home_team_name,
            "away_team_name": game.away_team_name,
            "home_score": game.home_score,
            "away_score": game.away_score,
            "inning": game.inning,
            "inning_half": game.inning_half,
            "venue": game.venue,
            "worker_active": game.worker_active,
            "data_label": game.data_label,
        }
        if extra:
            card["away_probable"] = extra.get("away_probable")
            card["home_probable"] = extra.get("home_probable")
            card["away_probable_id"] = extra.get("away_probable_id")
            card["home_probable_id"] = extra.get("home_probable_id")
        return card
