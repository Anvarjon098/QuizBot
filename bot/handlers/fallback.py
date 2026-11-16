"""Oddiy foydalanuvchilar uchun yopiq funksiyalarga javob (eng oxirgi router)."""

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from ..config import Config

router = Router()


@router.message(F.chat.type == ChatType.PRIVATE)
async def not_available(message: Message, config: Config) -> None:
    if message.from_user.id in config.admin_ids:
        return  # adminlar uchun noma'lum xabarlarga javob bermaymiz
    await message.answer(
        "Bu bot orqali faqat sizga yuborilgan testlarni ishlash mumkin. "
        "Testni boshlash uchun test havolasini oching.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.callback_query()
async def callback_not_available(call: CallbackQuery, config: Config) -> None:
    if call.from_user.id in config.admin_ids:
        await call.answer("Bu tugma eskirgan.")
    else:
        await call.answer("Bu funksiya siz uchun mavjud emas.", show_alert=True)
