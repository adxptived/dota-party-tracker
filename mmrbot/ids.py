"""Разбор идентификатора игрока Dota 2 в 32-битный account_id.

Принимаем:
- ссылки Dotabuff/OpenDota/Stratz вида .../players/<id> (id уже 32-битный account_id);
- ссылки Steam .../profiles/<steamid64> (конвертируем в account_id);
- голое число: >= SteamID64-базы — это SteamID64, иначе — готовый account_id;
- кастомные ссылки Steam /id/<vanity> распарсить нельзя (нужен Steam API-ключ) — понятная ошибка.
"""
from __future__ import annotations

import re

STEAMID64_BASE = 76561197960265728


def _to_account_id(number: int) -> int:
    """SteamID64 -> account_id; готовый account_id оставляем как есть."""
    if number > STEAMID64_BASE:
        return number - STEAMID64_BASE
    return number


def parse_account_id(text: str) -> int:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Пустой идентификатор. Дай ссылку Dotabuff/OpenDota или числовой ID.")

    # Steam vanity-ссылка — без Steam API-ключа не разрешить.
    if re.search(r"steamcommunity\.com/id/", raw, flags=re.IGNORECASE):
        raise ValueError(
            "Не могу определить ID по кастомной Steam-ссылке (/id/...). "
            "Дай ссылку Dotabuff/OpenDota (.../players/<id>) или числовой ID."
        )

    # .../players/<id> (Dotabuff, OpenDota, Stratz) — id уже account_id.
    match = re.search(r"/players/(\d+)", raw)
    if match:
        return _to_account_id(int(match.group(1)))

    # .../profiles/<steamid64> (Steam).
    match = re.search(r"/profiles/(\d+)", raw)
    if match:
        return _to_account_id(int(match.group(1)))

    # Голое число.
    if re.fullmatch(r"\d+", raw):
        return _to_account_id(int(raw))

    raise ValueError(
        "Не понял идентификатор. Пришли ссылку Dotabuff/OpenDota (.../players/<id>) "
        "или числовой account_id / SteamID64."
    )
