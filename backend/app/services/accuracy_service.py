"""Live Top-1 / Top-2 accuracy rollups."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Prediction


class AccuracyService:
    def summary(self, session: Session, *, game_pk: Optional[int] = None, pitcher_id: Optional[int] = None) -> dict[str, Any]:
        q = select(Prediction).where(Prediction.resolved_at.is_not(None))
        if game_pk is not None:
            q = q.where(Prediction.game_pk == game_pk)
        if pitcher_id is not None:
            q = q.where(Prediction.pitcher_id == pitcher_id)
        rows = list(session.scalars(q).all())
        n = len(rows)
        top1 = sum(1 for r in rows if r.top1_correct)
        top2 = sum(1 for r in rows if r.top2_correct)
        open_q = select(Prediction).where(Prediction.resolved_at.is_(None))
        if game_pk is not None:
            open_q = open_q.where(Prediction.game_pk == game_pk)
        open_n = len(list(session.scalars(open_q).all()))
        return {
            "resolved": n,
            "open_predictions": open_n,
            "top1_correct": top1,
            "top2_correct": top2,
            "top1_accuracy": round(top1 / n, 4) if n else None,
            "top2_accuracy": round(top2 / n, 4) if n else None,
        }
