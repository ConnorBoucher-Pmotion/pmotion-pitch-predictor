# PMotion Pitch Prediction Engine

Dodgers-focused next-pitch prediction POC: Statcast history → tendency + sklearn ML → live MLB Stats API / replay UI.

**Repo:** https://github.com/ConnorBoucher-Pmotion/pmotion-pitch-predictor  
**Public UI (Pages):** https://connorboucher-pmotion.github.io/pmotion-pitch-predictor/  
**API:** Railway / Fly (see `Dockerfile`, `railway.toml`, `fly.toml`)

## Stack

- Frontend: React + TypeScript + Vite (Dodger blue / white / red dark analytics UI)
- Backend: FastAPI
- Data: Baseball Savant Statcast + MLB Stats API (GUMBO live feed)
- ML: scikit-learn GradientBoosting multiclass (chronological holdout)

## Quick start

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8741 --reload

# Frontend
cd frontend
npm install
cp .env.example .env
npm run dev -- --host 0.0.0.0 --port 5174
```

Open http://127.0.0.1:5174

## Data

- `USE_SAMPLE_DATA=false` (default): download/cache Statcast for Dodgers starters into `data/cache/`
- Sample CSV remains an **explicit fallback** for the default pitcher only
- Warm starters: `POST /api/data/warm-starters` or `python scripts/fetch_dodgers_statcast.py`

Starters (configurable): Yamamoto, Glasnow, Buehler, Bobby Miller, Gavin Stone, Kershaw.

## Prediction

1. **Weighted baseline** — tendency slices (count, hand, previous pitch, …) with WHY
2. **sklearn GB multiclass** — chronological 70/30 split; compared to most-common, count-only, weighted
3. **Live** — MLB Stats API polling + state-change detection (`data_label: live_mlb_stats_api`)
4. **Replay** — labeled `replayed_historical`; logs prediction-vs-actual to `data/logs/predictions.jsonl`

Hard rule: never use the upcoming pitch’s type/velo/spin/location as features.

## Tests

```bash
cd backend && source .venv/bin/activate && pytest -q
```

## Production

### Frontend — GitHub Pages (qf-lab pattern)

```bash
# CI: .github/workflows/pages.yml on push to main
# Or manual:
VITE_BASE=/pmotion-pitch-predictor/ VITE_API_BASE_URL=https://YOUR-API.example \
  bash scripts/deploy-gh-pages.sh https://github.com/ConnorBoucher-Pmotion/pmotion-pitch-predictor.git
```

Set repo variable `VITE_API_BASE_URL` for Actions builds.

### Backend — Railway or Fly

```bash
# Railway
railway up

# Fly
fly launch --copy-config --no-deploy
fly deploy
```

Set `CORS_ORIGINS` to include `https://connorboucher-pmotion.github.io`.

## API sketch

| Path | Purpose |
|------|---------|
| `GET /api/health` | Health |
| `GET /api/config` | Defaults + starter IDs |
| `POST /api/predict` | Situation → probabilities |
| `POST /api/live/start` | MLB live session |
| `POST /api/replay/start` | Historical replay |
| `GET /api/model/performance` | ML vs baselines |
| `GET /api/logs/predictions` | Prediction logs |

## Limitations

- Live feed requires an in-progress MLB `game_pk`; empty/final games surface clear errors
- Statcast download depends on Baseball Savant availability; cache/sample fallback is labeled
- Public FE needs a hosted API URL in `VITE_API_BASE_URL` for full functionality on Pages
