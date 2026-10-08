"""Точка входа: python -m mmrbot — long-polling + планировщик дайджеста."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ErrorEvent

import mmrbot.bot as botmod
from mmrbot import avatars, cards, hero_icons, service
import mmrbot.tracker as tracker
from mmrbot.access import ChatGateMiddleware
from mmrbot.bot import PerfMiddleware, router, set_bot_commands
from mmrbot.lifecycle import router as lifecycle_router
from mmrbot.charts import warmup
from mmrbot.config import load_config
from mmrbot.opendota import OpenDota
from mmrbot.scheduler import setup_scheduler
from mmrbot.steam import Steam
from mmrbot.stratz import Stratz
from mmrbot.storage import Storage


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()

    storage = Storage(
        config.db_path, default_digest_hour=config.default_digest_hour,
        default_mmr_step=config.default_mmr_step, default_tz=config.default_tz,
    )
    od = OpenDota(
        api_key=config.opendota_api_key, min_interval=config.opendota_min_interval, burst=config.opendota_burst,
        background_reserve=config.opendota_daily_reserve, proxy=config.opendota_proxy,
    )
    tracker.ENRICH_DAYS = config.opendota_enrich_days
    service.COMMAND_REFRESH_WAIT = config.command_refresh_wait
    botmod.MAX_PLAYERS = config.max_players
    stratz = Stratz(config.stratz_api_key) if config.stratz_api_key else None
    data_dir = Path(config.db_path).resolve().parent
    icons = hero_icons.setup(str(data_dir / "hero_icons"))  # иконки для картинок
    avatars.setup(str(data_dir / "avatars"), health=icons.health)  # аватары Steam; общий предохранитель CDN
    steam = Steam(config.steam_api_key) if config.steam_api_key else None

    bot = Bot(config.bot_token, default=DefaultBotProperties(link_preview_is_disabled=True))
    dp = Dispatcher()
    dp["storage"] = storage
    dp["od"] = od
    dp["stratz"] = stratz
    gate = ChatGateMiddleware(config.allowed_chats, storage)
    dp.message.outer_middleware(gate)
    dp.callback_query.outer_middleware(gate)
    dp.message.outer_middleware(PerfMiddleware())
    dp.callback_query.outer_middleware(PerfMiddleware())
    dp.include_router(lifecycle_router)
    dp.include_router(router)

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        # Страховочная сеть: любой неотловленный сбой хендлера — в лог, а не в падение.
        logging.getLogger(__name__).exception("Необработанная ошибка хендлера: %s", event.exception)
        return True

    await set_bot_commands(bot)
    asyncio.get_running_loop().run_in_executor(None, warmup)  # прогрев matplotlib: первый график без задержки
    asyncio.get_running_loop().run_in_executor(None, cards.warmup)  # шрифты и первый рендер Pillow-карточек

    scheduler = setup_scheduler(
        bot, storage, od, stratz, backup_keep=config.backup_keep, steam=steam,
        heartbeat_path=str(Path(config.db_path).resolve().parent / "heartbeat"),
    )
    scheduler.start()
    logging.getLogger(__name__).info("Бот запущен (long-polling). Ctrl+C для остановки.")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
