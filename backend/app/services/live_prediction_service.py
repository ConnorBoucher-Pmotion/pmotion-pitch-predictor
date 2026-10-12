"""Create next-pitch predictions BEFORE actual arrives; resolve when pitch lands."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Prediction
from app.engines.features import situation_from_pitch
from app.mlb.live_provider import LiveGameState, ParsedPitch
from app.schema.pitch import PitchRecord, SituationInput
from app.services.predictor_service import PredictorService

logger = logging.getLogger(__name__)

MODEL_VERSION = "baseline_or_ml_v1"


class LivePredictionService:
    def __init__(self, predictor: PredictorService) -> None:
        self.predictor = predictor

    def create_next_prediction(
        self,
        session: Session,
        *,
        state: LiveGameState,
        data_label: str = "live_mlb_stats_api",
    ) -> Optional[Prediction]:
        """Predict the upcoming pitch and persist with prediction_created_at while actual is null."""
        situation, target = self._next_situation(state)
        if situation is None or target is None:
            return None

        ab_index, pitch_number = target
        existing = session.scalar(
            select(Prediction).where(
                Prediction.game_pk == state.game_pk,
                Prediction.at_bat_index == ab_index,
                Prediction.pitch_number == pitch_number,
                Prediction.model_version == MODEL_VERSION,
            )
        )
        if existing:
            return existing

        # CRITICAL: create prediction BEFORE actual pitch type is known
        created_at = datetime.now(timezone.utc)
        result = self.predictor.predict_situation(situation, data_label=data_label)
        probs = [
            {
                "pitch_type": p.pitch_type,
                "pitch_name": p.pitch_name,
                "probability": p.probability,
                "why": p.why,
            }
            for p in result.probabilities
        ]
        top_types = [p["pitch_type"] for p in probs[:3]]

        row = Prediction(
            game_pk=state.game_pk,
            at_bat_index=ab_index,
            pitch_number=pitch_number,
            pitcher_id=situation.pitcher_id,
            batter_id=(state.current_matchup or {}).get("batter_id") or state.batter_id,
            situation=situation.model_dump(),
            probabilities={"items": probs, "top_pitch": result.top_pitch},
            top1_pitch_type=top_types[0] if top_types else result.top_pitch,
            top2_pitch_type=top_types[1] if len(top_types) > 1 else None,
            top3_pitch_type=top_types[2] if len(top_types) > 2 else None,
            model_version=MODEL_VERSION,
            data_label=data_label,
            prediction_created_at=created_at,
            actual_pitch_type=None,  # must be null at insert time
            explanation=result.explanation_summary,
        )
        session.add(row)
        session.flush()
        logger.info(
            "Prediction stored BEFORE pitch game=%s ab=%s n=%s top1=%s at=%s actual=%s",
            state.game_pk,
            ab_index,
            pitch_number,
            row.top1_pitch_type,
            created_at.isoformat(),
            row.actual_pitch_type,
        )
        return row

    def resolve_with_pitch(self, session: Session, pitch_row_id: int, parsed: ParsedPitch) -> Optional[Prediction]:
        pred = session.scalar(
            select(Prediction).where(
                Prediction.game_pk == parsed.game_pk,
                Prediction.at_bat_index == parsed.at_bat_index,
                Prediction.pitch_number == parsed.pitch_number,
                Prediction.model_version == MODEL_VERSION,
            )
        )
        if pred is None:
            return None
        if pred.resolved_at is not None:
            return pred

        # Timing invariant: prediction must exist before resolution
        if pred.prediction_created_at is None:
            raise RuntimeError("Prediction missing prediction_created_at")

        now = datetime.now(timezone.utc)
        if pred.prediction_created_at > now:
            raise RuntimeError("prediction_created_at is in the future")

        actual = parsed.pitch_type
        pred.actual_pitch_type = actual
        pred.actual_pitch_id = pitch_row_id
        pred.top1_correct = pred.top1_pitch_type == actual
        top2 = {pred.top1_pitch_type, pred.top2_pitch_type}
        top3 = top2 | {pred.top3_pitch_type}
        pred.top2_correct = actual in {t for t in top2 if t}
        pred.top3_correct = actual in {t for t in top3 if t}
        pred.resolved_at = now
        session.flush()
        logger.info(
            "Resolved prediction id=%s created=%s resolved=%s actual=%s top1_ok=%s",
            pred.id,
            pred.prediction_created_at.isoformat(),
            pred.resolved_at.isoformat(),
            actual,
            pred.top1_correct,
        )
        return pred

    def open_prediction(self, session: Session, game_pk: int) -> Optional[Prediction]:
        return session.scalar(
            select(Prediction)
            .where(Prediction.game_pk == game_pk, Prediction.resolved_at.is_(None))
            .order_by(Prediction.prediction_created_at.desc())
        )

    def list_for_game(self, session: Session, game_pk: int, limit: int = 50) -> list[Prediction]:
        return list(
            session.scalars(
                select(Prediction)
                .where(Prediction.game_pk == game_pk)
                .order_by(Prediction.prediction_created_at.desc())
                .limit(limit)
            ).all()
        )

    def accuracy_summary(self, session: Session, game_pk: Optional[int] = None) -> dict[str, Any]:
        q = select(Prediction).where(Prediction.resolved_at.is_not(None))
        if game_pk is not None:
            q = q.where(Prediction.game_pk == game_pk)
        rows = list(session.scalars(q).all())
        n = len(rows)
        top1 = sum(1 for r in rows if r.top1_correct)
        top2 = sum(1 for r in rows if r.top2_correct)
        return {
            "resolved": n,
            "top1_correct": top1,
            "top2_correct": top2,
            "top1_accuracy": round(top1 / n, 4) if n else None,
            "top2_accuracy": round(top2 / n, 4) if n else None,
        }

    def _next_situation(
        self, state: LiveGameState
    ) -> tuple[Optional[SituationInput], Optional[tuple[int, int]]]:
        matchup = state.current_matchup
        if matchup and matchup.get("pitcher_id") and matchup.get("at_bat_index") is not None:
            ab = int(matchup["at_bat_index"])
            pitch_number = int(matchup.get("pitch_number_next") or 1)
            # Build situation from current linescore + last pitch in this PA if any
            pa_pitches = [p for p in state.pitches if p.at_bat_index == ab]
            prev = pa_pitches[-1] if pa_pitches else (state.pitches[-1] if state.pitches else None)
            situation = SituationInput(
                pitcher_id=int(matchup["pitcher_id"]),
                balls=min(max(state.balls, 0), 3),
                strikes=min(max(state.strikes, 0), 2),
                outs=min(max(state.outs, 0), 2),
                inning=int(state.inning or 1),
                stand=(matchup.get("stand") or "R")[:1].upper(),  # type: ignore[arg-type]
                on_1b=state.on_1b,
                on_2b=state.on_2b,
                on_3b=state.on_3b,
                previous_pitch_type=prev.pitch_type if prev and prev.at_bat_index == ab else None,
                previous_two_pitch_types=(
                    list(prev.previous_two_pitch_types) + [prev.pitch_type]
                    if prev and prev.at_bat_index == ab
                    else []
                )[-2:],
                times_through_order=prev.times_through_order if prev else 1,
                pitcher_pitch_count=(prev.pitcher_pitch_count + 1) if prev else 0,
            )
            if situation.stand not in ("L", "R"):
                situation.stand = "R"
            return situation, (ab, pitch_number)

        # Fallback: if game has pitches but no current matchup (between innings), skip
        if state.pitches and state.abstract_state == "Live":
            last = state.pitches[-1]
            # Predict next pitch number after last — may be next PA
            situation = situation_from_pitch(self._as_pitch_record(last))
            situation.previous_pitch_type = last.pitch_type
            situation.previous_two_pitch_types = (list(last.previous_two_pitch_types) + [last.pitch_type])[-2:]
            situation.pitcher_pitch_count = last.pitcher_pitch_count + 1
            return situation, (last.at_bat_index, last.pitch_number + 1)
        return None, None

    @staticmethod
    def _as_pitch_record(p: ParsedPitch) -> PitchRecord:
        return PitchRecord(
            game_pk=p.game_pk,
            game_date="",
            pitch_number_in_game=p.pitch_number_in_game,
            pitcher_id=p.pitcher_id,
            pitcher_name=p.pitcher_name,
            batter_id=p.batter_id,
            batter_name=p.batter_name,
            pitch_type=p.pitch_type,
            pitch_name=p.pitch_name,
            pitch_number_in_pa=p.pitch_number,
            balls=p.balls,
            strikes=p.strikes,
            outs=p.outs,
            inning=p.inning,
            inning_topbot=p.inning_half if p.inning_half in ("Top", "Bot") else "Top",  # type: ignore[arg-type]
            stand=p.stand if p.stand in ("L", "R") else "R",  # type: ignore[arg-type]
            p_throws=p.p_throws if p.p_throws in ("L", "R") else "R",  # type: ignore[arg-type]
            home_score=p.home_score,
            away_score=p.away_score,
            on_1b=p.on_1b,
            on_2b=p.on_2b,
            on_3b=p.on_3b,
            previous_pitch_type=p.previous_pitch_type,
            previous_two_pitch_types=list(p.previous_two_pitch_types),
            times_through_order=p.times_through_order,
            pitcher_pitch_count=p.pitcher_pitch_count,
            at_bat_number=p.at_bat_index,
            description=p.description,
            release_speed=p.release_speed,
            release_spin_rate=p.release_spin_rate,
            plate_x=p.plate_x,
            plate_z=p.plate_z,
        )

    @staticmethod
    def serialize(pred: Prediction) -> dict[str, Any]:
        return {
            "id": pred.id,
            "game_pk": pred.game_pk,
            "at_bat_index": pred.at_bat_index,
            "pitch_number": pred.pitch_number,
            "pitcher_id": pred.pitcher_id,
            "batter_id": pred.batter_id,
            "situation": pred.situation,
            "probabilities": pred.probabilities,
            "top1_pitch_type": pred.top1_pitch_type,
            "top2_pitch_type": pred.top2_pitch_type,
            "top3_pitch_type": pred.top3_pitch_type,
            "model_version": pred.model_version,
            "data_label": pred.data_label,
            "prediction_created_at": pred.prediction_created_at.isoformat() if pred.prediction_created_at else None,
            "actual_pitch_type": pred.actual_pitch_type,
            "top1_correct": pred.top1_correct,
            "top2_correct": pred.top2_correct,
            "top3_correct": pred.top3_correct,
            "resolved_at": pred.resolved_at.isoformat() if pred.resolved_at else None,
            "explanation": pred.explanation,
            "timing_proof": {
                "actual_was_null_at_creation": True,
                "prediction_created_at": pred.prediction_created_at.isoformat() if pred.prediction_created_at else None,
                "resolved_at": pred.resolved_at.isoformat() if pred.resolved_at else None,
                "created_before_resolve": (
                    pred.resolved_at is not None
                    and pred.prediction_created_at is not None
                    and pred.prediction_created_at <= pred.resolved_at
                ),
            },
        }
