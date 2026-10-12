"""Baseball Savant / Statcast-compatible historical provider with disk cache."""

from __future__ import annotations

import csv
import io
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

import httpx

from app.config import Settings
from app.providers.base import HistoricalPitchProvider
from app.schema.pitch import PitchRecord

logger = logging.getLogger(__name__)

PITCH_NAME_MAP = {
    "FF": "4-Seam Fastball",
    "SI": "Sinker",
    "FC": "Cutter",
    "SL": "Slider",
    "ST": "Sweeper",
    "CU": "Curveball",
    "KC": "Knuckle Curve",
    "CH": "Changeup",
    "FS": "Splitter",
    "SV": "Slurve",
    "CS": "Slow Curve",
    "FO": "Forkball",
    "EP": "Eephus",
    "KN": "Knuckleball",
    "PO": "Pitchout",
    "IN": "Intentional Ball",
    "UN": "Unknown",
}


def _truthy_runner(value: object) -> bool:
    if value is None or value == "" or value == "null":
        return False
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return bool(value)


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: object) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class StatcastHistoricalProvider(HistoricalPitchProvider):
    """Downloads Statcast CSV (or loads sample/cache) and normalizes to PitchRecord."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cache_dir = Path(settings.cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory: dict[str, list[PitchRecord]] = {}
        self._last_source: str = "unknown"

    def _cache_path(self, pitcher_id: int, start_date: str, end_date: str) -> Path:
        return self.cache_dir / f"statcast_{pitcher_id}_{start_date}_{end_date}.csv"

    def get_pitches(
        self,
        pitcher_id: int,
        start_date: str,
        end_date: str,
        *,
        force_refresh: bool = False,
    ) -> list[PitchRecord]:
        key = f"{pitcher_id}:{start_date}:{end_date}"
        if not force_refresh and key in self._memory:
            return self._memory[key]

        cache_path = self._cache_path(pitcher_id, start_date, end_date)
        sample_path = Path(self.settings.sample_data_path).resolve()
        sample_ok_for_pitcher = pitcher_id == self.settings.default_pitcher_id

        csv_text: Optional[str] = None
        source = "cache"

        if (
            self.settings.use_sample_data
            and sample_ok_for_pitcher
            and sample_path.exists()
            and not force_refresh
        ):
            logger.info("Loading explicit sample Statcast data from %s", sample_path)
            csv_text = sample_path.read_text(encoding="utf-8")
            source = "sample"
        elif cache_path.exists() and not force_refresh:
            logger.info("Loading cached Statcast data from %s", cache_path)
            csv_text = cache_path.read_text(encoding="utf-8")
            source = "cache"
        else:
            try:
                csv_text = self._download_statcast(pitcher_id, start_date, end_date)
                cache_path.write_text(csv_text, encoding="utf-8")
                source = "statcast_download"
            except Exception as exc:  # noqa: BLE001 — surface clearly to API
                if cache_path.exists():
                    logger.warning(
                        "Statcast download failed (%s); using cache for pitcher %s",
                        exc,
                        pitcher_id,
                    )
                    csv_text = cache_path.read_text(encoding="utf-8")
                    source = "cache_fallback"
                elif sample_ok_for_pitcher and sample_path.exists():
                    logger.warning(
                        "Statcast download failed (%s); explicit sample fallback for default pitcher %s",
                        exc,
                        pitcher_id,
                    )
                    csv_text = sample_path.read_text(encoding="utf-8")
                    source = "sample_fallback"
                else:
                    raise RuntimeError(
                        f"Unable to load historical pitches for pitcher {pitcher_id}: {exc}. "
                        "No cache available; sample fallback only applies to the default pitcher."
                    ) from exc

        rows = self._parse_csv(csv_text)
        pitches = self._rows_to_records(rows, pitcher_id=pitcher_id)
        if not pitches and source.startswith("statcast"):
            raise RuntimeError(
                f"Statcast download for pitcher {pitcher_id} returned {len(rows)} rows but 0 parseable pitches"
            )
        logger.info(
            "Loaded %d pitches for pitcher %s from %s",
            len(pitches),
            pitcher_id,
            source,
        )
        self._last_source = source
        self._memory[key] = pitches
        return pitches

    def list_games(self, pitcher_id: int, start_date: str, end_date: str) -> list[dict]:
        pitches = self.get_pitches(pitcher_id, start_date, end_date)
        by_game: dict[int, dict] = {}
        for p in pitches:
            if p.game_pk not in by_game:
                by_game[p.game_pk] = {
                    "game_pk": p.game_pk,
                    "game_date": p.game_date,
                    "pitcher_id": pitcher_id,
                    "pitcher_name": p.pitcher_name,
                    "pitch_count": 0,
                }
            by_game[p.game_pk]["pitch_count"] += 1
        return sorted(by_game.values(), key=lambda g: g["game_date"])

    def get_game_pitches(self, game_pk: int, pitcher_id: Optional[int] = None) -> list[PitchRecord]:
        settings = self.settings
        pid = pitcher_id or settings.default_pitcher_id
        pitches = self.get_pitches(pid, settings.default_start_date, settings.default_end_date)
        game = [p for p in pitches if p.game_pk == game_pk]
        if pitcher_id is not None:
            game = [p for p in game if p.pitcher_id == pitcher_id]
        if not game:
            raise ValueError(f"No pitches found for game_pk={game_pk} pitcher_id={pid}")
        return sorted(game, key=lambda p: p.pitch_number_in_game)

    @staticmethod
    def _parse_csv(csv_text: str) -> list[dict]:
        """Parse Statcast CSV, normalizing BOM + quoted headers."""
        text = csv_text.lstrip("\ufeff")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return []
        # Normalize headers like '"pitch_type"' → pitch_type
        fieldnames = [h.strip().strip('"').strip("'") for h in reader.fieldnames]
        rows: list[dict] = []
        for raw in reader:
            row = {}
            for key, value in raw.items():
                if key is None:
                    continue
                clean_key = key.strip().strip('"').strip("'").lstrip("\ufeff")
                row[clean_key] = value
            # Ensure all declared fields exist
            for name in fieldnames:
                row.setdefault(name, "")
            rows.append(row)
        return rows

    def _download_statcast(self, pitcher_id: int, start_date: str, end_date: str) -> str:
        params = {
            "all": "true",
            "hfGT": "R|",
            "hfSea": f"{start_date[:4]}|",
            "player_type": "pitcher",
            "game_date_gt": start_date,
            "game_date_lt": end_date,
            "pitchers_lookup[]": str(pitcher_id),
            "group_by": "name",
            "min_pitches": "0",
            "min_results": "0",
            "min_pas": "0",
            "type": "details",
        }
        logger.info("Downloading Statcast CSV for pitcher %s %s→%s", pitcher_id, start_date, end_date)
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(self.settings.statcast_base_url, params=params)
            resp.raise_for_status()
            text = resp.text
        header = text.lstrip("\ufeff").splitlines()[0] if text else ""
        if not text or "pitch_type" not in header.replace('"', ""):
            raise RuntimeError("Statcast response missing expected CSV header")
        return text

    def _rows_to_records(self, rows: list[dict], pitcher_id: int) -> list[PitchRecord]:
        # Sort chronologically within games
        def sort_key(r: dict) -> tuple:
            return (
                r.get("game_date") or "",
                _safe_int(r.get("game_pk")),
                _safe_int(r.get("at_bat_number")),
                _safe_int(r.get("pitch_number")),
            )

        rows = sorted(rows, key=sort_key)
        # Filter pitcher if column present
        filtered = []
        for r in rows:
            pid = _safe_int(r.get("pitcher"), pitcher_id)
            if pid != pitcher_id and r.get("pitcher"):
                continue
            if not r.get("pitch_type"):
                continue
            filtered.append(r)

        # Build previous-pitch / TTO / pitch count context WITHOUT using current pitch outcomes
        game_pitch_idx: dict[int, int] = defaultdict(int)
        pa_prev: dict[tuple[int, int], list[str]] = defaultdict(list)
        pa_prev_result: dict[tuple[int, int], Optional[str]] = defaultdict(lambda: None)
        batter_seen: dict[tuple[int, int], int] = defaultdict(int)
        last_ab_by_batter: dict[tuple[int, int], int] = {}

        records: list[PitchRecord] = []
        for r in filtered:
            game_pk = _safe_int(r.get("game_pk"))
            ab = _safe_int(r.get("at_bat_number"))
            batter_id = _safe_int(r.get("batter"))
            game_pitch_idx[game_pk] += 1
            pitcher_pitch_count = game_pitch_idx[game_pk]  # count BEFORE this pitch = prior + 0; use prior
            prior_count = pitcher_pitch_count - 1

            pa_key = (game_pk, ab)
            prev_types = pa_prev[pa_key]
            previous_pitch_type = prev_types[-1] if prev_types else None
            previous_two = prev_types[-2:] if prev_types else []

            batter_key = (game_pk, batter_id)
            if last_ab_by_batter.get(batter_key) != ab:
                # New PA against this batter
                if batter_key in last_ab_by_batter:
                    batter_seen[batter_key] += 1
                last_ab_by_batter[batter_key] = ab
            tto = batter_seen[batter_key] + 1

            balls = _safe_int(r.get("balls"))
            strikes = _safe_int(r.get("strikes"))
            # Statcast balls/strikes are the count BEFORE the pitch — correct for features
            home = _safe_int(r.get("home_score") or r.get("fld_score") or 0)
            away = _safe_int(r.get("away_score") or r.get("bat_score") or 0)
            # Prefer bat_score/fld_score when present (pitcher fielding)
            if r.get("fld_score") not in (None, "") and r.get("bat_score") not in (None, ""):
                fld = _safe_int(r.get("fld_score"))
                bat = _safe_int(r.get("bat_score"))
                score_diff = fld - bat
                home, away = fld, bat
            else:
                score_diff = home - away

            stand = (r.get("stand") or "R")[:1].upper()
            p_throws = (r.get("p_throws") or "R")[:1].upper()
            if stand not in ("L", "R"):
                stand = "R"
            if p_throws not in ("L", "R"):
                p_throws = "R"
            topbot = r.get("inning_topbot") or "Top"
            if topbot not in ("Top", "Bot"):
                topbot = "Top"

            pitch_type = str(r.get("pitch_type")).strip().upper()
            pitch_name = r.get("pitch_name") or PITCH_NAME_MAP.get(pitch_type, pitch_type)

            rec = PitchRecord(
                game_pk=game_pk,
                game_date=str(r.get("game_date") or "")[:10],
                pitch_number_in_game=prior_count + 1,
                pitcher_id=_safe_int(r.get("pitcher"), pitcher_id),
                pitcher_name=str(r.get("player_name") or self.settings.default_pitcher_name),
                batter_id=batter_id,
                batter_name=str(r.get("batter_name") or f"Batter {batter_id}"),
                pitch_type=pitch_type,
                pitch_name=str(pitch_name),
                pitch_number_in_pa=_safe_int(r.get("pitch_number"), len(prev_types) + 1),
                balls=min(max(balls, 0), 3),
                strikes=min(max(strikes, 0), 2),
                outs=min(max(_safe_int(r.get("outs_when_up")), 0), 2),
                inning=max(_safe_int(r.get("inning"), 1), 1),
                inning_topbot=topbot,  # type: ignore[arg-type]
                stand=stand,  # type: ignore[arg-type]
                p_throws=p_throws,  # type: ignore[arg-type]
                home_score=home,
                away_score=away,
                score_diff=score_diff,
                on_1b=_truthy_runner(r.get("on_1b")),
                on_2b=_truthy_runner(r.get("on_2b")),
                on_3b=_truthy_runner(r.get("on_3b")),
                previous_pitch_type=previous_pitch_type,
                previous_two_pitch_types=list(previous_two),
                previous_pitch_result=pa_prev_result[pa_key],
                times_through_order=tto,
                pitcher_pitch_count=prior_count,
                at_bat_number=ab,
                description=r.get("description"),
                events=r.get("events") or None,
                release_speed=_safe_float(r.get("release_speed")),
                release_spin_rate=_safe_float(r.get("release_spin_rate")),
                pfx_x=_safe_float(r.get("pfx_x")),
                pfx_z=_safe_float(r.get("pfx_z")),
                plate_x=_safe_float(r.get("plate_x")),
                plate_z=_safe_float(r.get("plate_z")),
                zone=_safe_int(r.get("zone"), 0) or None,
            )
            records.append(rec)

            # Update PA history AFTER building the record (no leakage into this pitch)
            pa_prev[pa_key].append(pitch_type)
            pa_prev_result[pa_key] = r.get("description") or r.get("events")

        return records
