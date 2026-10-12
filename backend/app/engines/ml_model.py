"""Chronological scikit-learn multiclass next-pitch model (no leakage)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from app.engines.baseline import WeightedBaselinePredictor, evaluate_vs_most_common
from app.engines.features import assert_no_target_leakage, feature_dict, situation_from_pitch
from app.engines.tendency import PitcherTendencyEngine
from app.schema.pitch import PitchProbability, PitchRecord, PredictionResult, SituationInput

logger = logging.getLogger(__name__)

CATEGORICAL = ["stand", "runners", "previous_pitch_type", "prev2", "count"]
NUMERIC = [
    "balls",
    "strikes",
    "outs",
    "inning",
    "times_through_order",
    "pitcher_pitch_count",
    "on_1b",
    "on_2b",
    "on_3b",
]


def _rows_from_pitches(pitches: list[PitchRecord]) -> tuple[list[dict[str, Any]], list[str]]:
    X: list[dict[str, Any]] = []
    y: list[str] = []
    for p in pitches:
        sit = situation_from_pitch(p)
        feats = feature_dict(sit)
        assert_no_target_leakage(feats, actual_pitch_type=p.pitch_type)
        # Flatten for sklearn
        row = {
            "balls": feats["balls"],
            "strikes": feats["strikes"],
            "outs": feats["outs"],
            "inning": feats["inning"],
            "times_through_order": feats["times_through_order"],
            "pitcher_pitch_count": feats["pitcher_pitch_count"],
            "stand": feats["stand"],
            "runners": feats["runners"],
            "previous_pitch_type": feats["previous_pitch_type"] or "NONE",
            "prev2": "→".join(feats["previous_two_pitch_types"])
            if feats["previous_two_pitch_types"]
            else "NONE",
            "count": feats["count"],
            "on_1b": int(sit.on_1b),
            "on_2b": int(sit.on_2b),
            "on_3b": int(sit.on_3b),
        }
        X.append(row)
        y.append(p.pitch_type)
    return X, y


def _count_only_predict(train: list[PitchRecord], test: list[PitchRecord]) -> float:
    from collections import Counter, defaultdict

    by_count: dict[str, Counter[str]] = defaultdict(Counter)
    overall = Counter(p.pitch_type for p in train)
    for p in train:
        by_count[f"{p.balls}-{p.strikes}"][p.pitch_type] += 1
    correct = 0
    for p in test:
        key = f"{p.balls}-{p.strikes}"
        dist = by_count.get(key) or overall
        guess = dist.most_common(1)[0][0]
        if guess == p.pitch_type:
            correct += 1
    return correct / max(len(test), 1)


@dataclass
class MlTrainResult:
    model_path: str
    train_size: int
    test_size: int
    metrics: dict[str, Any]
    classes: list[str]
    feature_note: str


class NextPitchMlModel:
    """Gradient boosting multiclass on leakage-safe situational features."""

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.pipeline: Optional[Pipeline] = None
        self.classes_: list[str] = []
        self.pitcher_id: Optional[int] = None

    def _build_pipeline(self) -> Pipeline:
        pre = ColumnTransformer(
            [
                (
                    "cat",
                    OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                    CATEGORICAL,
                ),
                ("num", "passthrough", NUMERIC),
            ]
        )
        clf = RandomForestClassifier(
            n_estimators=400,
            max_depth=10,
            min_samples_leaf=5,
            random_state=42,
            n_jobs=-1,
        )
        return Pipeline([("pre", pre), ("clf", clf)])

    def fit_chronological(
        self,
        pitches: list[PitchRecord],
        pitcher_id: int,
        *,
        train_frac: float = 0.7,
    ) -> MlTrainResult:
        if len(pitches) < 40:
            raise ValueError(f"Need ≥40 pitches to train ML; got {len(pitches)}")
        cut = int(len(pitches) * train_frac)
        train, test = pitches[:cut], pitches[cut:]
        X_train, y_train = _rows_from_pitches(train)
        X_test, y_test = _rows_from_pitches(test)

        pipe = self._build_pipeline()
        # sklearn Pipeline with dict rows via pandas-like list of dicts
        import pandas as pd

        pipe.fit(pd.DataFrame(X_train), y_train)
        preds = pipe.predict(pd.DataFrame(X_test))
        ml_acc = float(accuracy_score(y_test, preds))

        # Baselines on same chronological split
        engine = PitcherTendencyEngine()
        tendencies = engine.compute(train)
        weighted = evaluate_vs_most_common(tendencies, test, WeightedBaselinePredictor())
        count_acc = _count_only_predict(train, test)
        most_common = max(tendencies.arsenal.items(), key=lambda kv: kv[1])[0]
        mc_acc = weighted["most_common_accuracy"]

        self.pipeline = pipe
        self.classes_ = list(pipe.named_steps["clf"].classes_)
        self.pitcher_id = pitcher_id

        path = self.models_dir / f"next_pitch_{pitcher_id}.joblib"
        meta_path = self.models_dir / f"next_pitch_{pitcher_id}.meta.json"
        joblib.dump({"pipeline": pipe, "pitcher_id": pitcher_id, "classes": self.classes_}, path)
        metrics = {
            "ml_accuracy": ml_acc,
            "weighted_baseline_accuracy": weighted["weighted_accuracy"],
            "count_only_accuracy": count_acc,
            "most_common_accuracy": mc_acc,
            "most_common_pitch": most_common,
            "beats_most_common": ml_acc > mc_acc,
            "beats_count_only": ml_acc > count_acc,
            "beats_weighted_baseline": ml_acc > weighted["weighted_accuracy"],
            "train_pitches": len(train),
            "test_pitches": len(test),
        }
        meta_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        logger.info("Trained ML model pitcher=%s metrics=%s", pitcher_id, metrics)
        return MlTrainResult(
            model_path=str(path),
            train_size=len(train),
            test_size=len(test),
            metrics=metrics,
            classes=self.classes_,
            feature_note="situational only — no pitch_type/velo/spin/location of target pitch",
        )

    def load(self, pitcher_id: int) -> bool:
        path = self.models_dir / f"next_pitch_{pitcher_id}.joblib"
        if not path.exists():
            return False
        blob = joblib.load(path)
        self.pipeline = blob["pipeline"]
        self.classes_ = list(blob.get("classes") or [])
        self.pitcher_id = pitcher_id
        return True

    def predict(
        self,
        situation: SituationInput,
        *,
        pitcher_name: str,
        pitch_names: dict[str, str],
        data_label: str = "ml_model",
    ) -> PredictionResult:
        if self.pipeline is None:
            raise ValueError("ML model not loaded/trained")
        import pandas as pd

        feats = feature_dict(situation)
        assert_no_target_leakage(feats)
        row = {
            "balls": feats["balls"],
            "strikes": feats["strikes"],
            "outs": feats["outs"],
            "inning": feats["inning"],
            "times_through_order": feats["times_through_order"],
            "pitcher_pitch_count": feats["pitcher_pitch_count"],
            "stand": feats["stand"],
            "runners": feats["runners"],
            "previous_pitch_type": feats["previous_pitch_type"] or "NONE",
            "prev2": "→".join(feats["previous_two_pitch_types"])
            if feats["previous_two_pitch_types"]
            else "NONE",
            "count": feats["count"],
            "on_1b": int(situation.on_1b),
            "on_2b": int(situation.on_2b),
            "on_3b": int(situation.on_3b),
        }
        proba = self.pipeline.predict_proba(pd.DataFrame([row]))[0]
        classes = list(self.pipeline.named_steps["clf"].classes_)
        ranked = sorted(zip(classes, proba), key=lambda kv: (-kv[1], kv[0]))
        probabilities = [
            PitchProbability(
                pitch_type=pt,
                pitch_name=pitch_names.get(pt, pt),
                probability=round(float(p), 4),
                why=[f"sklearn random forest P({pt})={float(p):.0%}"],
            )
            for pt, p in ranked
        ]
        top_pt, top_p = ranked[0]
        return PredictionResult(
            pitcher_id=situation.pitcher_id,
            pitcher_name=pitcher_name,
            situation=situation,
            probabilities=probabilities,
            top_pitch=top_pt,
            top_probability=round(float(top_p), 4),
            baseline_most_common=top_pt,
            baseline_most_common_rate=0.0,
            explanation_summary=f"ML top {pitch_names.get(top_pt, top_pt)} ({float(top_p):.0%})",
            data_label=data_label,
            model="sklearn_rf_multiclass",
        )

    def meta(self, pitcher_id: int) -> Optional[dict[str, Any]]:
        path = self.models_dir / f"next_pitch_{pitcher_id}.meta.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
