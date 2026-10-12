"""MLB Stats API provider — schedule + live GUMBO. No silent fake data."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx

from app.providers.statcast import PITCH_NAME_MAP

logger = logging.getLogger(__name__)

MLB_LIVE_FEED = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
MLB_TEAMS = "https://statsapi.mlb.com/api/v1/teams"
MLB_ROSTER = "https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"


@dataclass
class ParsedPitch:
    """One pitch from GUMBO with idempotent key fields."""

    game_pk: int
    at_bat_index: int
    pitch_number: int  # within PA
    pitch_number_in_game: int
    pitcher_id: int
    batter_id: int
    pitcher_name: str
    batter_name: str
    pitch_type: str
    pitch_name: str
    balls: int
    strikes: int
    outs: int
    inning: int
    inning_half: str
    stand: str
    p_throws: str
    on_1b: bool
    on_2b: bool
    on_3b: bool
    home_score: int
    away_score: int
    description: Optional[str] = None
    release_speed: Optional[float] = None
    release_spin_rate: Optional[float] = None
    plate_x: Optional[float] = None
    plate_z: Optional[float] = None
    previous_pitch_type: Optional[str] = None
    previous_two_pitch_types: list[str] = field(default_factory=list)
    times_through_order: int = 1
    pitcher_pitch_count: int = 0

    @property
    def idempotent_key(self) -> tuple[int, int, int]:
        return (self.game_pk, self.at_bat_index, self.pitch_number)


@dataclass
class LiveGameState:
    game_pk: int
    status: str
    abstract_state: str
    home_team_id: Optional[int]
    away_team_id: Optional[int]
    home_team_name: str
    away_team_name: str
    home_score: int
    away_score: int
    inning: Optional[int]
    inning_half: Optional[str]
    outs: int
    balls: int
    strikes: int
    pitcher_id: Optional[int]
    pitcher_name: Optional[str]
    batter_id: Optional[int]
    batter_name: Optional[str]
    on_1b: bool
    on_2b: bool
    on_3b: bool
    pitches: list[ParsedPitch]
    current_matchup: Optional[dict[str, Any]]
    venue: Optional[str]
    game_date: str
    data_label: str = "live_mlb_stats_api"
    raw_status: Optional[dict[str, Any]] = None


class MLBLiveGameProvider:
    """Canonical MLB feed access for the live platform."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, follow_redirects=True)

    def get_todays_games(self, day: Optional[date] = None, *, sport_id: int = 1) -> list[dict[str, Any]]:
        day = day or datetime.now(timezone.utc).date()
        return self.get_schedule(day, sport_id=sport_id)

    def get_schedule(self, day: date, *, sport_id: int = 1, team_id: Optional[int] = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "sportId": sport_id,
            "date": day.isoformat(),
            "hydrate": "team,linescore,probablePitcher",
        }
        if team_id is not None:
            params["teamId"] = team_id
        with self._client() as client:
            resp = client.get(MLB_SCHEDULE, params=params)
            resp.raise_for_status()
            data = resp.json()
        games: list[dict[str, Any]] = []
        for d in data.get("dates") or []:
            for g in d.get("games") or []:
                games.append(self._normalize_schedule_game(g, d.get("date") or day.isoformat()))
        return games

    def _normalize_schedule_game(self, g: dict[str, Any], game_date: str) -> dict[str, Any]:
        status = g.get("status") or {}
        teams = g.get("teams") or {}
        away = teams.get("away") or {}
        home = teams.get("home") or {}
        linescore = g.get("linescore") or {}
        return {
            "game_pk": int(g["gamePk"]),
            "game_date": game_date,
            "status": status.get("detailedState") or status.get("abstractGameState") or "Unknown",
            "abstract_state": status.get("abstractGameState"),
            "coded_state": status.get("codedGameState"),
            "away_team_id": (away.get("team") or {}).get("id"),
            "home_team_id": (home.get("team") or {}).get("id"),
            "away_team_name": (away.get("team") or {}).get("name"),
            "home_team_name": (home.get("team") or {}).get("name"),
            "away_score": away.get("score"),
            "home_score": home.get("score"),
            "away_probable": ((away.get("probablePitcher") or {}).get("fullName")),
            "home_probable": ((home.get("probablePitcher") or {}).get("fullName")),
            "away_probable_id": ((away.get("probablePitcher") or {}).get("id")),
            "home_probable_id": ((home.get("probablePitcher") or {}).get("id")),
            "inning": linescore.get("currentInning"),
            "inning_half": linescore.get("inningHalf") or linescore.get("inningState"),
            "venue": (g.get("venue") or {}).get("name"),
            "game_type": g.get("gameType"),
            "data_label": "mlb_schedule",
        }

    def get_game(self, game_pk: int) -> dict[str, Any]:
        state = self.get_live_game_state(game_pk)
        return {
            "game_pk": state.game_pk,
            "status": state.status,
            "abstract_state": state.abstract_state,
            "home_team_id": state.home_team_id,
            "away_team_id": state.away_team_id,
            "home_team_name": state.home_team_name,
            "away_team_name": state.away_team_name,
            "home_score": state.home_score,
            "away_score": state.away_score,
            "inning": state.inning,
            "inning_half": state.inning_half,
            "venue": state.venue,
            "game_date": state.game_date,
            "data_label": state.data_label,
        }

    def get_live_feed(self, game_pk: int) -> dict[str, Any]:
        url = MLB_LIVE_FEED.format(game_pk=game_pk)
        with self._client() as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()

    def get_live_game_state(self, game_pk: int) -> LiveGameState:
        payload = self.get_live_feed(game_pk)
        return self.parse_live_state(payload, game_pk)

    def get_game_plays(self, game_pk: int) -> list[ParsedPitch]:
        return self.get_live_game_state(game_pk).pitches

    def get_current_matchup(self, game_pk: int) -> Optional[dict[str, Any]]:
        return self.get_live_game_state(game_pk).current_matchup

    def get_latest_pitch(self, game_pk: int) -> Optional[ParsedPitch]:
        pitches = self.get_game_plays(game_pk)
        return pitches[-1] if pitches else None

    def parse_live_state(self, payload: dict[str, Any], game_pk: int) -> LiveGameState:
        game_data = payload.get("gameData") or {}
        live = payload.get("liveData") or {}
        status_obj = game_data.get("status") or {}
        status = status_obj.get("detailedState") or status_obj.get("abstractGameState") or "Unknown"
        abstract = status_obj.get("abstractGameState") or "Unknown"
        teams = game_data.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        linescore = live.get("linescore") or {}
        offense = linescore.get("offense") or {}
        defense = linescore.get("defense") or {}
        count = linescore.get("balls"), linescore.get("strikes"), linescore.get("outs")
        players = game_data.get("players") or {}

        pitcher = defense.get("pitcher") or {}
        batter = offense.get("batter") or {}

        pitches = self._extract_all_pitches(payload, game_pk)

        current_play = (live.get("plays") or {}).get("currentPlay") or {}
        matchup = current_play.get("matchup") or {}
        current_matchup = None
        if matchup:
            current_matchup = {
                "pitcher_id": (matchup.get("pitcher") or {}).get("id"),
                "pitcher_name": (matchup.get("pitcher") or {}).get("fullName"),
                "batter_id": (matchup.get("batter") or {}).get("id"),
                "batter_name": (matchup.get("batter") or {}).get("fullName"),
                "stand": ((matchup.get("batSide") or {}).get("code") or "R")[:1].upper(),
                "p_throws": ((matchup.get("pitchHand") or {}).get("code") or "R")[:1].upper(),
                "at_bat_index": (current_play.get("about") or {}).get("atBatIndex"),
                "pitch_number_next": len(
                    [e for e in (current_play.get("playEvents") or []) if e.get("isPitch")]
                )
                + 1,
            }

        game_date = (
            (game_data.get("datetime") or {}).get("officialDate")
            or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )

        return LiveGameState(
            game_pk=game_pk,
            status=status,
            abstract_state=abstract,
            home_team_id=home.get("id"),
            away_team_id=away.get("id"),
            home_team_name=home.get("name") or "Home",
            away_team_name=away.get("name") or "Away",
            home_score=int((linescore.get("teams") or {}).get("home", {}).get("runs") or 0),
            away_score=int((linescore.get("teams") or {}).get("away", {}).get("runs") or 0),
            inning=linescore.get("currentInning"),
            inning_half=linescore.get("inningHalf") or linescore.get("inningState"),
            outs=int(count[2] or 0),
            balls=int(count[0] or 0),
            strikes=int(count[1] or 0),
            pitcher_id=pitcher.get("id") or (current_matchup or {}).get("pitcher_id"),
            pitcher_name=pitcher.get("fullName")
            or self._player_name(players, pitcher.get("id"))
            or (current_matchup or {}).get("pitcher_name"),
            batter_id=batter.get("id") or (current_matchup or {}).get("batter_id"),
            batter_name=batter.get("fullName")
            or self._player_name(players, batter.get("id"))
            or (current_matchup or {}).get("batter_name"),
            on_1b=bool(offense.get("first")),
            on_2b=bool(offense.get("second")),
            on_3b=bool(offense.get("third")),
            pitches=pitches,
            current_matchup=current_matchup,
            venue=(game_data.get("venue") or {}).get("name"),
            game_date=str(game_date)[:10],
            data_label="live_mlb_stats_api",
            raw_status=status_obj,
        )

    def _extract_all_pitches(self, payload: dict[str, Any], game_pk: int) -> list[ParsedPitch]:
        players = (payload.get("gameData") or {}).get("players") or {}
        linescore = (payload.get("liveData") or {}).get("linescore") or {}
        records: list[ParsedPitch] = []
        pitch_in_game = 0
        batter_tto: dict[int, int] = {}
        last_ab_for_batter: dict[int, int] = {}
        pitcher_counts: dict[int, int] = {}

        for play in (payload.get("liveData") or {}).get("plays", {}).get("allPlays") or []:
            matchup = play.get("matchup") or {}
            pitcher = matchup.get("pitcher") or {}
            batter = matchup.get("batter") or {}
            pitcher_id = int(pitcher.get("id") or 0)
            batter_id = int(batter.get("id") or 0)
            if not pitcher_id:
                continue
            pitcher_name = pitcher.get("fullName") or self._player_name(players, pitcher_id) or f"Pitcher {pitcher_id}"
            batter_name = batter.get("fullName") or self._player_name(players, batter_id) or f"Batter {batter_id}"
            stand = ((matchup.get("batSide") or {}).get("code") or "R")[:1].upper()
            p_throws = ((matchup.get("pitchHand") or {}).get("code") or "R")[:1].upper()
            if stand not in ("L", "R"):
                stand = "R"
            if p_throws not in ("L", "R"):
                p_throws = "R"

            about = play.get("about") or {}
            ab_index = int(about.get("atBatIndex") or 0)
            inning = int(about.get("inning") or 1)
            half = about.get("halfInning") or "top"
            topbot = "Top" if str(half).lower().startswith("top") else "Bot"
            outs = int((play.get("count") or {}).get("outs") or about.get("outs") or 0)

            if last_ab_for_batter.get(batter_id) != ab_index:
                if batter_id in last_ab_for_batter:
                    batter_tto[batter_id] = batter_tto.get(batter_id, 1) + 1
                else:
                    batter_tto[batter_id] = 1
                last_ab_for_batter[batter_id] = ab_index
            tto = batter_tto.get(batter_id, 1)

            prev_types: list[str] = []
            pitch_in_pa = 0
            for event in play.get("playEvents") or []:
                if not event.get("isPitch"):
                    continue
                details = event.get("details") or {}
                ptype = ((details.get("type") or {}).get("code") or "").upper()
                if not ptype:
                    continue
                count = event.get("count") or {}
                balls = int(count.get("balls") or 0)
                strikes = int(count.get("strikes") or 0)
                pre_balls, pre_strikes = self._pre_pitch_count(details, balls, strikes)

                offense = linescore.get("offense") or {}
                on1 = bool(offense.get("first"))
                on2 = bool(offense.get("second"))
                on3 = bool(offense.get("third"))

                pitch_in_pa += 1
                pitch_in_game += 1
                prior_count = pitcher_counts.get(pitcher_id, 0)
                pitch_name = (details.get("type") or {}).get("description") or PITCH_NAME_MAP.get(ptype, ptype)
                desc = details.get("description") or (details.get("call") or {}).get("description")
                pitch_data = event.get("pitchData") or {}

                records.append(
                    ParsedPitch(
                        game_pk=game_pk,
                        at_bat_index=ab_index,
                        pitch_number=pitch_in_pa,
                        pitch_number_in_game=pitch_in_game,
                        pitcher_id=pitcher_id,
                        batter_id=batter_id,
                        pitcher_name=pitcher_name,
                        batter_name=batter_name,
                        pitch_type=ptype,
                        pitch_name=str(pitch_name),
                        balls=min(max(pre_balls, 0), 3),
                        strikes=min(max(pre_strikes, 0), 2),
                        outs=min(max(outs, 0), 2),
                        inning=max(inning, 1),
                        inning_half=topbot,
                        stand=stand,
                        p_throws=p_throws,
                        on_1b=on1,
                        on_2b=on2,
                        on_3b=on3,
                        home_score=int((linescore.get("teams") or {}).get("home", {}).get("runs") or 0),
                        away_score=int((linescore.get("teams") or {}).get("away", {}).get("runs") or 0),
                        description=desc,
                        release_speed=pitch_data.get("startSpeed"),
                        release_spin_rate=(pitch_data.get("breaks") or {}).get("spinRate"),
                        plate_x=(pitch_data.get("coordinates") or {}).get("pX"),
                        plate_z=(pitch_data.get("coordinates") or {}).get("pZ"),
                        previous_pitch_type=prev_types[-1] if prev_types else None,
                        previous_two_pitch_types=list(prev_types[-2:]),
                        times_through_order=tto,
                        pitcher_pitch_count=prior_count,
                    )
                )
                prev_types.append(ptype)
                pitcher_counts[pitcher_id] = prior_count + 1
        return records

    @staticmethod
    def _pre_pitch_count(details: dict[str, Any], balls: int, strikes: int) -> tuple[int, int]:
        call = ((details.get("call") or {}).get("code") or "").upper()
        is_ball = call in {"B", "*B"} or "ball" in str(details.get("description") or "").lower()
        is_strike = call in {"C", "S", "F", "T", "W"} or any(
            k in str(details.get("description") or "").lower()
            for k in ("strike", "foul", "swinging", "missed")
        )
        pre_b, pre_s = balls, strikes
        if is_ball and balls > 0:
            pre_b = balls - 1
        elif is_strike and strikes > 0 and call != "F":
            pre_s = strikes - 1
        return pre_b, pre_s

    @staticmethod
    def _player_name(players: dict[str, Any], player_id: Optional[int]) -> Optional[str]:
        if not player_id:
            return None
        p = players.get(f"ID{player_id}") or {}
        return p.get("fullName") or p.get("boxscoreName")

    def list_mlb_teams(self, *, sport_id: int = 1, season: Optional[int] = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"sportId": sport_id}
        if season:
            params["season"] = season
        with self._client() as client:
            resp = client.get(MLB_TEAMS, params=params)
            resp.raise_for_status()
            data = resp.json()
        out = []
        for t in data.get("teams") or []:
            out.append(
                {
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "abbreviation": t.get("abbreviation"),
                    "league": (t.get("league") or {}).get("name"),
                    "division": (t.get("division") or {}).get("name"),
                }
            )
        return out

    def get_team_roster(self, team_id: int, *, roster_type: str = "active") -> list[dict[str, Any]]:
        url = MLB_ROSTER.format(team_id=team_id)
        with self._client() as client:
            resp = client.get(url, params={"rosterType": roster_type})
            resp.raise_for_status()
            data = resp.json()
        out = []
        for row in data.get("roster") or []:
            person = row.get("person") or {}
            pos = (row.get("position") or {}).get("abbreviation") or ""
            out.append(
                {
                    "player_id": person.get("id"),
                    "full_name": person.get("fullName"),
                    "jersey_number": row.get("jerseyNumber"),
                    "position": pos,
                    "status": (row.get("status") or {}).get("description"),
                    "is_pitcher": pos in {"P", "SP", "RP", "CP", "TWP"} or str(pos).startswith("P"),
                }
            )
        return out
