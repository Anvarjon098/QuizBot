"""Handlerlarni Telegram API'siz, soxta sessiya orqali sinash."""

import datetime as dt
import itertools

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import GetMe, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.config import Config
from bot.db import Database
from bot.handlers import admin, common, create, fallback, play, stats
from bot.middlewares import UserMiddleware
from bot.runner import QuizManager

BOT_USER = User(id=42, is_bot=True, first_name="Quiz", username="test_quiz_bot")
ME = User(id=1, is_bot=False, first_name="Anvar")
GUEST = User(id=2, is_bot=False, first_name="Mehmon")
CHAT = Chat(id=1, type="private")


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self.ids = itertools.count(1000)

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, GetMe):
            return BOT_USER
        ret = method.__returning__
        if ret is Message:
            chat_id = getattr(method, "chat_id", None) or CHAT.id
            return Message(message_id=next(self.ids), date=dt.datetime.now(),
                           chat=Chat(id=chat_id, type="private"), text=getattr(method, "text", None)).as_(bot)
        if ret is bool or "bool" in str(ret):
            return True
        raise NotImplementedError(type(method).__name__)

    async def stream_content(self, *a, **kw):
        yield b""

    async def close(self):
        pass

    def texts(self):
        return [getattr(c, "text", None) for c in self.calls if getattr(c, "text", None)]


@pytest.fixture
async def env(tmp_path):
    db = Database(str(tmp_path / "h.db"))
    await db.connect()
    session = FakeSession()
    bot = Bot("42:TEST", session=session)
    mgr = QuizManager(db)
    dp = Dispatcher(storage=MemoryStorage(), db=db, manager=mgr,
                    config=Config("42:TEST", frozenset({1}), ""))
    dp.update.outer_middleware(UserMiddleware(db))
    routers = (play.router, common.router, admin.router, create.router, stats.router, fallback.router)
    for r in routers:  # modul darajasidagi routerlarni oldingi testdagi dispatcher'dan ajratish
        r._parent_router = None
    dp.include_routers(*routers)
    upd = itertools.count(1)
    msg_ids = itertools.count(1)

    async def send(text, user=ME, chat=None):
        session.calls.clear()
        chat = chat or Chat(id=user.id, type="private")
        m = Message(message_id=next(msg_ids), date=dt.datetime.now(), chat=chat, from_user=user, text=text)
        await dp.feed_update(bot, Update(update_id=next(upd), message=m))
        return session

    async def press(data, user=ME):
        session.calls.clear()
        chat = Chat(id=user.id, type="private")
        m = Message(message_id=999, date=dt.datetime.now(), chat=chat, from_user=BOT_USER, text="x")
        cq = CallbackQuery(id="c", from_user=user, chat_instance="i", message=m, data=data)
        await dp.feed_update(bot, Update(update_id=next(upd), callback_query=cq))
        return session

    send.manager = mgr
    try:
        yield db, send, press
    finally:
        await db.close()


async def test_create_flow_and_open(env):
    db, send, press = env
    s = await send("/start")
    assert "Assalomu alaykum" in s.texts()[0]

    await send("➕ Yangi test")
    await send("Geografiya")
    await send("⏭ O'tkazib yuborish")
    s = await send("Poytaxt?\n+Toshkent\n-Samarqand\n\n2-savol?\nA) 1\n*B) 2\n\nXato savol\n+a")
    assert "2 ta savol qo'shildi" in s.texts()[0] and "Qabul qilinmadi (1)" in s.texts()[0]
    s = await send("↩️ Oxirgisini o'chirish")
    assert "Jami: <b>1</b>" in s.texts()[0]
    s = await send("✅ Tugatish")
    assert any("qancha vaqt" in t for t in s.texts())
    s = await press("tm:15")
    assert any("aralashtirilsinmi" in t for t in s.texts())
    s = await press("sh:both")
    assert any("Test tayyor" in t for t in s.texts())

    quizzes = await db.user_quizzes(1)
    assert len(quizzes) == 1
    q = quizzes[0]
    assert (q.title, q.open_period, q.shuffle_questions, q.shuffle_options, q.question_count) == \
        ("Geografiya", 15, True, True, 1)

    s = await send(f"/start quiz_{q.code}")
    assert any("Geografiya" in t for t in s.texts())
    s = await send("/start quiz_yoq")
    assert any("topilmadi" in t for t in s.texts())

    s = await send("📚 Mening testlarim")
    assert "Sizning testlaringiz" in s.texts()[0]
    s = await press(f"mq:stats:{q.id}")
    assert any("hech kim ishlamagan" in t for t in s.texts())
    s = await send("📊 Statistikam")
    assert "Yaratgan testlaringiz: <b>1</b>" in s.texts()[0]
    s = await send("🏆 Reyting")
    assert "Reyting hali bo'sh" in s.texts()[0]

    s = await send("/admin")
    assert "Admin panel" in s.texts()[0]
    s = await press("ad:stats:0:0")
    assert any("Foydalanuvchilar: <b>1</b>" in t for t in s.texts())
    s = await press("ad:quizzes:0:0")
    assert any("Barcha testlar" in t for t in s.texts())

    await press(f"mq:delok:{q.id}")
    assert await db.user_quizzes(1) == []


