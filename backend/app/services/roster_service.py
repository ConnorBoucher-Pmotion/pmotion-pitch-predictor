"""MLB roster pitcher directory."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Pitcher, PitcherProfile, Player, Roster, Team
from app.mlb.live_provider import MLBLiveGameProvider

logger = logging.getLogger(__name__)


class RosterService:
    def __init__(self, provider: Optional[MLBLiveGameProvider] = None) -> None:
        self.provider = provider or MLBLiveGameProvider()

    def sync_all_pitchers(self, session: Session, *, season: Optional[int] = None) -> dict[str, Any]:
        season = season or datetime.now(timezone.utc).year
        teams = self.provider.list_mlb_teams(season=season)
        pitcher_count = 0
        for t in teams:
            tid = t.get("id")
            if not tid:
                continue
            team = session.get(Team, tid)
            if team is None:
                session.add(
                    Team(
                        id=int(tid),
                        name=t.get("name") or f"Team {tid}",
                        abbreviation=t.get("abbreviation"),
                        league=t.get("league"),
                        division=t.get("division"),
                    )
                )
            else:
                team.name = t.get("name") or team.name
                team.abbreviation = t.get("abbreviation") or team.abbreviation
            try:
                roster = self.provider.get_team_roster(int(tid))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Roster fetch failed team=%s: %s", tid, exc)
                continue

            # Pass 1: players only (FK parents) — merge is idempotent across teams
            for row in roster:
                pid = row.get("player_id")
                if not pid:
                    continue
                session.merge(
                    Player(
                        id=int(pid),
                        full_name=row.get("full_name") or f"Player {pid}",
                        primary_position=row.get("position"),
                    )
                )
            session.flush()

            # Pass 2: roster + pitcher rows
            for row in roster:
                pid = row.get("player_id")
                if not pid:
                    continue
                pid_i = int(pid)
                existing = session.scalar(
                    select(Roster).where(
                        Roster.team_id == int(tid),
                        Roster.player_id == pid_i,
                        Roster.season == season,
                    )
                )
                if existing is None:
                    existing = Roster(
                        team_id=int(tid),
                        player_id=pid_i,
                        season=season,
                    )
                    session.add(existing)
                existing.position = row.get("position")
                existing.jersey_number = row.get("jersey_number")
                existing.status = row.get("status")
                existing.is_pitcher = bool(row.get("is_pitcher"))

                if row.get("is_pitcher"):
                    pitcher_count += 1
                    session.merge(Pitcher(id=pid_i, player_id=pid_i, team_id=int(tid)))
                    session.merge(
                        PitcherProfile(
                            pitcher_id=pid_i,
                            pitcher_name=row.get("full_name") or f"Pitcher {pid}",
                            team_id=int(tid),
                            data_label="mlb_roster",
                        )
                    )
            session.flush()
        session.flush()
        return {"teams": len(teams), "pitchers_seen": pitcher_count, "season": season, "data_label": "mlb_roster"}

    def list_pitchers(
        self,
        session: Session,
        *,
        team_id: Optional[int] = None,
        q: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(Roster, Player, Team)
            .join(Player, Player.id == Roster.player_id)
            .join(Team, Team.id == Roster.team_id)
            .where(Roster.is_pitcher.is_(True))
            .order_by(Team.name, Player.full_name)
            .limit(limit)
        )
        if team_id is not None:
            stmt = stmt.where(Roster.team_id == team_id)
        rows = session.execute(stmt).all()
        out: list[dict[str, Any]] = []
        for roster, player, team in rows:
            if q and q.lower() not in (player.full_name or "").lower():
                continue
            out.append(
                {
                    "player_id": player.id,
                    "full_name": player.full_name,
                    "team_id": team.id,
                    "team_name": team.name,
                    "team_abbreviation": team.abbreviation,
                    "position": roster.position,
                    "jersey_number": roster.jersey_number,
                    "status": roster.status,
                    "data_label": "mlb_roster",
                }
            )
        return out
