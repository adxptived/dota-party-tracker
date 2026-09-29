"""aiogram-хендлеры команд бота."""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BotCommand, Message

from mmrbot import commands as cmd
from mmrbot.formatting import render_player_list
from mmrbot.ids import parse_account_id
from mmrbot.opendota import OpenDota
from mmrbot.service import (
    render_board,
    render_heroes_board,
    render_player_board,
    render_together_board,
    split_message,
)
from mmrbot.storage import Storage
from mmrbot.tracker import refresh_player

router = Router()

# Меню команд (всплывает по «/», особенно полезно в группах).
BOT_COMMANDS = [
    BotCommand(command="stats", description="🏆 Лидерборд пати + награды"),
    BotCommand(command="today", description="📅 Активность за сутки"),
    BotCommand(command="together", description="🤝 Совместные игры пати"),
    BotCommand(command="heroes", description="🦸 Топ героев участников"),
    BotCommand(command="player", description="🎮 Карточка игрока: /player Имя"),
    BotCommand(command="add", description="➕ Добавить игрока: /add ссылка Имя MMR"),
    BotCommand(command="list", description="👥 Список игроков"),
    BotCommand(command="setmmr", description="🎯 Задать/поправить MMR: /setmmr Имя 5400"),
    BotCommand(command="setstep", description="⚙️ Шаг оценки MMR за игру"),
    BotCommand(command="settime", description="⏰ Час ежедневного дайджеста (МСК)"),
    BotCommand(command="remove", description="🗑 Убрать игрока: /remove Имя"),
    BotCommand(command="help", description="ℹ️ Справка"),
]


async def set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)

HELP_TEXT = (
    "🎮 Трекер MMR/статистики Dota 2 (данные OpenDota)\n\n"
    "Слежу за ранкед-играми участников с момента добавления: игры, оценка ±MMR, "
    "текущий MMR (≈), медаль, винрейт, KDA.\n\n"
    "⚠️ Точного MMR Dota 2 не отдаёт — он оценивается (±шаг за игру). Стартовый MMR "
    "вводишь ты, коррекция — /setmmr.\n"
    "⚠️ Данные видны, только если у игрока в Dota включены «Открытые данные матчей».\n\n"
    "Команды:\n"
    "/add <ссылка или ID> [Имя] [MMR] — добавить аккаунт\n"
    "   напр.: /add dotabuff.com/players/123456 Вася 5400\n"
    "/list — список участников\n"
    "/remove <Имя> — убрать\n"
    "/setmmr <Имя> <MMR> — задать/поправить MMR\n"
    "/setstep <шаг> — шаг оценки MMR за игру (по умолчанию 25)\n"
    "/settime <час> — время ежедневного дайджеста (МСК)\n"
    "/stats — полный лидерборд (+ награды пати)\n"
    "/today — активность за сутки\n"
    "/together — совместные игры пати\n"
    "/heroes — топ героев участников\n"
    "/player <Имя> — карточка игрока (GPM, соло/пати, время суток…)\n"
)


async def _reply_board(message: Message, coro) -> None:
    """Общий помощник: собрать текст (с обработкой ошибок сети) и отправить чанками."""
    try:
        text = await coro
    except Exception:
        logging.getLogger(__name__).exception("Ошибка сборки статистики для чата %s", message.chat.id)
        await message.answer("⚠️ Не удалось получить данные OpenDota, попробуй ещё раз чуть позже.")
        return
    if text is None:
        await message.answer("Не нашёл игрока. Смотри /list.")
        return
    for chunk in split_message(text):
        await message.answer(chunk)


@router.message(Command("start"))
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("add"))
async def cmd_add(message: Message, command: CommandObject, storage: Storage, od: OpenDota) -> None:
    try:
        identifier, name, mmr = cmd.parse_add_args(command.args or "")
        account_id = parse_account_id(identifier)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return

    storage.get_or_create_chat(message.chat.id)
    now = int(time.time())

    if not name:
        try:
            profile = await asyncio.to_thread(od.get_profile, account_id)
            name = profile.get("personaname") or f"id{account_id}"
        except Exception:
            name = f"id{account_id}"

    try:
        player = storage.add_player(message.chat.id, account_id, name, mmr, now, now)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return

    try:
        await asyncio.to_thread(refresh_player, storage, od, player, now)
    except Exception:
        pass  # первичная подгрузка не критична — досчитается в /stats

    mmr_note = f", старт MMR ≈ {mmr}" if mmr is not None else " (MMR не задан — добавь через /setmmr)"
    await message.answer(
        f"✅ Добавил {name} (id {account_id}){mmr_note}.\n"
        f"Отсчёт ранкед-игр — с этого момента. /stats — таблица."
    )


