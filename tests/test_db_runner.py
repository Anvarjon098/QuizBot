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


async def test_old_menu_cleanup_migration(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    # cheklovlardan oldingi sxema: menu_cleared ustuni yo'q
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, full_name TEXT NOT NULL DEFAULT '',"
                " can_message INTEGER NOT NULL DEFAULT 0, joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    con.executemany("INSERT INTO users (id, can_message) VALUES (?, ?)", [(1, 1), (2, 1), (3, 0)])
    con.commit(); con.close()

    d = Database(path)
    await d.connect()
    try:
        assert await d.users_with_old_menu(frozenset({1})) == [2]   # admin va guruhdagilar kirmaydi
        await d.upsert_user(user(4, "Yangi"), private=True)          # yangi foydalanuvchida eski menyu yo'q
        assert await d.users_with_old_menu(frozenset({1})) == [2]
        await d.mark_menu_cleared(2)
        assert await d.users_with_old_menu(frozenset({1})) == []
    finally:
        await d.close()


async def test_backup_and_restore(tmp_path):
    from bot.db import is_valid_backup
    from bot.models import Question
    src = Database(str(tmp_path / "a.db"))
    await src.connect()
    from aiogram.types import User
    await src.upsert_user(User(id=7, is_bot=False, first_name="A"), private=True)
    await src.create_quiz(7, "Zaxira", "", 30, False, False, [Question("2+2?", ["3", "4"], 1)])
    await src.backup_to(str(tmp_path / "backup.db"))
    await src.close()
    assert is_valid_backup(str(tmp_path / "backup.db"))

    (tmp_path / "junk.db").write_bytes(b"not a database")
    assert not is_valid_backup(str(tmp_path / "junk.db"))

    dst = Database(str(tmp_path / "b.db"))
    await dst.connect()
    assert await dst.count_quizzes() == 0
    await dst.restore_from(str(tmp_path / "backup.db"))
    assert await dst.count_quizzes() == 1
    assert (await dst.all_quizzes(0, 10))[0].title == "Zaxira"
    await dst.close()


async def test_on_idle_called_after_last_quiz(tmp_path):
    """Oxirgi test tugagach navbatdagi yangilanish chaqiriladi; to'xtatilgan test natijasi saqlanadi."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from bot.models import Question
    from bot.runner import QuizManager
    db = Database(str(tmp_path / "i.db"))
    await db.connect()
    try:
        quiz = await db.create_quiz(1, "T", "", 30, False, False, [Question("Q?", ["a", "b"], 0)])
        qs = await db.get_questions(quiz.id)
        bot = MagicMock()
        bot.send_message = AsyncMock()
        bot.send_poll = AsyncMock(return_value=MagicMock(message_id=1, poll=MagicMock(id="p")))
        bot.stop_poll = AsyncMock()
        bot.me = AsyncMock(return_value=MagicMock(username="b"))
        mgr = QuizManager(db)
        called = []

        async def idle():
            called.append(True)

        mgr.on_idle = idle
        mgr.start(bot, 10, quiz, qs, 1, is_group=False)
        await asyncio.sleep(0.05)
        await mgr.shutdown(reason="update")
        assert called == [True]
        last = bot.send_message.call_args_list[-1]
        assert "yangilanishi sababli" in last.args[1]
    finally:
        await db.close()


async def test_send_poll_retries_and_skips(tmp_path, monkeypatch):
    """Tarmoq uzilsa savol qayta yuboriladi; Telegram rad etgan savol o'tkazib yuboriladi."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
    from aiogram.methods import SendPoll
    from bot import runner
    from bot.models import Question
    from bot.runner import QuizManager
    monkeypatch.setattr(runner, "PAUSE_AFTER_ANSWER", 0)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(runner.asyncio, "sleep", lambda *_a, **_k: real_sleep(0))

    db = Database(str(tmp_path / "r.db"))
    await db.connect()
    try:
        quiz = await db.create_quiz(1, "T", "", 10, False, False,
                                    [Question(f"Q{i}?", ["a", "b"], 0) for i in range(3)])
        qs = await db.get_questions(quiz.id)
        m = SendPoll(chat_id=1, question="q", options=["a", "b"])
        results = [
            TelegramNetworkError(m, "timeout"),          # 1-savol: uzilish, keyin muvaffaqiyat
            MagicMock(message_id=1, poll=MagicMock(id="p1")),
            TelegramBadRequest(m, "Bad Request: poll question length must not exceed 300"),  # 2-savol rad
            MagicMock(message_id=3, poll=MagicMock(id="p3")),
        ]
        bot = MagicMock()
        bot.send_poll = AsyncMock(side_effect=results)
        bot.send_message = AsyncMock()
        bot.me = AsyncMock(return_value=MagicMock(username="b"))
        mgr = QuizManager(db)
        monkeypatch.setattr(runner, "INACTIVE_LIMIT", 99)
        quiz.open_period = 0  # har savol ~1 soniya kutadi
        s = mgr.start(bot, 10, quiz, qs, 1, is_group=False)
        await asyncio.wait_for(s.task, 5)
        assert s.stop_reason is None
        assert s.shown == 2 and s.skipped == 1
        # "<" belgili savollar HTML deb o'qilmasligi kerak
        kw = bot.send_poll.call_args.kwargs
        assert kw["question_parse_mode"] is None and kw["explanation_parse_mode"] is None
        assert "o'tkazib yuborildi" in bot.send_message.call_args_list[-1].args[1]
    finally:
        await db.close()
