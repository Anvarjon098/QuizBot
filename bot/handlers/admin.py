"""Admin panel: statistika, xabar yuborish, testlarni boshqarish, foydalanuvchilarni eksport qilish."""

import asyncio
import io
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..db import Database
from ..filters import IsAdmin
from ..keyboards import AdminCB, main_menu
from ..runner import QuizManager
from ..states import AdminState
from .stats import quiz_stats_text
from ..views import quiz_card

log = logging.getLogger(__name__)
PAGE_SIZE = 8


router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE, IsAdmin())
router.callback_query.filter(IsAdmin())


def panel_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📈 Statistika", callback_data=AdminCB(action="stats"))
    b.button(text="📢 Xabar yuborish", callback_data=AdminCB(action="bc"))
    b.button(text="📚 Testlar", callback_data=AdminCB(action="quizzes"))
    b.button(text="📥 Foydalanuvchilar (Excel)", callback_data=AdminCB(action="export"))
    b.adjust(2, 1, 1)
    return b.as_markup()


def back_kb(action: str = "panel", page: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Orqaga", callback_data=AdminCB(action=action, page=page).pack())
    ]])


@router.message(StateFilter("*"), Command("admin"))
async def admin_panel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🛠 <b>Admin panel</b>", reply_markup=panel_kb())


@router.callback_query(AdminCB.filter(F.action == "panel"))
async def panel_cb(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("🛠 <b>Admin panel</b>", reply_markup=panel_kb())
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "stats"))
async def stats_cb(call: CallbackQuery, db: Database, manager: QuizManager) -> None:
    c = await db.admin_counts()
    text = (
        "📈 <b>Umumiy statistika</b>\n\n"
        f"👤 Foydalanuvchilar: <b>{c['users']}</b> (bugun +{c['users_today']})\n"
        f"📬 Xabar yuborish mumkin: <b>{c['reachable']}</b>\n"
        f"📚 Testlar: <b>{c['quizzes']}</b> (bugun +{c['quizzes_today']})\n"
        f"🖊 Savollar: <b>{c['questions']}</b>\n"
        f"🎮 Urinishlar: <b>{c['attempts']}</b> (bugun +{c['attempts_today']})\n"
        f"▶️ Hozir ketayotgan testlar: <b>{len(manager.sessions)}</b>"
    )
    await call.message.edit_text(text, reply_markup=back_kb())
    await call.answer()


# ---------- testlar ----------

@router.callback_query(AdminCB.filter(F.action == "quizzes"))
async def quizzes_cb(call: CallbackQuery, callback_data: AdminCB, db: Database) -> None:
    total = await db.count_quizzes()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(0, callback_data.page), pages - 1)
    quizzes = await db.all_quizzes(page * PAGE_SIZE, PAGE_SIZE)
    b = InlineKeyboardBuilder()
    for q in quizzes:
        b.button(text=f"#{q.id} {q.title} ({q.question_count})",
                 callback_data=AdminCB(action="quiz", quiz_id=q.id, page=page))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=AdminCB(action="quizzes", page=page - 1).pack()))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data=AdminCB(action="noop").pack()))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=AdminCB(action="quizzes", page=page + 1).pack()))
    b.adjust(1)
    b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=AdminCB(action="panel").pack()))
    await call.message.edit_text(f"📚 <b>Barcha testlar</b> ({total} ta):", reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(AdminCB.filter(F.action.in_({"quiz", "qdel", "qdelok"})))
async def quiz_cb(call: CallbackQuery, callback_data: AdminCB, db: Database) -> None:
    quiz = await db.get_quiz(callback_data.quiz_id)
    if not quiz:
        await call.answer("Test topilmadi.", show_alert=True)
        return
    page = callback_data.page
    if callback_data.action == "qdelok":
        await db.delete_quiz(quiz.id)
        await call.message.edit_text(f"🗑 «{escape(quiz.title)}» o'chirildi.", reply_markup=back_kb("quizzes", page))
        await call.answer()
        return
    if callback_data.action == "qdel":
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Ha", callback_data=AdminCB(action="qdelok", quiz_id=quiz.id, page=page).pack()),
            InlineKeyboardButton(text="❌ Yo'q", callback_data=AdminCB(action="quiz", quiz_id=quiz.id, page=page).pack()),
        ]])
        await call.message.edit_text(f"«{escape(quiz.title)}» o'chirilsinmi?", reply_markup=kb)
        await call.answer()
        return
    text = (
        quiz_card(quiz)
        + f"\n👤 Muallif ID: <code>{quiz.owner_id}</code>\n📅 Yaratilgan: {quiz.created_at}\n\n"
        + await quiz_stats_text(db, quiz)
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 O'chirish",
                              callback_data=AdminCB(action="qdel", quiz_id=quiz.id, page=page).pack())],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=AdminCB(action="quizzes", page=page).pack())],
    ])
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "noop"))
async def noop_cb(call: CallbackQuery) -> None:
    await call.answer()


