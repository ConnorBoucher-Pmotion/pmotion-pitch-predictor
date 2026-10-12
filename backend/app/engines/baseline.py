"""Configurable weighted baseline next-pitch predictor with WHY explanations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.engines.features import feature_dict, situation_from_pitch
from app.schema.pitch import (
    PitchProbability,
    PitchRecord,
    PitcherTendencies,
    PredictionResult,
    SituationInput,
)


@dataclass
class BaselineWeights:
    overall: float = 0.15
    count: float = 0.30
    handedness: float = 0.15
    previous_pitch: float = 0.20
    sequence: float = 0.10
    runners: float = 0.05
    tto: float = 0.05

    def as_dict(self) -> dict[str, float]:
        return {
            "overall": self.overall,
            "count": self.count,
            "handedness": self.handedness,
            "previous_pitch": self.previous_pitch,
            "sequence": self.sequence,
            "runners": self.runners,
            "tto": self.tto,
        }


@dataclass
class WeightedBaselinePredictor:
    """Blend tendency slices into arsenal probabilities."""

    weights: BaselineWeights = field(default_factory=BaselineWeights)

    def predict(
        self,
        tendencies: PitcherTendencies,
        situation: SituationInput,
        *,
        data_label: str = "historical_tendencies",
    ) -> PredictionResult:
        arsenal = list(tendencies.arsenal.keys())
        if not arsenal:
            raise ValueError("Pitcher arsenal is empty")

        components: list[tuple[str, float, dict[str, float]]] = []
        w = self.weights

        components.append(("overall arsenal", w.overall, tendencies.arsenal))

        count_key = f"{situation.balls}-{situation.strikes}"
        if count_key in tendencies.by_count:
            components.append((f"count {count_key}", w.count, tendencies.by_count[count_key]))
        else:
            strike_key = str(situation.strikes)
            if strike_key in tendencies.by_strikes:
                components.append(
                    (f"{situation.strikes}-strike counts", w.count, tendencies.by_strikes[strike_key])
                )

        if situation.stand in tendencies.vs_hand:
            hand_label = "vs LHB" if situation.stand == "L" else "vs RHB"
            components.append((hand_label, w.handedness, tendencies.vs_hand[situation.stand]))

        if situation.previous_pitch_type and situation.previous_pitch_type in tendencies.after_pitch:
            components.append(
                (
                    f"after {situation.previous_pitch_type}",
                    w.previous_pitch,
                    tendencies.after_pitch[situation.previous_pitch_type],
                )
            )

        if len(situation.previous_two_pitch_types) == 2:
            seq_key = "→".join(situation.previous_two_pitch_types)
            if seq_key in tendencies.sequences_3:
                components.append((f"sequence {seq_key}", w.sequence, tendencies.sequences_3[seq_key]))
            elif situation.previous_pitch_type in tendencies.sequences_2:
                components.append(
                    (
                        f"sequence after {situation.previous_pitch_type}",
                        w.sequence,
                        tendencies.sequences_2[situation.previous_pitch_type],
                    )
                )

        runners = "empty"
        if situation.on_2b or situation.on_3b:
            runners = "risp"
        elif situation.on_1b:
            runners = "on"
        if runners in tendencies.by_runners:
            components.append((f"runners {runners}", w.runners, tendencies.by_runners[runners]))

        tto_key = str(min(situation.times_through_order, 3))
        if tto_key in tendencies.by_tto:
            components.append((f"TTO {tto_key}", w.tto, tendencies.by_tto[tto_key]))

        # Weighted average over available components; renormalize weights that fired
        weight_sum = sum(weight for _, weight, _ in components if weight > 0)
        if weight_sum <= 0:
            weight_sum = 1.0

        scores = {pt: 0.0 for pt in arsenal}
        why_by_pitch: dict[str, list[str]] = {pt: [] for pt in arsenal}

        for label, weight, rates in components:
            if weight <= 0:
                continue
            norm_w = weight / weight_sum
            for pt in arsenal:
                rate = rates.get(pt, 0.0)
                scores[pt] += norm_w * rate
                if rate >= 0.15:
                    why_by_pitch[pt].append(f"{label}: {rate:.0%}")

        total = sum(scores.values())
        if total <= 0:
            scores = dict(tendencies.arsenal)
            total = sum(scores.values()) or 1.0

        probs = {pt: scores[pt] / total for pt in arsenal}
        ranked = sorted(probs.items(), key=lambda kv: (-kv[1], kv[0]))

        most_common = max(tendencies.arsenal.items(), key=lambda kv: kv[1])
        top_pitch, top_p = ranked[0]

        probabilities = [
            PitchProbability(
                pitch_type=pt,
                pitch_name=tendencies.pitch_names.get(pt, pt),
                probability=round(p, 4),
                why=why_by_pitch.get(pt, [])[:4],
            )
            for pt, p in ranked
        ]

        summary_bits = [
            f"Top call {tendencies.pitch_names.get(top_pitch, top_pitch)} ({top_p:.0%})",
            f"vs always-{most_common[0]} baseline ({most_common[1]:.0%})",
        ]
        if situation.previous_pitch_type:
            summary_bits.append(f"prior pitch {situation.previous_pitch_type}")
        summary_bits.append(f"count {count_key}")

        # Touch feature_dict to keep feature path exercised / leakage-safe
        _ = feature_dict(situation)

        return PredictionResult(
            pitcher_id=tendencies.pitcher_id,
            pitcher_name=tendencies.pitcher_name,
            situation=situation,
            probabilities=probabilities,
            top_pitch=top_pitch,
            top_probability=round(top_p, 4),
            baseline_most_common=most_common[0],
            baseline_most_common_rate=round(most_common[1], 4),
            explanation_summary="; ".join(summary_bits),
            data_label=data_label,
            model="weighted_baseline",
        )

    def predict_for_pitch(
        self,
        tendencies: PitcherTendencies,
        pitch: PitchRecord,
        *,
        data_label: str = "replayed_historical",
    ) -> PredictionResult:
        return self.predict(tendencies, situation_from_pitch(pitch), data_label=data_label)


def evaluate_vs_most_common(
    tendencies: PitcherTendencies,
    pitches: list[PitchRecord],
    predictor: Optional[WeightedBaselinePredictor] = None,
) -> dict:
    """Chronological accuracy: weighted baseline vs always-guess most common."""
    predictor = predictor or WeightedBaselinePredictor()
    most_common = max(tendencies.arsenal.items(), key=lambda kv: kv[1])[0]
    correct = 0
    mc_correct = 0
    by_type: dict[str, dict[str, int]] = {}
    for pitch in pitches:
        pred = predictor.predict_for_pitch(tendencies, pitch)
        actual = pitch.pitch_type
        by_type.setdefault(actual, {"n": 0, "correct": 0})
        by_type[actual]["n"] += 1
        if pred.top_pitch == actual:
            correct += 1
            by_type[actual]["correct"] += 1
        if most_common == actual:
            mc_correct += 1
    n = len(pitches) or 1
    return {
        "total": len(pitches),
        "weighted_correct": correct,
        "weighted_accuracy": correct / n,
        "most_common_pitch": most_common,
        "most_common_correct": mc_correct,
        "most_common_accuracy": mc_correct / n,
        "beats_most_common": (correct / n) > (mc_correct / n),
        "by_pitch_type": by_type,
    }
