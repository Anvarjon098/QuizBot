"""Savollarni matn, .txt, .docx, .xlsx va .csv fayllardan o'qish."""

import csv
import io
import re
from dataclasses import dataclass, field

from .models import Question, validate_question

LATIN = "abcdefghij"
CYRILLIC = "абвгдежзийк"

_APOS = "['‘’`ʻʼ]?"
ANSWER_RE = re.compile(
    rf"^(?:javob|to{_APOS}g{_APOS}ri\s+javob|answer|ответ)\s*[:\-–]\s*([a-jа-к])\b", re.I
)
EXPL_RE = re.compile(r"^(?:izoh|explanation|пояснение)\s*[:\-–]\s*(.+)$", re.I)
LETTER_OPT_RE = re.compile(r"^(\*)?\s*([a-jа-к])\s*[).]\s*(.+?)\s*(\*)?$", re.I)
LETTER_PREFIX_RE = re.compile(r"^[a-jа-к]\s*[).]\s*", re.I)
NUMBER_RE = re.compile(r"^\s*(?:savol\s*)?\d+\s*[.)\-:]\s*", re.I)
HEADER_RE = re.compile(r"^(?:№\s*)?(?:savol(?:lar)?|questions?|вопрос[ы]?)\s*:?$", re.I)
EXPL_HEADER_RE = re.compile(r"izoh|explan|поясн", re.I)

MAX_FILE_SIZE = 5 * 1024 * 1024
SUPPORTED_EXTENSIONS = (".txt", ".docx", ".xlsx", ".csv")


@dataclass
class ParseResult:
    questions: list[Question] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def extend(self, other: "ParseResult") -> None:
        self.questions.extend(other.questions)
        self.errors.extend(other.errors)


@dataclass
class _Draft:
    line_no: int
    question: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    correct: list[int] = field(default_factory=list)
    letter_answer: str | None = None
    explanation: str | None = None


def _letter_index(letter: str) -> int:
    letter = letter.lower()
    return LATIN.index(letter) if letter in LATIN else CYRILLIC.index(letter)


SEPARATOR_RE = re.compile(r"^\++$")
TRAILING_HASH_RE = re.compile(r"\s+#+$")


ANSWER_DIVIDER_RE = re.compile(r"\s*={3,}\s*")
# Word/Telegram'dan nusxalanganda qo'shilib qoladigan ko'rinmas belgilar
INVISIBLE_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")
_CHAR_FIXES = str.maketrans({"\uff03": "#", "\uff1f": "?", "\uff0b": "+", "\u00a0": " ", "\u202f": " "})


def _normalize(raw: str) -> str:
    return INVISIBLE_RE.sub("", raw.translate(_CHAR_FIXES))

Lines = list[tuple[int, str]]  # (qator raqami, matn)


def _split_lines(text: str) -> Lines:
    """
    Qatorlarni raqami bilan qaytaradi. «====» (3 va undan ko'p «=») javoblarni ajratish
    uchun qo'yiladi: alohida qatordagi «====» tashlab yuboriladi, qator ichidagisi esa
    qatorni bir nechta qatorga bo'ladi («Toshkent ==== #Samarqand» → ikki variant).
    """
    lines: Lines = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        raw = _normalize(raw)
        if not ANSWER_DIVIDER_RE.search(raw):
            lines.append((line_no, raw.strip()))
            continue
        lines.extend((line_no, part) for part in ANSWER_DIVIDER_RE.split(raw.strip()) if part.strip())
    return lines


def parse_text(text: str) -> ParseResult:
    """Matnni o'qiydi. Format avtomatik aniqlanadi: «#»/«+» formati yoki klassik format."""
    lines = _split_lines(text)
    if any(SEPARATOR_RE.match(l) or l.startswith("#") for _, l in lines):
        return _parse_hash(lines)
    return _parse_classic(lines)


def _is_marked(line: str) -> bool:
    """Qator «#» bilan to'g'ri javob deb belgilanganmi («#Javob», «A) #Javob», «Javob #»)."""
    rest = LETTER_PREFIX_RE.sub("", line.lstrip("#").strip())
    return line.startswith("#") or rest.startswith("#") or bool(TRAILING_HASH_RE.search(rest))


