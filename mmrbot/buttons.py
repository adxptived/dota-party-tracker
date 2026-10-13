"""Кнопки бота: разбор callback_data таблицами (префикс → обработчик, действие меню → обработчик, выбор игрока →
обработчик). Сами отчёты собирают функции из bot.py — их зовём через модуль (`core.do_match`), чтобы подмена
в тестах (`monkeypatch.setattr(mmrbot.bot, ...)`) действовала и здесь.

Схема callback_data — в keyboards.py. Добавить кнопку: функция-обработчик и строка в нужную таблицу.
"""
from __future__ import annotations

import time

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton

from mmrbot import bot as core
from mmrbot import doubles, gather, seasons
from mmrbot.formatting import render_settings
from mmrbot.keyboards import (
    CATEGORIES, category_menu, category_title, list_actions, main_menu, nav_menu, parse_callback, players_picker,
    settings_menu,
)
from mmrbot.opendota import OpenDota
from mmrbot.storage import Storage
from mmrbot.texts import NOT_FOUND as NOT_FOUND_TEXT, TERMS

router = Router(name="buttons")

# Кнопки разбираются таблицами: префикс callback_data → обработчик, действие меню → обработчик. Обработчик получает
# контекст нажатия (_Press); добавить кнопку — дописать функцию и строку в таблицу, не трогая общий диспетчер.

PERIODS_ALL = {"day", "week", "month", "year", "all"}
PERIODS_NO_YEAR = {"day", "week", "month", "all"}


class _Press:
    """Нажатие кнопки: запрос, сообщение под кнопкой, хранилище и клиенты, аргументы callback_data."""

    def __init__(self, query: CallbackQuery, storage: Storage, od: OpenDota, stratz, args: list[str]) -> None:
        self.query, self.message, self.storage, self.od, self.stratz, self.args = (
            query, query.message, storage, od, stratz, args)

    @property
    def user(self):
        return getattr(self.query, "from_user", None)

    @property
    def bot(self):
        return getattr(self.query, "bot", None)

    def arg(self, i: int, default: str = "") -> str:
        return self.args[i] if len(self.args) > i else default


async def _cb_close(p: _Press) -> None:
    await core._delete(p.message)


async def _cb_settings(p: _Press) -> None:
    await core._on_settings(p.message, p.storage, p.args, p.bot, p.user)


async def _cb_records(p: _Press) -> None:
    period = p.arg(0, "week")
    if period in PERIODS_ALL:
        await core.do_records(p.message, p.storage, p.od, period, p.stratz, edit=True)  # меняем период на месте


async def _cb_contest(p: _Press) -> None:
    period = p.arg(0, "week")
    if period in core.PERIODS_KEYS:
        await core.do_contest(p.message, p.storage, p.od, period, p.stratz, edit=True)  # меняем период на месте


async def _cb_full_match(p: _Press) -> None:
    """«🎮 Весь матч» и цифры последних игр: тот же разбор, что и /match <id>."""
    try:
        match_id = int(p.arg(0))
    except ValueError:
        return
    focus = p.storage.get_player(p.message.chat.id, p.args[1]) if len(p.args) > 1 else None
    await core.do_match(p.message, p.storage, p.od, focus.display_name if focus else None, match_id, p.stratz)


async def _cb_lookup(p: _Press) -> None:
    """Кнопки под карточкой игрока не из пати: «➕ Добавить в пати»."""
    if len(p.args) == 2 and p.args[0] == "add" and p.args[1].isdigit():
        if p.storage.get_player_by_account_id(p.message.chat.id, int(p.args[1])) is not None:
            await p.message.answer("Этот игрок уже в пати.", reply_markup=nav_menu())
        else:
            await core.do_add(p.message, p.storage, p.od, p.args[1], p.stratz, user=p.user)


