FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/mmrbot.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mmrbot ./mmrbot

RUN mkdir -p /data

CMD ["python", "-m", "mmrbot"]
