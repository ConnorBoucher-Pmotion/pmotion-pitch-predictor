# FastAPI backend image (Railway / Fly / Render)
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend
COPY data /app/data
COPY models /app/models
COPY scripts /app/scripts

ENV PYTHONPATH=/app/backend
ENV HOST=0.0.0.0
ENV PORT=8741
ENV DATA_DIR=/app/data
ENV CACHE_DIR=/app/data/cache
ENV SAMPLE_DATA_PATH=/app/data/sample/yamamoto_2024_sample.csv
ENV MODELS_DIR=/app/models
ENV PREDICTION_LOG_PATH=/app/data/logs/predictions.jsonl
ENV USE_SAMPLE_DATA=false
ENV CORS_ORIGINS=*

WORKDIR /app/backend
EXPOSE 8741

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8741"]