async def _cb_matches(p: _Press, kind: str) -> None:
    """Список матчей игрока (ml), его матч (mv) и карточка (md) — правят то же сообщение."""
    try:
        numbers = [int(a) for a in p.args[1:]]
    except ValueError:
        return
    message, account = core._InPlace(p.message), p.arg(0)
    if kind == "ml" and len(numbers) == 1:
        await core.do_match_list(message, p.storage, account, numbers[0])
    elif kind == "mv" and len(numbers) == 2:
        await core.do_match_pick(message, p.storage, p.od, account, numbers[0], numbers[1], p.stratz)
    elif kind == "md" and len(numbers) == 2:
        await core.do_match_detail(message, p.storage, account, numbers[0], numbers[1])


async def _cb_text(p: _Press, kind: str) -> None:
    """«📝 Текстом»; mt — прежний формат кнопки под матчем (сообщения уже в чатах)."""
    await core.on_text_view(p.message, p.storage, p.od, p.args if kind == "tx" else ["match", *p.args], p.stratz)


async def _cb_graph(p: _Press) -> None:
    period, by_games = p.arg(0, "week"), "n" in p.args[1:]
    if period not in PERIODS_ALL:
        return
    if getattr(p.message, "photo", None):
        await core.edit_graph(p.message, p.storage, p.od, period, p.stratz, by_games)  # график меняется на месте
    else:
        await core._delete(p.message)
        await core.do_graph(p.message, p.storage, p.od, period, p.stratz, by_games)


async def _cb_matchups(p: _Press) -> None:
    if len(p.args) == 2 and p.args[1] in PERIODS_NO_YEAR:
        account = None if p.args[0] == "0" else p.args[0]
        await core.do_matchups(p.message, p.storage, p.od, account, p.args[1], p.stratz, edit=True)


async def _cb_player_period(p: _Press, kind: str) -> None:
    """Герои (hp) и позиции (rp) игрока: смена периода на месте."""
    if len(p.args) == 2 and p.args[1] in PERIODS_NO_YEAR:
        action = core.do_player_heroes if kind == "hp" else core.do_roles
        await action(p.message, p.storage, p.od, p.args[0], p.args[1], p.stratz, edit=True)


# --- главное меню (`m:<действие>`) ---

PICK_PROMPTS = {
    "remove": "Кого удалить", "setmmr": "Выберите игрока, чтобы задать MMR",
    "heroes": "Выберите игрока для просмотра героев", "roles": "Выберите игрока для просмотра позиций",
    "player": "Выберите игрока для просмотра карточки", "steam": "Выберите игрока для просмотра Steam-профиля",
    "double": "Чей последний матч отметить дабл-дауном (×2)",
}


async def _menu_settings(p: _Press, message) -> None:
    chat = p.storage.get_or_create_chat(message.chat.id)
    await message.answer(render_settings(chat), parse_mode="HTML", reply_markup=settings_menu(chat))


async def _menu_category(p: _Press, message) -> None:
    key = p.arg(1)
    if key in CATEGORIES:
        await message.answer(f"{category_title(key)} — выберите действие:", reply_markup=category_menu(key))
    else:
        await message.answer("📋 Выберите раздел:", reply_markup=main_menu())


async def _menu_me(p: _Press, message) -> None:
    if await core._has_players(message, p.storage):
        kick = [[InlineKeyboardButton(text="🚫 Отвязать меня", callback_data="pp:meoff:0")]]
        await message.answer(
            "🙋 Кто вы из игроков? Привяжу ваш Telegram к нему — тогда тег участника покажет ваш MMR.",
            reply_markup=players_picker(p.storage.list_players(message.chat.id), "me", extra=kick),
        )


def _needs_players(action):
    """Действие меню, которому нужны игроки: без них — подсказка добавить."""
    async def run(p: _Press, message) -> None:
        if await core._has_players(message, p.storage):
            await action(p, message)
    return run


