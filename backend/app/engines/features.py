"""Feature views for prediction — explicitly exclude the target pitch."""

from __future__ import annotations

from typing import Any, Optional

from app.schema.pitch import PitchRecord, SituationInput

# Fields that describe the pitch RESULT / identity — forbidden as features for that pitch
TARGET_LEAK_FIELDS = frozenset(
    {
        "pitch_type",
        "pitch_name",
        "release_speed",
        "release_spin_rate",
        "pfx_x",
        "pfx_z",
        "plate_x",
        "plate_z",
        "zone",
        "description",
        "events",
    }
)


def situation_from_pitch(pitch: PitchRecord) -> SituationInput:
    """Build a situation from a PitchRecord using only pre-pitch context."""
    return SituationInput(
        pitcher_id=pitch.pitcher_id,
        balls=pitch.balls,
        strikes=pitch.strikes,
        outs=pitch.outs,
        inning=pitch.inning,
        stand=pitch.stand,
        on_1b=pitch.on_1b,
        on_2b=pitch.on_2b,
        on_3b=pitch.on_3b,
        previous_pitch_type=pitch.previous_pitch_type,
        previous_two_pitch_types=list(pitch.previous_two_pitch_types),
        times_through_order=pitch.times_through_order,
        pitcher_pitch_count=pitch.pitcher_pitch_count,
    )


def feature_dict(situation: SituationInput) -> dict[str, Any]:
    """Serializable features with zero target leakage."""
    runners = "empty"
    if situation.on_2b or situation.on_3b:
        runners = "risp"
    elif situation.on_1b:
        runners = "on"
    return {
        "pitcher_id": situation.pitcher_id,
        "balls": situation.balls,
        "strikes": situation.strikes,
        "count": f"{situation.balls}-{situation.strikes}",
        "outs": situation.outs,
        "inning": situation.inning,
        "stand": situation.stand,
        "runners": runners,
        "previous_pitch_type": situation.previous_pitch_type,
        "previous_two_pitch_types": list(situation.previous_two_pitch_types),
        "times_through_order": situation.times_through_order,
        "pitcher_pitch_count": situation.pitcher_pitch_count,
    }


def assert_no_target_leakage(features: dict[str, Any], actual_pitch_type: Optional[str] = None) -> None:
    """Raise if forbidden fields appear or actual pitch type is embedded."""
    leak = TARGET_LEAK_FIELDS.intersection(features.keys())
    if leak:
        raise AssertionError(f"Target leakage fields present in features: {sorted(leak)}")
    if actual_pitch_type is not None:
        # Features must not equal the target pitch type as a top-level value named pitch_type
        if features.get("pitch_type") == actual_pitch_type:
            raise AssertionError("Feature dict contains pitch_type equal to target")
        # previous_* may legitimately equal the same type from an earlier pitch
        if "pitch_type" in features:
            raise AssertionError("Feature dict must not include pitch_type")
