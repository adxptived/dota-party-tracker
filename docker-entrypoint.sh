#!/bin/sh
# Точка входа контейнера: бот работает от непривилегированного пользователя bot (uid 10001).
#
# Контейнер стартует от root только ради одного шага: том с данными мог остаться от прежних образов,
# где бот работал от root, — такой том возвращаем пользователю bot, после чего привилегии сбрасываются
# и больше не возвращаются. Если контейнер уже запущен не от root (docker run --user …), шаг пропускается.
set -e

BOT_UID=10001
DATA_DIR="$(dirname "${DB_PATH:-/data/mmrbot.db}")"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    if [ "$(stat -c %u "$DATA_DIR")" != "$BOT_UID" ]; then
        chown -R "$BOT_UID:$BOT_UID" "$DATA_DIR"
    fi
    exec setpriv --reuid="$BOT_UID" --regid="$BOT_UID" --clear-groups "$@"
fi
exec "$@"
