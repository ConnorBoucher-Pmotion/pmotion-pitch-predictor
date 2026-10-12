"""Ensure next-pitch features never include the target pitch or its outcomes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.engines.baseline import WeightedBaselinePredictor
from app.engines.features import (
    TARGET_LEAK_FIELDS,
    assert_no_target_leakage,
    feature_dict,
    situation_from_pitch,
)
from app.engines.tendency import PitcherTendencyEngine
from app.providers.statcast import StatcastHistoricalProvider


@pytest.fixture(scope="module")
def pitches():
    settings = Settings(
        sample_data_path=Path(__file__).resolve().parents[2] / "data" / "sample" / "yamamoto_2024_sample.csv",
        use_sample_data=True,
        cache_dir=Path(__file__).resolve().parents[2] / "data" / "cache",
    )
    provider = StatcastHistoricalProvider(settings)
    return provider.get_pitches(808967, "2024-03-28", "2024-09-30")


def test_sample_data_loads(pitches):
    assert len(pitches) > 100


def test_situation_features_exclude_target_fields(pitches):
    for pitch in pitches[:50]:
        situation = situation_from_pitch(pitch)
        feats = feature_dict(situation)
        assert_no_target_leakage(feats, actual_pitch_type=pitch.pitch_type)
        for leak in TARGET_LEAK_FIELDS:
            assert leak not in feats
        # Pre-pitch count must not require knowing the result
        assert situation.balls == pitch.balls
        assert situation.strikes == pitch.strikes


def test_previous_pitch_is_not_current(pitches):
    for pitch in pitches:
        if pitch.pitch_number_in_pa == 1:
            assert pitch.previous_pitch_type is None
        if pitch.previous_pitch_type is not None:
            # previous may equal current by chance, but features must still omit pitch_type
            feats = feature_dict(situation_from_pitch(pitch))
            assert "pitch_type" not in feats


def test_prediction_does_not_ingest_statcast_outcomes(pitches):
    engine = PitcherTendencyEngine()
    # leave-one-game tendencies
    game_pk = pitches[0].game_pk
    train = [p for p in pitches if p.game_pk != game_pk]
    tendencies = engine.compute(train)
    predictor = WeightedBaselinePredictor()
    for pitch in [p for p in pitches if p.game_pk == game_pk][:20]:
        # Mutate outcome fields — prediction must be identical
        sit = situation_from_pitch(pitch)
        a = predictor.predict(tendencies, sit)
        pitch_clone = pitch.model_copy(
            update={
                "release_speed": 999.0,
                "plate_x": 9.9,
                "plate_z": 9.9,
                "pitch_type": "ZZ",  # even changing label on record shouldn't affect sit features
            }
        )
        sit2 = situation_from_pitch(pitch_clone)
        # situation_from_pitch ignores pitch_type — still same situation
        b = predictor.predict(tendencies, sit2)
        assert a.top_pitch == b.top_pitch
        assert a.probabilities[0].probability == b.probabilities[0].probability


def test_baseline_can_beat_most_common_on_holdout(pitches):
    from app.engines.baseline import evaluate_vs_most_common

    cut = int(len(pitches) * 0.7)
    train, test = pitches[:cut], pitches[cut:]
    tendencies = PitcherTendencyEngine().compute(train)
    metrics = evaluate_vs_most_common(tendencies, test)
    assert metrics["total"] == len(test)
    assert metrics["weighted_accuracy"] > metrics["most_common_accuracy"]
