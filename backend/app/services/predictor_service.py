"""Orchestrates data → tendencies → predictions; replay + live + ML + logs."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.config import Settings
from app.engines.baseline import BaselineWeights, WeightedBaselinePredictor, evaluate_vs_most_common
from app.engines.features import situation_from_pitch
from app.engines.ml_model import NextPitchMlModel
from app.engines.tendency import PitcherTendencyEngine
from app.providers.mlb_live import MlbLiveGameProvider
from app.providers.replay import ReplayLiveProvider
from app.providers.statcast import StatcastHistoricalProvider
from app.schema.pitch import (
    PitchRecord,
    PitcherTendencies,
    PredictionResult,
    ReplayAccuracy,
    SituationInput,
)
from app.services.prediction_log import PredictionLogStore

logger = logging.getLogger(__name__)


@dataclass
class ReplaySession:
    game_pk: int
    pitcher_id: int
    pitches: list[PitchRecord]
    index: int = 0
    revealed: set[int] = field(default_factory=set)
    predictions: dict[int, PredictionResult] = field(default_factory=dict)
    paused: bool = True
    speed: float = 1.0
    logged: set[int] = field(default_factory=set)


class PredictorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.historical = StatcastHistoricalProvider(settings)
        self.replay_provider = ReplayLiveProvider(self.historical)
        self.live_provider = MlbLiveGameProvider(poll_interval_sec=settings.live_poll_interval_sec)
        self.tendency_engine = PitcherTendencyEngine()
        self.predictor = WeightedBaselinePredictor()
        self.ml = NextPitchMlModel(Path(settings.models_dir).resolve())
        self.logs = PredictionLogStore(Path(settings.prediction_log_path).resolve())
        self._tendencies_cache: dict[int, PitcherTendencies] = {}
        self._replay: Optional[ReplaySession] = None
        self._live_game_pk: Optional[int] = None
        self._live_pitcher_id: Optional[int] = None

    def load_pitches(
        self,
        pitcher_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        *,
        force_refresh: bool = False,
    ) -> list[PitchRecord]:
        pid = pitcher_id or self.settings.default_pitcher_id
        start = start_date or self.settings.default_start_date
        end = end_date or self.settings.default_end_date
        return self.historical.get_pitches(pid, start, end, force_refresh=force_refresh)

    def warm_dodgers_starters(self, *, force_refresh: bool = False) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for pid in self.settings.dodgers_starter_id_list:
            try:
                pitches = self.load_pitches(pid, force_refresh=force_refresh)
                results[str(pid)] = {"ok": True, "pitches": len(pitches)}
            except Exception as exc:  # noqa: BLE001
                results[str(pid)] = {"ok": False, "error": str(exc)}
        return {
            "use_sample_data": self.settings.use_sample_data,
            "starters": results,
            "data_label": "sample" if self.settings.use_sample_data else "statcast_cache_or_download",
        }

    def get_tendencies(self, pitcher_id: Optional[int] = None) -> PitcherTendencies:
        pid = pitcher_id or self.settings.default_pitcher_id
        if pid not in self._tendencies_cache:
            pitches = self.load_pitches(pid)
            self._tendencies_cache[pid] = self.tendency_engine.compute(pitches)
            logger.info("Computed tendencies for pitcher %s (%d pitches)", pid, len(pitches))
        return self._tendencies_cache[pid]

    def ensure_ml(self, pitcher_id: int) -> dict[str, Any]:
        if self.ml.load(pitcher_id):
            meta = self.ml.meta(pitcher_id) or {}
            return {"loaded": True, "trained": False, "metrics": meta}
        pitches = self.load_pitches(pitcher_id)
        result = self.ml.fit_chronological(pitches, pitcher_id)
        return {"loaded": True, "trained": True, "metrics": result.metrics, "path": result.model_path}

    def predict_situation(
        self,
        situation: SituationInput,
        *,
        weights: Optional[dict[str, float]] = None,
        data_label: str = "historical_tendencies",
        model: Optional[str] = None,
    ) -> PredictionResult:
        tendencies = self.get_tendencies(situation.pitcher_id)
        prefer_ml = (model == "ml") or (model is None and self.settings.prefer_ml_predictions)
        if prefer_ml:
            try:
                self.ensure_ml(situation.pitcher_id)
                most_common = max(tendencies.arsenal.items(), key=lambda kv: kv[1])
                result = self.ml.predict(
                    situation,
                    pitcher_name=tendencies.pitcher_name,
                    pitch_names=tendencies.pitch_names,
                    data_label=data_label,
                )
                result.baseline_most_common = most_common[0]
                result.baseline_most_common_rate = round(most_common[1], 4)
                return result
            except Exception as exc:  # noqa: BLE001
                logger.warning("ML predict failed, falling back to weighted baseline: %s", exc)

        predictor = self.predictor
        if weights:
            predictor = WeightedBaselinePredictor(
                BaselineWeights(**{**self.predictor.weights.as_dict(), **weights})
            )
        return predictor.predict(tendencies, situation, data_label=data_label)

    def list_games(self, pitcher_id: Optional[int] = None) -> list[dict]:
        pid = pitcher_id or self.settings.default_pitcher_id
        return self.historical.list_games(
            pid, self.settings.default_start_date, self.settings.default_end_date
        )

    def list_starters(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for pid in self.settings.dodgers_starter_id_list:
            try:
                pitches = self.load_pitches(pid)
                name = pitches[0].pitcher_name if pitches else str(pid)
                out.append(
                    {
                        "pitcher_id": pid,
                        "pitcher_name": name,
                        "pitch_count": len(pitches),
                        "games": len({p.game_pk for p in pitches}),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                out.append({"pitcher_id": pid, "error": str(exc)})
        return out

    # --- Replay -----------------------------------------------------------------

    def start_replay(self, game_pk: int, pitcher_id: Optional[int] = None) -> dict[str, Any]:
        pid = pitcher_id or self.settings.default_pitcher_id
        pitches = self.historical.get_game_pitches(game_pk, pid)
        self.replay_provider.start_game(game_pk, pid)
        self._replay = ReplaySession(game_pk=game_pk, pitcher_id=pid, pitches=pitches)
        self._predict_index(0)
        return self.replay_state()

    def _require_replay(self) -> ReplaySession:
        if self._replay is None:
            raise ValueError("No active replay session. Call /api/replay/start first.")
        return self._replay

    def _predict_index(self, index: int) -> PredictionResult:
        session = self._require_replay()
        if index in session.predictions:
            return session.predictions[index]
        pitch = session.pitches[index]
        pred = self.predict_situation(
            situation_from_pitch(pitch),
            data_label="replayed_historical",
        )
        session.predictions[index] = pred
        return pred

    def replay_state(self) -> dict[str, Any]:
        session = self._require_replay()
        idx = session.index
        done = idx >= len(session.pitches)
        current_pitch = None if done else session.pitches[idx]
        pred = None if done else self._predict_index(idx)
        revealed = idx in session.revealed
        actual = current_pitch.pitch_type if (current_pitch and revealed) else None
        correct = (pred.top_pitch == actual) if (pred and actual) else None

        if revealed and current_pitch and pred and idx not in session.logged:
            self.logs.append(
                source="replay",
                game_pk=session.game_pk,
                pitcher_id=session.pitcher_id,
                situation=situation_from_pitch(current_pitch).model_dump(),
                predicted=pred.top_pitch,
                predicted_probability=pred.top_probability,
                actual=actual,
                correct=correct,
                model=pred.model,
                data_label="replayed_historical",
            )
            session.logged.add(idx)

        pa_pitches: list[dict] = []
        if current_pitch:
            ab = current_pitch.at_bat_number
            for i, p in enumerate(session.pitches):
                if p.at_bat_number != ab:
                    continue
                if i < idx or (i == idx and revealed):
                    pa_pitches.append(
                        {
                            "index": i,
                            "pitch_type": p.pitch_type,
                            "pitch_name": p.pitch_name,
                            "balls": p.balls,
                            "strikes": p.strikes,
                            "description": p.description,
                        }
                    )

        return {
            "data_label": "replayed_historical",
            "game_pk": session.game_pk,
            "pitcher_id": session.pitcher_id,
            "index": session.index,
            "total": len(session.pitches),
            "paused": session.paused,
            "speed": session.speed,
            "done": done,
            "revealed": revealed,
            "situation": situation_from_pitch(current_pitch).model_dump() if current_pitch else None,
            "prediction": pred.model_dump() if pred else None,
            "actual_pitch_type": actual,
            "correct": correct,
            "accuracy": self.replay_accuracy().model_dump(),
            "current_pa": pa_pitches,
            "pitch_meta": (
                {
                    "inning": current_pitch.inning,
                    "inning_topbot": current_pitch.inning_topbot,
                    "outs": current_pitch.outs,
                    "batter_name": current_pitch.batter_name,
                    "pitcher_name": current_pitch.pitcher_name,
                    "game_date": current_pitch.game_date,
                    "pitch_number_in_game": current_pitch.pitch_number_in_game,
                }
                if current_pitch
                else None
            ),
        }

    def replay_control(self, action: str, speed: Optional[float] = None) -> dict[str, Any]:
        session = self._require_replay()
        if action == "start":
            session.paused = False
        elif action == "pause":
            session.paused = True
        elif action == "next":
            if session.index < len(session.pitches):
                if session.index not in session.revealed:
                    session.revealed.add(session.index)
                else:
                    session.index = min(session.index + 1, len(session.pitches))
                    if session.index < len(session.pitches):
                        self._predict_index(session.index)
        elif action == "previous":
            session.index = max(0, session.index - 1)
        elif action == "reveal":
            if session.index < len(session.pitches):
                session.revealed.add(session.index)
        elif action == "reset":
            session.index = 0
            session.revealed.clear()
            session.predictions.clear()
            session.logged.clear()
            session.paused = True
            self._predict_index(0)
        elif action == "set_speed":
            if speed is None:
                raise ValueError("speed required for set_speed")
            session.speed = float(speed)
        else:
            raise ValueError(f"Unknown replay action: {action}")
        return self.replay_state()

    def replay_accuracy(self) -> ReplayAccuracy:
        session = self._require_replay()
        tendencies = self.get_tendencies(session.pitcher_id)
        most_common = max(tendencies.arsenal.items(), key=lambda kv: kv[1])[0]
        correct = 0
        mc_correct = 0
        by_type: dict[str, dict[str, Any]] = {}
        for idx in sorted(session.revealed):
            pitch = session.pitches[idx]
            pred = self._predict_index(idx)
            actual = pitch.pitch_type
            by_type.setdefault(actual, {"n": 0, "correct": 0})
            by_type[actual]["n"] += 1
            if pred.top_pitch == actual:
                correct += 1
                by_type[actual]["correct"] += 1
            if most_common == actual:
                mc_correct += 1
        n = len(session.revealed)
        acc = (correct / n) if n else 0.0
        mc_acc = (mc_correct / n) if n else 0.0
        return ReplayAccuracy(
            total_revealed=n,
            correct=correct,
            accuracy=round(acc, 4),
            most_common_baseline_correct=mc_correct,
            most_common_baseline_accuracy=round(mc_acc, 4),
            beats_most_common=acc > mc_acc if n else False,
            by_pitch_type=by_type,
        )

    def game_evaluation(self, game_pk: int, pitcher_id: Optional[int] = None) -> dict[str, Any]:
        pid = pitcher_id or self.settings.default_pitcher_id
        pitches = self.historical.get_game_pitches(game_pk, pid)
        all_pitches = self.load_pitches(pid)
        train = [p for p in all_pitches if p.game_pk != game_pk]
        train_label = "leave_one_game_out"
        if len(train) < 50:
            train = all_pitches
            train_label = "full_sample_fallback"
        tendencies = self.tendency_engine.compute(train)
        metrics = evaluate_vs_most_common(tendencies, pitches, self.predictor)
        return {
            "data_label": "replayed_historical",
            "train_label": train_label,
            "game_pk": game_pk,
            "pitcher_id": pid,
            "pitcher_name": tendencies.pitcher_name,
            "metrics": metrics,
            "model": "weighted_baseline",
        }

    # --- Live -------------------------------------------------------------------

    def start_live(self, game_pk: int, pitcher_id: Optional[int] = None) -> dict[str, Any]:
        pid = pitcher_id or self.settings.default_pitcher_id
        try:
            self.live_provider.start_game(game_pk, pid)
            self._live_game_pk = game_pk
            self._live_pitcher_id = pid
            return self.live_state()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Failed to start MLB live feed for game_pk={game_pk}: {exc}. "
                "Use Replay for historical games; live requires an in-progress MLB game."
            ) from exc

    def live_state(self) -> dict[str, Any]:
        if self._live_game_pk is None:
            raise ValueError("No live session. Call /api/live/start with a game_pk.")
        status = self.live_provider.status_dict()
        pitch = self.live_provider.peek_situation()
        # Predict the NEXT pitch: if we have N completed pitches, build situation from last
        # and note that upcoming pitch is unknown (true live next-pitch).
        prediction = None
        situation = None
        pitches = self.live_provider._require().pitches  # noqa: SLF001
        if pitch is not None:
            situation = situation_from_pitch(pitch)
            prediction = self.predict_situation(situation, data_label="live_mlb_stats_api")
        elif pitches:
            last = pitches[-1]
            situation = situation_from_pitch(last)
            situation.previous_pitch_type = last.pitch_type
            situation.previous_two_pitch_types = (list(last.previous_two_pitch_types) + [last.pitch_type])[-2:]
            situation.pitcher_pitch_count = last.pitcher_pitch_count + 1
            prediction = self.predict_situation(situation, data_label="live_mlb_stats_api")

        return {
            **status,
            "mode": "live",
            "situation": situation.model_dump() if situation else None,
            "prediction": prediction.model_dump() if prediction else None,
            "note": "Live MLB Stats API/GUMBO feed. If game is not in progress, feed may be empty or final.",
        }

    def live_control(self, action: str) -> dict[str, Any]:
        if action == "refresh":
            self.live_provider._refresh_from_api(force=True)  # noqa: SLF001
        elif action == "stop":
            self.live_provider.stop_polling()
        elif action == "start_polling":
            self.live_provider.start_polling()
        elif action == "log_current":
            state = self.live_state()
            pred = state.get("prediction")
            pitch = self.live_provider.peek_situation()
            if pred and pitch:
                self.logs.append(
                    source="live",
                    game_pk=self._live_game_pk,
                    pitcher_id=self._live_pitcher_id or 0,
                    situation=state.get("situation") or {},
                    predicted=pred["top_pitch"],
                    predicted_probability=pred["top_probability"],
                    actual=pitch.pitch_type,
                    correct=pred["top_pitch"] == pitch.pitch_type,
                    model=pred["model"],
                    data_label="live_mlb_stats_api",
                )
        else:
            raise ValueError(f"Unknown live action: {action}")
        return self.live_state()

    # --- Model performance ------------------------------------------------------

    def model_performance(self, pitcher_id: Optional[int] = None) -> dict[str, Any]:
        pid = pitcher_id or self.settings.default_pitcher_id
        pitches = self.load_pitches(pid)
        if len(pitches) < 40:
            raise ValueError("Not enough pitches for evaluation")

        cut = int(len(pitches) * 0.7)
        train, test = pitches[:cut], pitches[cut:]
        tendencies = self.tendency_engine.compute(train)
        weighted = evaluate_vs_most_common(tendencies, test, self.predictor)

        ml_info = self.ensure_ml(pid)
        ml_metrics = ml_info.get("metrics") or {}

        return {
            "data_label": "sample" if self.settings.use_sample_data else "historical_holdout",
            "pitcher_id": pid,
            "pitcher_name": tendencies.pitcher_name,
            "train_pitches": len(train),
            "test_pitches": len(test),
            "metrics": {
                "most_common_pitch": weighted["most_common_pitch"],
                "most_common_accuracy": weighted["most_common_accuracy"],
                "count_only_accuracy": ml_metrics.get("count_only_accuracy"),
                "weighted_baseline_accuracy": weighted["weighted_accuracy"],
                "ml_accuracy": ml_metrics.get("ml_accuracy"),
                "beats_most_common": bool(ml_metrics.get("beats_most_common")),
                "beats_count_only": bool(ml_metrics.get("beats_count_only")),
                "beats_weighted_baseline": bool(ml_metrics.get("beats_weighted_baseline")),
            },
            "weights": self.predictor.weights.as_dict(),
            "model": "sklearn_rf_multiclass",
            "ml_status": "trained" if ml_info.get("trained") or ml_info.get("loaded") else "unavailable",
            "prediction_log": self.logs.summary(),
            "use_sample_data": self.settings.use_sample_data,
        }
