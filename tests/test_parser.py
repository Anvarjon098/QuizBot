from bot.parser import SAMPLE_TXT, parse_file, parse_rows, parse_text, sample_xlsx


def test_sample_txt_all_formats():
    r = parse_text(SAMPLE_TXT)
    assert r.errors == []
    assert len(r.questions) == 3
    q1, q2, q3 = r.questions
    assert q1.text == "O'zbekistonning poytaxti qaysi shahar?"
    assert q1.options[q1.correct] == "Toshkent"
    assert q1.explanation == "Toshkent 1930-yildan beri poytaxt."
    assert q2.options == ["54", "56", "58", "64"] and q2.correct == 1
    assert q3.options[q3.correct] == "Tinch okeani"


def test_no_blank_lines_between_questions():
    r = parse_text("Savol 1?\n+ha\n-yo'q\nSavol 2?\n-a\n+b")
    assert [q.text for q in r.questions] == ["Savol 1?", "Savol 2?"]
    assert r.questions[1].correct == 1


def test_cyrillic_letters_and_trailing_star():
    r = parse_text("Вопрос?\nА) один\nБ) два *\nВ) три")
    assert r.errors == [] and r.questions[0].correct == 1
    r = parse_text("Вопрос?\nА) один\nБ) два\nВ) три\nОтвет: В")
    assert r.errors == [] and r.questions[0].correct == 2


def test_errors_reported():
    r = parse_text("Savol?\n-a\n-b\n\nIkki to'g'ri?\n+a\n+b\n\nBitta?\n+a\n\nYaxshi?\n+a\n-b")
    assert len(r.questions) == 1
    assert len(r.errors) == 3
    assert "belgilanmagan" in r.errors[0]
    assert "bir nechta" in r.errors[1]
    assert "kamida 2" in r.errors[2]


def test_rows_with_header_and_explanation():
    rows = [["Savol", "To'g'ri", "Xato", "Izoh"], ["2+2?", 4.0, 5, "oddiy"], [None, None], ["", "x", "y"]]
    r = parse_rows(rows)
    assert len(r.questions) == 1
    assert r.questions[0].options == ["4", "5"] and r.questions[0].correct == 0
    assert r.questions[0].explanation == "oddiy"
    assert r.errors == ["4-qator: savol matni bo'sh"]


def test_xlsx_and_csv_and_docx():
    r = parse_file("t.xlsx", sample_xlsx())
    assert len(r.questions) == 3 and r.errors == []
    assert r.questions[1].options[0] == "56"

    r = parse_file("t.csv", "Savol;Javob;Xato\nA?;ha;yo'q\n".encode())
    assert len(r.questions) == 1 and r.questions[0].options == ["ha", "yo'q"]

    import io
    from docx import Document
    d = Document()
    for line in SAMPLE_TXT.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO(); d.save(buf)
    r = parse_file("t.docx", buf.getvalue())
    assert len(r.questions) == 3 and r.errors == []


def test_unsupported_format():
    import pytest
    with pytest.raises(ValueError):
        parse_file("t.pdf", b"")


# ---------- «#» / «+» formati ----------
from bot.parser import SAMPLE_HASH_TXT


def test_hash_sample():
    r = parse_text(SAMPLE_HASH_TXT)
    assert r.errors == []
    assert [(q.text, q.options[q.correct]) for q in r.questions] == [
        ("O'zbekistonning poytaxti qaysi shahar?", "Toshkent"),
        ("7 × 8 nechaga teng?", "56"),
        ("Eng katta okean qaysi?", "Tinch okeani"),
    ]
    assert r.questions[0].options == ["Toshkent", "Samarqand", "Buxoro", "Xiva"]