async def test_cancel_and_help(env):
    db, send, press = env
    await send("➕ Yangi test")
    s = await send("❌ Bekor qilish")
    assert s.texts() == ["Bekor qilindi."]
    s = await send("❓ Yordam")
    assert "Matn formati" in s.texts()[0]
    s = await send("/stop")
    assert "hech qanday test" in s.texts()[0]


def _buttons(call):
    kb = getattr(call, "reply_markup", None)
    rows = getattr(kb, "inline_keyboard", None) or []
    return [b.text for row in rows for b in row]


async def test_guest_can_only_take_quizzes(env):
    db, send, press = env
    from bot.models import Question
    quiz = await db.create_quiz(1, "Tarix", None, 30, False, False, [Question("Savol?", ["a", "b"], 0)])

    s = await send("/start", GUEST)
    assert "sizga yuborilgan testlarni" in s.texts()[0]
    assert type(s.calls[0].reply_markup).__name__ == "ReplyKeyboardRemove"

    # yopiq funksiyalar
    for text in ("➕ Yangi test", "📥 Fayldan import", "📚 Mening testlarim", "📊 Statistikam",
                 "🏆 Reyting", "❓ Yordam", "/new", "/help", "/namuna", "/admin"):
        s = await send(text, GUEST)
        assert len(s.calls) == 1 and "faqat sizga yuborilgan" in s.texts()[0], text
    s = await press(f"mq:stats:{quiz.id}", GUEST)
    assert s.calls[0].show_alert and "mavjud emas" in s.calls[0].text
    s = await press("ad:stats:0:0", GUEST)
    assert "mavjud emas" in s.calls[0].text
    assert await db.user_quizzes(2) == []

    # havola orqali: testni boshlash va guruhda o'tkazish (boshqaruv tugmalarisiz)
    s = await send(f"/start quiz_{quiz.code}", GUEST)
    card = s.calls[-1]
    assert "Tarix" in card.text and _buttons(card) == ["▶️ Testni boshlash", "👥 Guruhda o'tkazish"]
    group_url = card.reply_markup.inline_keyboard[1][0].url
    assert group_url == f"https://t.me/test_quiz_bot?startgroup=quiz_{quiz.code}"

    # admin esa to'liq tugmalarni ko'radi
    s = await send(f"/start quiz_{quiz.code}")
    assert "👥 Guruhda o'tkazish" in _buttons(s.calls[-1]) and "📊 Statistika" in _buttons(s.calls[-1])


async def test_guest_can_start_quiz_in_group(env):
    db, send, press = env
    from bot.models import Question
    quiz = await db.create_quiz(1, "Guruh testi", None, 30, False, False, [Question("Savol?", ["a", "b"], 0)])
    s = await send(f"/start@test_quiz_bot quiz_{quiz.code}", GUEST, chat=Chat(id=-100, type="supergroup"))
    lobby = next(c for c in s.calls if getattr(c, "text", None))
    assert "Guruh testi" in lobby.text and _buttons(lobby)[0] == "✋ Men tayyorman!"


