"""Real MLB Stats API / GUMBO live game provider with polling + state-change detection."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx

from app.providers.base import LiveGameProvider
from app.providers.statcast import PITCH_NAME_MAP
from app.schema.pitch import PitchRecord

logger = logging.getLogger(__name__)

MLB_LIVE_FEED = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"


@dataclass
class LiveSnapshot:
    """Point-in-time live feed summary for change detection."""

    pitch_index: int
    last_play_id: str
    status: str
    hash_key: str


@dataclass
class MlbLiveSession:
    game_pk: int
    pitcher_id: int
    pitches: list[PitchRecord] = field(default_factory=list)
    index: int = 0
    last_snapshot: Optional[LiveSnapshot] = None
    polling: bool = False
    poll_error: Optional[str] = None
    data_label: str = "live_mlb_stats_api"


class MlbLiveGameProvider(LiveGameProvider):
    """Polls MLB live feed; advances when new pitches appear for the tracked pitcher."""

    def __init__(
        self,
        *,
        poll_interval_sec: float = 5.0,
        on_change: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self.poll_interval_sec = poll_interval_sec
        self.on_change = on_change
        self._session: Optional[MlbLiveSession] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start_game(self, game_pk: int, pitcher_id: int) -> None:
        self.stop_polling()
        with self._lock:
            self._session = MlbLiveSession(game_pk=game_pk, pitcher_id=pitcher_id)
        self._refresh_from_api(force=True)
        self.start_polling()

    def start_polling(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        if self._session:
            self._session.polling = True
        self._thread = threading.Thread(target=self._poll_loop, name="mlb-live-poll", daemon=True)
        self._thread.start()
        logger.info("MLB live polling started game_pk=%s", self._session.game_pk if self._session else None)

    def stop_polling(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        if self._session:
            self._session.polling = False

    def _poll_loop(self) -> None:
        while not self._stop.wait(self.poll_interval_sec):
            try:
                changed = self._refresh_from_api(force=False)
                if changed and self.on_change and self._session:
                    self.on_change(self.status_dict())
            except Exception as exc:  # noqa: BLE001
                logger.exception("Live poll failed: %s", exc)
                if self._session:
                    self._session.poll_error = str(exc)

    def _refresh_from_api(self, *, force: bool) -> bool:
        session = self._require()
        url = MLB_LIVE_FEED.format(game_pk=session.game_pk)
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            payload = resp.json()

        pitches = self._extract_pitches(payload, session.pitcher_id, session.game_pk)
        status = (
            payload.get("gameData", {}).get("status", {}).get("detailedState")
            or payload.get("gameData", {}).get("status", {}).get("abstractGameState")
            or "Unknown"
        )
        last_play_id = ""
        all_plays = payload.get("liveData", {}).get("plays", {}).get("allPlays") or []
        if all_plays:
            last_play_id = str(all_plays[-1].get("about", {}).get("atBatIndex", len(all_plays)))
        snap = LiveSnapshot(
            pitch_index=len(pitches),
            last_play_id=last_play_id,
            status=status,
            hash_key=f"{len(pitches)}:{last_play_id}:{status}",
        )
        changed = force or (session.last_snapshot is None) or (session.last_snapshot.hash_key != snap.hash_key)
        with self._lock:
            session.pitches = pitches
            session.last_snapshot = snap
            session.poll_error = None
            # Keep index at latest pitch for live (predict next = current end)
            if session.index > len(pitches):
                session.index = len(pitches)
        if changed:
            logger.info(
                "Live state change game_pk=%s pitches=%d status=%s",
                session.game_pk,
                len(pitches),
                status,
            )
        return changed

    def _extract_pitches(self, payload: dict[str, Any], pitcher_id: int, game_pk: int) -> list[PitchRecord]:
        game_date = (
            (payload.get("gameData", {}).get("datetime", {}) or {}).get("officialDate")
            or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )
        players = payload.get("gameData", {}).get("players") or {}
        pitcher_name = self._player_name(players, pitcher_id) or f"Pitcher {pitcher_id}"

        records: list[PitchRecord] = []
        pitch_num = 0
        batter_tto: dict[int, int] = {}
        last_ab_for_batter: dict[int, int] = {}

        for play in payload.get("liveData", {}).get("plays", {}).get("allPlays") or []:
            matchup = play.get("matchup") or {}
            play_pitcher = (matchup.get("pitcher") or {}).get("id")
            if play_pitcher != pitcher_id:
                continue
            batter = matchup.get("batter") or {}
            batter_id = int(batter.get("id") or 0)
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
            prev_result: Optional[str] = None
            for event in play.get("playEvents") or []:
                if not event.get("isPitch"):
                    continue
                details = event.get("details") or {}
                ptype = ((details.get("type") or {}).get("code") or "").upper()
                if not ptype:
                    continue
                count = event.get("count") or {}
                # MLB count on the event is typically AFTER the pitch; prefer start count if present
                start = event.get("pitchData", {}).get("startSpeed")  # noqa: F841 — kept for later
                balls = int(count.get("balls") or 0)
                strikes = int(count.get("strikes") or 0)
                # Back out pre-pitch count when possible from description flags
                pre_balls, pre_strikes = self._pre_pitch_count(details, balls, strikes)

                runners = play.get("runners") or []
                on1 = on2 = on3 = False
                # Prefer current play offense state from about/linescore if available
                offense = (payload.get("liveData", {}).get("linescore", {}) or {}).get("offense") or {}
                # Per-pitch base state is imperfect in feed; use play-level matchup context when present
                for r in runners:
                    mb = (r.get("movement") or {}).get("end") or (r.get("movement") or {}).get("start")
                    if mb == "1B":
                        on1 = True
                    elif mb == "2B":
                        on2 = True
                    elif mb == "3B":
                        on3 = True
                if offense.get("first"):
                    on1 = True
                if offense.get("second"):
                    on2 = True
                if offense.get("third"):
                    on3 = True

                pitch_num += 1
                pitch_name = (details.get("type") or {}).get("description") or PITCH_NAME_MAP.get(ptype, ptype)
                desc = details.get("description") or details.get("call", {}).get("description")
                result = details.get("event") or details.get("call", {}).get("code")

                rec = PitchRecord(
                    game_pk=game_pk,
                    game_date=str(game_date)[:10],
                    pitch_number_in_game=pitch_num,
                    pitcher_id=pitcher_id,
                    pitcher_name=pitcher_name,
                    batter_id=batter_id,
                    batter_name=batter_name,
                    pitch_type=ptype,
                    pitch_name=str(pitch_name),
                    pitch_number_in_pa=len(prev_types) + 1,
                    balls=min(max(pre_balls, 0), 3),
                    strikes=min(max(pre_strikes, 0), 2),
                    outs=min(max(outs, 0), 2),
                    inning=max(inning, 1),
                    inning_topbot=topbot,  # type: ignore[arg-type]
                    stand=stand,  # type: ignore[arg-type]
                    p_throws=p_throws,  # type: ignore[arg-type]
                    home_score=int((payload.get("liveData", {}).get("linescore", {}) or {}).get("teams", {}).get("home", {}).get("runs") or 0),
                    away_score=int((payload.get("liveData", {}).get("linescore", {}) or {}).get("teams", {}).get("away", {}).get("runs") or 0),
                    score_diff=0,
                    on_1b=on1,
                    on_2b=on2,
                    on_3b=on3,
                    previous_pitch_type=prev_types[-1] if prev_types else None,
                    previous_two_pitch_types=list(prev_types[-2:]),
                    previous_pitch_result=prev_result,
                    times_through_order=tto,
                    pitcher_pitch_count=pitch_num - 1,
                    at_bat_number=ab_index,
                    description=desc,
                    events=result,
                    release_speed=(event.get("pitchData") or {}).get("startSpeed"),
                    release_spin_rate=((event.get("pitchData") or {}).get("breaks") or {}).get("spinRate"),
                    plate_x=((event.get("pitchData") or {}).get("coordinates") or {}).get("pX"),
                    plate_z=((event.get("pitchData") or {}).get("coordinates") or {}).get("pZ"),
                )
                records.append(rec)
                prev_types.append(ptype)
                prev_result = desc or result
        return records

    @staticmethod
    def _pre_pitch_count(details: dict[str, Any], balls: int, strikes: int) -> tuple[int, int]:
        """Infer count before the pitch from post-count + call when possible."""
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
        # Fouls often keep 2-strike count — leave strikes as-is when already 2
        return pre_b, pre_s

    @staticmethod
    def _player_name(players: dict[str, Any], player_id: int) -> Optional[str]:
        key = f"ID{player_id}"
        p = players.get(key) or {}
        return p.get("fullName") or p.get("boxscoreName")

    def _require(self) -> MlbLiveSession:
        if self._session is None:
            raise ValueError("No live session. Call start_game first.")
        return self._session

    def current_index(self) -> int:
        return self._require().index

    def total_pitches(self) -> int:
        return len(self._require().pitches)

    def peek_situation(self) -> Optional[PitchRecord]:
        s = self._require()
        if s.index >= len(s.pitches):
            return None
        return s.pitches[s.index]

    def reveal_actual(self) -> Optional[PitchRecord]:
        return self.peek_situation()

    def advance(self) -> Optional[PitchRecord]:
        s = self._require()
        if s.index < len(s.pitches) - 1:
            s.index += 1
            return self.peek_situation()
        s.index = len(s.pitches)
        return None

    def step_back(self) -> Optional[PitchRecord]:
        s = self._require()
        if s.index > 0:
            s.index -= 1
        return self.peek_situation()

    def reset(self) -> None:
        s = self._require()
        s.index = 0

    def data_label(self) -> str:
        if self._session is None:
            return "live_mlb_stats_api"
        return self._session.data_label

    def status_dict(self) -> dict[str, Any]:
        s = self._require()
        return {
            "data_label": s.data_label,
            "game_pk": s.game_pk,
            "pitcher_id": s.pitcher_id,
            "pitch_count": len(s.pitches),
            "index": s.index,
            "polling": s.polling,
            "status": s.last_snapshot.status if s.last_snapshot else None,
            "poll_error": s.poll_error,
            "last_change": s.last_snapshot.hash_key if s.last_snapshot else None,
        }

    @staticmethod
    def find_team_games(team_id: int, date: str) -> list[dict[str, Any]]:
        """Schedule lookup helper (Dodgers team_id=119)."""
        params = {"sportId": 1, "teamId": team_id, "date": date}
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(MLB_SCHEDULE, params=params)
            resp.raise_for_status()
            data = resp.json()
        games: list[dict[str, Any]] = []
        for d in data.get("dates") or []:
            for g in d.get("games") or []:
                games.append(
                    {
                        "game_pk": g.get("gamePk"),
                        "game_date": d.get("date"),
                        "status": (g.get("status") or {}).get("detailedState"),
                        "away": (g.get("teams") or {}).get("away", {}).get("team", {}).get("name"),
                        "home": (g.get("teams") or {}).get("home", {}).get("team", {}).get("name"),
                    }
                )
        return games
