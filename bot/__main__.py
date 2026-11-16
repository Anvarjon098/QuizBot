import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from .config import load_config
from .db import Database
from .handlers import admin, common, create, play, stats
from .middlewares import UserMiddleware
from .runner import QuizManager


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    db = Database(config.db_path)
    await db.connect()
    manager = QuizManager(db)

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage(), db=db, config=config, manager=manager)
    dp.update.outer_middleware(UserMiddleware(db))
    # Tartib muhim: deep link /start va /stop birinchi, keyin umumiy buyruqlar va bekor qilish.
    dp.include_routers(play.router, common.router, admin.router, create.router, stats.router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Bosh menyu"),
        BotCommand(command="new", description="Yangi test yaratish"),
        BotCommand(command="stop", description="Joriy testni to'xtatish"),
        BotCommand(command="help", description="Yordam"),
        BotCommand(command="namuna", description="Import uchun namuna fayllar"),
        BotCommand(command="cancel", description="Amalni bekor qilish"),
    ])
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await manager.shutdown()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
