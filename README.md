# PMotion Pitch Intelligence Platform (Milestone 1)

Live MLB pitch intelligence: auto schedule discovery, simultaneous `LiveGameWorker`s, PostgreSQL pitch + prediction storage with **pre-pitch timing proof**, scoreboard home, live game pages, and roster pitcher directory.

Expands https://github.com/ConnorBoucher-Pmotion/pmotion-pitch-predictor — not a manual pitcher/game picker. The UI is a window into an already-running backend engine.

## Stack

- **Frontend:** React + TypeScript + Vite (Dodgers chrome; all-MLB data)
- **Backend:** FastAPI + SQLAlchemy
- **DB:** PostgreSQL (`docker compose` or local)
- **Feeds:** MLB Stats API schedule + GUMBO live feed
- **Models:** Existing weighted baseline + sklearn ML (wired for next-pitch)

## Quick start

```bash
# Postgres
docker compose up -d db
# or local Postgres with DATABASE_URL=postgresql+psycopg://pitch:pitch@127.0.0.1:5432/pitch_intel

# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8741 --reload

# Frontend
cd frontend
npm install
cp .env.example .env   # VITE_BASE=/ for local
npm run dev -- --host 0.0.0.0 --port 5174
```

Open http://127.0.0.1:5174

## What runs automatically

On API startup (`AUTO_START_WORKERS=true`):

1. `ScheduleOrchestrator` syncs today’s MLB schedule into Postgres
2. For each **LIVE** game, starts a `LiveGameWorker` (poll ~3s)
3. New pitches upserted idempotently (`game_pk + at_bat_index + pitch_number`)
4. Open prediction is **resolved**, then the **next** prediction is stored with `prediction_created_at` while `actual_pitch_type` is still null
5. Roster pitchers synced from MLB team rosters

No UI button is required to track live games.

## UI

| Route | Purpose |
|-------|---------|
| `/` TODAY | Scoreboard cards (Scheduled / Live / Final) |
| `/games` | Game list |
| `/games/:gamePk` | Live game: score, count, matchup, runners, pitch history, open prediction, timing log |
| `/pitchers` | MLB roster pitcher directory |
| `/lab` | Legacy replay / tendency lab |

## Critical timing rule

Predictions are inserted with `prediction_created_at` **before** `actual_pitch_type` is known. Never backfill “live” predictions after seeing the answer. Verify via `GET /api/predictions/timing-proof`.

## Offseason / Scheduled-only days

If no games are LIVE, workers idle and the scoreboard shows Scheduled/Final honestly. Optional **labeled** demo:

`POST /api/demo/historical-live` with a completed `game_pk` → `data_label: labeled_historical_demo` (never silent fake live).

## Tests

```bash
cd backend && source .venv/bin/activate && pytest -q
```

## API sketch (M1)

| Path | Purpose |
|------|---------|
| `GET /api/schedule/today` | Today’s games + live worker ids |
| `GET /api/games/{gamePk}` | Live detail + pitches + predictions |
| `POST /api/games/{gamePk}/track` | Force-attach worker |
| `GET /api/pitchers` | Roster pitcher directory |
| `GET /api/accuracy` | Top-1 / Top-2 live accuracy |
| `GET /api/predictions/timing-proof` | Pre-pitch timing evidence |
| `POST /api/demo/historical-live` | Labeled historical demo |
| Prior `/api/predict`, `/api/replay/*`, `/api/model/*` | Unchanged lab endpoints |
