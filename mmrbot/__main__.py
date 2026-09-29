"""Точка входа: python -m mmrbot — long-polling + планировщик дайджеста."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent

from mmrbot.bot import router, set_bot_commands
from mmrbot.config import load_config
from mmrbot.opendota import OpenDota
from mmrbot.scheduler import setup_scheduler
from mmrbot.storage import Storage


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()

    storage = Storage(config.db_path)
    od = OpenDota(api_key=config.opendota_api_key)

    bot = Bot(config.bot_token)
    dp = Dispatcher()
    dp["storage"] = storage
    dp["od"] = od
    dp.include_router(router)

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        # Страховочная сеть: любой неотловленный сбой хендлера — в лог, а не в падение.
        logging.getLogger(__name__).exception("Необработанная ошибка хендлера: %s", event.exception)
        return True

    await set_bot_commands(bot)

    scheduler = setup_scheduler(bot, storage, od)
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
