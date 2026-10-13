"""Чистый разбор аргументов команд (без aiogram) — легко тестируется."""
from __future__ import annotations

import re
from typing import Optional

MMR_MIN = 0
MMR_MAX = 20000
NAME_MAX = 32  # длиннее ник не помещается в кнопки и таблицы


def _is_int(token: str) -> bool:
    try:
        int(token)
        return True
    except (TypeError, ValueError):
        return False


def _validate_mmr(mmr: int) -> int:
    if mmr < MMR_MIN or mmr > MMR_MAX:
        raise ValueError(f"MMR — число от {MMR_MIN} до {MMR_MAX}.")
    return mmr


def parse_add_args(args: str) -> tuple[str, Optional[str], Optional[int]]:
    """`/add <identifier> [Имя ...] [MMR]` → (identifier, name|None, mmr|None).

    Эвристика: первый токен — идентификатор; если последний токен — число, это MMR;
    всё между ними — имя (может быть из нескольких слов).
    """
    tokens = (args or "").split()
    if not tokens:
        raise ValueError("Формат: /add ссылка_или_ID [имя] [MMR]")

    identifier = tokens[0]
    rest = tokens[1:]

    mmr: Optional[int] = None
    if rest and _is_int(rest[-1]):
        mmr = _validate_mmr(int(rest[-1]))
        rest = rest[:-1]

    name = " ".join(rest) if rest else None
    if name is not None and len(name) > NAME_MAX:
        raise ValueError(f"Имя слишком длинное — до {NAME_MAX} символов.")
    return identifier, name, mmr


def parse_name_and_mmr(args: str) -> tuple[str, int]:
    """`/setmmr <Имя ...> <MMR>` → (name, mmr)."""
    tokens = (args or "").split()
    if len(tokens) < 2 or not _is_int(tokens[-1]):
        raise ValueError("Формат: /setmmr Вася 5300")
    mmr = _validate_mmr(int(tokens[-1]))
    name = " ".join(tokens[:-1])
    return name, mmr


def parse_mmr_value(text: str) -> int:
    """Ответ на подсказку кнопки «Задать MMR»: одно число в допустимом диапазоне."""
    token = (text or "").strip()
    if not _is_int(token):
        raise ValueError("Нужно одно число, например 5300.")
    return _validate_mmr(int(token))


def parse_step(args: str) -> int:
    """`/setstep <шаг>` → положительный int."""
    token = (args or "").strip()
    if not _is_int(token):
        raise ValueError("Формат: /setstep 25")
    step = int(token)
    if step <= 0 or step > 200:
        raise ValueError("Шаг — число от 1 до 200.")
    return step


def parse_hour(args: str) -> int:
    """`/settime <час>` → 0..23."""
    token = (args or "").strip()
    if not _is_int(token):
        raise ValueError("Формат: /settime 10 (час от 0 до 23)")
    hour = int(token)
    if hour < 0 or hour > 23:
        raise ValueError("Час — число от 0 до 23.")
    return hour


_SEASON_START = {"start", "старт", "начать", "новый", "new"}
_SEASON_END = {"end", "stop", "finish", "конец", "стоп", "завершить", "закончить"}
SEASON_DEFAULT_DAYS, SEASON_MIN_DAYS, SEASON_MAX_DAYS = 30, 7, 365


def parse_season_args(args: str) -> tuple[str, Optional[int]]:
    """`/season [start [дней] | end]` → ('show'|'start'|'end'|'error', дней | None).

    Длина сезона — 7…365 дней (по умолчанию 30): короче — мало игр для номинаций, длиннее — сезон теряет смысл.
    """
    tokens = (args or "").split()
    if not tokens:
        return "show", None
    word = tokens[0].lower()
    if word in _SEASON_END and len(tokens) == 1:
        return "end", None
    if word in _SEASON_START and len(tokens) <= 2:
        if len(tokens) == 1:
            return "start", SEASON_DEFAULT_DAYS
        if _is_int(tokens[1]) and SEASON_MIN_DAYS <= int(tokens[1]) <= SEASON_MAX_DAYS:
            return "start", int(tokens[1])
    return "error", None


_PERIOD_WORDS = {
    "день": "day", "сутки": "day", "сегодня": "day", "day": "day", "today": "day",
    "неделя": "week", "неделю": "week", "week": "week",
    "месяц": "month", "month": "month",
    "год": "year", "year": "year",
    "всё": "all", "все": "all", "всё_время": "all", "all": "all",
}
_LAST_WORDS = {"последний", "последняя", "last", "latest"}


