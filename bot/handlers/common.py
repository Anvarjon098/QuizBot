from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, Message

from ..keyboards import BTN_CANCEL, BTN_HELP, main_menu
from ..parser import SAMPLE_TXT, sample_xlsx

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

WELCOME = (
    "👋 Assalomu alaykum, <b>{name}</b>!\n\n"
    "Men test (viktorina) botiman. Men bilan:\n"
    "• o'z testingizni yaratishingiz,\n"
    "• savollarni Word, Excel yoki matn fayldan yuklashingiz,\n"
    "• testni do'stlaringiz bilan yoki guruhda o'tkazishingiz,\n"
    "• natija va reytinglarni kuzatishingiz mumkin.\n\n"
    "Quyidagi menyudan tanlang 👇"
)

HELP = (
    "<b>❓ Yordam</b>\n\n"
    "<b>➕ Yangi test</b> — testni bosqichma-bosqich yaratish. Savollarni uch xil usulda "
    "qo'shish mumkin:\n"
    "  1) «➕ Savol yaratish» tugmasi orqali Telegram viktorinasini tuzish;\n"
    "  2) savolni matn ko'rinishida yuborish (format quyida);\n"
    "  3) fayl yuborish (.txt, .docx, .xlsx, .csv).\n\n"
    "<b>📥 Fayldan import</b> — barcha savollarni bitta fayldan yuklash.\n\n"
    "<b>Matn formati:</b>\n"
    "<pre>1. Savol matni?\n"
    "+To'g'ri javob\n"
    "-Noto'g'ri javob\n"
    "-Noto'g'ri javob\n"
    "Izoh: ixtiyoriy izoh</pre>\n"
    "yoki\n"
    "<pre>2. Savol matni?\n"
    "A) Variant\n"
    "*B) To'g'ri variant\n"
    "C) Variant</pre>\n"
    "(«*» o'rniga oxirida «Javob: B» qatorini yozsa ham bo'ladi.) "
    "Savollar orasiga bo'sh qator qoldiring.\n\n"
    "<b>Excel / CSV:</b> 1-ustun — savol, 2-ustun — to'g'ri javob, keyingi ustunlar — "
    "noto'g'ri javoblar. Sarlavhasi «Izoh» bo'lgan ustun izoh sifatida o'qiladi.\n\n"
    "Namuna fayllar: /namuna\n\n"
    "<b>Buyruqlar:</b>\n"
    "/start — bosh menyu\n"
    "/new — yangi test\n"
    "/stop — joriy testni to'xtatish\n"
    "/cancel — amalni bekor qilish"
)


@router.message(StateFilter("*"), Command("cancel"))
@router.message(StateFilter("*"), F.text == BTN_CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=main_menu())


@router.message(StateFilter("*"), CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME.format(name=message.from_user.first_name), reply_markup=main_menu())


@router.message(StateFilter(None), Command("help"))
@router.message(StateFilter(None), F.text == BTN_HELP)
async def help_(message: Message) -> None:
    await message.answer(HELP, reply_markup=main_menu())


@router.message(Command("namuna"))
async def samples(message: Message) -> None:
    await message.answer_document(
        BufferedInputFile(SAMPLE_TXT.encode("utf-8"), "namuna.txt"),
        caption="📄 Matn formatidagi namuna (.txt yoki Word uchun ham shu format)",
    )
    await message.answer_document(
        BufferedInputFile(sample_xlsx(), "namuna.xlsx"),
        caption="📊 Excel formatidagi namuna",
    )