MENU_ACTIONS = {
    "menu": lambda p, m: m.answer("📋 Выберите раздел:", reply_markup=main_menu()),
    "c": _menu_category,
    "season": lambda p, m: core.do_season(m, p.storage, p.od, p.stratz),
    "hall": lambda p, m: m.answer(seasons.render_hall(p.storage.list_seasons(m.chat.id),
                                                      p.storage.get_or_create_chat(m.chat.id).tz),
                                  parse_mode="HTML", reply_markup=nav_menu()),
    "matchups": _needs_players(lambda p, m: core.do_matchups(m, p.storage, p.od, None, "all", p.stratz)),
    "records": _needs_players(lambda p, m: core.do_records(m, p.storage, p.od, "week", p.stratz)),
    "graph": _needs_players(lambda p, m: core.do_graph(m, p.storage, p.od, "week", p.stratz)),
    "achv": _needs_players(lambda p, m: core.do_contest(m, p.storage, p.od, "week", p.stratz)),
    "settings": _menu_settings,
    "tags": _menu_settings,
    "help": lambda p, m: m.answer(core.HELP_TEXT, reply_markup=nav_menu()),
    "terms": lambda p, m: m.answer(TERMS, reply_markup=nav_menu()),
    "list": lambda p, m: _send_roster(p, m),
    "stats": lambda p, m: core.do_stats(m, p.storage, p.od, p.stratz),
    "today": lambda p, m: core.do_stats(m, p.storage, p.od, p.stratz, today_only=True),
    "week": lambda p, m: core.do_period_stats(m, p.storage, p.od, "week", p.stratz),
    "month": lambda p, m: core.do_period_stats(m, p.storage, p.od, "month", p.stratz),
    "compare": lambda p, m: core.do_compare(m, p.storage, p.od, p.stratz),
    "together": lambda p, m: core.do_together(m, p.storage, p.od, p.stratz),
    "match": lambda p, m: core._ask_match(m, p.storage),
    "matchid": lambda p, m: core._prompt_matchid(m),
    "find": lambda p, m: core._prompt_find(m),
    "hero": lambda p, m: core._prompt_hero(m),
    "add": lambda p, m: core._prompt_add(m),
    "me": _menu_me,
    **{action: _needs_players(lambda p, m, action=action: core._ask_player(m, p.storage, action, f"{PICK_PROMPTS[action]}:"))
       for action in PICK_PROMPTS},
}


async def _send_roster(p: _Press, message) -> None:
    await message.answer(await core._roster_text(p.storage, message.chat.id), parse_mode="HTML", reply_markup=list_actions())


async def _cb_menu(p: _Press) -> None:
    action = p.arg(0, "menu")
    if action in {"go", "status", "last"}:  # отвечают новым сообщением и зависят от того, кто нажал
        raw, user = p.message, p.query.from_user
        if action == "go":
            await gather.start(raw, p.storage, user)
        elif action == "status":
            await core.do_status(raw, p.storage, p.od, p.stratz, p.query.bot, user)
        elif await core._has_players(raw, p.storage):
            mine = next((pl for pl in p.storage.list_players(raw.chat.id) if pl.tg_user_id == user.id), None)
            await core.do_match(raw, p.storage, p.od, mine.display_name if mine else None, None, p.stratz)
        return
    handler = MENU_ACTIONS.get(action)
    if handler is not None:  # переход в другой раздел правит то же сообщение на месте — чат не засоряется
        await handler(p, core._InPlace(p.message))


# --- выбор игрока (`pp:<что>:<account_id>`) ---

async def _pick_player(p: _Press, message, account: str):
    """Игрок чата по account_id из кнопки; нет — сообщение «не найден» и None."""
    player = p.storage.get_player(message.chat.id, account)
    if player is None:
        await message.answer(NOT_FOUND_TEXT, reply_markup=nav_menu())
    return player


async def _pick_double(p: _Press, message, account: str) -> None:
    player = p.storage.get_player(message.chat.id, account)
    result = doubles.toggle(p.storage, message.chat.id, player, None, int(time.time())) if player else None
    text = (doubles.describe(player.display_name, result) if result else
            (NOT_FOUND_TEXT if player is None else doubles.NO_MATCH))
    await message.answer(text, parse_mode="HTML", reply_markup=nav_menu())


