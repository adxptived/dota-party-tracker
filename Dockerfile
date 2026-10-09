FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/mmrbot.db \
    HOME=/data \
    MPLCONFIGDIR=/data/.matplotlib

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mmrbot ./mmrbot
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Бот работает от пользователя bot; писать он может только в /data (база, бэкапы, кэши иконок).
RUN useradd --uid 10001 --user-group --no-create-home --home-dir /data --shell /usr/sbin/nologin bot \
    && mkdir -p /data && chown bot:bot /data \
    && chmod 755 /usr/local/bin/docker-entrypoint.sh

# Планировщик раз в минуту обновляет /data/heartbeat; файл старше 5 минут — цикл событий завис.
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import os,sys,time; sys.exit(0 if time.time()-os.path.getmtime('/data/heartbeat')<300 else 1)"

# Привилегии сбрасывает точка входа: сначала она возвращает пользователю bot том от прежних образов (см. скрипт).
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "mmrbot"]
