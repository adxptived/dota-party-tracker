FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/mmrbot.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mmrbot ./mmrbot

RUN mkdir -p /data

# Планировщик раз в минуту обновляет /data/heartbeat; файл старше 5 минут — цикл событий завис.
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import os,sys,time; sys.exit(0 if time.time()-os.path.getmtime('/data/heartbeat')<300 else 1)"

CMD ["python", "-m", "mmrbot"]
