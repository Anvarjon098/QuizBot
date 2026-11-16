# QuizBot — Telegram test (viktorina) boti

[aiogram 3](https://docs.aiogram.dev) asosida yozilgan bot. Unda test yaratib, uni shaxsiy chatda yoki guruhda o'tkazish mumkin. Savollar Telegramning **quiz** rejimidagi so'rovnomalari sifatida yuboriladi.

## Imkoniyatlar

**Asosiy**
- Testni bosqichma-bosqich yaratish: nom, tavsif, savollar, savolga beriladigan vaqt (10 soniyadan 5 daqiqagacha), savollar va javoblarni aralashtirish.
- Savol qo'shishning uch usuli: Telegramning o'z viktorina oynasi, matn ko'rinishi yoki fayl.
- Shaxsiy chatda o'tkazish. Foydalanuvchi ketma-ket 2 ta savolga javob bermasa, test to'xtatiladi.
- Guruhda o'tkazish. «Men tayyorman» tugmasini kamida 2 kishi bossa, test boshlanadi. Oxirida g'oliblar ro'yxati chiqadi.
- Test havolasi, «Guruhda o'tkazish» va «Ulashish» tugmalari.

**Qo'shimcha**
- 📥 **Fayldan import**: `.txt`, `.docx` (matn va jadvallar), `.xlsx`, `.csv`. Xato yozilgan savollar qator raqami bilan ko'rsatiladi. Namuna fayllar `/namuna` buyrug'i bilan olinadi.
- 📊 **Statistika va reyting**:
  - shaxsiy statistika: urinishlar, to'g'ri javoblar foizi, eng yaxshi natija, so'nggi natijalar;
  - har bir test bo'yicha: o'rtacha natija va vaqt, eng yaxshi 10 ishtirokchi, eng qiyin savollar;
  - umumiy reyting: har bir testdagi eng yaxshi natija hisoblanadi, o'z testlaringizdagi natija kirmaydi.
- 🛠 **Admin panel** (`/admin`):
  - umumiy statistika;
  - barcha foydalanuvchilarga xabar yuborish (istalgan turdagi xabar, botni bloklaganlar hisobga olinadi);
  - barcha testlarni sahifalab ko'rish va o'chirish;
  - foydalanuvchilar ro'yxatini Excel faylga yuklab olish.

## O'rnatish

Python 3.11 yoki undan yangi versiya kerak.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # BOT_TOKEN va ADMIN_IDS ni to'ldiring
python -m bot
```

`.env` sozlamalari:

| O'zgaruvchi | Tavsif |
|---|---|
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) bergan token |
| `ADMIN_IDS` | Adminlarning Telegram ID raqamlari, vergul bilan ajratiladi |
| `DB_PATH` | SQLite baza fayli (standart qiymati: `quizbot.db`) |

> Bot guruhda ham ishlashi uchun @BotFather'da **Allow Groups** yoqilgan bo'lishi kerak. Privacy mode'ni o'chirish shart emas: bot buyruqlar, tugmalar va javoblar bilan ishlaydi.

## Fayl formatlari

**Matn (`.txt`, `.docx`, yoki to'g'ridan-to'g'ri xabar sifatida):**

```
1. Savol matni?
+To'g'ri javob
-Noto'g'ri javob
-Noto'g'ri javob
Izoh: ixtiyoriy izoh

2. Savol matni?
A) Variant
*B) To'g'ri variant
C) Variant
```

To'g'ri javobni «*» bilan belgilash o'rniga oxiriga `Javob: B` qatorini yozish ham mumkin. Kirill harflari (А, Б, В…) ham qabul qilinadi.

**Jadval (`.xlsx`, `.csv`, Word jadvali):**

| Savol | To'g'ri javob | Noto'g'ri 1 | Noto'g'ri 2 | Izoh |
|---|---|---|---|---|

Birinchi qator sarlavha bo'lsa, u o'tkazib yuboriladi. Sarlavhasi «Izoh» bo'lgan ustun izoh sifatida o'qiladi.

**Telegram cheklovlari:**
- savol uzunligi 280 belgigacha;
- 2 tadan 10 tagacha variant, har biri 100 belgigacha;
- izoh 200 belgigacha;
- bitta testda 200 tagacha savol.

## Loyiha tuzilmasi

```
bot/
  __main__.py     — ishga tushirish
  config.py       — .env sozlamalari
  db.py           — SQLite (aiosqlite): foydalanuvchilar, testlar, urinishlar, javoblar
  parser.py       — fayl va matndan savollarni o'qish
  runner.py       — testni chatda o'tkazish (quiz-poll'lar, vaqt, natijalar)
  keyboards.py    — tugmalar va callback ma'lumotlari
  handlers/
    play.py       — test havolasi, guruh lobbisi, /stop, javoblar
    common.py     — /start, /help, /cancel, /namuna
    create.py     — test yaratish va import
    stats.py      — testlarim, statistika, reyting
    admin.py      — admin panel
tests/            — pytest testlari
```

## Testlar

```bash
pip install pytest==8.3.5 pytest-asyncio==0.25.3
python -m pytest -q
```