# ---------- foydalanuvchilarni eksport ----------

@router.callback_query(AdminCB.filter(F.action == "export"))
async def export_cb(call: CallbackQuery, db: Database) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    users = await db.all_users()
    wb = Workbook()
    ws = wb.active
    ws.title = "Foydalanuvchilar"
    ws.append(["ID", "Username", "Ism", "Xabar yuborish mumkin", "Qo'shilgan", "Testlari", "Urinishlari"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for u in users:
        ws.append([u["id"], f"@{u['username']}" if u["username"] else "", u["full_name"],
                   "ha" if u["can_message"] else "yo'q", u["joined_at"], u["quizzes"], u["attempts"]])
    for col, width in zip("ABCDEFG", (14, 20, 30, 12, 20, 10, 12)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    await call.message.answer_document(
        BufferedInputFile(buf.getvalue(), "foydalanuvchilar.xlsx"),
        caption=f"👤 Jami: {len(users)} ta foydalanuvchi",
    )
    await call.answer()


# ---------- xabar yuborish ----------

@router.callback_query(AdminCB.filter(F.action == "bc"))
async def broadcast_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminState.broadcast)
    await call.message.edit_text(
        "📢 Barcha foydalanuvchilarga yuboriladigan xabarni yuboring "
        "(matn, rasm, video, fayl — istalgan turdagi xabar).",
        reply_markup=back_kb(),
    )
    await call.answer()


@router.message(AdminState.broadcast)
async def broadcast_preview(message: Message, state: FSMContext, db: Database) -> None:
    count = len(await db.messageable_user_ids())
    await state.update_data(bc_chat=message.chat.id, bc_msg=message.message_id)
    await state.set_state(AdminState.broadcast_confirm)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yuborish", callback_data=AdminCB(action="bcok").pack()),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data=AdminCB(action="panel").pack()),
    ]])
    await message.answer(f"Yuqoridagi xabar <b>{count}</b> ta foydalanuvchiga yuborilsinmi?", reply_markup=kb)


@router.callback_query(AdminState.broadcast_confirm, AdminCB.filter(F.action == "bcok"))
async def broadcast_go(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    await call.message.edit_text("⏳ Xabar yuborilmoqda… Tugagach hisobot yuboraman.")
    await call.answer()
    asyncio.create_task(_broadcast(bot, db, call.from_user.id, data["bc_chat"], data["bc_msg"]))


async def _broadcast(bot: Bot, db: Database, admin_id: int, from_chat: int, message_id: int) -> None:
    ok = failed = blocked = 0
    for uid in await db.messageable_user_ids():
        for _ in range(3):
            try:
                await bot.copy_message(uid, from_chat, message_id)
                ok += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramForbiddenError:
                blocked += 1
                await db.set_can_message(uid, False)
                break
            except TelegramBadRequest:
                failed += 1
                break
            except Exception:
                log.exception("Xabar yuborishda xato (user %s)", uid)
                failed += 1
                break
        await asyncio.sleep(0.05)  # Telegram limiti: ~30 xabar/soniya
    await bot.send_message(
        admin_id,
        f"📢 <b>Xabar yuborish yakunlandi</b>\n\n✅ Yetkazildi: {ok}\n🚫 Botni bloklagan: {blocked}\n"
        f"⚠️ Xato: {failed}",
        reply_markup=main_menu(),
    )


# ---------- zaxira nusxa: /backup va /restore ----------

@router.message(StateFilter("*"), Command("backup"))
async def backup(message: Message, db: Database) -> None:
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "quizbot.db")
        await db.backup_to(path)
        with open(path, "rb") as f:
            data = f.read()
    await message.answer_document(
        BufferedInputFile(data, filename="quizbot.db"),
        caption="💾 Bazaning zaxira nusxasi.\nBoshqa serverga ko'chirish: shu faylni yangi botga "
                "<code>/restore</code> izohi bilan yuboring.",
    )


