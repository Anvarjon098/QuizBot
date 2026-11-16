"""Chatlarda testlarni o'tkazish: savollarni quiz-poll sifatida yuborish va javoblarni hisoblash."""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from html import escape

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, PollAnswer

from .db import Database
from .keyboards import PlayCB, group_link, share_link
from .models import Question, Quiz
from .views import fmt_duration, place_mark

log = logging.getLogger(__name__)

INACTIVE_LIMIT = 2  # shaxsiy chatda ketma-ket javobsiz savollar soni
PAUSE_AFTER_ANSWER = 1.5  # izohni o'qib olish uchun


@dataclass
class Participant:
    user_id: int
    name: str
    score: int = 0
    time: float = 0.0
    answers: dict[int, bool] = field(default_factory=dict)


@dataclass
class Session:
    chat_id: int
    quiz: Quiz
    questions: list[Question]
    launcher_id: int
    is_group: bool
    participants: dict[int, Participant] = field(default_factory=dict)
    shown: int = 0
    sent_at: float = 0.0
    answered: asyncio.Event = field(default_factory=asyncio.Event)
    stop_reason: str | None = None  # None | manual | inactive
    task: asyncio.Task | None = None


@dataclass
class Lobby:
    quiz_id: int
    launcher_id: int
    message_id: int
    ready: dict[int, str] = field(default_factory=dict)


def prepare_questions(quiz: Quiz, questions: list[Question], rng: random.Random | None = None) -> list[Question]:
    """Sozlamaga ko'ra savollar va/yoki javoblarni aralashtiradi."""
    rng = rng or random.Random()
    result = []
    for q in questions:
        options = list(q.options)
        correct = q.correct
        if quiz.shuffle_options:
            order = list(range(len(options)))
            rng.shuffle(order)
            options = [q.options[i] for i in order]
            correct = order.index(q.correct)
        result.append(Question(q.text, options, correct, q.explanation, q.id))
    if quiz.shuffle_questions:
        rng.shuffle(result)
    return result