@router.message(Command("list"))
async def cmd_list(message: Message, storage: Storage) -> None:
    players = storage.list_players(message.chat.id)
    await message.answer(render_player_list(players))


@router.message(Command("remove"))
async def cmd_remove(message: Message, command: CommandObject, storage: Storage) -> None:
    name = (command.args or "").strip()
    if not name:
        await message.answer("Формат: /remove Имя")
        return
    ok = storage.remove_player(message.chat.id, name)
    await message.answer("🗑 Убрал." if ok else "Не нашёл такого игрока. Смотри /list.")


@router.message(Command("setmmr"))
async def cmd_setmmr(message: Message, command: CommandObject, storage: Storage) -> None:
    try:
        name, mmr = cmd.parse_name_and_mmr(command.args or "")
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    player = storage.get_player(message.chat.id, name)
    if player is None:
        await message.answer("Не нашёл игрока. Смотри /list.")
        return
    storage.set_player_anchor(player.id, mmr, int(time.time()))
    await message.answer(
        f"✅ MMR {player.display_name} переякорен на ≈ {mmr}. Дальше считаю оценку от этой точки."
    )


@router.message(Command("setstep"))
async def cmd_setstep(message: Message, command: CommandObject, storage: Storage) -> None:
    try:
        step = cmd.parse_step(command.args or "")
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    storage.set_chat_step(message.chat.id, step)
    await message.answer(f"✅ Шаг оценки MMR: ±{step} за ранкед-игру.")


@router.message(Command("settime"))
async def cmd_settime(message: Message, command: CommandObject, storage: Storage) -> None:
    try:
        hour = cmd.parse_hour(command.args or "")
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    storage.set_chat_digest_hour(message.chat.id, hour)
    await message.answer(f"✅ Ежедневный дайджест в {hour:02d}:00 (МСК).")


@router.message(Command("stats"))
async def cmd_stats(message: Message, storage: Storage, od: OpenDota) -> None:
    if not storage.list_players(message.chat.id):
        await message.answer("В этом чате пока нет игроков. Добавь: /add <ссылка или ID> Имя [MMR]")
        return
    await message.answer("⏳ Собираю статистику из OpenDota…")
    await _reply_board(message, render_board(storage, od, message.chat.id, today_only=False, refresh=True))


@router.message(Command("today"))
async def cmd_today(message: Message, storage: Storage, od: OpenDota) -> None:
    if not storage.list_players(message.chat.id):
        await message.answer("В этом чате пока нет игроков. Добавь: /add <ссылка или ID> Имя [MMR]")
        return
    await message.answer("⏳ Собираю сегодняшнюю статистику…")
    await _reply_board(message, render_board(storage, od, message.chat.id, today_only=True, refresh=True))


@router.message(Command("together"))
async def cmd_together(message: Message, storage: Storage, od: OpenDota) -> None:
    if not storage.list_players(message.chat.id):
        await message.answer("В этом чате пока нет игроков. Добавь: /add <ссылка или ID> Имя [MMR]")
        return
    await message.answer("⏳ Считаю совместные игры…")
    await _reply_board(message, render_together_board(storage, od, message.chat.id))


@router.message(Command("heroes"))
async def cmd_heroes(message: Message, storage: Storage, od: OpenDota) -> None:
    if not storage.list_players(message.chat.id):
        await message.answer("В этом чате пока нет игроков. Добавь: /add <ссылка или ID> Имя [MMR]")
        return
    await message.answer("⏳ Собираю героев…")
    await _reply_board(message, render_heroes_board(storage, od, message.chat.id))


@router.message(Command("player"))
async def cmd_player(message: Message, command: CommandObject, storage: Storage, od: OpenDota) -> None:
    name = (command.args or "").strip()
    if not name:
        await message.answer("Формат: /player Имя (например: /player Вася)")
        return
    await message.answer(f"⏳ Собираю карточку {name}…")
    await _reply_board(message, render_player_board(storage, od, message.chat.id, name))
