from urllib.parse import quote

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonPollType,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .models import TIMER_CHOICES, Quiz

# ---------- tugma matnlari ----------
BTN_NEW = "➕ Yangi test"
BTN_IMPORT = "📥 Fayldan import"
BTN_MY = "📚 Mening testlarim"
BTN_STATS = "📊 Statistikam"
BTN_RATING = "🏆 Reyting"
BTN_HELP = "❓ Yordam"

BTN_CANCEL = "❌ Bekor qilish"
BTN_SKIP = "⏭ O'tkazib yuborish"
BTN_DONE = "✅ Tugatish"
BTN_UNDO = "↩️ Oxirgisini o'chirish"
BTN_ADD_POLL = "➕ Savol yaratish"


# ---------- callback ma'lumotlari ----------
class TimerCB(CallbackData, prefix="tm"):
    seconds: int


class ShuffleCB(CallbackData, prefix="sh"):
    mode: str  # none | q | o | both


class PlayCB(CallbackData, prefix="pl"):
    quiz_id: int


class ResumeCB(CallbackData, prefix="rs"):
    quiz_id: int


class LobbyCB(CallbackData, prefix="lb"):
    action: str  # ready | go


class MyQuizCB(CallbackData, prefix="mq"):
    action: str  # list | view | stats | del | delok
    quiz_id: int = 0


class AdminCB(CallbackData, prefix="ad"):
    action: str
    page: int = 0
    quiz_id: int = 0


# ---------- havolalar ----------
def quiz_link(bot_username: str, quiz: Quiz) -> str:
    return f"https://t.me/{bot_username}?start=quiz_{quiz.code}"


def group_link(bot_username: str, quiz: Quiz) -> str:
    return f"https://t.me/{bot_username}?startgroup=quiz_{quiz.code}"


def share_link(bot_username: str, quiz: Quiz) -> str:
    return (
        f"https://t.me/share/url?url={quote(quiz_link(bot_username, quiz))}"
        f"&text={quote('«' + quiz.title + '» testini ishlab ko‘ring!')}"
    )


def share_button(quiz: Quiz) -> InlineKeyboardButton:
    """Chat tanlab, test kartochkasini inline rejimda yuborish (@bot quiz:KOD)."""
    return InlineKeyboardButton(text="📤 Ulashish", switch_inline_query=f"quiz:{quiz.code}")


def card_kb(bot_username: str, quiz: Quiz) -> InlineKeyboardMarkup:
    """Inline rejimda yuborilgan test kartochkasi tugmalari."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Testni boshlash", url=quiz_link(bot_username, quiz))],
        [InlineKeyboardButton(text="👥 Guruhda o'tkazish", url=group_link(bot_username, quiz))],
    ])


# ---------- reply klaviaturalar ----------
def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_NEW), KeyboardButton(text=BTN_IMPORT)],
            [KeyboardButton(text=BTN_MY)],
            [KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_RATING)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)


def skip_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SKIP)], [KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )


def questions_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD_POLL, request_poll=KeyboardButtonPollType(type="quiz"))],
            [KeyboardButton(text=BTN_DONE), KeyboardButton(text=BTN_UNDO)],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


# ---------- inline klaviaturalar ----------
def fmt_seconds(sec: int) -> str:
    return f"{sec // 60} daq" if sec >= 60 and sec % 60 == 0 else f"{sec} son"


def timer_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for sec in TIMER_CHOICES:
        b.button(text=fmt_seconds(sec), callback_data=TimerCB(seconds=sec))
    b.adjust(4)
    return b.as_markup()


def shuffle_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Aralashtirilmasin", callback_data=ShuffleCB(mode="none"))
    b.button(text="🔀 Savollar", callback_data=ShuffleCB(mode="q"))
    b.button(text="🔀 Javoblar", callback_data=ShuffleCB(mode="o"))
    b.button(text="🔀 Ikkalasi ham", callback_data=ShuffleCB(mode="both"))
    b.adjust(1, 2, 1)
    return b.as_markup()


def guest_kb(bot_username: str, quiz: Quiz) -> InlineKeyboardMarkup:
    """Oddiy foydalanuvchilar uchun: testni boshlash va guruhda o'tkazish."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Testni boshlash", callback_data=PlayCB(quiz_id=quiz.id).pack())],
        [InlineKeyboardButton(text="👥 Guruhda o'tkazish", url=group_link(bot_username, quiz))],
    ])


def play_kb(bot_username: str, quiz: Quiz) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Testni boshlash", callback_data=PlayCB(quiz_id=quiz.id).pack())],
            [InlineKeyboardButton(text="👥 Guruhda o'tkazish", url=group_link(bot_username, quiz))],
            [share_button(quiz)],
        ]
    )


def owner_kb(bot_username: str, quiz: Quiz) -> InlineKeyboardMarkup:
    kb = play_kb(bot_username, quiz)
    kb.inline_keyboard.extend(
        [
            [
                InlineKeyboardButton(
                    text="📊 Statistika", callback_data=MyQuizCB(action="stats", quiz_id=quiz.id).pack()
                ),
                InlineKeyboardButton(
                    text="🗑 O'chirish", callback_data=MyQuizCB(action="del", quiz_id=quiz.id).pack()
                ),
            ],
            [InlineKeyboardButton(text="⬅️ Testlarim", callback_data=MyQuizCB(action="list").pack())],
        ]
    )
    return kb


def lobby_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✋ Men tayyorman!", callback_data=LobbyCB(action="ready").pack())],
            [InlineKeyboardButton(text="▶️ Hozir boshlash", callback_data=LobbyCB(action="go").pack())],
        ]
    )