async def test_update_command(env, monkeypatch):
    from bot import updater
    _, send, _ = env

    async def latest():
        return updater.Commit("abc1234567", "Yangi funksiya")

    applied = []

    async def apply(commit):
        applied.append(commit.sha)

    monkeypatch.setattr(updater, "latest_commit", latest)
    monkeypatch.setattr(updater, "apply_update", apply)
    monkeypatch.setattr(updater, "save_notice", lambda *a: None)

    monkeypatch.setattr(updater, "current_version", lambda: "abc1234567")
    s = await send("/update")
    assert any("eng so'nggi" in t for t in s.texts())
    assert applied == []

    monkeypatch.setattr(updater, "current_version", lambda: "old")
    s = await send("/update")
    assert applied == ["abc1234567"]
    assert any("qayta ishga tushmoqda" in t for t in s.texts())

    s = await send("/update", user=GUEST)
    assert applied == ["abc1234567"]


async def test_update_waits_for_running_quizzes(env, monkeypatch):
    import asyncio
    from bot import updater
    from bot.runner import Session
    _, send, _ = env
    mgr = send.manager

    async def latest():
        return updater.Commit("new0000000", "Yangi")

    applied = []

    async def apply(commit):
        applied.append(commit.sha)

    monkeypatch.setattr(updater, "latest_commit", latest)
    monkeypatch.setattr(updater, "apply_update", apply)
    monkeypatch.setattr(updater, "save_notice", lambda *a: None)
    monkeypatch.setattr(updater, "current_version", lambda: "old")

    # bitta test ketmoqda -> yangilanish navbatga qo'yiladi
    mgr.sessions[555] = Session(555, None, [], 7, False)
    s = await send("/update")
    assert any("tugashi bilan" in t for t in s.texts())
    assert applied == [] and mgr.updating and mgr.on_idle is not None

    # navbat paytida yangi test boshlanmaydi
    s = await send("/update")
    assert any("allaqachon navbatda" in t for t in s.texts())

    # bekor qilish
    s = await send("/update bekor")
    assert mgr.on_idle is None and not mgr.updating

    # yana navbatga qo'yib, test tugaganini taqlid qilamiz
    await send("/update")
    mgr.sessions.clear()
    callback, mgr.on_idle = mgr.on_idle, None
    await callback()
    assert applied == ["new0000000"]


async def test_update_force_stops_quizzes(env, monkeypatch):
    from bot import updater
    _, send, _ = env
    mgr = send.manager
    stopped = []

    async def fake_shutdown(reason="manual"):
        stopped.append(reason)
        mgr.sessions.clear()

    async def latest():
        return updater.Commit("new0000000", "Yangi")

    applied = []

    async def apply(commit):
        applied.append(commit.sha)

    monkeypatch.setattr(mgr, "shutdown", fake_shutdown)
    monkeypatch.setattr(updater, "latest_commit", latest)
    monkeypatch.setattr(updater, "apply_update", apply)
    monkeypatch.setattr(updater, "save_notice", lambda *a: None)
    monkeypatch.setattr(updater, "current_version", lambda: "old")

    mgr.sessions[555] = object()
    s = await send("/update majburiy")
    assert stopped == ["update"]
    assert applied == ["new0000000"]
    assert any("qayta ishga tushmoqda" in t for t in s.texts())


async def test_admin_panel_update_and_backup_buttons(env, monkeypatch):
    from aiogram.methods import SendDocument
    from bot import updater
    from bot.keyboards import AdminCB
    _, send, press = env

    s = await send("/admin")
    kb = [b.callback_data for row in s.calls[-1].reply_markup.inline_keyboard for b in row]
    assert AdminCB(action="upd").pack() in kb and AdminCB(action="backup").pack() in kb

    s = await press(AdminCB(action="backup").pack())
    assert any(isinstance(c, SendDocument) for c in s.calls)

    async def latest():
        return updater.Commit("same000000", "x")

    monkeypatch.setattr(updater, "latest_commit", latest)
    monkeypatch.setattr(updater, "current_version", lambda: "same000000")
    s = await press(AdminCB(action="upd").pack())
    assert any("eng so'nggi" in t for t in s.texts())

    # mehmon uchun bu tugmalar ishlamaydi
    s = await press(AdminCB(action="backup").pack(), user=GUEST)
    assert not any(isinstance(c, SendDocument) for c in s.calls)
