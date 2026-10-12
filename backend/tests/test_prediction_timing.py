"""Prove predictions are created before actual pitch type is known."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base
from app.database.models import Game, Prediction
from app.mlb.live_provider import LiveGameState, ParsedPitch
from app.services.live_prediction_service import LivePredictionService
from app.services.pitch_event_service import PitchEventService


class StubPredictor:
    def predict_situation(self, situation, data_label: str = "test"):
        from app.schema.pitch import PitchProbability, PredictionResult

        return PredictionResult(
            pitcher_id=situation.pitcher_id,
            pitcher_name="Test Pitcher",
            situation=situation,
            probabilities=[
                PitchProbability(pitch_type="FF", pitch_name="4-Seam", probability=0.45, why=["test"]),
                PitchProbability(pitch_type="SL", pitch_name="Slider", probability=0.30, why=["test"]),
                PitchProbability(pitch_type="CH", pitch_name="Changeup", probability=0.25, why=["test"]),
            ],
            top_pitch="FF",
            top_probability=0.45,
            baseline_most_common="FF",
            baseline_most_common_rate=0.4,
            explanation_summary="stub",
            data_label=data_label,
            model="stub",
        )


@pytest.fixture()
def db_session(tmp_path):
    # Use Postgres if available; else skip — M1 requires Postgres
    url = "postgresql+psycopg://pitch:pitch@127.0.0.1:5432/pitch_intel"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(bind=engine)
    Factory = sessionmaker(bind=engine, future=True)
    session: Session = Factory()
    # isolate with a unique game_pk
    yield session
    session.rollback()
    session.close()


def _pitch(game_pk: int, ab: int, n: int, ptype: str = "SL") -> ParsedPitch:
    return ParsedPitch(
        game_pk=game_pk,
        at_bat_index=ab,
        pitch_number=n,
        pitch_number_in_game=n,
        pitcher_id=808967,
        batter_id=123,
        pitcher_name="Yoshinobu Yamamoto",
        batter_name="Test Batter",
        pitch_type=ptype,
        pitch_name="Slider" if ptype == "SL" else ptype,
        balls=0,
        strikes=0,
        outs=0,
        inning=1,
        inning_half="Top",
        stand="R",
        p_throws="R",
        on_1b=False,
        on_2b=False,
        on_3b=False,
        home_score=0,
        away_score=0,
    )


def test_prediction_created_before_actual(db_session: Session):
    import time

    from app.database.models import Pitch, PlateAppearance, Player, Team

    game_pk = 910000000 + int(time.time()) % 100000
    # cleanup prior runs for this pk (and keep schema tidy)
    db_session.query(Prediction).filter(Prediction.game_pk == game_pk).delete()
    db_session.query(Pitch).filter(Pitch.game_pk == game_pk).delete()
    db_session.query(PlateAppearance).filter(PlateAppearance.game_pk == game_pk).delete()
    db_session.query(Game).filter(Game.game_pk == game_pk).delete()
    db_session.commit()

    for tid, name in ((1, "Home Test"), (2, "Away Test")):
        if db_session.get(Team, tid) is None:
            db_session.add(Team(id=tid, name=name))
    for pid, name in ((808967, "Yoshinobu Yamamoto"), (123, "Test Batter")):
        if db_session.get(Player, pid) is None:
            db_session.add(Player(id=pid, full_name=name))
    db_session.flush()

    db_session.add(
        Game(
            game_pk=game_pk,
            game_date=date.today(),
            status="In Progress",
            abstract_state="Live",
            home_team_id=1,
            away_team_id=2,
            home_team_name="Home",
            away_team_name="Away",
            data_label="test",
        )
    )
    db_session.commit()

    svc = LivePredictionService(StubPredictor())  # type: ignore[arg-type]
    pitches = PitchEventService()

    state = LiveGameState(
        game_pk=game_pk,
        status="In Progress",
        abstract_state="Live",
        home_team_id=1,
        away_team_id=2,
        home_team_name="Home",
        away_team_name="Away",
        home_score=0,
        away_score=0,
        inning=1,
        inning_half="Top",
        outs=0,
        balls=0,
        strikes=0,
        pitcher_id=808967,
        pitcher_name="Yoshinobu Yamamoto",
        batter_id=123,
        batter_name="Test Batter",
        on_1b=False,
        on_2b=False,
        on_3b=False,
        pitches=[],
        current_matchup={
            "pitcher_id": 808967,
            "batter_id": 123,
            "stand": "R",
            "p_throws": "R",
            "at_bat_index": 0,
            "pitch_number_next": 1,
        },
        venue="Test",
        game_date=date.today().isoformat(),
        data_label="test",
    )

    pred = svc.create_next_prediction(db_session, state=state, data_label="test")
    db_session.commit()
    assert pred is not None
    assert pred.actual_pitch_type is None
    assert pred.resolved_at is None
    assert pred.prediction_created_at is not None
    created = pred.prediction_created_at

    # Actual arrives later
    parsed = _pitch(game_pk, 0, 1, "SL")
    row, created_flag = pitches.upsert_pitch(db_session, parsed)
    assert created_flag
    resolved = svc.resolve_with_pitch(db_session, row.id, parsed)
    db_session.commit()

    assert resolved is not None
    assert resolved.actual_pitch_type == "SL"
    assert resolved.top1_correct is False  # predicted FF
    assert resolved.top2_correct is True  # SL is top2
    assert created <= resolved.resolved_at

    # Reload and verify timing proof query shape
    again = db_session.scalar(select(Prediction).where(Prediction.id == pred.id))
    assert again.prediction_created_at <= again.resolved_at
    assert again.prediction_created_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)
