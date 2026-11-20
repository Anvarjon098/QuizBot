from html import escape

from .keyboards import fmt_seconds
from .models import Quiz

MEDALS = ("🥇", "🥈", "🥉")


def fmt_duration(sec: float) -> str:
    sec = max(0.0, sec)
    if sec < 60:
        return f"{sec:.1f} son"
    m, s = divmod(int(round(sec)), 60)
    if m < 60:
        return f"{m} daq {s} son"
    h, m = divmod(m, 60)
    return f"{h} soat {m} daq"


def fmt_duration_long(sec: float) -> str:
    """50.5 soniya · 3 daqiqa 5 soniya · 1 soat 2 daqiqa"""
    sec = max(0.0, sec)
    if sec < 60:
        return f"{sec:.1f} soniya"
    m, s = divmod(int(round(sec)), 60)
    if m < 60:
        return f"{m} daqiqa {s} soniya" if s else f"{m} daqiqa"
    h, m = divmod(m, 60)
    return f"{h} soat {m} daqiqa" if m else f"{h} soat"


def rank_text(place: int, total: int) -> str:
    """«7 tadan 🥇 1-o‘rin. Siz ushbu testda ishtirok etgan 100% odamlardan yuqoriroq ball to‘pladingiz.»
    place — 0 dan boshlanadigan o'rin."""
    medal = f"{MEDALS[place]} " if place < len(MEDALS) else ""
    text = f"{total} tadan {medal}<b>{place + 1}-o‘rin</b>."
    if total > 1:
        pct = round(100 * (total - 1 - place) / (total - 1))
        text += f" Siz ushbu testda ishtirok etgan {pct}% odamlardan yuqoriroq ball to‘pladingiz."
    else:
        text += " Siz bu testni birinchi bo‘lib ishladingiz!"
    return text


def place_mark(i: int) -> str:
    return MEDALS[i] if i < len(MEDALS) else f"{i + 1}."


def shuffle_text(quiz: Quiz) -> str:
    if quiz.shuffle_questions and quiz.shuffle_options:
        return "savollar va javoblar"
    if quiz.shuffle_questions:
        return "savollar"
    if quiz.shuffle_options:
        return "javoblar"
    return "yo'q"


def quiz_card(quiz: Quiz) -> str:
    lines = [f"🎲 <b>{escape(quiz.title)}</b>"]
    if quiz.description:
        lines.append(escape(quiz.description))
    lines += [
        "",
        f"🖊 Savollar: <b>{quiz.question_count}</b> ta",
        f"⏱ Har bir savolga: <b>{fmt_seconds(quiz.open_period)}</b>",
        f"🔀 Aralashtirish: {shuffle_text(quiz)}",
    ]
    return "\n".join(lines)
