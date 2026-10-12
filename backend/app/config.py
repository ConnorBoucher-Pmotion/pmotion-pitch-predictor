"""Environment-driven application settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8741
    log_level: str = "INFO"
    cors_origins: str = "http://127.0.0.1:5174,http://localhost:5174,http://127.0.0.1:43124,http://localhost:43124,*"

    default_pitcher_id: int = 808967
    default_pitcher_name: str = "Yoshinobu Yamamoto"
    default_start_date: str = "2024-03-28"
    default_end_date: str = "2024-09-30"
    default_game_pk: int = 746168

    # Yamamoto, Glasnow, Buehler, Bobby Miller, Gavin Stone, Kershaw
    dodgers_starter_ids: str = "808967,607192,621111,676272,694297,477132"
    dodgers_team_id: int = 119

    data_dir: Path = Path("../data")
    cache_dir: Path = Path("../data/cache")
    sample_data_path: Path = Path("../data/sample/yamamoto_2024_sample.csv")
    models_dir: Path = Path("../models")
    prediction_log_path: Path = Path("../data/logs/predictions.jsonl")
    statcast_base_url: str = "https://baseballsavant.mlb.com/statcast_search/csv"
    use_sample_data: bool = False

    live_poll_interval_sec: float = 3.0
    schedule_poll_interval_sec: float = 20.0
    prefer_ml_predictions: bool = True
    auto_start_workers: bool = True

    # PostgreSQL — Docker Compose default; override via DATABASE_URL
    database_url: str = "postgresql+psycopg://pitch:pitch@127.0.0.1:5432/pitch_intel"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def dodgers_starter_id_list(self) -> list[int]:
        return [int(x.strip()) for x in self.dodgers_starter_ids.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
