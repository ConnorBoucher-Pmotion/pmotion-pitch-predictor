"""Leakage + ML chronological evaluation tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.engines.features import TARGET_LEAK_FIELDS, assert_no_target_leakage, feature_dict, situation_from_pitch
from app.engines.ml_model import NextPitchMlModel, _rows_from_pitches
from app.engines.tendency import PitcherTendencyEngine
from app.providers.statcast import StatcastHistoricalProvider


@pytest.fixture(scope="module")
def settings(tmp_path_factory):
    root = Path(__file__).resolve().parents[2]
    models = tmp_path_factory.mktemp("models")
    return Settings(
        sample_data_path=root / "data" / "sample" / "yamamoto_2024_sample.csv",
        use_sample_data=True,
        cache_dir=root / "data" / "cache",
        models_dir=models,
        prediction_log_path=tmp_path_factory.mktemp("logs") / "predictions.jsonl",
    )


@pytest.fixture(scope="module")
def pitches(settings):
    provider = StatcastHistoricalProvider(settings)
    return provider.get_pitches(808967, "2024-03-28", "2024-09-30")


def test_feature_rows_have_no_leak_fields(pitches):
    X, y = _rows_from_pitches(pitches[:80])
    for row, label in zip(X, y):
        assert "pitch_type" not in row
        for leak in TARGET_LEAK_FIELDS:
            assert leak not in row
        assert_no_target_leakage(feature_dict(situation_from_pitch(pitches[0])), actual_pitch_type=label)


def test_ml_beats_most_common_on_sample(pitches, settings):
    model = NextPitchMlModel(Path(settings.models_dir))
    result = model.fit_chronological(pitches, 808967)
    assert result.metrics["test_pitches"] > 0
    assert result.metrics["ml_accuracy"] >= result.metrics["most_common_accuracy"]
    assert "count_only_accuracy" in result.metrics
    assert "weighted_baseline_accuracy" in result.metrics


def test_ml_predict_ignores_target_outcomes(pitches, settings):
    model = NextPitchMlModel(Path(settings.models_dir))
    model.fit_chronological(pitches, 808967)
    pitch = pitches[100]
    sit = situation_from_pitch(pitch)
    tendencies = PitcherTendencyEngine().compute(pitches[:200])
    a = model.predict(sit, pitcher_name="t", pitch_names=tendencies.pitch_names)
    sit2 = situation_from_pitch(
        pitch.model_copy(update={"release_speed": 999.0, "plate_x": 9.0, "pitch_type": "ZZ"})
    )
    b = model.predict(sit2, pitcher_name="t", pitch_names=tendencies.pitch_names)
    assert a.top_pitch == b.top_pitch
