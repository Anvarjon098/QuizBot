import asyncio
import itertools
from types import SimpleNamespace

import pytest

import bot.runner as runner_mod
from bot.db import Database
from bot.models import Question
from bot.runner import QuizManager, prepare_questions


class FakeUser(SimpleNamespace):
    is_bot = False


def user(uid, name):
    return FakeUser(id=uid, username=None, full_name=name)


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    await d.connect()
    yield d
    await d.close()


QS = [Question(f"Q{i}?", ["a", "b", "c"], i % 3, None) for i in range(4)]


class FakeBot:
    def __init__(self):
        self.ids = itertools.count(1)
        self.sent = []
        self.polls = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)

    async def send_poll(self, **kw):
        pid = str(next(self.ids))
        self.polls.append((pid, kw))
        return SimpleNamespace(message_id=int(pid), poll=SimpleNamespace(id=pid))

    async def stop_poll(self, *a):
        pass

    async def me(self):
        return SimpleNamespace(username="test_bot")


async def test_create_and_stats(db):
    await db.upsert_user(user(1, "Owner"), private=True)
    await db.upsert_user(user(2, "Ali"), private=False)
    quiz = await db.create_quiz(1, "T", None, 30, False, False, QS)
    assert quiz.question_count == 4
    assert (await db.get_quiz_by_code(quiz.code)).id == quiz.id
    qs = await db.get_questions(quiz.id)
    await db.save_attempt(quiz.id, 2, 2, 3, 4, 10.0, {qs[0].id: True, qs[1].id: False})
    await db.save_attempt(quiz.id, 2, 2, 4, 4, 20.0, {})
    await db.save_attempt(quiz.id, 1, 1, 1, 4, 5.0, {})
    board = await db.quiz_leaderboard(quiz.id)
    assert [(r["name"], r["score"]) for r in board] == [("Ali", 4), ("Owner", 1)]
    # o'z testi umumiy reytingga kirmaydi
    rating = await db.global_rating()
    assert [(r["name"], r["points"]) for r in rating] == [("Ali", 4)]
    assert (await db.user_global_place(2))["place"] == 1
    assert (await db.user_global_place(1)) is None
    assert (await db.question_stats(quiz.id))[0]["pct"] == 0
    assert (await db.messageable_user_ids()) == [1]
    counts = await db.admin_counts()
    assert counts["users"] == 2 and counts["attempts"] == 3
    await db.delete_quiz(quiz.id)
    assert await db.get_quiz(quiz.id) is None
    assert (await db.user_stats(2))["attempts"] == 0


def test_shuffle_keeps_correct_answer():
    quiz = SimpleNamespace(shuffle_options=True, shuffle_questions=True)
    for _ in range(20):
        for orig, new in zip(sorted(QS, key=lambda q: q.text),
                             sorted(prepare_questions(quiz, QS), key=lambda q: q.text)):
            assert new.options[new.correct] == orig.options[orig.correct]


async def run_private(db, answers, monkeypatch):
    monkeypatch.setattr(runner_mod, "PAUSE_AFTER_ANSWER", 0)
    orig_sleep = asyncio.sleep
    monkeypatch.setattr(runner_mod.asyncio, "sleep", lambda s: orig_sleep(0))
    await db.upsert_user(user(5, "Vali"), private=True)
    quiz = await db.create_quiz(1, "Private", None, 1, False, False, QS)
    qs = await db.get_questions(quiz.id)
    bot, mgr = FakeBot(), QuizManager(db)
    s = mgr.start(bot, 5, quiz, qs, 5, is_group=False)
    for i, opt in enumerate(answers):
        while len(bot.polls) <= i:
            await orig_sleep(0.01)
        if opt is not None:
            await mgr.handle_answer(SimpleNamespace(poll_id=bot.polls[i][0], user=user(5, "Vali"), option_ids=[opt]))
    await asyncio.wait_for(s.task, 10)
    return bot, mgr, quiz


async def test_private_run_full(db, monkeypatch):
    # to'g'ri javoblar: 0,1,2,0 -> 3 ta to'g'ri, 1 ta xato
    bot, mgr, quiz = await run_private(db, [0, 1, 2, 2], monkeypatch)
    assert len(bot.polls) == 4
    assert bot.polls[0][1]["question"] == "[1/4] Q0?" and bot.polls[0][1]["is_anonymous"] is False
    assert "To'g'ri: <b>3</b>" in bot.sent[-1] and "Test yakunlandi" in bot.sent[-1]
    assert not mgr.sessions and not mgr.polls
    board = await db.quiz_leaderboard(quiz.id)
    assert board[0]["score"] == 3 and board[0]["total"] == 4


async def test_private_stops_when_inactive(db, monkeypatch):
    bot, mgr, quiz = await run_private(db, [0, None, None], monkeypatch)
    assert len(bot.polls) == 3
    assert "javob bermadingiz" in bot.sent[-1]


async def test_manual_stop_and_duplicate_answers(db, monkeypatch):
    quiz = await db.create_quiz(1, "G", None, 30, False, False, QS)
    qs = await db.get_questions(quiz.id)
    bot, mgr = FakeBot(), QuizManager(db)
    orig_sleep = asyncio.sleep
    monkeypatch.setattr(runner_mod.asyncio, "sleep",
                        lambda s: orig_sleep(0 if s < 5 else 60))
    s = mgr.start(bot, -100, quiz, qs, 7, is_group=True)
    while not bot.polls:
        await orig_sleep(0.01)
    pid = bot.polls[0][0]
    for uid, opt in ((7, 0), (8, 1), (7, 1)):  # 7 ikkinchi marta javob bera olmaydi
        await mgr.handle_answer(SimpleNamespace(poll_id=pid, user=user(uid, f"U{uid}"), option_ids=[opt]))
    assert mgr.stop(-100)
    await asyncio.wait_for(s.task, 5)
    assert "to'xtatildi" in bot.sent[-1] and "U7" in bot.sent[-1]
    board = await db.quiz_leaderboard(quiz.id)
    assert [(r["user_id"], r["score"], r["total"]) for r in board] == [(7, 1, 1), (8, 0, 1)]