@router.message(StateFilter("*"), F.document, F.caption.regexp(r"^/restore(@\w+)?\s*$"))
async def restore(message: Message, db: Database, manager: QuizManager, bot: Bot) -> None:
    import os
    import tempfile
    from ..db import is_valid_backup
    if manager.sessions:
        await message.answer("⚠️ Hozir testlar ketmoqda. Ular tugagach qayta urinib ko'ring.")
        return
    if message.document.file_size and message.document.file_size > 50 * 1024 * 1024:
        await message.answer("⚠️ Fayl juda katta.")
        return
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "upload.db")
        await bot.download(message.document, destination=path)
        if not is_valid_backup(path):
            await message.answer("⚠️ Bu fayl QuizBot bazasi emas yoki shikastlangan.")
            return
        await db.restore_from(path)
    manager.lobbies.clear()
    counts = await db.admin_counts()
    await message.answer(
        "✅ Baza tiklandi!\n"
        f"👥 Foydalanuvchilar: <b>{counts['users']}</b>\n"
        f"📚 Testlar: <b>{counts['quizzes']}</b> ({counts['questions']} savol)\n"
        f"🎮 Urinishlar: <b>{counts['attempts']}</b>"
    )


# ---------- /update: GitHub'dan yangi kodni yuklab, qayta ishga tushish ----------
#   /update           — testlar ketayotgan bo'lsa, ular tugashini kutib yangilanadi
#   /update majburiy  — testlarni darhol yakunlab (natijalar saqlanadi), yangilanadi
#   /update bekor     — navbatdagi yangilanishni bekor qiladi

FORCE_WORDS = {"majburiy", "force", "darhol", "hozir"}
CANCEL_WORDS = {"bekor", "cancel"}


async def _perform_update(bot: Bot, chat_id: int, dispatcher, manager: QuizManager) -> None:
    """Eng so'nggi kodni o'rnatadi va botni qayta ishga tushiradi."""
    from .. import updater
    try:
        commit = await updater.latest_commit()
        if commit.sha == updater.current_version():
            manager.updating = False
            await bot.send_message(chat_id, f"✅ Bot eng so'nggi versiyada.\n"
                                            f"<code>{commit.sha[:7]}</code> {escape(commit.message)}")
            return
        await bot.send_message(chat_id, f"⬇️ Yuklanmoqda: <code>{commit.sha[:7]}</code> {escape(commit.message)}")
        await updater.apply_update(commit)
    except Exception as e:
        manager.updating = False
        if not isinstance(e, updater.UpdateError):
            log.exception("Yangilashda xato")
        await bot.send_message(chat_id, f"⚠️ Yangilab bo'lmadi: {escape(str(e) or type(e).__name__)}")
        return
    updater.save_notice(chat_id, commit)
    await bot.send_message(chat_id, "♻️ Kod yangilandi, bot qayta ishga tushmoqda (5–15 soniya)...")
    if dispatcher is not None:
        # handler tugashini kutmasdan to'xtatish (aks holda o'zini o'zi kutib qoladi)
        asyncio.get_running_loop().call_later(1, lambda: asyncio.create_task(dispatcher.stop_polling()))


@router.message(StateFilter("*"), Command("update"))
async def update_bot(message: Message, command: CommandObject, manager: QuizManager, bot: Bot,
                     dispatcher=None) -> None:
    arg = (command.args or "").strip().lower()
    chat_id = message.chat.id

    if arg in CANCEL_WORDS:
        if manager.on_idle is None:
            await message.answer("Navbatda yangilanish yo'q.")
            return
        manager.on_idle = None
        manager.updating = False
        await message.answer("❎ Yangilanish bekor qilindi, testlar odatdagidek boshlanaveradi.")
        return

    force = arg in FORCE_WORDS
    if manager.sessions and not force:
        if manager.on_idle is not None:
            await message.answer(f"⏳ Yangilanish allaqachon navbatda ({len(manager.sessions)} ta test ketmoqda).\n"
                                 "Darhol: <code>/update majburiy</code> · Bekor: <code>/update bekor</code>")
            return
        manager.updating = True
        manager.on_idle = lambda: _perform_update(bot, chat_id, dispatcher, manager)
        await message.answer(
            f"⏳ Hozir <b>{len(manager.sessions)}</b> ta test ketmoqda. Ular tugashi bilan bot o'zi yangilanadi "
            "va sizga xabar beradi. Shu orada yangi testlar boshlanmaydi.\n\n"
            "Darhol yangilash: <code>/update majburiy</code>\nBekor qilish: <code>/update bekor</code>"
        )
        return

    manager.updating = True
    manager.on_idle = None
    if manager.sessions:
        await message.answer(f"⏹ {len(manager.sessions)} ta test yakunlanmoqda, natijalar saqlanadi...")
        await manager.shutdown(reason="update")
    else:
        await message.answer("🔎 Yangilanish tekshirilmoqda...")
    await _perform_update(bot, chat_id, dispatcher, manager)
