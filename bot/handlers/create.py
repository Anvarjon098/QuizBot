"""Test yaratish va fayldan import qilish."""

from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..db import Database
from ..keyboards import (
    BTN_DONE, BTN_IMPORT, BTN_NEW, BTN_SKIP, BTN_UNDO,
    ShuffleCB, TimerCB, cancel_kb, fmt_seconds, main_menu, owner_kb,
    questions_kb, shuffle_kb, skip_kb, timer_kb,
)
from ..models import (
    DESCRIPTION_MAX, QUESTIONS_PER_QUIZ_MAX, TIMER_CHOICES, TITLE_MAX,
    Question, validate_question,
)
from ..parser import MAX_FILE_SIZE, ParseResult, parse_file, parse_text
from ..states import CreateQuiz, ImportQuiz
from ..views import quiz_card

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

MAX_ERRORS_SHOWN = 10

QUESTIONS_HINT = (
    "Endi savollarni qo'shing. Uch xil usul bor:\n\n"
    "1️⃣ «➕ Savol yaratish» tugmasini bosib, Telegram viktorinasini tuzing;\n"
    "2️⃣ savolni matn ko'rinishida yuboring:\n"
    "<pre>Savol matni?\n#To'g'ri javob\nNoto'g'ri javob\nNoto'g'ri javob\n+</pre>\n"
    "3️⃣ savollar yozilgan faylni yuboring (.txt, .docx, .xlsx, .csv) — /namuna\n\n"
    "Barcha savollar qo'shilgach «✅ Tugatish» tugmasini bosing."
)


def _errors_text(errors: list[str]) -> str:
    if not errors:
        return ""
    shown = "\n".join(f"• {escape(e)}" for e in errors[:MAX_ERRORS_SHOWN])
    more = f"\n… va yana {len(errors) - MAX_ERRORS_SHOWN} ta" if len(errors) > MAX_ERRORS_SHOWN else ""
    return f"\n\n⚠️ <b>Qabul qilinmadi ({len(errors)}):</b>\n{shown}{more}"


async def _download_and_parse(bot: Bot, message: Message) -> ParseResult | None:
    doc = message.document
    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        await message.answer("❗️ Fayl juda katta (maksimal hajm — 5 MB).")
        return None
    data = await bot.download(doc)
    try:
        return parse_file(doc.file_name or "", data.read())
    except ValueError as e:
        await message.answer(f"❗️ {escape(str(e))}")
    except Exception:
        await message.answer("❗️ Faylni o'qib bo'lmadi. Fayl buzilmaganini tekshiring.")
    return None


async def _add_questions(message: Message, state: FSMContext, new: list[Question], errors: list[str]) -> None:
    data = await state.get_data()
    questions: list[dict] = data.get("questions", [])
    free = QUESTIONS_PER_QUIZ_MAX - len(questions)
    if len(new) > free:
        errors = errors + [f"bitta testda ko'pi bilan {QUESTIONS_PER_QUIZ_MAX} ta savol bo'lishi mumkin; "
                           f"{len(new) - free} ta savol qo'shilmadi"]
        new = new[:free]
    questions.extend(q.to_dict() for q in new)
    await state.update_data(questions=questions)

    if new:
        head = (f"✅ Savol qo'shildi." if len(new) == 1 else f"✅ {len(new)} ta savol qo'shildi.")
        text = f"{head} Jami: <b>{len(questions)}</b> ta."
    else:
        text = "Hech qanday savol qo'shilmadi."
    await message.answer(text + _errors_text(errors), reply_markup=questions_kb())


# ---------- boshlash ----------

@router.message(StateFilter(None), Command("new"))
@router.message(StateFilter(None), F.text == BTN_NEW)
async def new_quiz(message: Message, state: FSMContext) -> None:
    await state.set_state(CreateQuiz.title)
    await state.update_data(questions=[])
    await message.answer(
        "📝 Yangi test yaratamiz.\n\nAvval testning <b>nomini</b> yuboring:",
        reply_markup=cancel_kb(),
    )


@router.message(StateFilter(None), F.text == BTN_IMPORT)
async def import_quiz(message: Message, state: FSMContext) -> None:
    await state.set_state(ImportQuiz.file)
    await message.answer(
        "📥 Savollar yozilgan faylni yuboring: <b>.txt, .docx, .xlsx</b> yoki <b>.csv</b>.\n\n"
        "Format haqida: /help · Namuna fayllar: /namuna",
        reply_markup=cancel_kb(),
    )


@router.message(ImportQuiz.file, F.document)
async def import_file(message: Message, state: FSMContext, bot: Bot) -> None:
    result = await _download_and_parse(bot, message)
    if result is None:
        return
    if not result.questions:
        await message.answer(
            "Fayldan birorta ham savol topilmadi." + _errors_text(result.errors)
            + "\n\nFormatni tekshirib, faylni qayta yuboring (/help).",
        )
        return
    questions = result.questions[:QUESTIONS_PER_QUIZ_MAX]
    await state.update_data(questions=[q.to_dict() for q in questions])
    await state.set_state(CreateQuiz.title)
    await message.answer(
        f"✅ Fayldan <b>{len(questions)}</b> ta savol o'qildi." + _errors_text(result.errors)
        + "\n\nEndi testning <b>nomini</b> yuboring:",
        reply_markup=cancel_kb(),
    )


@router.message(ImportQuiz.file)
async def import_wrong(message: Message) -> None:
    await message.answer("Iltimos, fayl yuboring (.txt, .docx, .xlsx, .csv).")


# ---------- nom va tavsif ----------

