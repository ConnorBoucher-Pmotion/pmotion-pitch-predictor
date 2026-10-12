#!/usr/bin/env python3
"""Generate Statcast-compatible sample CSV for Yoshinobu Yamamoto (POC).

Patterns are intentionally situational so a weighted tendency model can beat
always-guessing the most common pitch (FF).
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

PITCHER_ID = 808967
PITCHER_NAME = "Yamamoto, Yoshinobu"
OUT = Path(__file__).resolve().parents[1] / "data" / "sample" / "yamamoto_2024_sample.csv"

# Game definitions: (game_pk, date, innings_target_pitches)
GAMES = [
    (745545, "2024-04-06", 95),
    (745612, "2024-04-12", 88),
    (745701, "2024-04-18", 102),
    (745790, "2024-04-24", 90),
    (745880, "2024-05-01", 97),
    (745970, "2024-05-07", 85),
]

BATTERS = [
    (665742, "Judge, Aaron", "R"),
    (660271, "Ohtani, Shohei", "L"),
    (592450, "Judge, DummyR", "R"),
    (605141, "Lefty, Spec", "L"),
    (543037, "Righty, Spec", "R"),
    (518692, "Switchish, R", "R"),
    (502671, "Contact, L", "L"),
    (457705, "Power, R", "R"),
]

# Base arsenal priors (FF most common ~32%)
BASE = {"FF": 0.32, "ST": 0.22, "CU": 0.16, "FS": 0.18, "FC": 0.12}

HEADERS = [
    "pitch_type",
    "game_date",
    "release_speed",
    "release_spin_rate",
    "player_name",
    "batter",
    "pitcher",
    "events",
    "description",
    "zone",
    "stand",
    "p_throws",
    "balls",
    "strikes",
    "pfx_x",
    "pfx_z",
    "plate_x",
    "plate_z",
    "on_3b",
    "on_2b",
    "on_1b",
    "outs_when_up",
    "inning",
    "inning_topbot",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "home_score",
    "away_score",
    "bat_score",
    "fld_score",
    "pitch_name",
    "batter_name",
]

PITCH_META = {
    "FF": ("4-Seam Fastball", 95.5, 2400),
    "ST": ("Sweeper", 86.0, 2650),
    "CU": ("Curveball", 77.5, 2800),
    "FS": ("Splitter", 89.0, 1500),
    "FC": ("Cutter", 91.5, 2450),
}


def weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights.keys())
    vals = [max(0.0, weights[k]) for k in keys]
    s = sum(vals) or 1.0
    vals = [v / s for v in vals]
    r = rng.random()
    acc = 0.0
    for k, v in zip(keys, vals):
        acc += v
        if r <= acc:
            return k
    return keys[-1]


def situation_weights(
    balls: int,
    strikes: int,
    stand: str,
    prev: str | None,
    prev2: list[str],
    runners: str,
    tto: int,
) -> dict[str, float]:
    w = dict(BASE)
    # Count patterns
    if strikes == 0 and balls == 0:
        w["FF"] += 0.18
        w["ST"] -= 0.05
    if strikes == 2:
        w["ST"] += 0.22
        w["FS"] += 0.12
        w["FF"] -= 0.15
    if balls >= 2 and strikes <= 1:
        w["FF"] += 0.20
        w["CU"] -= 0.08
    if balls == 3 and strikes == 2:
        w["FF"] += 0.25
        w["FC"] += 0.08
        w["CU"] -= 0.10
    # Handedness
    if stand == "L":
        w["ST"] += 0.18
        w["FF"] -= 0.08
        w["FS"] += 0.05
    else:
        w["FS"] += 0.10
        w["CU"] += 0.06
        w["ST"] -= 0.05
    # Sequencing
    if prev == "FF":
        w["ST"] += 0.14
        w["FS"] += 0.08
        w["FF"] -= 0.10
    if prev == "ST":
        w["FF"] += 0.12
        w["CU"] += 0.06
    if prev == "FS":
        w["FF"] += 0.10
        w["ST"] += 0.06
    if prev2 == ["FF", "ST"]:
        w["FS"] += 0.15
        w["FF"] -= 0.05
    if runners == "risp":
        w["ST"] += 0.08
        w["FS"] += 0.06
        w["CU"] -= 0.04
    if tto >= 3:
        w["ST"] += 0.06
        w["FS"] += 0.04
    return w


def describe(pitch: str, balls: int, strikes: int, rng: random.Random) -> tuple[str, str | None, int, int]:
    """Return description, events, new_balls, new_strikes."""
    roll = rng.random()
    if pitch in ("FF", "FC") and roll < 0.28:
        return "swinging_strike", None, balls, min(strikes + 1, 2)
    if roll < 0.35:
        return "ball", None, min(balls + 1, 3), strikes
    if roll < 0.55:
        return "called_strike", None, balls, min(strikes + 1, 2)
    if roll < 0.75:
        return "foul", None, balls, min(max(strikes, 1), 2) if strikes < 2 else 2
    if roll < 0.88:
        return "hit_into_play", "field_out", 0, 0
    return "hit_into_play", "single", 0, 0


def main() -> None:
    rng = random.Random(42)
    rows: list[dict] = []

    for game_pk, game_date, target in GAMES:
        ab_number = 0
        outs = 0
        inning = 1
        topbot = "Top"
        home = 0
        away = 0
        pitches_in_game = 0
        batter_tto: dict[int, int] = {}
        seen_batters_in_order: list[int] = []

        while pitches_in_game < target and inning <= 7:
            batter_id, batter_name, stand = rng.choice(BATTERS)
            if batter_id not in batter_tto:
                batter_tto[batter_id] = 1
            elif batter_id in seen_batters_in_order[-9:]:
                batter_tto[batter_id] = min(3, batter_tto[batter_id] + 1)
            seen_batters_in_order.append(batter_id)
            tto = batter_tto[batter_id]

            ab_number += 1
            balls = 0
            strikes = 0
            pitch_number = 0
            prev: str | None = None
            prev2: list[str] = []
            on1 = on2 = on3 = False
            if rng.random() < 0.35:
                on1 = True
            if rng.random() < 0.18:
                on2 = True
            if rng.random() < 0.08:
                on3 = True
            runners = "empty"
            if on2 or on3:
                runners = "risp"
            elif on1:
                runners = "on"

            pa_done = False
            while not pa_done and pitches_in_game < target:
                pitch_number += 1
                pitches_in_game += 1
                weights = situation_weights(balls, strikes, stand, prev, prev2, runners, tto)
                pitch = weighted_choice(rng, weights)
                name, vel, spin = PITCH_META[pitch]
                desc, event, nb, ns = describe(pitch, balls, strikes, rng)

                rows.append(
                    {
                        "pitch_type": pitch,
                        "game_date": game_date,
                        "release_speed": round(vel + rng.uniform(-1.5, 1.5), 1),
                        "release_spin_rate": int(spin + rng.randint(-80, 80)),
                        "player_name": PITCHER_NAME,
                        "batter": batter_id,
                        "pitcher": PITCHER_ID,
                        "events": event or "",
                        "description": desc,
                        "zone": rng.randint(1, 14),
                        "stand": stand,
                        "p_throws": "R",
                        "balls": balls,
                        "strikes": strikes,
                        "pfx_x": round(rng.uniform(-1.2, 1.2), 2),
                        "pfx_z": round(rng.uniform(-0.5, 1.5), 2),
                        "plate_x": round(rng.uniform(-1.2, 1.2), 2),
                        "plate_z": round(rng.uniform(1.2, 3.5), 2),
                        "on_3b": batter_id if on3 else "",
                        "on_2b": batter_id if on2 else "",
                        "on_1b": batter_id if on1 else "",
                        "outs_when_up": outs,
                        "inning": inning,
                        "inning_topbot": topbot,
                        "game_pk": game_pk,
                        "at_bat_number": ab_number,
                        "pitch_number": pitch_number,
                        "home_score": home,
                        "away_score": away,
                        "bat_score": away if topbot == "Top" else home,
                        "fld_score": home if topbot == "Top" else away,
                        "pitch_name": name,
                        "batter_name": batter_name,
                    }
                )

                prev2 = ([prev] if prev else []) + ([pitch])
                prev2 = prev2[-2:]
                prev = pitch

                if event in ("field_out", "single", "double", "home_run"):
                    pa_done = True
                    if event == "field_out":
                        outs += 1
                    elif event == "single":
                        on3, on2, on1 = on2, on1, True
                    if balls == 3 and desc == "ball":
                        pa_done = True
                elif balls == 3 and desc == "ball":
                    pa_done = True
                    on3, on2, on1 = on2, on1, True
                elif strikes == 2 and desc in ("swinging_strike", "called_strike"):
                    pa_done = True
                    outs += 1
                else:
                    balls, strikes = nb, ns
                    if balls >= 4:
                        pa_done = True
                        on3, on2, on1 = on2, on1, True
                    if strikes >= 3:
                        pa_done = True
                        outs += 1

                if outs >= 3:
                    outs = 0
                    if topbot == "Top":
                        topbot = "Bot"
                    else:
                        topbot = "Top"
                        inning += 1
                    on1 = on2 = on3 = False
                    break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} pitches → {OUT}")


if __name__ == "__main__":
    main()