def _parse_hash(lines: Lines) -> ParseResult:
    """
    «#» formati:

        O'zbekistonning poytaxti qaysi?     <- «?» belgisi bor qator — savol
        #Toshkent                           <- «#» belgisi bor variant — to'g'ri javob
        Samarqand
        Buxoro
        +                                   <- savol tugadi, keyingisi boshlanadi
        7 × 8 nechaga teng?
        54
        #56
        +

    «+» qo'yilmasa ham, variantlardan keyin kelgan «?» li qator yangi savolni boshlaydi.
    Javoblar orasidagi «====» qatorlari o'qilmaydi.
    Savol matnida «?» bo'lmasa, blokning birinchi qatori savol deb olinadi.
    """
    def question_end(block: list[tuple[int, str]]) -> int | None:
        return next((i for i, (_, l) in enumerate(block) if "?" in l), None)

    # «+» ajratgichli faylda «?» belgili qator yangi savolni faqat shunda boshlaydi:
    # joriy savolda to'g'ri javob allaqachon bor va bu qatordan keyin (keyingi «+» gacha)
    # «#» belgili variant ham keladi. Aks holda «Bilmayman?» kabi javoblar savolni bo'lib yuborardi.
    has_separators = any(SEPARATOR_RE.match(l) for _, l in lines)

    def starts_new_question(idx: int, cur: list[tuple[int, str]]) -> bool:
        q_end = question_end(cur)
        if "?" not in lines[idx][1] or q_end is None or q_end >= len(cur) - 1:
            return False
        if not has_separators:
            return True
        if not any(_is_marked(l) for _, l in cur[q_end + 1:]):
            return False
        following = []
        for _, l in lines[idx + 1:]:
            if SEPARATOR_RE.match(l):
                break
            if l:
                following.append(l)
        return len(following) >= 2 and any(_is_marked(l) for l in following)

    blocks: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    for idx, (line_no, line) in enumerate(lines):
        if not line:
            continue
        if SEPARATOR_RE.match(line):
            blocks.append(cur)
            cur = []
            continue
        if starts_new_question(idx, cur):
            blocks.append(cur)
            cur = []
        cur.append((line_no, line))
    blocks.append(cur)

    drafts: list[_Draft] = []
    for block in blocks:
        if not block:
            continue
        q_end = question_end(block)
        q_end = 0 if q_end is None else q_end
        d = _Draft(block[0][0], question=[l for _, l in block[: q_end + 1]])
        for _, line in block[q_end + 1:]:
            if m := EXPL_RE.match(line):
                d.explanation = m.group(1).strip()
                continue
            # «#Javob», «#A) Javob», «A) #Javob» va «Javob #» — hammasi to'g'ri javob belgisi
            correct = line.startswith("#")
            line = LETTER_PREFIX_RE.sub("", line.lstrip("#").strip())
            if line.startswith("#"):
                correct = True
                line = line.lstrip("#").strip()
            if TRAILING_HASH_RE.search(line):
                correct = True
                line = TRAILING_HASH_RE.sub("", line)
            if correct:
                d.correct.append(len(d.options))
            d.options.append(line)
        drafts.append(d)
    if drafts:
        _drop_preamble(drafts[0])
    return _drafts_to_result(drafts)


def _drop_preamble(d: "_Draft") -> None:
    """Fayl boshidagi izoh matnini («Жами 143 та савол. Тўғри жавоблар ...») birinchi savoldan ajratadi:
    savoldan oldingi, nuqta yoki undov bilan tugagan qatorlar savolga qo'shilmaydi."""
    while len(d.question) > 1 and d.question[0].rstrip().endswith((".", "!", "…")):
        d.question.pop(0)


def _parse_classic(lines: Lines) -> ParseResult:
    """
    Klassik formatlar (bir faylda aralash bo'lishi ham mumkin):

        1. Savol matni?             1. Savol matni?
        +To'g'ri javob              A) Variant
        -Noto'g'ri javob            *B) To'g'ri variant   (yoki "Javob: B")
        Izoh: ixtiyoriy izoh        C) Variant

    Savollar bo'sh qator bilan yoki yangi savol matni bilan ajratiladi.
    """
    drafts: list[_Draft] = []
    cur: _Draft | None = None

    def flush() -> None:
        nonlocal cur
        if cur and (cur.question or cur.options):
            drafts.append(cur)
        cur = None

    for line_no, line in lines:
        if not line:
            if cur and cur.options:
                flush()
            continue
        if cur is None:
            cur = _Draft(line_no)

        if cur.question:
            if m := ANSWER_RE.match(line):
                cur.letter_answer = m.group(1)
                continue
            if m := EXPL_RE.match(line):
                cur.explanation = m.group(1).strip()
                continue
            if line.startswith("!"):
                cur.explanation = line[1:].strip()
                continue
            if line[0] in "+-":
                if line[0] == "+":
                    cur.correct.append(len(cur.options))
                cur.options.append(LETTER_PREFIX_RE.sub("", line[1:].strip()))
                continue
            if m := LETTER_OPT_RE.match(line):
                if m.group(1) or m.group(4):
                    cur.correct.append(len(cur.options))
                cur.options.append(m.group(3).strip())
                continue

        # oddiy matn qatori — savol matni
        if cur.options:  # variantlardan keyin kelgan matn yangi savolni boshlaydi
            flush()
            cur = _Draft(line_no)
        cur.question.append(line)
    flush()
    return _drafts_to_result(drafts)


