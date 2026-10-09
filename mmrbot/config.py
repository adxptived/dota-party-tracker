"""Конфигурация из окружения/.env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

from mmrbot.storage import DEFAULT_DIGEST_HOUR, DEFAULT_MMR_STEP, DEFAULT_TZ
from mmrbot.timezones import RENAMED, is_valid


@dataclass
class Config:
    bot_token: str
    opendota_api_key: Optional[str]
    stratz_api_key: Optional[str]
    db_path: str
    opendota_min_interval: float = 1.1  # пауза между запросами к OpenDota, сек
    backup_keep: int = 7  # сколько ежедневных копий БД хранить (0 — бэкап выключен)
    steam_api_key: Optional[str] = None  # Steam Web API: оповещения «зашёл в Dota 2» (без ключа выключены)
    opendota_burst: int = 5  # сколько запросов к OpenDota можно отправить подряд без паузы
    opendota_enrich_days: int = 90  # детали матчей догружаем только за столько последних дней (0 — за всю историю)
    opendota_daily_reserve: int = 800  # без ключа: столько запросов суточного лимита фон не трогает
    default_digest_hour: int = DEFAULT_DIGEST_HOUR  # настройки новых чатов
    default_mmr_step: int = DEFAULT_MMR_STEP
    default_tz: str = DEFAULT_TZ
    allowed_chats: frozenset = field(default_factory=frozenset)  # пусто — бот отвечает всем
    max_players: int = 16  # игроков на чат: каждый — это запросы к OpenDota из общего лимита
    command_refresh_wait: float = 4.0  # сек: команда ждёт обновление игроков не дольше, дальше — ответ из БД
    opendota_proxy: Optional[str] = None  # прокси только для OpenDota (socks5h://… или http://…); в нём может быть пароль
    error_chat_id: Optional[int] = None  # куда слать отчёты об ошибках (Telegram ID владельца или чата); None — никуда
    inline_cache_chat: Optional[int] = None  # чат-хранилище картинок для inline-режима; None — inline отвечает текстом
    sentry_dsn: Optional[str] = None  # адрес проекта Sentry; нужен пакет sentry-sdk

    def secrets(self) -> tuple:
        """Значения, которые нельзя показывать в отчётах об ошибках и логах."""
        return tuple(s for s in (self.bot_token, self.opendota_api_key, self.stratz_api_key, self.steam_api_key,
                                 self.opendota_proxy, self.sentry_dsn) if s)


def _chat_ids(raw: str) -> frozenset:
    """`ALLOWED_CHATS=-100123, 456` → {-100123, 456}; мусор в списке — ошибка запуска, а не «пускаем всех»."""
    ids = set()
    for token in (raw or "").replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            ids.add(int(token))
        except ValueError:
            raise RuntimeError(f"ALLOWED_CHATS: «{token}» — не числовой ID чата.") from None
    return frozenset(ids)


def _tz_env(name: str, default: str) -> str:
    value = (os.getenv(name) or "").strip() or default
    return RENAMED.get(value, value) if is_valid(value) else default


def _chat_id_env(name: str) -> Optional[int]:
    """ID чата из окружения: пусто — None; не число — ошибка запуска (молча потерять отчёты об ошибках хуже)."""
    value = (os.getenv(name) or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(f"{name}: «{value}» — не числовой ID чата.") from None


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, default)))
    except ValueError:
        return default


_PROXY_SCHEMES = ("http://", "https://", "socks4://", "socks4a://", "socks5://", "socks5h://")


def _proxy_env(name: str) -> Optional[str]:
    """Прокси из окружения: пусто — нет; неизвестная схема — ошибка запуска (значение в тексте не повторяем: там пароль)."""
    value = (os.getenv(name) or "").strip()
    if not value:
        return None
    if not value.lower().startswith(_PROXY_SCHEMES):
        raise RuntimeError(f"{name}: ожидается адрес вида socks5h://хост:порт или http://хост:порт.")
    return value


def load_config() -> Config:
    load_dotenv()  # подхватывает .env из текущей директории
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "BOT_TOKEN не задан. Скопируйте .env.example в .env и впишите токен от @BotFather."
        )
    api_key = os.getenv("OPENDOTA_API_KEY") or None
    # С ключом лимиты OpenDota выше — можно опрашивать чаще (быстрее графики и /stats).
    default_interval = 0.25 if api_key else 1.1
    try:
        interval = max(0.0, float(os.getenv("OPENDOTA_MIN_INTERVAL", default_interval)))
    except ValueError:
        interval = default_interval
    return Config(
        bot_token=token,
        opendota_api_key=api_key,
        opendota_min_interval=interval,
        stratz_api_key=os.getenv("STRATZ_API_KEY") or None,
        steam_api_key=os.getenv("STEAM_API_KEY") or None,
        db_path=os.getenv("DB_PATH", "mmrbot.db"),
        backup_keep=_int_env("BACKUP_KEEP", 7),
        # 5 подряд + по одному в 1.1 с — это меньше 60 запросов в любую минуту.
        opendota_burst=max(1, _int_env("OPENDOTA_BURST", 5)),
        opendota_enrich_days=_int_env("OPENDOTA_ENRICH_DAYS", 90),
        opendota_daily_reserve=_int_env("OPENDOTA_DAILY_RESERVE", 800),
        default_digest_hour=min(23, _int_env("DEFAULT_DIGEST_HOUR", DEFAULT_DIGEST_HOUR)),
        default_mmr_step=min(200, max(1, _int_env("DEFAULT_MMR_STEP", DEFAULT_MMR_STEP))),
        default_tz=_tz_env("DEFAULT_TZ", DEFAULT_TZ),
        allowed_chats=_chat_ids(os.getenv("ALLOWED_CHATS", "")),
        max_players=max(1, _int_env("MAX_PLAYERS", 16)),
        command_refresh_wait=_float_env("COMMAND_REFRESH_WAIT", 4.0),
        opendota_proxy=_proxy_env("OPENDOTA_PROXY"),
        error_chat_id=_chat_id_env("ERROR_CHAT_ID"),
        inline_cache_chat=_chat_id_env("INLINE_CACHE_CHAT"),
        sentry_dsn=(os.getenv("SENTRY_DSN") or "").strip() or None,
    )