def _clean_name(tokens: list[str]) -> Optional[str]:
    name = " ".join(tokens).strip().lstrip("@").strip()
    return name or None


def parse_target_period(args: str) -> tuple[Optional[str], str]:
    """`[игрок|@тег] [период]` → (имя|None, 'day'|'week'|'month'|'all'). Период — в любом месте."""
    period = "all"
    rest = []
    for token in (args or "").split():
        key = token.lower()
        if key in _PERIOD_WORDS:
            period = _PERIOD_WORDS[key]
        else:
            rest.append(token)
    return _clean_name(rest), period


_MATCH_URL_RE = re.compile(r"/matches?/(\d{6,})", re.IGNORECASE)


def match_id_from_link(token: str) -> Optional[int]:
    """ID матча из ссылки Dotabuff/OpenDota/Stratz (…/matches/<id>); не ссылка на матч — None."""
    found = _MATCH_URL_RE.search(token or "")
    return int(found.group(1)) if found else None


def parse_match_args(args: str) -> tuple[Optional[int], Optional[str]]:
    """`[match_id|ссылка на матч|последний] [игрок|@тег]` → (match_id|None, имя|None)."""
    match_id = None
    rest = []
    for token in (args or "").split():
        if token.lower() in _LAST_WORDS:
            continue
        if match_id is None and match_id_from_link(token) is not None:
            match_id = match_id_from_link(token)
        elif match_id is None and token.isascii() and token.isdigit() and len(token) >= 8:
            match_id = int(token)
        else:
            rest.append(token)
    return match_id, _clean_name(rest)


LOOKUP_HELP = ("Пришлите ID матча, ID игрока (account_id или SteamID64) или ссылку Dotabuff / OpenDota / Stratz / Steam. "
               "Например: 8012345678 или dotabuff.com/players/123456789.")
_MATCH_WORDS = {"матч", "match", "m", "м", "игра"}
_PLAYER_WORDS = {"игрок", "player", "p", "и", "профиль", "аккаунт", "account"}
PLAYER_FIRST_BELOW = 2_000_000_000  # account_id сейчас меньше; ID матчей с 2016 года — больше


def parse_lookup(text: str) -> tuple[str, object]:
    """Запрос поиска → (вид, значение) без сети.

    Виды: "match" (ID матча), "player" (account_id), "vanity" (кастомная ссылка Steam — её разрешает сеть),
    "auto" (голое число, которое может оказаться и игроком, и матчем: решает поиск по OpenDota).
    Слово «матч»/«игрок» перед числом снимает неоднозначность. Не похоже ни на что — ValueError с подсказкой.
    """
    from mmrbot.ids import STEAMID64_BASE, extract_vanity, parse_account_id

    tokens = (text or "").strip().split()
    if not tokens:
        raise ValueError(LOOKUP_HELP)
    forced = None
    if tokens[0].lower().rstrip(":") in _MATCH_WORDS | _PLAYER_WORDS and len(tokens) > 1:
        forced = "match" if tokens.pop(0).lower().rstrip(":") in _MATCH_WORDS else "player"
    raw = tokens[0]
    match_id = match_id_from_link(raw)
    if match_id is not None:
        return "match", match_id
    if extract_vanity(raw):
        return "vanity", raw
    if re.search(r"/(players|profiles)/\d+", raw):
        return "player", parse_account_id(raw)
    digits = raw.lstrip("#")
    if not (digits.isascii() and digits.isdigit()):
        raise ValueError(LOOKUP_HELP)
    number = int(digits)
    if number > STEAMID64_BASE:  # SteamID64 — всегда игрок
        return "player", parse_account_id(digits)
    if forced == "player":
        return "player", parse_account_id(digits)
    if forced == "match" or number > 0xFFFFFFFF:  # больше 32 бит account_id не бывает
        if number <= 0:
            raise ValueError(LOOKUP_HELP)
        return "match", number
    if number <= 0:
        raise ValueError(LOOKUP_HELP)
    return "auto", number


def looks_like_player_id(text: str) -> bool:
    """Аргумент /player — ID или ссылка на игрока (а не ник участника пати)?"""
    try:
        kind, _ = parse_lookup(text)
    except ValueError:
        return False
    return kind in {"player", "vanity", "auto"}


def parse_on_off(args: str) -> bool:
    """`/tags on|off` → True/False."""
    token = (args or "").strip().lower()
    if token in {"on", "вкл", "включить", "1"}:
        return True
    if token in {"off", "выкл", "выключить", "0"}:
        return False
    raise ValueError("Формат: /tags on или /tags off")
