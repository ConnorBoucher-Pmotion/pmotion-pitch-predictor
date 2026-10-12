#!/usr/bin/env python3
"""Pull multi-game Statcast CSVs for Dodgers starters into data/cache/.

Usage:
  cd pmotion-pitch-predictor/backend && source .venv/bin/activate
  USE_SAMPLE_DATA=false python ../scripts/fetch_dodgers_statcast.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings
from app.providers.statcast import StatcastHistoricalProvider


def main() -> None:
    os.environ.setdefault("USE_SAMPLE_DATA", "false")
    settings = Settings(
        use_sample_data=False,
        cache_dir=ROOT / "data" / "cache",
        sample_data_path=ROOT / "data" / "sample" / "yamamoto_2024_sample.csv",
        data_dir=ROOT / "data",
    )
    provider = StatcastHistoricalProvider(settings)
    ids = settings.dodgers_starter_id_list
    print(f"Fetching Statcast for Dodgers starters: {ids}")
    print(f"Date window: {settings.default_start_date} → {settings.default_end_date}")
    for pid in ids:
        try:
            pitches = provider.get_pitches(
                pid,
                settings.default_start_date,
                settings.default_end_date,
                force_refresh=True,
            )
            print(f"  {pid}: {len(pitches)} pitches cached")
        except Exception as exc:  # noqa: BLE001
            print(f"  {pid}: FAILED — {exc}")
    print("Done. Cache dir:", settings.cache_dir.resolve())


if __name__ == "__main__":
    main()
