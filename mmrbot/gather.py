"""Сбор пати: `/go [текст]` — сообщение с кнопками «иду / через 15 минут / пас».

Привязанных через /me игроков, которые ещё не ответили, бот упоминает: им придёт уведомление. Ответы хранятся в
базе, поэтому кнопки работают и после перезапуска бота. В чате открыт один сбор — новый /go закрывает прежний.
Через TTL сбор считается законченным: нажатие кнопки уже ничего не меняет и убирает клавиатуру.
"""
from __future__ import annotations

import html
import time
from typing import Optional

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from mmrbot.keyboards import parse_callback
from mmrbot.storage import Gather, Storage

router = Router()

TTL = 3 * 3600  # сколько сбор принимает ответы
PARTY = 5  # игроков в пати
NOTE_LIMIT = 120  # длина пояснения («в 21:00, ранкед»)
CHOICES = (("go", "✅ Иду"), ("late", "⏱ Через 15 мин"), ("no", "❌ Пас"))
_KNOWN = {key for key, _ in CHOICES}


def is_expired(call: Gather, now: int) -> bool:
    return now - call.created_ts >= TTL


def buttons(call_id: int) -> InlineKeyboardMarkup:
    """Три кнопки ответа в один ряд: `go:<id сбора>:<go|late|no>`."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data=f"go:{call_id}:{key}") for key, label in CHOICES
    ]])


def _mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


def render(call: Gather, votes: list[dict], linked: dict[int, str], now: int) -> str:
    """Текст сбора: кто идёт, кто позже, кто пас, сколько собрано и кого ещё ждём (упоминанием).

    linked — {Telegram-id: ник игрока} привязанных через /me: их показываем по нику, а молчащих зовём.
    """
    def who(vote: dict) -> str:
        return html.escape(linked.get(vote["user_id"]) or vote["name"])

    lines = [f"🎮 <b>Сбор пати!</b> · {html.escape(call.by_name or 'кто-то')}"]
    if call.note:
        lines.append(f"<i>{html.escape(call.note)}</i>")
    going = [v for v in votes if v["choice"] == "go"]
    lines.append(f"\nСобрано {len(going)}/{PARTY}")
    for key, label in CHOICES:
        group = [v for v in votes if v["choice"] == key]
        if group:
            lines.append(f"{label} ({len(group)}): " + ", ".join(who(v) for v in group))
    expired = is_expired(call, now)
    voted = {v["user_id"] for v in votes}
    waiting = [(uid, name) for uid, name in linked.items() if uid not in voted]
    if waiting and not expired:
        lines.append("⏳ Ждём: " + ", ".join(_mention(uid, name) for uid, name in waiting))
    if len(going) >= PARTY and not expired:
        lines.append("\n🔥 Пати собрана — заходим!")
    if expired:
        lines.append("\n⌛ Сбор закончился.")
    return "\n".join(lines)


def linked_players(storage: Storage, chat_id: int) -> dict[int, str]:
    return {p.tg_user_id: p.display_name for p in storage.list_players(chat_id) if p.tg_user_id}


async def _clear_keyboard(bot, chat_id: int, message_id: Optional[int]) -> None:
    if message_id is None or bot is None:
        return
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
    except Exception:
        pass  # сообщение удалено или слишком старое — кнопки и так не нужны


@router.message(Command("go"))
async def cmd_go(message: Message, command: CommandObject, storage: Storage) -> None:
    """`/go [текст]` — позвать пати играть. Автор сразу отмечен «иду»; новый сбор закрывает прежний."""
    user = getattr(message, "from_user", None)
    if user is None:
        await message.answer("🎮 Сбор пати запускается от имени пользователя (не анонимного админа).")
        return
    chat_id = message.chat.id
    now = int(time.time())
    note = " ".join((command.args or "").split())[:NOTE_LIMIT] or None
    linked = linked_players(storage, chat_id)
    name = linked.get(user.id) or user.full_name
    for old in storage.close_gathers(chat_id):
        await _clear_keyboard(getattr(message, "bot", None), chat_id, old.message_id)
    call = storage.create_gather(chat_id, now, user.id, name, note)
    storage.vote_gather(call.id, user.id, name, "go", now)
    # автора в «ждём» не зовём — он уже ответил (render берёт ждущих из тех, кто не голосовал)
    text = render(call, storage.gather_votes(call.id), linked, now)
    sent = await message.answer(text, parse_mode="HTML", reply_markup=buttons(call.id))
    message_id = getattr(sent, "message_id", None)
    if message_id is not None:
        storage.set_gather_message(call.id, message_id)


@router.callback_query(lambda c: bool(c.data) and c.data.startswith("go:"))
async def on_button(query: CallbackQuery, storage: Storage) -> None:
    """Нажатие «иду / через 15 мин / пас»: записывает ответ и перерисовывает сообщение."""
    message, user = query.message, getattr(query, "from_user", None)
    _, args = parse_callback(query.data)
    try:
        call_id, choice = int(args[0]), args[1]
    except (IndexError, ValueError):
        await query.answer()
        return
    call = storage.get_gather(call_id)
    if message is None or user is None or call is None or choice not in _KNOWN or message.chat.id != call.chat_id:
        await query.answer()
        return
    await query.answer()
    now = int(time.time())
    if call.closed:  # заменён новым сбором: просто убираем кнопки
        await _edit_markup_none(message)
        return
    linked = linked_players(storage, call.chat_id)
    if is_expired(call, now):
        storage.close_gather(call.id)
        await _edit(message, render(call, storage.gather_votes(call.id), linked, now), None)
        return
    storage.vote_gather(call.id, user.id, linked.get(user.id) or user.full_name, choice, now)
    await _edit(message, render(call, storage.gather_votes(call.id), linked, now), buttons(call.id))


async def _edit_markup_none(message) -> None:
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


async def _edit(message, text: str, markup) -> None:
    try:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        pass  # «message is not modified» или сообщение удалено — ответ уже сохранён
