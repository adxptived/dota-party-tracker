"""Ограниченный по времени запуск бота для проверки коннекта и старта polling.

Запускает реальный main() на несколько секунд и корректно отменяет — используется
только для локальной проверки, не для продакшена.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher

from mmrbot.bot import router
from mmrbot.config import load_config
from mmrbot.opendota import OpenDota
from mmrbot.scheduler import setup_scheduler
from mmrbot.storage import Storage

RUN_SECONDS = 7


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = load_config()
    storage = Storage(config.db_path)
    od = OpenDota(api_key=config.opendota_api_key)
    bot = Bot(config.bot_token)

    me = await bot.get_me()
    print(f"GET_ME OK -> @{me.username} (id={me.id})")

    dp = Dispatcher()
    dp["storage"] = storage
    dp["od"] = od
    dp.include_router(router)

    scheduler = setup_scheduler(bot, storage, od)
    scheduler.start()
    print("SCHEDULER STARTED")

    poll_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    print(f"POLLING STARTED, наблюдаю {RUN_SECONDS} c…")
    await asyncio.sleep(RUN_SECONDS)

    await dp.stop_polling()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass
    scheduler.shutdown(wait=False)
    await bot.session.close()
    print("SHUTDOWN CLEAN")


if __name__ == "__main__":
    asyncio.run(run())
