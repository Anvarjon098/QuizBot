"""Mening testlarim, shaxsiy statistika va umumiy reyting."""

from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..db import Database
from ..filters import IsAdmin
from ..keyboards import BTN_MY, BTN_RATING, BTN_STATS, MyQuizCB, owner_kb
from ..views import fmt_duration, place_mark, quiz_card

router = Router()
# Testlarim, statistika va reyting faqat adminlar uchun
router.message.filter(F.chat.type == ChatType.PRIVATE, StateFilter(None), IsAdmin())
router.callback_query.filter(IsAdmin())


# ---------- mening testlarim ----------

async def _my_quizzes_view(db: Database, user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    quizzes = await db.user_quizzes(user_id)
    if not quizzes:
        return "Sizda hali testlar yo'q. «➕ Yangi test» tugmasi orqali yarating.", None
    b = InlineKeyboardBuilder()
    for q in quizzes[:50]:
        b.button(text=f"{q.title} ({q.question_count})", callback_data=MyQuizCB(action="view", quiz_id=q.id))
    b.adjust(1)
    return f"📚 <b>Sizning testlaringiz</b> ({len(quizzes)} ta):", b.as_markup()


@router.message(F.text == BTN_MY)
async def my_quizzes(message: Message, db: Database) -> None:
    text, kb = await _my_quizzes_view(db, message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(MyQuizCB.filter(F.action == "list"))
async def my_quizzes_cb(call: CallbackQuery, db: Database) -> None:
    text, kb = await _my_quizzes_view(db, call.from_user.id)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(MyQuizCB.filter(F.action != "list"))
async def my_quiz_action(call: CallbackQuery, callback_data: MyQuizCB, db: Database, bot: Bot) -> None:
    quiz = await db.get_quiz(callback_data.quiz_id)
    if not quiz or quiz.owner_id != call.from_user.id:
        await call.answer("Test topilmadi.", show_alert=True)
        return
    username = (await bot.me()).username
    back = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Orqaga", callback_data=MyQuizCB(action="view", quiz_id=quiz.id).pack())
    ]])

    if callback_data.action == "view":
        await call.message.edit_text(quiz_card(quiz), reply_markup=owner_kb(username, quiz))

    elif callback_data.action == "stats":
        await call.message.edit_text(await quiz_stats_text(db, quiz), reply_markup=back)

    elif callback_data.action == "del":
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Ha, o'chirilsin",
                                 callback_data=MyQuizCB(action="delok", quiz_id=quiz.id).pack()),
            InlineKeyboardButton(text="❌ Yo'q", callback_data=MyQuizCB(action="view", quiz_id=quiz.id).pack()),
        ]])
        await call.message.edit_text(
            f"«<b>{escape(quiz.title)}</b>» testi va uning barcha natijalari o'chiriladi. Ishonchingiz komilmi?",
            reply_markup=kb,
        )

    elif callback_data.action == "delok":
        await db.delete_quiz(quiz.id)
        await call.answer("O'chirildi")
        text, kb = await _my_quizzes_view(db, call.from_user.id)
        await call.message.edit_text(text, reply_markup=kb)
        return
    await call.answer()


async def quiz_stats_text(db: Database, quiz) -> str:
    st = await db.quiz_stats(quiz.id)
    lines = [f"📊 <b>{escape(quiz.title)}</b> — statistika", ""]
    if not st["attempts"]:
        lines.append("Bu testni hali hech kim ishlamagan.")
        return "\n".join(lines)
    lines += [
        f"🎮 Urinishlar: <b>{st['attempts']}</b>",
        f"👥 Ishtirokchilar: <b>{st['players']}</b>",
        f"🎯 O'rtacha natija: <b>{st['avg_pct']:.0f}%</b>",
        f"⏱ O'rtacha vaqt: <b>{fmt_duration(st['avg_duration'])}</b>",
        "",
        "🏆 <b>Eng yaxshi natijalar:</b>",
    ]
    for i, r in enumerate((await db.quiz_leaderboard(quiz.id))[:10]):
        lines.append(f"{place_mark(i)} {escape(r['name'])} — {r['score']}/{r['total']} ({fmt_duration(r['duration'])})")
    qstats = await db.question_stats(quiz.id)
    if qstats:
        lines += ["", "🧩 <b>Eng qiyin savollar:</b>"]
        for r in qstats[:3]:
            text = r["text"] if len(r["text"]) <= 50 else r["text"][:50] + "…"
            lines.append(f"{r['position'] + 1}. {escape(text)} — <b>{r['pct']:.0f}%</b> to'g'ri")
    return "\n".join(lines)


# ---------- shaxsiy statistika ----------

@router.message(F.text == BTN_STATS)
async def my_stats(message: Message, db: Database) -> None:
    uid = message.from_user.id
    st = await db.user_stats(uid)
    lines = ["📊 <b>Sizning statistikangiz</b>", ""]
    if st["attempts"]:
        pct = 100 * st["correct"] / st["total"] if st["total"] else 0
        lines += [
            f"🎮 Ishlangan testlar: <b>{st['attempts']}</b> (turli: {st['quizzes']})",
            f"✅ To'g'ri javoblar: <b>{st['correct']}</b> / {st['total']} ({pct:.0f}%)",
            f"🌟 Eng yaxshi natija: <b>{st['best_pct']:.0f}%</b>",
        ]
    else:
        lines.append("Siz hali birorta test ishlamagansiz.")
    lines += [
        f"📝 Yaratgan testlaringiz: <b>{st['created']}</b>",
        f"👀 Testlaringiz ishlangan: <b>{st['plays_of_mine']}</b> marta",
    ]
    place = await db.user_global_place(uid)
    if place:
        lines.append(f"🏆 Umumiy reytingdagi o'rningiz: <b>{place['place']}</b> / {place['total']} "
                     f"({place['points']} ball)")
    recent = await db.user_recent_attempts(uid)
    if recent:
        lines += ["", "🕘 <b>So'nggi natijalar:</b>"]
        for r in recent:
            lines.append(f"• {escape(r['title'])} — {r['score']}/{r['total']}")
    await message.answer("\n".join(lines))


# ---------- umumiy reyting ----------

@router.message(F.text == BTN_RATING)
async def rating(message: Message, db: Database) -> None:
    top = await db.global_rating(10)
    lines = ["🏆 <b>Umumiy reyting</b>",
             "<i>Har bir testdagi eng yaxshi natija hisobga olinadi (o'z testlaringizdan tashqari).</i>", ""]
    if not top:
        lines.append("Reyting hali bo'sh.")
    for i, r in enumerate(top):
        lines.append(f"{place_mark(i)} {escape(r['name'])} — <b>{r['points']}</b> ball ({r['quizzes']} test)")
    place = await db.user_global_place(message.from_user.id)
    if place:
        lines.append(f"\nSizning o'rningiz: <b>{place['place']}</b> / {place['total']} ({place['points']} ball)")
    await message.answer("\n".join(lines))