async def _pick_remove(p: _Press, message, account: str) -> None:
    player = await _pick_player(p, message, account)
    if player is not None:
        await core._confirm_remove(message, player)


async def _pick_remove_yes(p: _Press, message, account: str) -> None:
    player = await _pick_player(p, message, account)
    if player is not None and await core._may_remove(message, p.storage, player, p.user, p.bot):
        p.storage.remove_player(message.chat.id, str(player.account_id))
        await message.answer(f"🗑️ {player.display_name} удалён.", reply_markup=nav_menu())


async def _pick_me(p: _Press, message, account: str, off: bool = False) -> None:
    if message.chat.type == "private":
        await message.answer("🙋 Работает в группе.", reply_markup=nav_menu())
    elif off:
        await core._unlink_me(message, p.storage, p.query.bot, p.query.from_user)
    else:
        player = await _pick_player(p, message, account)
        if player is not None:
            await core._link_me(message, p.storage, p.query.bot, p.query.from_user, player)


async def _pick_match(p: _Press, message, account: str) -> None:
    player = None if account == "last" else p.storage.get_player(message.chat.id, account)
    await core.do_match(message, p.storage, p.od, player.display_name if player else None, None, p.stratz)


async def _pick_setmmr(p: _Press, message, account: str) -> None:
    player = await _pick_player(p, message, account)
    if player is not None:
        await core._prompt_setmmr(message, player)


PICK_ACTIONS = {
    "matches": lambda p, m, a: core.do_match_list(m, p.storage, a, 0),
    "heroes": lambda p, m, a: core.do_player_heroes(m, p.storage, p.od, a, "all", p.stratz),
    "roles": lambda p, m, a: core.do_roles(m, p.storage, p.od, a, "all", p.stratz),
    "player": lambda p, m, a: core.do_player_card(m, p.storage, p.od, a, p.stratz),
    "steam": lambda p, m, a: core.do_steam(m, p.storage, p.od, a),
    "double": _pick_double,
    "remove": _pick_remove,
    "rmyes": _pick_remove_yes,
    "me": _pick_me,
    "meoff": lambda p, m, a: _pick_me(p, m, a, off=True),
    "match": _pick_match,
    "setmmr": _pick_setmmr,
}


async def _cb_pick(p: _Press) -> None:
    handler = PICK_ACTIONS.get(p.arg(0)) if len(p.args) == 2 else None
    if handler is not None:
        await handler(p, core._InPlace(p.message), p.args[1])


CALLBACKS = {
    "x": _cb_close, "s": _cb_settings, "r": _cb_records, "c": _cb_contest, "mx": _cb_full_match, "lk": _cb_lookup,
    "ml": lambda p: _cb_matches(p, "ml"), "md": lambda p: _cb_matches(p, "md"), "mv": lambda p: _cb_matches(p, "mv"),
    "tx": lambda p: _cb_text(p, "tx"), "mt": lambda p: _cb_text(p, "mt"), "g": _cb_graph, "m": _cb_menu,
    "pp": _cb_pick, "mu": _cb_matchups, "hp": lambda p: _cb_player_period(p, "hp"),
    "rp": lambda p: _cb_player_period(p, "rp"),
}


@router.callback_query(lambda c: bool(c.data) and c.data.split(":")[0] in CALLBACKS)
async def on_callback(query: CallbackQuery, storage: Storage, od: OpenDota, stratz=None) -> None:
    """Нажатие кнопки: убираем «часики» и передаём обработчику из таблицы CALLBACKS по префиксу callback_data."""
    await query.answer()
    if query.message is None:
        return
    kind, args = parse_callback(query.data)
    handler = CALLBACKS.get(kind)
    if handler is not None:
        await handler(_Press(query, storage, od, stratz, args))
