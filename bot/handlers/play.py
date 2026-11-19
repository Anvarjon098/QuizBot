"""Testni boshlash (shaxsiy chat va guruh), to'xtatish va javoblarni qabul qilish."""

import re
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, PollAnswer, ReplyKeyboardRemove

from ..config import Config
from ..db import Database
from ..keyboards import LobbyCB, PlayCB, ResumeCB, lobby_kb, main_menu, owner_kb, play_kb, guest_kb
from aiogram.types import InlineKeyboardButton
from ..runner import Lobby, QuizManager
from ..views import quiz_card

router = Router()

GROUPS = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
PRIVATE = F.chat.type == ChatType.PRIVATE
DEEP_LINK = re.compile(r"^quiz_([A-Za-z0-9_-]+)$")
READY_TO_START = 2
UPDATING_TEXT = "🔧 Bot hozir yangilanmoqda. Bir daqiqadan keyin qayta urinib ko'ring."


async def _is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR)


def _lobby_text(quiz, lobby: Lobby) -> str:
    names = ", ".join(escape(n) for n in lobby.ready.values()) or "—"
    return (
        quiz_card(quiz)
        + f"\n\nTest kamida <b>{READY_TO_START}</b> kishi tayyor bo'lganda boshlanadi.\n"
        f"✋ Tayyor ({len(lobby.ready)}): {names}"
    )


# ---------- deep link: /start quiz_CODE ----------

@router.message(StateFilter("*"), CommandStart(deep_link=True, magic=F.args.regexp(DEEP_LINK)), PRIVATE)
async def open_quiz_private(message: Message, command: CommandObject, state: FSMContext,
                            db: Database, bot: Bot, config: Config) -> None:
    await state.clear()
    is_admin = message.from_user.id in config.admin_ids
    menu = main_menu() if is_admin else ReplyKeyboardRemove()
    quiz = await db.get_quiz_by_code(DEEP_LINK.match(command.args).group(1))
    if not quiz:
        await message.answer("😕 Bu test topilmadi yoki o'chirilgan.", reply_markup=menu)
        return
    await message.answer("Test topildi 👇", reply_markup=menu)
    username = (await bot.me()).username
    if not is_admin:
        kb = guest_kb(username, quiz)
    else:
        kb = owner_kb(username, quiz) if quiz.owner_id == message.from_user.id else play_kb(username, quiz)
    progress = await db.get_progress(message.from_user.id, quiz.id)
    if progress:
        kb.inline_keyboard.insert(1, [InlineKeyboardButton(
            text=f"▶️ Davom etish ({progress['position'] + 1}/{len(progress['questions'])})",
            callback_data=ResumeCB(quiz_id=quiz.id).pack(),
        )])
    await message.answer(quiz_card(quiz), reply_markup=kb)


@router.message(CommandStart(deep_link=True, magic=F.args.regexp(DEEP_LINK)), GROUPS)
async def open_quiz_group(message: Message, command: CommandObject, db: Database,
                          manager: QuizManager) -> None:
    quiz = await db.get_quiz_by_code(DEEP_LINK.match(command.args).group(1))
    if not quiz:
        await message.answer("😕 Bu test topilmadi yoki o'chirilgan.")
        return
    if manager.is_running(message.chat.id):
        await message.answer("Bu guruhda test allaqachon ketmoqda. To'xtatish: /stop")
        return
    if manager.updating:
        await message.answer(UPDATING_TEXT)
        return
    lobby = Lobby(quiz.id, message.from_user.id, message_id=0)
    sent = await message.answer(_lobby_text(quiz, lobby), reply_markup=lobby_kb())
    lobby.message_id = sent.message_id
    manager.lobbies[message.chat.id] = lobby


@router.message(CommandStart(), GROUPS)
async def start_group(message: Message) -> None:
    await message.answer(
        "👋 Salom! Guruhda test o'tkazish uchun men bilan shaxsiy chatda testni oching va "
        "«👥 Guruhda o'tkazish» tugmasini bosing."
    )


# ---------- guruh lobbisi ----------

