import asyncio
import logging
import os
import ssl

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from .config import load_config
from .db import Database
from .handlers import admin, common, create, fallback, play, stats
from .middlewares import UserMiddleware
from .runner import QuizManager


def make_session() -> AiohttpSession:
    """HTTPS_PROXY / SSL_CERT_FILE berilgan bo'lsa (masalan, korporativ tarmoqda), ulardan foydalanadi."""
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    session = AiohttpSession(proxy=proxy) if proxy else AiohttpSession()
    cafile = os.getenv("SSL_CERT_FILE")
    if cafile:
        session._connector_init["ssl"] = ssl.create_default_context(cafile=cafile)
    return session


USER_COMMANDS = [
    BotCommand(command="start", description="Boshlash"),
    BotCommand(command="stop", description="Joriy testni to'xtatish"),
]
ADMIN_COMMANDS = [
    BotCommand(command="start", description="Bosh menyu"),
    BotCommand(command="new", description="Yangi test yaratish"),
    BotCommand(command="stop", description="Joriy testni to'xtatish"),
    BotCommand(command="admin", description="Admin panel"),
    BotCommand(command="help", description="Yordam"),
    BotCommand(command="namuna", description="Import uchun namuna fayllar"),
    BotCommand(command="cancel", description="Amalni bekor qilish"),
]


async def setup_commands(bot: Bot, admin_ids: frozenset[int]) -> None:
    """Oddiy foydalanuvchilarga qisqa, adminlarga to'liq buyruqlar menyusi."""
    await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:  # admin botga hali /start bosmagan bo'lsa
            logging.warning("Admin %s uchun buyruqlar menyusini o'rnatib bo'lmadi", admin_id)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    db = Database(config.db_path)
    await db.connect()
    manager = QuizManager(db, config.admin_ids)

    bot = Bot(config.bot_token, session=make_session(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage(), db=db, config=config, manager=manager)
    dp.update.outer_middleware(UserMiddleware(db))
    # Tartib muhim: deep link /start va /stop birinchi, keyin umumiy buyruqlar va bekor qilish.
    dp.include_routers(play.router, common.router, admin.router, create.router, stats.router, fallback.router)

    await setup_commands(bot, config.admin_ids)
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
