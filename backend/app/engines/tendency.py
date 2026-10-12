"""Pitcher tendency engine — usage rates by situation slices."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from app.providers.statcast import PITCH_NAME_MAP
from app.schema.pitch import PitchRecord, PitcherTendencies


def _normalize(counts: Counter[str]) -> dict[str, float]:
    total = sum(counts.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))}


def _bucket_rates(items: Iterable[tuple[str, str]], min_n: int = 1) -> dict[str, dict[str, float]]:
    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    for key, pitch in items:
        buckets[key][pitch] += 1
    return {k: _normalize(c) for k, c in buckets.items() if sum(c.values()) >= min_n}


class PitcherTendencyEngine:
    """Compute consumable tendency tables from historical PitchRecords."""

    def compute(self, pitches: list[PitchRecord]) -> PitcherTendencies:
        if not pitches:
            raise ValueError("Cannot compute tendencies from empty pitch list")

        pitcher_id = pitches[0].pitcher_id
        pitcher_name = pitches[0].pitcher_name
        overall = Counter(p.pitch_type for p in pitches)
        pitch_names: dict[str, str] = {}
        for p in pitches:
            if p.pitch_type not in pitch_names:
                pitch_names[p.pitch_type] = p.pitch_name or PITCH_NAME_MAP.get(p.pitch_type, p.pitch_type)

        by_strikes = _bucket_rates((str(p.strikes), p.pitch_type) for p in pitches)
        by_count = _bucket_rates((p.count_key, p.pitch_type) for p in pitches)
        vs_hand = _bucket_rates((p.stand, p.pitch_type) for p in pitches)
        by_runners = _bucket_rates((p.runners_state, p.pitch_type) for p in pitches)
        by_inning = _bucket_rates((str(min(p.inning, 9)), p.pitch_type) for p in pitches)
        by_tto = _bucket_rates((str(min(p.times_through_order, 3)), p.pitch_type) for p in pitches)
        after_pitch = _bucket_rates(
            (p.previous_pitch_type, p.pitch_type)
            for p in pitches
            if p.previous_pitch_type
        )

        seq2_items: list[tuple[str, str]] = []
        seq3_items: list[tuple[str, str]] = []
        for p in pitches:
            if p.previous_pitch_type:
                seq2_items.append((p.previous_pitch_type, p.pitch_type))
            if len(p.previous_two_pitch_types) == 2:
                key = "→".join(p.previous_two_pitch_types)
                seq3_items.append((key, p.pitch_type))

        return PitcherTendencies(
            pitcher_id=pitcher_id,
            pitcher_name=pitcher_name,
            pitch_count=len(pitches),
            arsenal=_normalize(overall),
            by_strikes=by_strikes,
            by_count=by_count,
            vs_hand=vs_hand,
            by_runners=by_runners,
            by_inning=by_inning,
            by_tto=by_tto,
            after_pitch=after_pitch,
            sequences_2=_bucket_rates(seq2_items),
            sequences_3=_bucket_rates(seq3_items),
            pitch_names=pitch_names,
        )