@router.message(CreateQuiz.title, F.text)
async def set_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if len(title) > TITLE_MAX:
        await message.answer(f"Nom juda uzun ({len(title)}/{TITLE_MAX}). Qisqaroq nom yuboring:")
        return
    await state.update_data(title=title)
    await state.set_state(CreateQuiz.description)
    await message.answer(
        "Test uchun qisqacha <b>tavsif</b> yuboring yoki bu qadamni o'tkazib yuboring:",
        reply_markup=skip_kb(),
    )


@router.message(CreateQuiz.description, F.text)
async def set_description(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if text in (BTN_SKIP, "/skip"):
        text = None
    elif len(text) > DESCRIPTION_MAX:
        await message.answer(f"Tavsif juda uzun ({len(text)}/{DESCRIPTION_MAX}). Qisqartirib yuboring:")
        return
    await state.update_data(description=text)
    await state.set_state(CreateQuiz.questions)
    count = len((await state.get_data()).get("questions", []))
    if count:
        await message.answer(
            f"Testda hozircha <b>{count}</b> ta savol bor. Yana savol qo'shishingiz yoki "
            f"«✅ Tugatish» tugmasini bosishingiz mumkin.",
            reply_markup=questions_kb(),
        )
    else:
        await message.answer(QUESTIONS_HINT, reply_markup=questions_kb())


# ---------- savollar ----------

@router.message(CreateQuiz.questions, F.poll)
async def add_poll(message: Message, state: FSMContext) -> None:
    poll = message.poll
    if poll.type != "quiz" or poll.correct_option_id is None:
        await message.answer(
            "❗️ Bu viktorina emas yoki to'g'ri javobi noma'lum. "
            "«➕ Savol yaratish» tugmasi orqali viktorina tuzing."
        )
        return
    q = Question(
        text=poll.question,
        options=[o.text for o in poll.options],
        correct=poll.correct_option_id,
        explanation=poll.explanation,
    )
    if err := validate_question(q):
        await message.answer(f"❗️ Savol qabul qilinmadi: {escape(err)}")
        return
    await _add_questions(message, state, [q], [])


@router.message(CreateQuiz.questions, F.document)
async def add_file(message: Message, state: FSMContext, bot: Bot) -> None:
    result = await _download_and_parse(bot, message)
    if result is not None:
        await _add_questions(message, state, result.questions, result.errors)


@router.message(CreateQuiz.questions, F.text == BTN_UNDO)
async def undo(message: Message, state: FSMContext) -> None:
    questions = (await state.get_data()).get("questions", [])
    if not questions:
        await message.answer("O'chirish uchun savol yo'q.")
        return
    removed = questions.pop()
    await state.update_data(questions=questions)
    await message.answer(
        f"↩️ O'chirildi: «{escape(removed['text'][:60])}»\nJami: <b>{len(questions)}</b> ta.",
        reply_markup=questions_kb(),
    )


@router.message(CreateQuiz.questions, F.text == BTN_DONE)
async def done(message: Message, state: FSMContext) -> None:
    questions = (await state.get_data()).get("questions", [])
    if not questions:
        await message.answer("Avval kamida bitta savol qo'shing.")
        return
    await state.set_state(CreateQuiz.timer)
    await message.answer(f"👍 Jami <b>{len(questions)}</b> ta savol.", reply_markup=cancel_kb())
    await message.answer("⏱ Har bir savolga qancha vaqt berilsin?", reply_markup=timer_kb())


@router.message(CreateQuiz.questions, F.text)
async def add_text(message: Message, state: FSMContext) -> None:
    result = parse_text(message.text)
    if not result.questions and not result.errors:
        await message.answer("Savol topilmadi. Formatni /help orqali ko'ring.")
        return
    await _add_questions(message, state, result.questions, result.errors)


@router.message(CreateQuiz.questions)
async def questions_other(message: Message) -> None:
    await message.answer("Viktorina, matn yoki fayl yuboring. Tugatish uchun «✅ Tugatish».")


# ---------- vaqt va aralashtirish ----------

@router.callback_query(CreateQuiz.timer, TimerCB.filter())
async def set_timer(call: CallbackQuery, callback_data: TimerCB, state: FSMContext) -> None:
    if callback_data.seconds not in TIMER_CHOICES:
        await call.answer()
        return
    await state.update_data(open_period=callback_data.seconds)
    await state.set_state(CreateQuiz.shuffle)
    await call.message.edit_text(f"⏱ Har bir savolga: <b>{fmt_seconds(callback_data.seconds)}</b>")
    await call.message.answer("🔀 Savollar yoki javoblar aralashtirilsinmi?", reply_markup=shuffle_kb())
    await call.answer()


@router.callback_query(CreateQuiz.shuffle, ShuffleCB.filter())
async def set_shuffle(call: CallbackQuery, callback_data: ShuffleCB, state: FSMContext,
                      db: Database, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    mode = callback_data.mode
    quiz = await db.create_quiz(
        owner_id=call.from_user.id,
        title=data["title"],
        description=data.get("description"),
        open_period=data["open_period"],
        shuffle_questions=mode in ("q", "both"),
        shuffle_options=mode in ("o", "both"),
        questions=[Question.from_dict(d) for d in data["questions"]],
    )
    await call.message.delete()
    await call.message.answer("🎉 Test tayyor!", reply_markup=main_menu())
    username = (await bot.me()).username
    await call.message.answer(quiz_card(quiz), reply_markup=owner_kb(username, quiz))
    await call.answer()


@router.callback_query(StateFilter(CreateQuiz.timer, CreateQuiz.shuffle))
async def stale_choice(call: CallbackQuery) -> None:
    await call.answer("Yuqoridagi tugmalardan birini tanlang.")
