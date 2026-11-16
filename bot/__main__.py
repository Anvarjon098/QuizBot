import asyncio
import logging
import os
import ssl

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ErrorEvent, BotCommand, BotCommandScopeChat, BotCommandScopeDefault, ReplyKeyboardRemove

from .config import load_config
from .db import Database
from .handlers import admin, common, create, fallback, play, stats
from .middlewares import UserMiddleware
from .runner import QuizManager
from . import updater
from html import escape


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
    BotCommand(command="backup", description="Bazaning zaxira nusxasi"),
    BotCommand(command="update", description="Botni GitHub'dan yangilash"),
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


async def clear_old_menus(bot: Bot, db: Database, admin_ids: frozenset[int]) -> None:
    """Cheklovlardan oldin kirgan oddiy foydalanuvchilarning eski menyu tugmalarini bir marta o'chiradi."""
    for user_id in await db.users_with_old_menu(admin_ids):
        try:
            await bot.send_message(
                user_id,
                "🔄 Bot yangilandi. Testni ishlash uchun sizga yuborilgan test havolasini oching.",
                reply_markup=ReplyKeyboardRemove(),
            )
        except TelegramForbiddenError:
            await db.set_can_message(user_id, False)
        except Exception:
            logging.exception("Foydalanuvchi %s menyusini tozalab bo'lmadi", user_id)
            continue
        await db.mark_menu_cleared(user_id)
        await asyncio.sleep(0.05)


async def notify_updated(bot: Bot) -> None:
    """/update dan keyin qayta yonganda adminga xabar beradi."""
    notice = updater.pop_notice()
    if not notice:
        return
    try:
        await bot.send_message(
            notice["chat_id"],
            f"✅ Bot yangilandi va ishlayapti!\n<code>{notice['sha'][:7]}</code> {escape(notice['message'])}",
        )
    except Exception:
        logging.exception("Yangilanish haqida xabar yuborib bo'lmadi")


async def on_error(event: ErrorEvent) -> bool:
    """Bot guruhdan chiqarilgan yoki foydalanuvchi uni bloklagan bo'lsa — uzun xato o'rniga bitta qator."""
    exc = event.exception
    if isinstance(exc, (TelegramForbiddenError, TelegramBadRequest)):
        logging.warning("Telegram rad etdi: %s", exc.message)
        return True
    logging.exception("Kutilmagan xato", exc_info=exc)
    return True


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
    dp.errors.register(on_error)
    # Tartib muhim: deep link /start va /stop birinchi, keyin umumiy buyruqlar va bekor qilish.
    dp.include_routers(play.router, common.router, admin.router, create.router, stats.router, fallback.router)

    await setup_commands(bot, config.admin_ids)
    await clear_old_menus(bot, db, config.admin_ids)
    await notify_updated(bot)
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
