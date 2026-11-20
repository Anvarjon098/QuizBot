"""Chatlarda testlarni o'tkazish: savollarni quiz-poll sifatida yuborish va javoblarni hisoblash."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html import escape

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter, TelegramServerError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, PollAnswer, ReplyKeyboardRemove

from .db import Database
from .keyboards import PlayCB, ResumeCB, group_link, share_button
from .models import Question, Quiz
from .views import fmt_duration, fmt_duration_long, place_mark, rank_text

log = logging.getLogger(__name__)

INACTIVE_LIMIT = 2  # shaxsiy chatda ketma-ket javobsiz savollar soni
PAUSE_AFTER_ANSWER = 1.5  # izohni o'qib olish uchun
SEND_ATTEMPTS = 6  # tarmoq uzilsa, savolni qayta yuborish urinishlari
POLL_QUESTION_MAX = 300  # Telegram cheklovlari
POLL_OPTION_MAX = 100
POLL_EXPLANATION_MAX = 200
LETTERS = "ABCDEFGHIJ"


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
    stop_reason: str | None = None  # None | manual | inactive | update | error
    skipped: int = 0  # Telegram rad etgan savollar
    start_at: int = 0  # davom ettirilganda: shu indeksdagi savoldan boshlanadi
    prev_attempt_id: int | None = None  # davom ettirilganda: oldingi qisman urinish (almashtiriladi)
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
        # /update navbatda bo'lsa: yangi testlar boshlanmaydi, oxirgisi tugagach on_idle chaqiriladi
        self.updating = False
        self.on_idle: Callable[[], Awaitable[None]] | None = None

    def is_running(self, chat_id: int) -> bool:
        return chat_id in self.sessions

    def get(self, chat_id: int) -> Session | None:
        return self.sessions.get(chat_id)

    def start(self, bot: Bot, chat_id: int, quiz: Quiz, questions: list[Question],
              launcher_id: int, is_group: bool) -> Session:
        session = Session(chat_id, quiz, prepare_questions(quiz, questions), launcher_id, is_group)
        return self._launch(bot, session)

    def resume(self, bot: Bot, chat_id: int, quiz: Quiz, progress: dict, user_id: int, name: str) -> Session:
        """To'xtatilgan testni saqlangan joyidan davom ettiradi (savollar tartibi o'sha-o'sha)."""
        questions = [Question.from_dict(d) for d in progress["questions"]]
        session = Session(chat_id, quiz, questions, user_id, is_group=False,
                          start_at=progress["position"], prev_attempt_id=progress.get("attempt_id"))
        session.shown = progress["position"]
        session.participants[user_id] = Participant(
            user_id, name, score=progress["score"], time=progress["time"],
            answers={int(k): v for k, v in progress["answers"].items()},
        )
        return self._launch(bot, session)

    def _launch(self, bot: Bot, session: Session) -> Session:
        chat_id = session.chat_id
        if chat_id in self.sessions:
            raise RuntimeError("Bu chatda test allaqachon ketmoqda")
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

    async def shutdown(self, reason: str = "manual") -> None:
        tasks = [s.task for s in self.sessions.values() if s.task]
        for s in self.sessions.values():
            s.stop_reason = reason
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

    @staticmethod
    def poll_payload(q: Question, i: int, total: int) -> tuple[str | None, str, list[str]]:
        """(oldindan yuboriladigan matn yoki None, poll savoli, poll variantlari).

        Telegram poll varianti 100, savoli 300 belgidan oshmasligi kerak. Uzunroq bo'lsa,
        to'liq matn alohida xabarda yuboriladi, pollda esa A, B, C... harflari qoladi."""
        head = f"[{i}/{total}] "
        long_options = any(len(o) > POLL_OPTION_MAX for o in q.options)
        long_question = len(head + q.text) > POLL_QUESTION_MAX
        if not long_options and not long_question:
            return None, head + q.text, list(q.options)
        letters = [LETTERS[k] for k in range(len(q.options))]
        lines = [f"<b>{head}</b>{escape(q.text)}", ""]
        lines += [f"<b>{letter})</b> {escape(o)}" for letter, o in zip(letters, q.options)]
        poll_question = head + ("Savol va javoblar yuqorida 👆" if long_question
                                else f"{q.text}\n(javoblar yuqorida 👆)")
        if len(poll_question) > POLL_QUESTION_MAX:
            poll_question = head + "Savol va javoblar yuqorida 👆"
        return "\n".join(lines), poll_question, letters

    async def _send_poll(self, bot: Bot, s: Session, q: Question, i: int, total: int):
        """Savolni yuboradi. Tarmoq uzilishi va Telegram cheklovlarida kutib, qayta urinadi.
        Telegram savolni rad etsa (noto'g'ri ma'lumot) — None qaytaradi."""
        intro, question, options = self.poll_payload(q, i, total)
        for attempt in range(1, SEND_ATTEMPTS + 1):
            try:
                if intro is not None:
                    await bot.send_message(s.chat_id, intro)
                    intro = None  # qayta urinishda takrorlanmasin
                return await bot.send_poll(
                    chat_id=s.chat_id,
                    question=question,
                    options=options,
                    type="quiz",
                    correct_option_id=q.correct,
                    explanation=_cut(q.explanation, POLL_EXPLANATION_MAX) if q.explanation else None,
                    is_anonymous=False,
                    open_period=s.quiz.open_period,
                    # savol matni oddiy matn: "<", ">" , "&" belgilari HTML deb o'qilmasin
                    question_parse_mode=None,
                    explanation_parse_mode=None,
                )
            except TelegramRetryAfter as e:
                log.warning("Telegram cheklovi (chat %s): %s s kutamiz", s.chat_id, e.retry_after)
                await asyncio.sleep(e.retry_after + 1)
            except (TelegramNetworkError, TelegramServerError) as e:
                if attempt == SEND_ATTEMPTS:
                    raise
                log.warning("Savolni yuborib bo'lmadi (chat %s, urinish %s): %s", s.chat_id, attempt, e)
                await asyncio.sleep(min(2 * attempt, 10))
            except TelegramBadRequest as e:
                if "chat not found" in e.message.lower():
                    raise
                log.error("Savol rad etildi (quiz %s, savol %s): %s", s.quiz.id, q.id, e.message)
                return None
        raise RuntimeError("Savolni yuborib bo'lmadi")

    async def _run(self, bot: Bot, s: Session) -> None:
        loop = asyncio.get_running_loop()
        missed = 0
        current_msg_id: int | None = None
        try:
            intro = (
                f"▶️ <b>{escape(s.quiz.title)}</b> testi davom etmoqda!\n"
                f"🖊 {s.start_at + 1}-savoldan · jami {len(s.questions)} ta · "
                if s.start_at else
                f"🏁 <b>{escape(s.quiz.title)}</b> testi boshlanmoqda!\n"
                f"🖊 {len(s.questions)} ta savol · "
            )
            await bot.send_message(
                s.chat_id,
                intro + f"⏱ har biriga {s.quiz.open_period} soniya\n\nTo'xtatish uchun: /stop",
                # oddiy foydalanuvchida eski menyu tugmalari qolgan bo'lsa, olib tashlanadi
                reply_markup=ReplyKeyboardRemove()
                if not s.is_group and s.launcher_id not in self.admin_ids else None,
            )
            await asyncio.sleep(2)
            total = len(s.questions)
            for i, q in enumerate(s.questions[s.start_at:], s.start_at + 1):
                msg = await self._send_poll(bot, s, q, i, total)
                if msg is None:  # Telegram bu savolni qabul qilmadi — o'tkazib yuboramiz
                    s.skipped += 1
                    continue
                current_msg_id = msg.message_id
                s.shown += 1
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
            if not self.sessions and self.on_idle is not None:
                callback, self.on_idle = self.on_idle, None
                try:
                    await callback()
                except Exception:
                    log.exception("on_idle xatosi")

    # ---------- natijalar ----------

    async def _save_progress(self, s: Session, p: Participant | None, attempt_id: int | None) -> int | None:
        """Shaxsiy chatda test oxirigacha bormay to'xtasa, davom ettirish uchun holatni saqlaydi.
        Davom etiladigan savol indeksini qaytaradi (yoki None — test tugagan)."""
        answered = p.answers if p else {}
        last = max((i for i, q in enumerate(s.questions) if q.id in answered), default=s.start_at - 1)
        position = max(last + 1, s.start_at) if answered else s.start_at
        if s.stop_reason is None or position >= len(s.questions):
            await self.db.delete_progress(s.launcher_id, s.quiz.id)
            return None
        await self.db.save_progress(s.launcher_id, s.quiz.id, {
            "questions": [{**q.to_dict(), "id": q.id} for q in s.questions],
            "position": position,
            "score": p.score if p else 0,
            "time": p.time if p else 0.0,
            "answers": {str(k): v for k, v in answered.items()},
            "attempt_id": attempt_id,
        })
        return position

    async def _finish(self, bot: Bot, s: Session) -> None:
        players = sorted(
            (p for p in s.participants.values() if p.answers),
            key=lambda p: (-p.score, p.time),
        )
        attempt_ids: dict[int, int] = {}
        if s.prev_attempt_id is not None:  # davom ettirilgan test — eski qisman urinish almashtiriladi
            await self.db.delete_attempt(s.prev_attempt_id)
        for p in players:
            attempt_ids[p.user_id] = await self.db.save_attempt(
                s.quiz.id, p.user_id, s.chat_id, p.score, s.shown, p.time, p.answers
            )
        total_q = len(s.questions)

        header = {
            "manual": "⏹ Test to'xtatildi.",
            "update": "🔧 Bot yangilanishi sababli test to'xtatildi. Natijangiz saqlandi — "
                      "bir daqiqadan keyin qayta ishlashingiz mumkin.",
            "inactive": f"⏸ Siz ketma-ket {INACTIVE_LIMIT} ta savolga javob bermadingiz, test to'xtatildi.",
            "error": "⚠️ Telegram bilan aloqa uzilgani sababli test to'xtatildi. "
                     "Javob berilgan savollar natijasi saqlandi.",
        }.get(s.stop_reason or "", "🏁 Test yakunlandi!")
        title = f"<b>{escape(s.quiz.title)}</b>"
        username = (await bot.me()).username

        if s.is_group:
            lines = [header, title, ""]
            if not players:
                lines.append("Hech kim qatnashmadi 🤷")
            else:
                lines.append(f"🖊 {s.shown} / {total_q} ta savol · 👥 {len(players)} ishtirokchi\n")
                for i, p in enumerate(players[:20]):
                    lines.append(
                        f"{place_mark(i)} {escape(p.name)} — <b>{p.score}</b> "
                        f"({fmt_duration(p.time)})"
                    )
                lines.append("\n🏆 G'oliblarni tabriklaymiz!")
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔄 Boshqa guruhda o'tkazish", url=group_link(username, s.quiz)),
            ]])
            await bot.send_message(s.chat_id, "\n".join(lines), reply_markup=kb)
            return

        p = s.participants.get(s.launcher_id)
        score = p.score if p else 0
        answered = len(p.answers) if p else 0
        name = f"“{escape(s.quiz.title)}”"
        head = {
            "manual": f"⏹ {name} testi to‘xtatildi.",
            "update": f"🔧 {name} testi bot yangilanishi sababli to‘xtatildi.",
            "inactive": f"⏸ {name} testi to‘xtatildi: siz ketma-ket {INACTIVE_LIMIT} ta savolga javob bermadingiz.",
            "error": f"⚠️ {name} testi Telegram bilan aloqa uzilgani sababli to‘xtatildi.",
        }.get(s.stop_reason or "", f"🏁 {name} testi yakunlandi!")
        of_total = f" (jami {total_q} tadan)" if s.shown < total_q else ""
        lines = [
            head, "",
            f"<i>Siz <b>{s.shown}</b> ta savolga javob berdingiz{of_total}:</i>", "",
            f"✅ To‘g‘ri – <b>{score}</b>",
            f"❌ Xato – <b>{answered - score}</b>",
            f"⌛️ Tashlab ketilgan – <b>{s.shown - answered}</b>",
        ]
        if p and answered:
            lines.append(f"⏱ {fmt_duration_long(p.time)}")
        if s.skipped:
            lines.append(f"⚠️ Telegram qabul qilmagan savollar – <b>{s.skipped}</b>")
        if p and answered:
            board = await self.db.quiz_leaderboard(s.quiz.id)
            place = next((i for i, r in enumerate(board) if r["user_id"] == s.launcher_id), None)
            if place is not None:
                lines += ["", rank_text(place, len(board))]
            lines += ["", "<i>Bu testni yana ishlashingiz mumkin — reytingda eng yaxshi natijangiz hisobga olinadi.</i>"]
        rows = [[InlineKeyboardButton(text="🔄 Qayta ishlash", callback_data=PlayCB(quiz_id=s.quiz.id).pack())]]
        position = await self._save_progress(s, p, attempt_ids.get(s.launcher_id))
        if position is not None:
            rows.append([InlineKeyboardButton(
                text=f"▶️ Davom etish ({position + 1}/{total_q})",
                callback_data=ResumeCB(quiz_id=s.quiz.id).pack(),
            )])
        rows.append([InlineKeyboardButton(text="👥 Guruhda o'tkazish", url=group_link(username, s.quiz))])
        if s.launcher_id in self.admin_ids:  # «Ulashish» faqat adminlarga
            rows.append([share_button(s.quiz)])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        await bot.send_message(s.chat_id, "\n".join(lines), reply_markup=kb)
