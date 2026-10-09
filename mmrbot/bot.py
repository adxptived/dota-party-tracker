"""aiogram-хендлеры команд бота."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time

import re
from collections import OrderedDict
from typing import Optional

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BotCommand, BufferedInputFile, CallbackQuery, ForceReply, InlineKeyboardButton, InputMediaPhoto, Message

from mmrbot import commands as cmd
from mmrbot import perf
from mmrbot.boards import ImageBoard
from mmrbot.access import DENIED, is_chat_admin, may_manage
from mmrbot.formatting import render_mmr_set, render_player_list, render_settings, render_steam_profile, tz_label
from mmrbot.health import log_network_error
from mmrbot.heroes import find_hero, hero_name
from mmrbot.ids import resolve_account_id
from mmrbot.keyboards import CATEGORIES, STEPS, category_menu, category_title, TIMEZONES, confirm_remove, graph_buttons, list_actions, match_photo_buttons, player_actions, with_text_button, without_text_button, stats_tabs, main_menu, nav_menu, records_buttons, contest_buttons, settings_menu, parse_callback, period_buttons, players_picker
from mmrbot.opendota import OpenDota
from mmrbot.progress import DeferredStatus
from mmrbot.service import (
    STATS_MODES,
    contest_board,
    stats_board,
    compare_board,
    render_compare_board,
    hero_board,
    render_hero_board,
    render_graph_board,
    records_board,
    render_contest_text,
    render_records_board,
    heroes_board,
    render_heroes_board,
    match_board,
    player_board,
    player_heroes_board,
    render_match_board,
    render_player_board,
    render_player_heroes_board,
    render_roles_board,
    together_board,
    render_together_board,
    split_message,
)
from mmrbot.status import collect_status, render_status
from mmrbot.storage import Storage
from mmrbot.tags import auto_link_user, clear_member_tag, link_adder, sync_member_tags
from mmrbot.texts import FAILED, NOT_FOUND as NOT_FOUND_TEXT, NO_PLAYERS, TERMS, WAIT
from mmrbot.ranks import rank_label
from mmrbot.tracker import build_leaderboard, refresh_player, set_player_mmr

router = Router()
log = logging.getLogger(__name__)

PERIODS_KEYS = {"day", "week", "month", "year", "all"}


async def _can_manage(message, storage: Storage, user=None, bot=None) -> bool:
    """Право менять настройки/удалять игроков; при отказе отвечает сам. user — кто нажал кнопку (у команды — автор)."""
    actor = user if user is not None else getattr(message, "from_user", None)
    sender_chat = None if user is not None else getattr(message, "sender_chat", None)
    if await may_manage(bot or getattr(message, "bot", None), storage, message.chat, actor, sender_chat):
        return True
    await message.answer(DENIED)
    return False


class PerfMiddleware(BaseMiddleware):
    """Замер каждой команды/кнопки: строка `perf cmd=… total=… refresh=… build=… render=… send=…` в лог."""

    async def __call__(self, handler, event, data):
        trace = perf.begin()
        try:
            return await handler(event, data)
        finally:
            chat = getattr(event, "chat", None) or getattr(getattr(event, "message", None), "chat", None)
            perf.finish(trace, perf.label(event), getattr(chat, "id", None))


class DeleteCommandMiddleware(BaseMiddleware):
    """После ответа на команду удаляет само сообщение с командой (/menu и т.п.), чтобы не засорять чат.

    Без права «удалять сообщения» (в группе) или у старых сообщений — молча пропускаем.
    """

    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        finally:
            if (getattr(event, "text", None) or "").startswith("/"):
                try:
                    await event.delete()
                except Exception:
                    pass


router.message.middleware(DeleteCommandMiddleware())


class AutoLinkMiddleware(BaseMiddleware):
    """В чатах с включёнными тегами привязывает автора сообщения к игроку с совпавшим ником (без /me)."""

    async def __call__(self, handler, event, data):
        try:
            storage = data.get("storage")
            user = getattr(event, "from_user", None)
            if storage is not None and user is not None and event.chat.type != "private"                     and storage.get_or_create_chat(event.chat.id).tag_mmr:
                auto_link_user(storage, event.chat.id, user)
        except Exception:
            logging.getLogger(__name__).warning("Автопривязка не удалась", exc_info=True)
        return await handler(event, data)


router.message.middleware(AutoLinkMiddleware())

# Меню команд (всплывает по «/», особенно полезно в группах).
BOT_COMMANDS = [
    BotCommand(command="stats", description="🏆 Рейтинг и награды"),
    BotCommand(command="today", description="📅 Сегодня"),
    BotCommand(command="compare", description="⚡ Кто сильнее"),
    BotCommand(command="together", description="🤝 Игры вместе"),
    BotCommand(command="menu", description="📋 Меню"),
    BotCommand(command="heroes", description="🦸 Герои и позиции"),
    BotCommand(command="roles", description="🧭 Позиции игрока"),
    BotCommand(command="last", description="🏁 Последний матч"),
    BotCommand(command="match", description="🎮 Разбор матча"),
    BotCommand(command="player", description="🪪 Карточка игрока"),
    BotCommand(command="records", description="🌟 Рекорды пати"),
    BotCommand(command="graph", description="📈 График MMR"),
    BotCommand(command="achievements", description="🏅 Соревнование чата"),
    BotCommand(command="steam", description="🎭 Steam-профиль"),
    BotCommand(command="add", description="➕ Добавить игрока"),
    BotCommand(command="list", description="👥 Список игроков"),
    BotCommand(command="settings", description="⚙️ Настройки"),
    BotCommand(command="setmmr", description="✏️ Задать MMR"),
    BotCommand(command="double", description="✖️ Отметить игру с дабл-дауном (×2 MMR)"),
    BotCommand(command="setstep", description="⚙️ Шаг MMR за игру"),
    BotCommand(command="settime", description="⏰ Час сводки"),
    BotCommand(command="me", description="🙋 Привязать себя к игроку"),
    BotCommand(command="tags", description="🏷️ Теги с MMR (вкл/выкл)"),
    BotCommand(command="remove", description="🗑️ Удалить игрока"),
    BotCommand(command="status", description="🩺 Состояние бота (админам)"),
    BotCommand(command="help", description="📖 Справка"),
]


async def set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)

HELP_TEXT = (
    '📖 Трекер ранкед-игр Dota 2 для пати\n\n'
    'Начать: /add ссылка_или_ID [имя] [MMR]\n'
    'Пример: /add dotabuff.com/players/123456 Вася 5400\n\n'
    'Смотреть:\n'
    '/stats — рейтинг и награды (сегодня, неделя, месяц)\n'
    '/player имя — карточка игрока\n'
    '/heroes [имя или герой] — герои\n'
    '/last [игрок] — последний матч\n'
    '/match [id] — разбор матча\n'
    '/together — игры вместе\n'
    '/compare — кто сильнее\n'
    '/records · /graph · /achievements (соревнование чата)\n\n'
    'Управлять: /list · /remove · /setmmr · /settings\n'
    '/double [имя] — игра с дабл-дауном (±2 шага MMR)\n'
    '/menu — всё кнопками, там же «Термины»\n\n'
    '≈MMR — оценка: старт ± шаг за игру, точный MMR Dota не отдаёт.\n'
    'Нужна опция «Выставлять публичные данные матчей».'
)


async def _delete(message) -> None:
    """Удалить сообщение бота (старше 48ч или без прав — молча пропускаем)."""
    if message is None:
        return
    try:
        await message.delete()
    except Exception:
        pass


class _InPlace:
    """Обёртка над сообщением с нажатой кнопкой: `answer` правит его на месте, а не шлёт новое.

    Так чат не засоряется — каждый клик меняет одно и то же сообщение. Не получилось отредактировать
    (фото, ForceReply, старое сообщение) — убираем старое и шлём новое. Дополнительные куски длинного
    текста — через `answer_new`.
    """

    def __init__(self, message: Message) -> None:
        self._m = message

    def __getattr__(self, name):
        return getattr(self._m, name)

    async def answer_new(self, *args, **kwargs):
        return await self._m.answer(*args, **kwargs)

    async def answer(self, text: str, **kwargs):
        markup = kwargs.get("reply_markup")
        if markup is None:
            kwargs["reply_markup"] = nav_menu()  # без кнопок сообщение стало бы тупиком
        if not isinstance(markup, ForceReply) and not getattr(self._m, "photo", None):
            try:
                await self._m.edit_text(text, **kwargs)
                return self._m
            except Exception as exc:
                if "not modified" in str(exc):
                    return self._m
        await _delete(self._m)
        return await self._m.answer(text, **kwargs)

    async def answer_photo(self, *args, **kwargs):
        sent = await self._m.answer_photo(*args, **kwargs)
        await _delete(self._m)  # «Считаю…» убираем, когда картинка уже отправлена
        return sent


async def _progress(message: Message, text: str, action: str = "typing") -> DeferredStatus:
    """Отложенное «⏳ Считаю…»: быстрый ответ обходится без статуса вовсе (экономим 2 запроса к Telegram).

    Через ~0.7 с — индикатор действия (action: «печатает…» / «отправляет фото»), через ~2 с — само сообщение.
    На месте кнопки (_InPlace) статус правит это же сообщение и не удаляется — его заменит отчёт.
    """
    chat_id = message.chat.id

    async def send_action():
        await message.bot.send_chat_action(chat_id, action)

    in_place = isinstance(message, _InPlace)
    # Под картинкой (кнопка периода на карточке) текстовый статус затёр бы саму карточку — только индикатор действия.
    over_photo = in_place and bool(getattr(message, "photo", None))
    return DeferredStatus(send_action, None if over_photo else (lambda: message.answer(text)), delete_sent=not in_place)


async def _send_chunks(message: Message, text: str, markup=None) -> None:
    chunks = split_message(text)
    send_more = getattr(message, "answer_new", message.answer)
    for i, chunk in enumerate(chunks):
        send = message.answer if i == 0 else send_more
        await send(chunk, parse_mode="HTML", reply_markup=markup if i == len(chunks) - 1 else None)


async def _reply_board(message: Message, coro, status=None, markup=None) -> None:
    """Общий помощник: собрать текст (с обработкой ошибок сети) и отправить чанками.

    status — временное сообщение «Формирование…» (удаляется); под отчётом кнопки «В меню»/«Закрыть».
    """
    try:
        text = await coro
    except Exception:
        logging.getLogger(__name__).exception("Ошибка сборки статистики для чата %s", message.chat.id)
        await _delete(status)
        await message.answer(FAILED, reply_markup=nav_menu())
        return
    await _delete(status)
    if text is None:
        await message.answer(NOT_FOUND_TEXT, reply_markup=nav_menu())
        return
    await _send_chunks(message, text, markup or nav_menu())


async def _show_text(message: Message, text: str, markup, edit: bool) -> None:
    """Текстовый отчёт с кнопками. edit — нажата кнопка вкладки/периода: правим то же сообщение, а не плодим новые;
    под фото (картинки отключили настройкой) — шлём текст и убираем старую картинку."""
    if not isinstance(message, _InPlace):  # _InPlace и так правит сообщение на месте
        photo = bool(getattr(message, "photo", None))
        if edit and not photo and len(split_message(text)) == 1:
            try:
                await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
                return
            except Exception as exc:
                if "not modified" in str(exc):
                    return
        await _send_chunks(message, text, markup)
        if edit and photo:
            await _delete(message)
        return
    await _send_chunks(message, text, markup)


_file_ids: OrderedDict = OrderedDict()  # sha1 PNG → file_id уже отправленной картинки (B7)
FILE_ID_LIMIT = 256


def _remember_file_id(digest: str, sent) -> None:
    """Запомнить file_id самого крупного размера из ответа Telegram (у фейков и True ответа нет — тогда ничего)."""
    try:
        file_id = sent.photo[-1].file_id
    except (AttributeError, IndexError, TypeError):
        return
    if isinstance(file_id, str) and file_id:
        _file_ids[digest] = file_id
        _file_ids.move_to_end(digest)
        while len(_file_ids) > FILE_ID_LIMIT:
            _file_ids.popitem(last=False)


async def _send_photo(message: Message, photo, caption, markup, edit: bool):
    """Показать картинку: edit — заменить на месте (не вышло — новая, прежняя убирается), иначе новое сообщение."""
    if edit and getattr(message, "photo", None):
        try:
            return await message.edit_media(InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML"), reply_markup=markup)
        except Exception as exc:
            if "not modified" in str(exc):
                return None
            if isinstance(photo, str):  # file_id отвергнут — пусть вызывающий пробует загрузить PNG
                raise
            sent = await message.answer_photo(photo, caption=caption, parse_mode="HTML", reply_markup=markup)
            await _delete(message)
            return sent
    sent = await message.answer_photo(photo, caption=caption, parse_mode="HTML", reply_markup=markup)
    if edit:
        await _delete(message)
    return sent


async def _reply_image(message: Message, board: ImageBoard, markup, status=None, edit: Optional[bool] = None) -> None:
    """Картинка + подпись + кнопки; не собралась (или в чате выбраны отчёты текстом) или Telegram не принял —
    тот же отчёт текстом, с теми же вкладками/периодами, но без «📝 Текстом».

    edit=True — под сообщением-фото нажата кнопка (период и т.п.): картинка меняется на месте (edit_media);
    не вышло (старое сообщение) — шлём новую и убираем прежнюю.
    """
    if edit is None:
        edit = isinstance(message, _InPlace)  # кнопка на сообщении: правим его на месте
    if board.png is not None:
        digest = hashlib.sha1(board.png).hexdigest()
        known = _file_ids.get(digest)
        for photo in ([known] if known else []) + [BufferedInputFile(board.png, filename="card.png")]:
            try:
                sent = await _send_photo(message, photo, board.caption, markup, bool(edit))
            except Exception:
                if photo is known:  # Telegram не принял старый file_id — грузим картинку заново
                    _file_ids.pop(digest, None)
                    log.info("file_id картинки устарел — отправляем PNG заново")
                    continue
                log.warning("Не удалось отправить картинку — шлём текстом", exc_info=True)
                break
            _remember_file_id(digest, sent)
            await _delete(status)
            return
    await _delete(status)
    await _show_text(message, board.text, without_text_button(markup) if markup is not None else nav_menu(), bool(edit))


async def _image_report(message: Message, make_board, markup, what: str, edit: Optional[bool] = None) -> None:
    """Общий путь «отчёт картинкой»: индикатор → сборка борда → картинка с кнопками (не вышло — текстом).

    make_board — корутина, дающая ImageBoard; markup — кнопки под отчётом; what — для лога при сбое сборки.
    """
    status = await _progress(message, WAIT, "upload_photo")
    try:
        board = await make_board
    except Exception:
        log.exception("Ошибка сборки %s для чата %s", what, message.chat.id)
        await _delete(status)
        await message.answer(FAILED, reply_markup=nav_menu())
        return
    await _reply_image(message, board, markup, status, edit=edit)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())


@router.message(Command("start"))
@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer("📋 Выберите раздел:", reply_markup=main_menu())


ADD_PROMPT = "➕ Ответьте ссылкой или ID. Имя и MMR — по желанию."
ADD_EXAMPLE = "Пример: dotabuff.com/players/123456 Вася 5400"
SETMMR_PROMPT = "✏️ Задать MMR игрока {name} (id {account}): ответьте числом."
HERO_PROMPT = "🔎 Ответьте названием героя, например Axe."
MATCHID_PROMPT = "🔢 Ответьте ID матча (8+ цифр)."
_SETMMR_RE = re.compile(r"^✏️ Задать MMR игрока .+ \(id (\d+)\)")


async def _prompt_add(message: Message) -> None:
    await message.answer(
        f"{ADD_PROMPT}\n{ADD_EXAMPLE}",
        reply_markup=ForceReply(force_reply=True, input_field_placeholder="ссылка или ID  Имя  MMR"),
    )


async def _prompt_hero(message: Message) -> None:
    await message.answer(HERO_PROMPT, reply_markup=ForceReply(force_reply=True, input_field_placeholder="Axe"))


async def _prompt_matchid(message: Message) -> None:
    await message.answer(MATCHID_PROMPT, reply_markup=ForceReply(force_reply=True, input_field_placeholder="7812345678"))


async def _ask_match(message: Message, storage: Storage) -> None:
    extra = [
        [InlineKeyboardButton(text="🕘 Последний в чате", callback_data="pp:match:last")],
        [InlineKeyboardButton(text="🔢 По ID матча", callback_data="m:matchid")],
    ]
    await message.answer(
        "Чей матч показать?", reply_markup=players_picker(storage.list_players(message.chat.id), "match", extra=extra)
    )


async def _prompt_setmmr(message: Message, player) -> None:
    await message.answer(
        SETMMR_PROMPT.format(name=player.display_name, account=player.account_id),
        reply_markup=ForceReply(force_reply=True, input_field_placeholder="например 5300"),
    )


@router.message(Command("add"))
async def cmd_add(
    message: Message, command: CommandObject, storage: Storage, od: OpenDota, stratz=None
) -> None:
    if not (command.args or "").strip():
        await _prompt_add(message)
        return
    await do_add(message, storage, od, command.args or "", stratz)


async def do_add(message: Message, storage: Storage, od: OpenDota, args: str, stratz=None) -> None:
    try:
        identifier, name, mmr = cmd.parse_add_args(args)
        account_id = await asyncio.to_thread(resolve_account_id, identifier)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return

    storage.get_or_create_chat(message.chat.id)
    now = int(time.time())
    if storage.count_players(message.chat.id) >= storage.max_players:
        await message.answer(f"⚠️ В чате уже {storage.max_players} игроков — это предел. Удалите кого-нибудь: /remove")
        return

    if not name:
        try:
            profile = await asyncio.to_thread(od.get_profile, account_id)
            name = profile.get("personaname") or f"id{account_id}"
        except Exception:
            name = f"id{account_id}"
        name = name[:cmd.NAME_MAX]
        if storage.nick_taken(message.chat.id, name):  # автоник совпал с чужим — делаем уникальным
            name = f"{name[:cmd.NAME_MAX - 5]}#{account_id % 10000}"

    try:
        player = storage.add_player(message.chat.id, account_id, name, mmr, now, now)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return

    if getattr(message.chat, "type", None) != "private":  # кто добавил — того и считаем этим игроком (если своего ещё нет)
        link_adder(storage, message.chat.id, player, getattr(message, "from_user", None))

    try:
        await asyncio.to_thread(refresh_player, storage, od, player, now, stratz)
    except Exception as exc:  # первичная подгрузка не критична — досчитается в /stats
        log_network_error(log, f"Первая загрузка истории игрока {account_id} не удалась", exc,
                          health=getattr(od, "health", None))

    try:  # история при добавлении — не «новые игры»: помечаем оповещённой, чтобы не завалить чат
        storage.mark_notified(player.id)
    except Exception:
        logging.getLogger(__name__).warning("Не удалось инициализировать оповещения игрока", exc_info=True)

    mmr_note = f", ≈{mmr} MMR" if mmr is not None else f". Задайте MMR: /setmmr {name} 5400"
    await message.answer(f"✅ {name} добавлен{mmr_note}")


async def _roster_text(storage: Storage, chat_id: int) -> str:
    """Список игроков из кэша БД (без запросов в сеть): текущий MMR считается по сохранённым матчам."""
    summaries = await asyncio.to_thread(build_leaderboard, storage, None, chat_id, int(time.time()), False)
    return render_player_list(summaries)


@router.message(Command("list"))
async def cmd_list(message: Message, storage: Storage) -> None:
    await message.answer(await _roster_text(storage, message.chat.id), parse_mode="HTML", reply_markup=list_actions())


@router.message(Command("remove"))
async def cmd_remove(message: Message, command: CommandObject, storage: Storage, bot: Optional[Bot] = None) -> None:
    name = (command.args or "").strip().lstrip("@").strip()
    if not name:
        if await _has_players(message, storage):
            await _ask_player(message, storage, "remove", "Кого удалить?")
        return
    player = storage.get_player(message.chat.id, name)
    if player is None:
        await message.answer(NOT_FOUND_TEXT)
        return
    await _confirm_remove(message, player)


async def _confirm_remove(message, player) -> None:
    """Удаление стирает историю — всегда через подтверждение (права проверяются при нажатии «Да»)."""
    await message.answer(
        f"🗑️ Удалить игрока {player.display_name}? История его матчей будут стёрты.",
        reply_markup=confirm_remove(player.account_id),
    )


async def _may_remove(message, storage: Storage, player, user, bot) -> bool:
    """Себя (привязанного через «Это я») может удалить сам игрок, остальных — тот, кто управляет чатом."""
    if user is not None and player.tg_user_id is not None and player.tg_user_id == getattr(user, "id", None):
        return True
    return await _can_manage(message, storage, user, bot)


@router.message(Command("setmmr"))
async def cmd_setmmr(message: Message, command: CommandObject, storage: Storage) -> None:
    if not (command.args or "").strip():
        if await _has_players(message, storage):
            await _ask_player(message, storage, "setmmr", "Выберите игрока, чтобы задать MMR:")
        return
    try:
        name, mmr = cmd.parse_name_and_mmr(command.args or "")
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    player = storage.get_player(message.chat.id, name)
    if player is None:
        await message.answer(NOT_FOUND_TEXT)
        return
    before, after = set_player_mmr(storage, message.chat.id, player, mmr, int(time.time()))
    await message.answer(render_mmr_set(player.display_name, mmr, before, after), parse_mode="HTML")


@router.message(Command("setstep"))
async def cmd_setstep(message: Message, command: CommandObject, storage: Storage, bot: Optional[Bot] = None) -> None:
    try:
        step = cmd.parse_step(command.args or "")
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    if not await _can_manage(message, storage, bot=bot):
        return
    storage.set_chat_step(message.chat.id, step)
    await message.answer(f"✅ Шаг: ±{step} MMR за игру")


@router.message(Command("settime"))
async def cmd_settime(message: Message, command: CommandObject, storage: Storage, bot: Optional[Bot] = None) -> None:
    try:
        hour = cmd.parse_hour(command.args or "")
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    if not await _can_manage(message, storage, bot=bot):
        return
    storage.set_chat_digest_hour(message.chat.id, hour)
    tz = storage.get_or_create_chat(message.chat.id).tz
    await message.answer(f"✅ Сводка в {hour:02d}:00 ({tz_label(tz)})")


@router.message(Command("me"))
async def cmd_me(message: Message, command: CommandObject, storage: Storage, bot: Bot) -> None:
    """`/me ник` — привязать свой Telegram к игроку (для тега с MMR); `/me off` — отвязать."""
    user = message.from_user
    if user is None or message.chat.type == "private":
        await message.answer("🙋 Команда работает в группе.")
        return
    name = (command.args or "").strip()
    if name.lower() in {"off", "выкл"}:
        await _unlink_me(message, storage, bot, user)
        return
    if not name:
        mine = next((p for p in storage.list_players(message.chat.id) if p.tg_user_id == user.id), None)
        hint = f"Вы — {mine.display_name}. Отвязать: /me off" if mine else "Формат: /me ник (ник из /list)"
        await message.answer(hint)
        return
    player = storage.get_player(message.chat.id, name.lstrip("@"))
    if player is None:
        await message.answer(NOT_FOUND_TEXT)
        return
    await _link_me(message, storage, bot, user, player)


async def _link_me(message, storage: Storage, bot: Bot, user, player) -> None:
    """Привязать аккаунт `user` к игроку и сразу поставить тег, если теги в чате включены."""
    storage.link_user(message.chat.id, player.id, user.id)
    note = ""
    if storage.get_or_create_chat(message.chat.id).tag_mmr:
        await sync_member_tags(bot, storage, message.chat.id, int(time.time()))
    else:
        note = " Теги с MMR включаются в ⚙️ Настройках (или /tags on)."
    await message.answer(f"✅ Вы — {player.display_name}.{note}", reply_markup=nav_menu())


async def _unlink_me(message, storage: Storage, bot: Bot, user) -> None:
    player = storage.unlink_user(message.chat.id, user.id)
    if player is None:
        await message.answer("Вы ни к кому не привязаны.", reply_markup=nav_menu())
        return
    await clear_member_tag(bot, message.chat.id, user.id)
    await message.answer(f"✅ Отвязал от {player.display_name}.", reply_markup=nav_menu())


@router.message(Command("tags"))
async def cmd_tags(message: Message, command: CommandObject, storage: Storage, bot: Bot) -> None:
    """`/tags on|off` — теги участников с их MMR (боту нужно право админа «Управлять тегами»)."""
    args = (command.args or "").strip()
    if not args:
        on = storage.get_or_create_chat(message.chat.id).tag_mmr
        await message.answer(
            f"🏷️ Теги с MMR: {'включены' if on else 'выключены'}.\n"
            "Каждый привязывает себя командой /me ник. Боту нужно право админа «Управлять тегами»; "
            "админам и владельцу чата Telegram тег поставить не даёт."
        )
        return
    try:
        enabled = cmd.parse_on_off(args)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    if not await _can_manage(message, storage, bot=bot):
        return
    storage.set_chat_tag_mmr(message.chat.id, enabled)
    if enabled:
        await sync_member_tags(bot, storage, message.chat.id, int(time.time()))
    await message.answer("✅ Теги с MMR включены." if enabled else "✅ Теги с MMR выключены (поставленные останутся).")




async def _has_players(message: Message, storage: Storage) -> bool:
    if storage.list_players(message.chat.id):
        return True
    await message.answer(NO_PLAYERS)
    return False


async def _ask_player(message: Message, storage: Storage, kind: str, prompt: str) -> None:
    await message.answer(prompt, reply_markup=players_picker(storage.list_players(message.chat.id), kind))


# --- действия (общие для команд и кнопок) -------------------------------

async def do_stats(message: Message, storage: Storage, od: OpenDota, stratz=None, today_only: bool = False) -> None:
    await _stats_card(message, storage, od, "today" if today_only else "stats", stratz)


async def do_period_stats(message: Message, storage: Storage, od: OpenDota, period: str, stratz=None) -> None:
    await _stats_card(message, storage, od, period, stratz)


async def _stats_card(message: Message, storage: Storage, od: OpenDota, mode: str, stratz=None) -> None:
    """Рейтинг картинкой (stats | today | week | month) с вкладками периодов и «📝 Текстом»; не вышло — текстом."""
    if not await _has_players(message, storage):
        return
    status = await _progress(message, WAIT, "upload_photo")
    try:
        board = await stats_board(storage, od, message.chat.id, mode, stratz)
    except Exception:
        log.exception("Ошибка сборки рейтинга для чата %s", message.chat.id)
        await _delete(status)
        await message.answer(FAILED, reply_markup=nav_menu())
        return
    await _reply_image(message, board, with_text_button(stats_tabs(mode), "stats", mode), status)


async def do_together(message: Message, storage: Storage, od: OpenDota, stratz=None) -> None:
    """Совместные игры картинкой (плитки и матрица пар) с кнопкой «📝 Текстом»; не вышло — текстом."""
    if not await _has_players(message, storage):
        return
    await _image_report(message, together_board(storage, od, message.chat.id, stratz),
                        with_text_button(nav_menu(), "together"), "совместных игр")


async def do_compare(message: Message, storage: Storage, od: OpenDota, stratz=None) -> None:
    """Сравнение игроков картинкой (индекс и места по показателям) с кнопкой «📝 Текстом»; не вышло — текстом."""
    if not await _has_players(message, storage):
        return
    await _image_report(message, compare_board(storage, od, message.chat.id, stratz),
                        with_text_button(nav_menu(), "compare"), "сравнения")


async def do_heroes_board(message: Message, storage: Storage, od: OpenDota, stratz=None) -> None:
    """Любимые герои пати картинкой (под ней «📝 Текстом»); не вышло с картинкой — текстом."""
    if not await _has_players(message, storage):
        return
    await _image_report(message, heroes_board(storage, od, message.chat.id, stratz),
                        with_text_button(nav_menu(), "heroes"), "героев пати")


async def do_hero(message: Message, storage: Storage, od: OpenDota, query: str, period: str, stratz=None) -> None:
    """Герой и кто из пати на нём играл — картинкой; нет такого героя — подсказка текстом."""
    status = await _progress(message, WAIT, "upload_photo")
    try:
        board = await hero_board(storage, od, message.chat.id, query, period, stratz)
    except Exception:
        log.exception("Ошибка сборки героя для чата %s", message.chat.id)
        await _delete(status)
        await message.answer(FAILED, reply_markup=nav_menu())
        return
    markup = with_text_button(nav_menu(), "hero", board.hero_id, period) if board.hero_id else nav_menu()
    await _reply_image(message, board, markup, status)


async def _reply_with_period(message: Message, kind: str, prefix: str, storage: Storage, od: OpenDota, name: str,
                             period: str, stratz, edit: bool) -> None:
    """Герои/позиции игрока картинкой + ряд кнопок периода и «📝 Текстом» (edit=True — правим сообщение с кнопкой)."""
    player = storage.get_player(message.chat.id, name)
    if player is None:
        await message.answer(NOT_FOUND_TEXT)
        return
    status = await _progress(message, WAIT, "upload_photo")
    try:
        board = await player_heroes_board(storage, od, message.chat.id, name, period, stratz, kind=kind)
    except Exception:
        log.exception("Ошибка сборки борда для чата %s", message.chat.id)
        await _delete(status)
        await message.answer(FAILED, reply_markup=nav_menu())
        return
    if board is None:
        await _delete(status)
        await message.answer(NOT_FOUND_TEXT, reply_markup=nav_menu())
        return
    markup = with_text_button(period_buttons(prefix, player.account_id, period), prefix, player.account_id, period)
    await _reply_image(message, board, markup, status, edit=edit)


async def do_player_heroes(message: Message, storage: Storage, od: OpenDota, name: str, period: str,
                           stratz=None, edit: bool = False) -> None:
    await _reply_with_period(message, "heroes", "hp", storage, od, name, period, stratz, edit)


async def do_roles(message: Message, storage: Storage, od: OpenDota, name: str, period: str,
                   stratz=None, edit: bool = False) -> None:
    await _reply_with_period(message, "roles", "rp", storage, od, name, period, stratz, edit)


async def do_match(message: Message, storage: Storage, od: OpenDota, name, match_id, stratz=None) -> None:
    """Матч картинкой (иконки героев, ники, K/D/A…) с кнопкой «Текстом»; не вышло с картинкой — текстом."""
    status = await _progress(message, WAIT, "upload_photo")
    try:
        board = await match_board(storage, od, message.chat.id, name, match_id, stratz)
    except Exception:
        log.exception("Ошибка сборки матча для чата %s", message.chat.id)
        await _delete(status)
        await message.answer(FAILED, reply_markup=nav_menu())
        return
    await _reply_image(message, board, match_photo_buttons(board.match_id, board.focus), status)


# Текстовые версии карточек для кнопки «📝 Текстом»: вид → корутина (storage, od, chat_id, args, stratz) → текст.
async def _text_match(storage: Storage, od: OpenDota, chat_id: int, args: list[str], stratz=None) -> Optional[str]:
    """tx:match:<match_id>:<account_id|0> — тот же матч текстом."""
    try:
        match_id, account = int(args[0]), int(args[1])
    except (IndexError, ValueError):
        return None
    player = storage.get_player(chat_id, str(account)) if account else None
    return await render_match_board(storage, od, chat_id, player.display_name if player else None, match_id, stratz)


async def _text_stats(storage: Storage, od: OpenDota, chat_id: int, args: list[str], stratz=None) -> Optional[str]:
    """tx:stats:<stats|today|week|month> — тот же рейтинг текстом."""
    mode = args[0] if args else ""
    if mode not in STATS_MODES:
        return None
    return (await stats_board(storage, od, chat_id, mode, stratz, image=False)).text


async def _text_player(storage: Storage, od: OpenDota, chat_id: int, args: list[str], stratz=None) -> Optional[str]:
    """tx:player:<account_id> — карточка игрока текстом."""
    return await render_player_board(storage, od, chat_id, args[0], stratz) if args else None


async def _text_player_heroes(storage: Storage, od: OpenDota, chat_id: int, args: list[str], stratz=None) -> Optional[str]:
    """tx:hp:<account_id>:<period> — герои (и позиции) игрока текстом."""
    if len(args) != 2 or args[1] not in PERIODS_KEYS:
        return None
    return await render_player_heroes_board(storage, od, chat_id, args[0], args[1], stratz)


async def _text_roles(storage: Storage, od: OpenDota, chat_id: int, args: list[str], stratz=None) -> Optional[str]:
    """tx:rp:<account_id>:<period> — позиции игрока текстом."""
    if len(args) != 2 or args[1] not in PERIODS_KEYS:
        return None
    return await render_roles_board(storage, od, chat_id, args[0], args[1], stratz)


async def _text_party_heroes(storage: Storage, od: OpenDota, chat_id: int, args: list[str], stratz=None) -> Optional[str]:
    """tx:heroes — любимые герои пати текстом."""
    return await render_heroes_board(storage, od, chat_id, stratz)


async def _text_hero(storage: Storage, od: OpenDota, chat_id: int, args: list[str], stratz=None) -> Optional[str]:
    """tx:hero:<hero_id>:<period> — герой и пати на нём текстом."""
    try:
        hero_id = int(args[0])
    except (IndexError, ValueError):
        return None
    if len(args) != 2 or args[1] not in PERIODS_KEYS:
        return None
    return await render_hero_board(storage, od, chat_id, hero_name(hero_id), args[1], stratz)


async def _text_contest(storage: Storage, od: OpenDota, chat_id: int, args: list[str], stratz=None) -> Optional[str]:
    """tx:ach:<period> — соревнование чата текстом."""
    if len(args) != 1 or args[0] not in PERIODS_KEYS:
        return None
    return await render_contest_text(storage, od, chat_id, args[0], stratz)


async def _text_together(storage: Storage, od: OpenDota, chat_id: int, args: list[str], stratz=None) -> Optional[str]:
    """tx:together — совместные игры текстом."""
    return await render_together_board(storage, od, chat_id, stratz)


async def _text_compare(storage: Storage, od: OpenDota, chat_id: int, args: list[str], stratz=None) -> Optional[str]:
    """tx:compare — сравнение игроков текстом."""
    return await render_compare_board(storage, od, chat_id, stratz)


async def _text_records(storage: Storage, od: OpenDota, chat_id: int, args: list[str], stratz=None) -> Optional[str]:
    """tx:records:<period> — рекорды пати текстом."""
    if len(args) != 1 or args[0] not in PERIODS_KEYS:
        return None
    return await render_records_board(storage, od, chat_id, args[0], stratz)


TEXT_VIEWS = {"together": _text_together, "compare": _text_compare, "records": _text_records, "match": _text_match, "stats": _text_stats, "player": _text_player, "hp": _text_player_heroes,
              "rp": _text_roles, "heroes": _text_party_heroes, "hero": _text_hero, "ach": _text_contest}


async def on_text_view(message: Message, storage: Storage, od: OpenDota, args: list[str], stratz=None) -> None:
    """Кнопка «📝 Текстом» под картинкой: тот же отчёт текстом отдельным сообщением, кнопку под фото убираем."""
    view = TEXT_VIEWS.get(args[0]) if args else None
    if view is None:
        return
    await _reply_board(message, view(storage, od, message.chat.id, args[1:], stratz))
    try:
        await message.edit_reply_markup(reply_markup=without_text_button(getattr(message, "reply_markup", None)))
    except Exception:
        pass  # старое сообщение / уже изменено — не важно


async def do_player_card(message: Message, storage: Storage, od: OpenDota, name: str, stratz=None) -> None:
    """Карточка игрока картинкой (под ней кнопки игрока и «📝 Текстом»); не вышло — текстом."""
    status = await _progress(message, WAIT, "upload_photo")
    player = storage.get_player(message.chat.id, name)
    try:
        board = await player_board(storage, od, message.chat.id, name, stratz)
    except Exception:
        log.exception("Ошибка сборки карточки игрока для чата %s", message.chat.id)
        await _delete(status)
        await message.answer(FAILED, reply_markup=nav_menu())
        return
    if board is None:
        await _delete(status)
        await message.answer(NOT_FOUND_TEXT, reply_markup=nav_menu())
        return
    markup = with_text_button(player_actions(player.account_id), "player", player.account_id) if player else nav_menu()
    await _reply_image(message, board, markup, status)


async def do_records(message: Message, storage: Storage, od: OpenDota, period: str, stratz=None,
                     edit: bool = False) -> None:
    """Рекорды пати картинкой (периоды меняют её на месте, «📝 Текстом» — текстом); не вышло — текстом."""
    await _image_report(message, records_board(storage, od, message.chat.id, period, stratz),
                        with_text_button(records_buttons(period), "records", period), "рекордов", edit=edit)


async def do_graph(
    message: Message, storage: Storage, od: OpenDota, period: str, stratz=None, by_games: bool = False
) -> None:
    """График ±MMR по игрокам за период (картинка + кнопки периодов)."""
    if not await _has_players(message, storage):
        return
    status = await _progress(message, WAIT, "upload_photo")
    try:
        result = await render_graph_board(storage, od, message.chat.id, period, stratz, by_games=by_games)
    except Exception:
        logging.getLogger(__name__).exception("Ошибка построения графика для чата %s", message.chat.id)
        await _delete(status)
        await message.answer(FAILED, reply_markup=nav_menu())
        return
    if result is None:
        await message.answer("💤 За период игр не было.", reply_markup=graph_buttons(period, by_games))
        await _delete(status)
        return
    png, caption = result
    await message.answer_photo(
        BufferedInputFile(png, filename="mmr.png"), caption=caption, parse_mode="HTML",
        reply_markup=graph_buttons(period, by_games),
    )
    await _delete(status)  # «⏳ Считаю…» исчезает, когда график уже отправлен


async def edit_graph(
    message: Message, storage: Storage, od: OpenDota, period: str, stratz=None, by_games: bool = False
) -> None:
    """Смена периода под графиком: подменяем картинку и подпись в том же сообщении."""
    try:
        result = await render_graph_board(storage, od, message.chat.id, period, stratz, refresh=False, by_games=by_games)
    except Exception:
        logging.getLogger(__name__).exception("Ошибка построения графика для чата %s", message.chat.id)
        return
    try:
        if result is None:
            await message.edit_caption(
                caption="💤 За период игр не было.", reply_markup=graph_buttons(period, by_games)
            )
            return
        png, caption = result
        await message.edit_media(
            InputMediaPhoto(media=BufferedInputFile(png, filename="mmr.png"), caption=caption, parse_mode="HTML"),
            reply_markup=graph_buttons(period, by_games),
        )
    except Exception as exc:
        if "not modified" in str(exc):
            return  # тот же период — картинка не изменилась
        logging.getLogger(__name__).exception("Не удалось сменить период графика")


async def do_contest(message: Message, storage: Storage, od: OpenDota, period: str, stratz=None,
                     edit: bool = False) -> None:
    """Соревнование чата картинкой (периоды меняют её на месте, «📝 Текстом» — текстом); не вышло — текстом."""
    await _image_report(message, contest_board(storage, od, message.chat.id, period, stratz),
                        with_text_button(contest_buttons(period), "ach", period), "соревнования", edit=edit)


async def do_steam(message: Message, storage: Storage, od: OpenDota, name: str) -> None:
    """Аватарка + текущий ник из профиля Steam (через OpenDota) одним сообщением."""
    player = storage.get_player(message.chat.id, name)
    if player is None:
        await message.answer(NOT_FOUND_TEXT, reply_markup=nav_menu())
        return
    status = await _progress(message, WAIT)
    try:
        profile = await asyncio.to_thread(od.get_profile, player.account_id)
    except Exception:
        logging.getLogger(__name__).exception("Ошибка загрузки Steam-профиля %s", player.account_id)
        await _delete(status)
        await message.answer(FAILED, reply_markup=nav_menu())
        return
    await _delete(status)
    caption = render_steam_profile(
        player.display_name, player.account_id, profile,
        rank_label(profile.get("rank_tier"), profile.get("leaderboard_rank")),
    )
    avatar = profile.get("avatarfull")
    if avatar:
        try:
            await message.answer_photo(avatar, caption=caption, parse_mode="HTML", reply_markup=nav_menu())
            return
        except Exception:
            logging.getLogger(__name__).warning("Не удалось отправить аватар %s", avatar, exc_info=True)
    await message.answer(caption, parse_mode="HTML", reply_markup=nav_menu())


# --- команды ------------------------------------------------------------

@router.message(Command("stats"))
@router.message(Command("today"))
async def cmd_stats(message: Message, command: CommandObject, storage: Storage, od: OpenDota, stratz=None) -> None:
    """/stats — лидерборд; /stats сегодня|неделя|месяц — за период (/today — старый алиас)."""
    _, period = cmd.parse_target_period(command.args or "")
    if period in ("week", "month") and command.command != "today":
        await do_period_stats(message, storage, od, period, stratz)
        return
    today = period == "day" or command.command == "today"
    await do_stats(message, storage, od, stratz, today_only=today)


@router.message(Command("together"))
async def cmd_together(message: Message, storage: Storage, od: OpenDota, stratz=None) -> None:
    await do_together(message, storage, od, stratz)


@router.message(Command("compare"))
@router.message(Command("table"))
async def cmd_compare(message: Message, storage: Storage, od: OpenDota, stratz=None) -> None:
    await do_compare(message, storage, od, stratz)


@router.message(Command("heroes"))
async def cmd_heroes(message: Message, command: CommandObject, storage: Storage, od: OpenDota, stratz=None) -> None:
    if not await _has_players(message, storage):
        return
    name, period = cmd.parse_target_period(command.args or "")
    if name is None:
        await do_heroes_board(message, storage, od, stratz)
    elif storage.get_player(message.chat.id, name) is not None:
        await do_player_heroes(message, storage, od, name, period, stratz)  # герои + позиции игрока
    elif find_hero(name) is not None:
        await do_hero(message, storage, od, name, period, stratz)
    else:
        await message.answer(f"🔍 Не нашёл ни игрока, ни героя «{name}». Список: /list. Героя пишите по-английски: /heroes Axe")


@router.message(Command("match"))
@router.message(Command("last"))  # /last [игрок] — последний матч: то же, что /match без id
async def cmd_match(message: Message, command: CommandObject, storage: Storage, od: OpenDota, stratz=None) -> None:
    match_id, name = cmd.parse_match_args(command.args or "")
    if match_id is None and not await _has_players(message, storage):
        return
    if command.command == "last" and match_id is None and name is None:  # /last без аргументов — игра того, кто спросил
        user = getattr(message, "from_user", None)
        mine = next((p for p in storage.list_players(message.chat.id) if user and p.tg_user_id == user.id), None)
        name = mine.display_name if mine else None  # не привязан (/me) — последний матч пати, как у /match
    await do_match(message, storage, od, name, match_id, stratz)


@router.message(Command("roles"))
async def cmd_roles(message: Message, command: CommandObject, storage: Storage, od: OpenDota, stratz=None) -> None:
    if not await _has_players(message, storage):
        return
    name, period = cmd.parse_target_period(command.args or "")
    if name is None:
        await _ask_player(message, storage, "roles", "Выберите игрока для просмотра позиций:")
    else:
        await do_roles(message, storage, od, name, period, stratz)


@router.message(Command("records"))
async def cmd_records(message: Message, command: CommandObject, storage: Storage, od: OpenDota, stratz=None) -> None:
    if not await _has_players(message, storage):
        return
    _, period = cmd.parse_target_period(command.args or "")
    await do_records(message, storage, od, period if (command.args or "").strip() else "week", stratz)


@router.message(Command("graph"))
async def cmd_graph(message: Message, command: CommandObject, storage: Storage, od: OpenDota, stratz=None) -> None:
    _, period = cmd.parse_target_period(command.args or "")
    await do_graph(message, storage, od, period if (command.args or "").strip() else "week", stratz)


@router.message(Command("achievements", "contest"))
async def cmd_achievements(message: Message, command: CommandObject, storage: Storage, od: OpenDota, stratz=None) -> None:
    if not await _has_players(message, storage):
        return
    _, period = cmd.parse_target_period(command.args or "")
    await do_contest(message, storage, od, period if (command.args or "").strip() else "week", stratz)


@router.message(Command("steam"))
async def cmd_steam(message: Message, command: CommandObject, storage: Storage, od: OpenDota, stratz=None) -> None:
    name = (command.args or "").strip().lstrip("@").strip()
    if not name:
        if await _has_players(message, storage):
            await _ask_player(message, storage, "steam", "Выберите игрока для просмотра Steam-профиля:")
        return
    await do_steam(message, storage, od, name)


@router.message(Command("player"))
async def cmd_player(message: Message, command: CommandObject, storage: Storage, od: OpenDota, stratz=None) -> None:
    name = (command.args or "").strip().lstrip("@").strip()
    if not name:
        if await _has_players(message, storage):
            await _ask_player(message, storage, "player", "Выберите игрока для просмотра карточки:")
        return
    await do_player_card(message, storage, od, name, stratz)


# --- ответы на подсказки кнопок («Добавить», «Задать MMR») ---------------

def _is_reply_to_prompt(message: Message) -> bool:
    reply = message.reply_to_message
    return bool(reply and reply.from_user and reply.from_user.is_bot and reply.text and message.text
                and not message.text.startswith("/"))


@router.message(F.reply_to_message, F.text, _is_reply_to_prompt)
async def on_prompt_reply(message: Message, storage: Storage, od: OpenDota, stratz=None) -> None:
    prompt = message.reply_to_message.text or ""
    if prompt.startswith(ADD_PROMPT):
        await do_add(message, storage, od, message.text or "", stratz)
        return
    if prompt.startswith(HERO_PROMPT):
        await do_hero(message, storage, od, (message.text or "").strip(), "all", stratz)
        return
    if prompt.startswith(MATCHID_PROMPT):
        match_id, name = cmd.parse_match_args(message.text or "")
        if match_id is None:
            await message.answer("⚠️ ID матча — число из 8+ цифр.")
            return
        await do_match(message, storage, od, name, match_id, stratz)
        return
    match = _SETMMR_RE.match(prompt)
    if match is None:
        return
    player = storage.get_player(message.chat.id, match.group(1))
    if player is None:
        await message.answer(NOT_FOUND_TEXT, reply_markup=nav_menu())
        return
    try:
        mmr = cmd.parse_mmr_value(message.text or "")
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    before, after = set_player_mmr(storage, message.chat.id, player, mmr, int(time.time()))
    await message.answer(render_mmr_set(player.display_name, mmr, before, after), parse_mode="HTML",
                         reply_markup=nav_menu())


# --- кнопки -------------------------------------------------------------

async def _on_settings(message: Message, storage: Storage, args: list[str], bot=None, user=None) -> None:
    """Кнопки настроек (`s:<что>:<значение>`): меняем значение и правим сообщение на месте."""
    chat_id = message.chat.id
    chat = storage.get_or_create_chat(chat_id)
    what = args[0] if args else ""
    value = args[1] if len(args) > 1 else ""
    if what != "noop" and not await _can_manage(message, storage, user, bot):
        return
    try:
        if what == "step" and int(value) in STEPS:
            storage.set_chat_step(chat_id, int(value))
        elif what == "hour" and value in {"-1", "1"}:
            storage.set_chat_digest_hour(chat_id, (chat.digest_hour + int(value)) % 24)
        elif what == "tz" and 0 <= int(value) < len(TIMEZONES):
            storage.set_chat_tz(chat_id, TIMEZONES[int(value)][1])
        elif what == "steam":
            storage.set_chat_notify_steam(chat_id, not chat.notify_steam)
        elif what == "start":
            storage.set_chat_notify_start(chat_id, not chat.notify_start)
        elif what == "games":
            storage.set_chat_notify_games(chat_id, not chat.notify_games)
        elif what == "weekly":
            storage.set_chat_notify_weekly(chat_id, not chat.notify_weekly)
        elif what == "digest":
            storage.set_chat_notify_digest(chat_id, not chat.notify_digest)
        elif what == "images":
            storage.set_chat_prefer_text(chat_id, not chat.prefer_text)
        elif what == "admins":
            storage.set_chat_admin_only(chat_id, not chat.admin_only)
        elif what == "tags":
            storage.set_chat_tag_mmr(chat_id, not chat.tag_mmr)
            if not chat.tag_mmr and bot is not None:  # только что включили — ставим теги сразу
                await sync_member_tags(bot, storage, chat_id, int(time.time()))
        elif what != "noop":
            return
    except ValueError:
        return
    chat = storage.get_or_create_chat(chat_id)
    try:
        await message.edit_text(render_settings(chat), parse_mode="HTML", reply_markup=settings_menu(chat))
    except Exception:
        pass  # «message is not modified» — значение не изменилось


@router.message(Command("status"))
async def cmd_status(message: Message, storage: Storage, od: OpenDota, stratz=None, bot: Optional[Bot] = None) -> None:
    """Состояние бота: внешние сервисы, очереди дозагрузки, свежесть данных. Только админам чата."""
    actor = getattr(message, "from_user", None)
    sender_chat = getattr(message, "sender_chat", None)
    if not await is_chat_admin(bot or getattr(message, "bot", None), message.chat, actor, sender_chat):
        await message.answer(DENIED)
        return
    data = await asyncio.to_thread(collect_status, storage, od, stratz)
    await message.answer(render_status(data), parse_mode="HTML")


@router.message(Command("settings"))
async def cmd_settings(message: Message, storage: Storage) -> None:
    chat = storage.get_or_create_chat(message.chat.id)
    await message.answer(render_settings(chat), parse_mode="HTML", reply_markup=settings_menu(chat))


@router.callback_query(lambda c: bool(c.data) and c.data.split(":")[0] in {"m", "pp", "hp", "rp", "x", "s", "g", "r", "c", "mt", "tx", "mx"})
async def on_callback(query: CallbackQuery, storage: Storage, od: OpenDota, stratz=None) -> None:
    await query.answer()  # убрать «часики» на кнопке
    message = query.message
    if message is None:
        return
    kind, args = parse_callback(query.data)

    if kind == "x":
        await _delete(message)
        return

    if kind == "s":
        await _on_settings(message, storage, args, getattr(query, "bot", None), getattr(query, "from_user", None))
        return

    if kind == "r":
        period = args[0] if args else "week"
        if period in {"day", "week", "month", "year", "all"}:
            await do_records(message, storage, od, period, stratz, edit=True)  # меняем период на месте
        return

    if kind == "c":
        period = args[0] if args else "week"
        if period in PERIODS_KEYS:
            await do_contest(message, storage, od, period, stratz, edit=True)  # меняем период на месте
        return

    if kind == "mx":  # «🎮 Весь матч» под оповещением: тот же разбор, что и /match <id>
        try:
            match_id = int(args[0])
        except (IndexError, ValueError):
            return
        await do_match(message, storage, od, None, match_id, stratz)
        return

    if kind in {"tx", "mt"}:  # mt — прежний формат кнопки «Текстом» под матчем (сообщения уже в чатах)
        await on_text_view(message, storage, od, args if kind == "tx" else ["match", *args], stratz)
        return

    if kind == "g":
        period = args[0] if args else "week"
        by_games = "n" in args[1:]
        if period in {"day", "week", "month", "year", "all"}:
            if getattr(message, "photo", None):
                await edit_graph(message, storage, od, period, stratz, by_games)  # график меняется на месте
            else:
                await _delete(message)
                await do_graph(message, storage, od, period, stratz, by_games)
        return

    # переход в другой раздел и смена периода правят то же сообщение на месте — чат не засоряется
    if kind in {"m", "pp"}:
        message = _InPlace(message)

    if kind == "m":
        action = args[0] if args else "menu"
        if action == "menu":
            await message.answer("📋 Выберите раздел:", reply_markup=main_menu())
        elif action == "c":
            key = args[1] if len(args) > 1 else ""
            if key in CATEGORIES:
                await message.answer(f"{category_title(key)} — выберите действие:", reply_markup=category_menu(key))
            else:
                await message.answer("📋 Выберите раздел:", reply_markup=main_menu())
        elif action == "records":
            if await _has_players(message, storage):
                await do_records(message, storage, od, "week", stratz)
        elif action == "graph":
            if await _has_players(message, storage):
                await do_graph(message, storage, od, "week", stratz)
        elif action == "achv":
            if await _has_players(message, storage):
                await do_contest(message, storage, od, "week", stratz)
        elif action == "settings":
            chat = storage.get_or_create_chat(message.chat.id)
            await message.answer(render_settings(chat), parse_mode="HTML", reply_markup=settings_menu(chat))
        elif action == "help":
            await message.answer(HELP_TEXT, reply_markup=nav_menu())
        elif action == "terms":
            await message.answer(TERMS, reply_markup=nav_menu())
        elif action == "list":
            await message.answer(
                await _roster_text(storage, message.chat.id), parse_mode="HTML", reply_markup=list_actions()
            )
        elif action == "stats":
            await do_stats(message, storage, od, stratz)
        elif action == "today":
            await do_stats(message, storage, od, stratz, today_only=True)
        elif action in {"week", "month"}:
            await do_period_stats(message, storage, od, action, stratz)
        elif action == "compare":
            await do_compare(message, storage, od, stratz)
        elif action == "together":
            await do_together(message, storage, od, stratz)
        elif action == "match":
            await _ask_match(message, storage)
        elif action == "matchid":
            await _prompt_matchid(message)
        elif action == "hero":
            await _prompt_hero(message)
        elif action == "add":
            await _prompt_add(message)
        elif action == "me":
            if await _has_players(message, storage):
                kick = [[InlineKeyboardButton(text="🚫 Отвязать меня", callback_data="pp:meoff:0")]]
                await message.answer(
                    "🙋 Кто вы из игроков? Привяжу ваш Telegram к нему — тогда тег участника покажет ваш MMR.",
                    reply_markup=players_picker(storage.list_players(message.chat.id), "me", extra=kick),
                )
        elif action == "tags":
            chat = storage.get_or_create_chat(message.chat.id)
            await message.answer(render_settings(chat), parse_mode="HTML", reply_markup=settings_menu(chat))
        elif action in {"remove", "setmmr", "heroes", "roles", "player", "steam"}:
            if await _has_players(message, storage):
                label = {"remove": "Кого удалить", "setmmr": "Выберите игрока, чтобы задать MMR", "heroes": "Выберите игрока для просмотра героев", "roles": "Выберите игрока для просмотра позиций", "player": "Выберите игрока для просмотра карточки", "steam": "Выберите игрока для просмотра Steam-профиля"}[action]
                await _ask_player(message, storage, action, f"{label}:")
        return

    if kind == "pp" and len(args) == 2:
        pick, account = args
        if pick == "heroes":
            await do_player_heroes(message, storage, od, account, "all", stratz)
        elif pick == "roles":
            await do_roles(message, storage, od, account, "all", stratz)
        elif pick == "player":
            await do_player_card(message, storage, od, account, stratz)
        elif pick == "steam":
            await do_steam(message, storage, od, account)
        elif pick == "remove":
            player = storage.get_player(message.chat.id, account)
            if player is None:
                await message.answer(NOT_FOUND_TEXT, reply_markup=nav_menu())
            else:
                await _confirm_remove(message, player)
        elif pick in {"me", "meoff"}:
            if message.chat.type == "private":
                await message.answer("🙋 Работает в группе.", reply_markup=nav_menu())
            elif pick == "meoff":
                await _unlink_me(message, storage, query.bot, query.from_user)
            else:
                player = storage.get_player(message.chat.id, account)
                if player is None:
                    await message.answer(NOT_FOUND_TEXT, reply_markup=nav_menu())
                else:
                    await _link_me(message, storage, query.bot, query.from_user, player)
        elif pick == "match":
            player = None if account == "last" else storage.get_player(message.chat.id, account)
            await do_match(message, storage, od, player.display_name if player else None, None, stratz)
        elif pick == "rmyes":
            player = storage.get_player(message.chat.id, account)
            if player is None:
                await message.answer(NOT_FOUND_TEXT, reply_markup=nav_menu())
            elif await _may_remove(
                message, storage, player, getattr(query, "from_user", None), getattr(query, "bot", None)
            ):
                storage.remove_player(message.chat.id, str(player.account_id))
                await message.answer(f"🗑️ {player.display_name} удалён.", reply_markup=nav_menu())
        elif pick == "setmmr":
            player = storage.get_player(message.chat.id, account)
            if player is None:
                await message.answer(NOT_FOUND_TEXT, reply_markup=nav_menu())
            else:
                await _prompt_setmmr(message, player)
        return

    if kind in {"hp", "rp"} and len(args) == 2:
        account, period = args
        if period not in {"day", "week", "month", "all"}:
            return
        action = do_player_heroes if kind == "hp" else do_roles
        await action(message, storage, od, account, period, stratz, edit=True)


# --- разделы в своих модулях ------------------------------------------------
# Подключаются к этому роутеру: на них действуют те же middleware (удаление сообщения с командой, автопривязка).
from mmrbot import doubles  # noqa: E402

router.include_router(doubles.router)