class QuizManager:
    def __init__(self, db: Database, admin_ids: frozenset[int] = frozenset()):
        self.db = db
        self.admin_ids = admin_ids
        self.sessions: dict[int, Session] = {}
        self.polls: dict[str, tuple[Session, Question]] = {}
        self.lobbies: dict[int, Lobby] = {}

    def is_running(self, chat_id: int) -> bool:
        return chat_id in self.sessions

    def get(self, chat_id: int) -> Session | None:
        return self.sessions.get(chat_id)

    def start(self, bot: Bot, chat_id: int, quiz: Quiz, questions: list[Question],
              launcher_id: int, is_group: bool) -> Session:
        if chat_id in self.sessions:
            raise RuntimeError("Bu chatda test allaqachon ketmoqda")
        session = Session(chat_id, quiz, prepare_questions(quiz, questions), launcher_id, is_group)
        self.sessions[chat_id] = session
        self.lobbies.pop(chat_id, None)
        session.task = asyncio.create_task(self._run(bot, session))
        return session

    def stop(self, chat_id: int) -> bool:
        session = self.sessions.get(chat_id)
        if not session or not session.task:
            return False
        session.stop_reason = "manual"
        session.task.cancel()
        return True

    async def shutdown(self) -> None:
        tasks = [s.task for s in self.sessions.values() if s.task]
        for s in self.sessions.values():
            s.stop_reason = "manual"
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # ---------- javoblar ----------

    async def handle_answer(self, answer: PollAnswer) -> None:
        entry = self.polls.get(answer.poll_id)
        if not entry or not answer.user or not answer.option_ids:
            return
        session, question = entry
        user = answer.user
        p = session.participants.get(user.id)
        if p is None:
            p = session.participants[user.id] = Participant(user.id, user.full_name)
        if question.id in p.answers:
            return
        is_correct = answer.option_ids[0] == question.correct
        p.answers[question.id] = is_correct
        p.score += int(is_correct)
        p.time += asyncio.get_running_loop().time() - session.sent_at
        if not session.is_group and user.id == session.launcher_id:
            session.answered.set()

    # ---------- asosiy sikl ----------

    async def _run(self, bot: Bot, s: Session) -> None:
        loop = asyncio.get_running_loop()
        missed = 0
        current_msg_id: int | None = None
        try:
            await bot.send_message(
                s.chat_id,
                f"🏁 <b>{escape(s.quiz.title)}</b> testi boshlanmoqda!\n"
                f"🖊 {len(s.questions)} ta savol · ⏱ har biriga {s.quiz.open_period} soniya\n\n"
                f"To'xtatish uchun: /stop",
            )
            await asyncio.sleep(2)
            total = len(s.questions)
            for i, q in enumerate(s.questions, 1):
                msg = await bot.send_poll(
                    chat_id=s.chat_id,
                    question=f"[{i}/{total}] {q.text}",
                    options=q.options,
                    type="quiz",
                    correct_option_id=q.correct,
                    explanation=q.explanation or None,
                    is_anonymous=False,
                    open_period=s.quiz.open_period,
                )
                current_msg_id = msg.message_id
                s.shown = i
                s.sent_at = loop.time()
                s.answered.clear()
                self.polls[msg.poll.id] = (s, q)
                try:
                    if s.is_group:
                        await asyncio.sleep(s.quiz.open_period + 1)
                    else:
                        await asyncio.wait_for(s.answered.wait(), timeout=s.quiz.open_period + 1)
                except TimeoutError:
                    pass
                finally:
                    self.polls.pop(msg.poll.id, None)
                current_msg_id = None

                if not s.is_group:
                    if s.answered.is_set():
                        missed = 0
                        if i < total:
                            await asyncio.sleep(PAUSE_AFTER_ANSWER)
                    else:
                        missed += 1
                        if missed >= INACTIVE_LIMIT and i < total:
                            s.stop_reason = "inactive"
                            break
        except asyncio.CancelledError:
            if current_msg_id is not None:
                try:
                    await bot.stop_poll(s.chat_id, current_msg_id)
                except Exception:
                    pass
        except Exception:
            log.exception("Testni o'tkazishda xato (chat %s)", s.chat_id)
            s.stop_reason = s.stop_reason or "error"
        finally:
            self.sessions.pop(s.chat_id, None)
            for pid in [k for k, v in self.polls.items() if v[0] is s]:
                self.polls.pop(pid, None)
            try:
                await self._finish(bot, s)
            except Exception:
                log.exception("Natijalarni yuborishda xato (chat %s)", s.chat_id)

    # ---------- natijalar ----------

    async def _finish(self, bot: Bot, s: Session) -> None:
        players = sorted(
            (p for p in s.participants.values() if p.answers),
            key=lambda p: (-p.score, p.time),
        )
        for p in players:
            await self.db.save_attempt(
                s.quiz.id, p.user_id, s.chat_id, p.score, s.shown, p.time, p.answers
            )

        header = {
            "manual": "⏹ Test to'xtatildi.",
            "inactive": f"⏸ Siz ketma-ket {INACTIVE_LIMIT} ta savolga javob bermadingiz, test to'xtatildi.",
            "error": "⚠️ Texnik xato tufayli test to'xtatildi.",
        }.get(s.stop_reason or "", "🏁 Test yakunlandi!")
        title = f"<b>{escape(s.quiz.title)}</b>"
        username = (await bot.me()).username

        if s.is_group:
            lines = [header, title, ""]
            if not players:
                lines.append("Hech kim qatnashmadi 🤷")
            else:
                lines.append(f"🖊 {s.shown} ta savol · 👥 {len(players)} ishtirokchi\n")
                for i, p in enumerate(players[:20]):
                    lines.append(
                        f"{place_mark(i)} {escape(p.name)} — <b>{p.score}</b> "
                        f"({fmt_duration(p.time)})"
                    )
                lines.append("\n🏆 G'oliblarni tabriklaymiz!")
            await bot.send_message(s.chat_id, "\n".join(lines))
            return

        p = s.participants.get(s.launcher_id)
        score = p.score if p else 0
        answered = len(p.answers) if p else 0
        lines = [
            header, title, "",
            f"✅ To'g'ri: <b>{score}</b>",
            f"❌ Noto'g'ri: <b>{answered - score}</b>",
            f"⌛️ Javobsiz: <b>{s.shown - answered}</b>",
        ]
        if p and answered:
            lines.append(f"⏱ Sarflangan vaqt: <b>{fmt_duration(p.time)}</b>")
            board = await self.db.quiz_leaderboard(s.quiz.id)
            place = next((i for i, r in enumerate(board) if r["user_id"] == s.launcher_id), None)
            if place is not None:
                lines.append(f"\n🏆 Ushbu testdagi o'rningiz: <b>{place + 1}</b> / {len(board)}")
        rows = [[InlineKeyboardButton(text="🔄 Qayta ishlash", callback_data=PlayCB(quiz_id=s.quiz.id).pack())]]
        if s.launcher_id in self.admin_ids:  # ulashish tugmalari faqat adminlarga
            rows += [
                [InlineKeyboardButton(text="👥 Guruhda o'tkazish", url=group_link(username, s.quiz))],
                [InlineKeyboardButton(text="📤 Ulashish", url=share_link(username, s.quiz))],
            ]
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        await bot.send_message(s.chat_id, "\n".join(lines), reply_markup=kb)