def test_hash_variants_and_missing_plus():
    text = (
        "1. Matn bilan boshlangan\nikki qatorli savol?\nA) #bir\nB) ikki\n+\n"
        "Uchinchi?\nx\ny #\n"          # oxirida «#», «+» yo'q
        "To'rtinchi?\n#C# tili\nJava\n"  # «?» li qator yangi savolni boshlaydi; «C#» matni saqlanadi
    )
    r = parse_text(text)
    assert r.errors == []
    q1, q2, q3 = r.questions
    assert q1.text == "Matn bilan boshlangan\nikki qatorli savol?"
    assert q1.options == ["bir", "ikki"] and q1.correct == 0
    assert q2.options == ["x", "y"] and q2.correct == 1
    assert q3.options == ["C# tili", "Java"] and q3.correct == 0


def test_hash_errors_and_no_question_mark():
    text = "Javobsiz?\na\nb\n+\nIkki to'g'ri?\n#a\n#b\n+\nSavol belgisiz\n#ha\nyo'q\n+\n+\n"
    r = parse_text(text)
    assert [q.text for q in r.questions] == ["Savol belgisiz"]
    assert len(r.errors) == 2
    assert "belgilanmagan" in r.errors[0] and "bir nechta" in r.errors[1]


def test_hash_docx():
    import io
    from docx import Document
    d = Document()
    for line in SAMPLE_HASH_TXT.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO(); d.save(buf)
    r = parse_file("t.docx", buf.getvalue())
    assert len(r.questions) == 3 and r.errors == []


def test_equals_dividers_are_ignored():
    text = (
        "Poytaxt qaysi?\n====\n#Toshkent\n====\nSamarqand\n=====\nBuxoro\n+\n"
        "2 + 2 = ?\nToshkent ==== #4 ==== 5\n+\n"
    )
    r = parse_text(text)
    assert r.errors == []
    q1, q2 = r.questions
    assert q1.options == ["Toshkent", "Samarqand", "Buxoro"] and q1.correct == 0
    assert q2.text == "2 + 2 = ?"
    assert q2.options == ["Toshkent", "4", "5"] and q2.correct == 1


def test_equals_dividers_classic_and_rows():
    r = parse_text("1. Savol?\n+ha\n====\n-yo'q\n====\n\n2. Ikkinchi?\nA) x\n====\n*B) y")
    assert r.errors == [] and [len(q.options) for q in r.questions] == [2, 2]
    r = parse_rows([["Savol?", "ha", "====", "yo'q"]])
    assert r.questions[0].options == ["ha", "yo'q"]


def test_header_detection_is_strict():
    assert len(parse_rows([["Savol nima?", "ha", "yo'q"]]).questions) == 1
    assert len(parse_rows([["Savollar", "To'g'ri", "Xato"], ["A?", "ha", "yo'q"]]).questions) == 1


def test_hash_format_answer_with_question_mark_is_not_split():
    text = "Qaysi biri to'g'ri?\nBilmayman?\n#Toshkent\nSamarqand\n+\nIkkinchi savol?\n#Ha\nYo'q\n+\n"
    r = parse_text(text)
    assert r.errors == []
    assert len(r.questions) == 2
    assert r.questions[0].options == ["Bilmayman?", "Toshkent", "Samarqand"]
    assert r.questions[0].correct == 1


def test_hash_format_invisible_chars_and_fullwidth_hash():
    text = "﻿Savol?\n​#To'g'ri\nNoto'g'ri\n+\nIkkinchi？\n＃Ha javob\nYo'q\n+\n"
    r = parse_text(text)
    assert r.errors == []
    assert [q.options[q.correct] for q in r.questions] == ["To'g'ri", "Ha javob"]


def test_long_question_allowed_and_error_shows_snippet():
    long_q = "Uzun savol " + "x" * 400 + "?"
    r = parse_text(f"{long_q}\n#A\nB\n+\nJavobsiz savol?\nA\nB\n+\n")
    assert len(r.questions) == 1 and len(r.questions[0].text) > 300
    assert len(r.errors) == 1 and "«Javobsiz savol?»" in r.errors[0]


def test_question_mark_answer_after_correct_answer():
    r = parse_text("Poytaxt qaysi?\n#Toshkent\nBilmayman?\nSamarqand\n+\n")
    assert r.errors == []
    assert r.questions[0].options == ["Toshkent", "Bilmayman?", "Samarqand"]
