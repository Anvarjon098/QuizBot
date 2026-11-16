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
