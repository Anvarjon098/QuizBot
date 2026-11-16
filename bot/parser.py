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
HEADER_RE = re.compile(r"savol|question|вопрос", re.I)
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


def parse_text(text: str) -> ParseResult:
    """
    Qo'llab-quvvatlanadigan formatlar (bir faylda aralash bo'lishi ham mumkin):

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

    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
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

    result = ParseResult()
    for n, d in enumerate(drafts, 1):
        where = f"{n}-savol ({d.line_no}-qator)"
        text_ = NUMBER_RE.sub("", "\n".join(d.question)).strip()
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
    return str(value).strip()


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
    if first is not None and table[first] and HEADER_RE.search(table[first][0]):
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