def _drafts_to_result(drafts: list[_Draft]) -> ParseResult:
    result = ParseResult()
    for n, d in enumerate(drafts, 1):
        text_ = NUMBER_RE.sub("", "\n".join(d.question)).strip()
        snippet = " ".join(text_.split())
        snippet = snippet if len(snippet) <= 40 else snippet[:40] + "…"
        where = f"{n}-savol ({d.line_no}-qator" + (f", «{snippet}»)" if snippet else ")")
        correct = d.correct
        if d.letter_answer:
            idx = _letter_index(d.letter_answer)
            if idx >= len(d.options):
                result.errors.append(f"{where}: «Javob: {d.letter_answer}» varianti yo'q")
                continue
            correct = [idx]
        if not correct:
            result.errors.append(f"{where}: to'g'ri javob belgilanmagan")
            continue
        if len(correct) > 1:
            result.errors.append(f"{where}: bir nechta to'g'ri javob belgilangan")
            continue
        q = Question(text_, d.options, correct[0], d.explanation)
        if err := validate_question(q):
            result.errors.append(f"{where}: {err}")
            continue
        result.questions.append(q)
    return result


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return "" if re.fullmatch(r"=*", text) else text


def parse_rows(rows: list[list]) -> ParseResult:
    """
    Jadval formati: 1-ustun — savol, 2-ustun — to'g'ri javob, keyingilari — noto'g'ri javoblar.
    Agar 1-qator sarlavha bo'lsa ("Savol", ...), u o'tkazib yuboriladi; sarlavhasi "Izoh"
    bo'lgan ustun izoh sifatida o'qiladi.
    """
    table = [[_cell(c) for c in row] for row in rows]
    result = ParseResult()
    expl_col: int | None = None
    start = 0
    first = next((i for i, r in enumerate(table) if any(r)), None)
    if first is not None and table[first] and HEADER_RE.match(table[first][0]):
        start = first + 1
        for i, h in enumerate(table[first]):
            if EXPL_HEADER_RE.search(h):
                expl_col = i

    for row_no, row in enumerate(table[start:], start + 1):
        if not any(row):
            continue
        where = f"{row_no}-qator"
        text_ = NUMBER_RE.sub("", row[0]).strip() if row else ""
        if not text_:
            result.errors.append(f"{where}: savol matni bo'sh")
            continue
        explanation = row[expl_col] if expl_col is not None and expl_col < len(row) else ""
        options = [c for i, c in enumerate(row) if i > 0 and i != expl_col and c]
        q = Question(text_, options, 0, explanation or None)
        if err := validate_question(q):
            result.errors.append(f"{where}: {err}")
            continue
        result.questions.append(q)
    return result


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_file(filename: str, data: bytes) -> ParseResult:
    name = filename.lower()
    if name.endswith(".txt"):
        return parse_text(_decode(data))

    if name.endswith(".docx"):
        from docx import Document

        doc = Document(io.BytesIO(data))
        result = parse_text("\n".join(p.text for p in doc.paragraphs))
        for table in doc.tables:
            result.extend(parse_rows([[cell.text for cell in row.cells] for row in table.rows]))
        return result

    if name.endswith(".xlsx"):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            return parse_rows([list(r) for r in wb.worksheets[0].iter_rows(values_only=True)])
        finally:
            wb.close()

    if name.endswith(".csv"):
        text = _decode(data)
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return parse_rows(list(csv.reader(io.StringIO(text), dialect)))

    raise ValueError(
        "Bu fayl formati qo'llab-quvvatlanmaydi. Mumkin: " + ", ".join(SUPPORTED_EXTENSIONS)
    )


# ---------- namuna fayllar ----------

SAMPLE_HASH_TXT = """O'zbekistonning poytaxti qaysi shahar?
#Toshkent
Samarqand
Buxoro
Xiva
+
7 × 8 nechaga teng?
54
#56
58
64
+
Eng katta okean qaysi?
Atlantika okeani
Hind okeani
#Tinch okeani
+
"""

SAMPLE_TXT = """1. O'zbekistonning poytaxti qaysi shahar?
+Toshkent
-Samarqand
-Buxoro
-Xiva
Izoh: Toshkent 1930-yildan beri poytaxt.

2. 7 × 8 nechaga teng?
A) 54
*B) 56
C) 58
D) 64

3. Eng katta okean qaysi?
A) Atlantika okeani
B) Hind okeani
C) Tinch okeani
Javob: C
"""


def sample_xlsx() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Savollar"
    ws.append(["Savol", "To'g'ri javob", "Noto'g'ri 1", "Noto'g'ri 2", "Noto'g'ri 3", "Izoh"])
    ws.append(["O'zbekistonning poytaxti qaysi shahar?", "Toshkent", "Samarqand", "Buxoro", "Xiva",
               "Toshkent 1930-yildan beri poytaxt."])
    ws.append(["7 × 8 nechaga teng?", 56, 54, 58, 64, ""])
    ws.append(["Eng katta okean qaysi?", "Tinch okeani", "Atlantika okeani", "Hind okeani", "", ""])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for col, width in zip("ABCDEF", (45, 20, 20, 20, 20, 40)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