@router.callback_query(LobbyCB.filter())
async def lobby_action(call: CallbackQuery, callback_data: LobbyCB, db: Database,
                       manager: QuizManager, bot: Bot) -> None:
    chat_id = call.message.chat.id
    lobby = manager.lobbies.get(chat_id)
    if not lobby or lobby.message_id != call.message.message_id:
        await call.answer("Bu taklif eskirgan.", show_alert=True)
        return
    quiz = await db.get_quiz(lobby.quiz_id)
    if not quiz:
        manager.lobbies.pop(chat_id, None)
        await call.answer("Test o'chirilgan.", show_alert=True)
        return

    if callback_data.action == "ready":
        if call.from_user.id in lobby.ready:
            await call.answer("Siz allaqachon tayyorsiz ✋")
            return
        lobby.ready[call.from_user.id] = call.from_user.full_name
        await call.answer("Qabul qilindi!")
        if len(lobby.ready) < READY_TO_START:
            await call.message.edit_text(_lobby_text(quiz, lobby), reply_markup=lobby_kb())
            return
    elif callback_data.action == "go":
        if call.from_user.id != lobby.launcher_id and not await _is_chat_admin(bot, chat_id, call.from_user.id):
            await call.answer("Testni faqat uni chaqirgan kishi yoki guruh admini boshlay oladi.", show_alert=True)
            return
        await call.answer()
    else:
        await call.answer()
        return

    if manager.is_running(chat_id):
        return
    if manager.updating:
        await call.message.answer(UPDATING_TEXT)
        return
    questions = await db.get_questions(quiz.id)
    await call.message.edit_text(_lobby_text(quiz, lobby) + "\n\n🚀 Boshladik!")
    manager.start(bot, chat_id, quiz, questions, lobby.launcher_id, is_group=True)


# ---------- shaxsiy chatda boshlash ----------

@router.callback_query(PlayCB.filter())
async def play(call: CallbackQuery, callback_data: PlayCB, db: Database, manager: QuizManager,
               bot: Bot, state: FSMContext) -> None:
    if call.message.chat.type != ChatType.PRIVATE:
        await call.answer()
        return
    chat_id = call.message.chat.id
    if manager.is_running(chat_id):
        await call.answer("Avval joriy testni tugating yoki /stop buyrug'ini yuboring.", show_alert=True)
        return
    if manager.updating:
        await call.answer(UPDATING_TEXT, show_alert=True)
        return
    quiz = await db.get_quiz(callback_data.quiz_id)
    if not quiz:
        await call.answer("Bu test o'chirilgan.", show_alert=True)
        return
    questions = await db.get_questions(quiz.id)
    if not questions:
        await call.answer("Bu testda savollar yo'q.", show_alert=True)
        return
    await state.clear()
    await db.delete_progress(call.from_user.id, quiz.id)  # boshidan boshlanadi
    await call.answer("Boshladik! 🚀")
    manager.start(bot, chat_id, quiz, questions, call.from_user.id, is_group=False)


@router.callback_query(ResumeCB.filter())
async def resume(call: CallbackQuery, callback_data: ResumeCB, db: Database, manager: QuizManager,
                 bot: Bot, state: FSMContext) -> None:
    if call.message.chat.type != ChatType.PRIVATE:
        await call.answer()
        return
    chat_id = call.message.chat.id
    if manager.is_running(chat_id):
        await call.answer("Avval joriy testni tugating yoki /stop buyrug'ini yuboring.", show_alert=True)
        return
    if manager.updating:
        await call.answer(UPDATING_TEXT, show_alert=True)
        return
    quiz = await db.get_quiz(callback_data.quiz_id)
    if not quiz:
        await call.answer("Bu test o'chirilgan.", show_alert=True)
        return
    progress = await db.get_progress(call.from_user.id, quiz.id)
    if not progress:
        await call.answer("Davom ettirish uchun saqlangan holat yo'q. «🔄 Qayta ishlash» ni bosing.",
                          show_alert=True)
        return
    await state.clear()
    await call.answer("Davom etamiz! ▶️")
    manager.resume(bot, chat_id, quiz, progress, call.from_user.id, call.from_user.full_name)


# ---------- to'xtatish ----------

@router.message(StateFilter("*"), Command("stop"))
async def stop(message: Message, manager: QuizManager, bot: Bot) -> None:
    chat_id = message.chat.id
    session = manager.get(chat_id)
    if session is None:
        if manager.lobbies.pop(chat_id, None):
            await message.answer("Test bekor qilindi.")
        else:
            await message.answer("Hozir hech qanday test ketmayapti.")
        return
    if session.is_group and message.from_user.id != session.launcher_id \
            and not await _is_chat_admin(bot, chat_id, message.from_user.id):
        await message.answer("Testni faqat uni boshlagan kishi yoki guruh admini to'xtata oladi.")
        return
    manager.stop(chat_id)


# ---------- javoblar ----------

@router.poll_answer()
async def poll_answer(answer: PollAnswer, manager: QuizManager) -> None:
    await manager.handle_answer(answer)
