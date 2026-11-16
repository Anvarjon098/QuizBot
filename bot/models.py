from dataclasses import dataclass, field

# Telegram quiz-poll cheklovlari (savol oldiga "[12/100] " qo'shiladi, shuning uchun 300 emas)
QUESTION_MAX = 280
OPTION_MAX = 100
OPTIONS_MIN = 2
OPTIONS_MAX = 10
EXPLANATION_MAX = 200
QUESTIONS_PER_QUIZ_MAX = 200
TITLE_MAX = 100
DESCRIPTION_MAX = 500

TIMER_CHOICES = (10, 15, 20, 30, 45, 60, 120, 300)


@dataclass
class Question:
    text: str
    options: list[str]
    correct: int
    explanation: str | None = None
    id: int | None = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "options": list(self.options),
            "correct": self.correct,
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Question":
        return cls(d["text"], list(d["options"]), d["correct"], d.get("explanation"), d.get("id"))


@dataclass
class Quiz:
    id: int
    code: str
    owner_id: int
    title: str
    description: str | None
    open_period: int
    shuffle_questions: bool
    shuffle_options: bool
    created_at: str
    question_count: int = 0
    questions: list[Question] = field(default_factory=list)


def validate_question(q: Question) -> str | None:
    """Xato matnini qaytaradi yoki savol to'g'ri bo'lsa None."""
    if not q.text.strip():
        return "savol matni bo'sh"
    if len(q.text) > QUESTION_MAX:
        return f"savol juda uzun ({len(q.text)}/{QUESTION_MAX} belgi)"
    if len(q.options) < OPTIONS_MIN:
        return f"kamida {OPTIONS_MIN} ta variant kerak"
    if len(q.options) > OPTIONS_MAX:
        return f"ko'pi bilan {OPTIONS_MAX} ta variant bo'lishi mumkin"
    for opt in q.options:
        if not opt.strip():
            return "bo'sh variant bor"
        if len(opt) > OPTION_MAX:
            return f"variant juda uzun: «{opt[:25]}…» (maks. {OPTION_MAX} belgi)"
    if len(set(q.options)) != len(q.options):
        return "variantlar takrorlangan"
    if not 0 <= q.correct < len(q.options):
        return "to'g'ri javob noto'g'ri belgilangan"
    if q.explanation and len(q.explanation) > EXPLANATION_MAX:
        return f"izoh juda uzun (maks. {EXPLANATION_MAX} belgi)"
    return None
