"""Дабл-дауны: игра с жетоном удвоения меняет MMR на два шага, а не на один.

API жетон не отдаёт, поэтому пометку ставят сами игроки: кнопкой «×2» под оповещением о матче
или командой `/double [имя] [id матча]`. Повторное нажатие снимает пометку.
"""
from __future__ import annotations

import html
import time
from typing import Optional

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from mmrbot import commands as cmd
from mmrbot import stats
from mmrbot.heroes import hero_name
from mmrbot.keyboards import alert_buttons, nav_menu, parse_callback
from mmrbot.storage import Player, Storage
from mmrbot.texts import NOT_FOUND
from mmrbot.tracker import build_player_summary

router = Router()

NO_MATCH = "🔍 У игрока нет такого ранкед-матча."
WHO = "Чей матч отметить? Формат: /double имя [id матча] — или привяжите себя: /me ник"


def toggle(storage: Storage, chat_id: int, player: Player, match_id: Optional[int], now: int) -> Optional[dict]:
    """Переключить пометку «×2» у матча игрока (match_id=None — у последнего). None — матча нет.

    → {match, on, delta, plain, mmr}: строка матча, новое состояние, ±MMR за матч теперь и без удвоения, текущая оценка.
    """
    if match_id is None:
        history = storage.get_matches(player.id)
        if not history:
            return None
        match_id = history[-1]["match_id"]
    state = storage.set_double_down(player.id, match_id)
    if state is None:
        return None
    chat = storage.get_or_create_chat(chat_id)
    match = storage.get_match(player.id, match_id)
    summary = build_player_summary(storage, chat, storage.get_player_by_id(player.id) or player, now)
    return {
        "match": match, "on": state, "delta": stats.match_mmr_delta(match, chat.mmr_step),
        "plain": stats.match_mmr_delta({**match, "double_down": 0}, chat.mmr_step), "mmr": summary.current_mmr,
    }


def describe(name: str, result: dict, short: bool = False) -> str:
    """Что изменилось: коротко (всплывающая подсказка кнопки, без разметки) или строкой ответа на команду (HTML)."""
    mmr = f", ≈{result['mmr']} MMR" if result["mmr"] is not None else ""
    if short:
        if result["on"]:
            return f"{name}: дабл-даун, {result['delta']:+d} вместо {result['plain']:+d}{mmr}"
        return f"{name}: дабл-даун снят, {result['delta']:+d}{mmr}"
    match = result["match"]
    outcome = "победа" if stats.is_win(match["player_slot"], match["radiant_win"]) else "поражение"
    what = f"матч {match['match_id']} ({html.escape(hero_name(match.get('hero_id')))}, {outcome})"
    if result["on"]:
        return (f"✅ <b>{html.escape(name)}</b>: {what} засчитан с дабл-дауном — "
                f"{result['delta']:+d} вместо {result['plain']:+d}{mmr}.\nСнять пометку — той же командой.")
    return f"↩️ <b>{html.escape(name)}</b>: {what} — дабл-даун снят, {result['delta']:+d}{mmr}."


def refreshed_markup(storage: Storage, chat_id: int, match_id: int, markup):
    """Клавиатура оповещения с актуальными пометками «×2»: игроки берутся из её же кнопок."""
    marks = []
    for row in getattr(markup, "inline_keyboard", None) or []:
        for button in row:
            kind, args = parse_callback(getattr(button, "callback_data", None) or "")
            if kind != "dd" or len(args) != 2:
                continue
            player = storage.get_player(chat_id, args[1])
            match = storage.get_match(player.id, match_id) if player else None
            if player is not None and match is not None:
                marks.append((player.account_id, player.display_name, bool(match["double_down"])))
    return alert_buttons(match_id, marks)


@router.callback_query(lambda c: bool(c.data) and c.data.startswith("dd:"))
async def on_double_button(query: CallbackQuery, storage: Storage) -> None:
    """«×2 Имя» под оповещением о матче: переключает дабл-даун и перерисовывает кнопки."""
    message = query.message
    _, args = parse_callback(query.data)
    try:
        match_id, account = int(args[0]), args[1]
    except (IndexError, ValueError):
        await query.answer()
        return
    player = storage.get_player(message.chat.id, account) if message is not None else None
    if player is None:
        await query.answer("Игрок уже удалён из чата.", show_alert=False)
        return
    result = toggle(storage, message.chat.id, player, match_id, int(time.time()))
    if result is None:
        await query.answer("Матч не найден.", show_alert=False)
        return
    await query.answer(describe(player.display_name, result, short=True)[:200])
    try:
        await message.edit_reply_markup(
            reply_markup=refreshed_markup(storage, message.chat.id, match_id, getattr(message, "reply_markup", None)))
    except Exception:
        pass  # «not modified» или старое сообщение — пометка уже сохранена


@router.message(Command("double", "x2", "dd"))
async def cmd_double(message: Message, command: CommandObject, storage: Storage) -> None:
    """`/double [имя] [id матча]` — отметить (или снять) дабл-даун; без имени — свой матч, без id — последний."""
    match_id, name = cmd.parse_match_args(command.args or "")
    if name is None:
        user = getattr(message, "from_user", None)
        mine = next((p for p in storage.list_players(message.chat.id) if user and p.tg_user_id == user.id), None)
        if mine is None:
            await message.answer(WHO)
            return
        player = mine
    else:
        player = storage.get_player(message.chat.id, name)
        if player is None:
            await message.answer(NOT_FOUND)
            return
    result = toggle(storage, message.chat.id, player, match_id, int(time.time()))
    if result is None:
        await message.answer(NO_MATCH)
        return
    await message.answer(describe(player.display_name, result), parse_mode="HTML", reply_markup=nav_menu())
