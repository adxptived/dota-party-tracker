"""Конфигурация из окружения/.env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Config:
    bot_token: str
    opendota_api_key: Optional[str]
    db_path: str
    opendota_min_interval: float = 1.1


def load_config() -> Config:
    load_dotenv()  # подхватывает .env из текущей директории
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "BOT_TOKEN не задан. Скопируй .env.example в .env и вставь токен от @BotFather."
        )
    api_key = os.getenv("OPENDOTA_API_KEY") or None
    # С ключом лимит OpenDota сильно выше — можно опрашивать чаще (быстрее /stats).
    default_interval = 0.25 if api_key else 1.1
    try:
        interval = float(os.getenv("OPENDOTA_MIN_INTERVAL", default_interval))
    except ValueError:
        interval = default_interval
    return Config(
        bot_token=token,
        opendota_api_key=api_key,
        db_path=os.getenv("DB_PATH", "mmrbot.db"),
        opendota_min_interval=interval,
    )
