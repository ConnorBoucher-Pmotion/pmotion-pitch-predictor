"""Persist prediction-vs-actual logs (JSONL)."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PredictionLogStore:
    def __init__(self, log_path: Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(
        self,
        *,
        source: str,
        game_pk: Optional[int],
        pitcher_id: int,
        situation: dict[str, Any],
        predicted: str,
        predicted_probability: float,
        actual: Optional[str],
        correct: Optional[bool],
        model: str,
        data_label: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "game_pk": game_pk,
            "pitcher_id": pitcher_id,
            "situation": situation,
            "predicted": predicted,
            "predicted_probability": predicted_probability,
            "actual": actual,
            "correct": correct,
            "model": model,
            "data_label": data_label,
            **(extra or {}),
        }
        line = json.dumps(row, ensure_ascii=False)
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        return row

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        rows: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(rows))

    def summary(self) -> dict[str, Any]:
        rows = self.recent(limit=10_000)
        scored = [r for r in rows if r.get("correct") is not None]
        correct = sum(1 for r in scored if r.get("correct"))
        by_source: dict[str, dict[str, int]] = {}
        for r in scored:
            src = str(r.get("source") or "unknown")
            by_source.setdefault(src, {"n": 0, "correct": 0})
            by_source[src]["n"] += 1
            if r.get("correct"):
                by_source[src]["correct"] += 1
        n = len(scored)
        return {
            "total_logged": len(rows),
            "scored": n,
            "accuracy": (correct / n) if n else None,
            "by_source": by_source,
            "log_path": str(self.log_path),
        }
