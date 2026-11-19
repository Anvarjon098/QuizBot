"""Inline rejim: istalgan chatda «@bot quiz:KOD» yozilsa, test kartochkasi chiqadi."""

import re
from html import escape

from aiogram import Bot, Router
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent

from ..config import Config
from ..db import Database
from ..keyboards import card_kb, fmt_seconds
from ..models import Quiz

router = Router()

CODE_RE = re.compile(r"^(?:quiz[:_ ]?)?([A-Za-z0-9_-]{4,16})$", re.IGNORECASE)


def card_text(quiz: Quiz) -> str:
    lines = [f"🎲 Test «<b>{escape(quiz.title)}</b>»"]
    if quiz.description:
        lines.append(f"<i>{escape(quiz.description)}</i>")
    lines.append(f"🖊 {quiz.question_count} ta savol · ⏱ {fmt_seconds(quiz.open_period)}")
    return "\n".join(lines)


def _article(username: str, quiz: Quiz) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=f"quiz{quiz.id}",
        title=quiz.title,
        description=f"{quiz.question_count} ta savol · {fmt_seconds(quiz.open_period)}",
        input_message_content=InputTextMessageContent(message_text=card_text(quiz), parse_mode="HTML"),
        reply_markup=card_kb(username, quiz),
    )


@router.inline_query()
async def inline_quiz(query: InlineQuery, db: Database, bot: Bot, config: Config) -> None:
    text = query.query.strip()
    quizzes: list[Quiz] = []
    if m := CODE_RE.match(text):  # aniq kod: hamma uchun
        quiz = await db.get_quiz_by_code(m.group(1))
        if quiz:
            quizzes = [quiz]
    if not quizzes and query.from_user.id in config.admin_ids:  # admin: nomi bo'yicha qidiruv
        quizzes = await db.search_quizzes(re.sub(r"^quiz:?", "", text, flags=re.IGNORECASE).strip())
    username = (await bot.me()).username
    await query.answer(
        [_article(username, q) for q in quizzes if q.question_count],
        cache_time=10,
        is_personal=True,
    )
