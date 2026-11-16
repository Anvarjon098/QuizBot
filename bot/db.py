import json
import secrets

import aiosqlite
from aiogram.types import User

from .models import Question, Quiz

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT NOT NULL DEFAULT '',
    can_message INTEGER NOT NULL DEFAULT 0,
    menu_cleared INTEGER NOT NULL DEFAULT 1,
    joined_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS quizzes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT UNIQUE NOT NULL,
    owner_id          INTEGER NOT NULL,
    title             TEXT NOT NULL,
    description       TEXT,
    open_period       INTEGER NOT NULL DEFAULT 30,
    shuffle_questions INTEGER NOT NULL DEFAULT 0,
    shuffle_options   INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS questions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id     INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    text        TEXT NOT NULL,
    options     TEXT NOT NULL,
    correct     INTEGER NOT NULL,
    explanation TEXT
);
CREATE TABLE IF NOT EXISTS attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id     INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL,
    chat_id     INTEGER NOT NULL,
    score       INTEGER NOT NULL,
    total       INTEGER NOT NULL,
    duration    REAL NOT NULL,
    finished_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS answers (
    attempt_id  INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    is_correct  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_quiz ON questions(quiz_id, position);
CREATE INDEX IF NOT EXISTS idx_attempts_quiz ON attempts(quiz_id);
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_answers_question ON answers(question_id);
CREATE INDEX IF NOT EXISTS idx_quizzes_owner ON quizzes(owner_id);
"""

# Har bir foydalanuvchining har bir testdagi eng yaxshi natijasi (o'z testlari hisobga olinmaydi)
_BEST_CTE = """
WITH best AS (
    SELECT a.user_id, a.quiz_id, MAX(a.score) AS s
    FROM attempts a JOIN quizzes q ON q.id = a.quiz_id
    WHERE q.owner_id != a.user_id
    GROUP BY a.user_id, a.quiz_id
), totals AS (
    SELECT user_id, SUM(s) AS points, COUNT(*) AS quizzes FROM best GROUP BY user_id
)
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "Database.connect() chaqirilmagan"
        return self._conn

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.executescript(SCHEMA)
        await self._migrate()
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def backup_to(self, dest: str) -> None:
        """Ishlab turgan bazaning to'liq nusxasini dest fayliga yozadi."""
        await self.conn.commit()
        target = await aiosqlite.connect(dest)
        try:
            await self.conn.backup(target)
        finally:
            await target.close()

    async def restore_from(self, src: str) -> None:
        """Bazani src faylidagi nusxa bilan almashtiradi (src oldindan tekshirilgan bo'lishi kerak)."""
        import os
        import shutil
        await self.close()
        for suffix in ("-wal", "-shm"):
            if os.path.exists(self.path + suffix):
                os.remove(self.path + suffix)
        shutil.copyfile(src, self.path)
        await self.connect()

    # ---------- foydalanuvchilar ----------

    async def upsert_user(self, user: User, private: bool) -> None:
        await self.conn.execute(
            """
            INSERT INTO users (id, username, full_name, can_message, menu_cleared) VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                can_message = MAX(users.can_message, excluded.can_message)
            """,
            (user.id, user.username, user.full_name, int(private)),
        )
        await self.conn.commit()

    async def set_can_message(self, user_id: int, value: bool) -> None:
        await self.conn.execute("UPDATE users SET can_message = ? WHERE id = ?", (int(value), user_id))
        await self.conn.commit()

    async def _migrate(self) -> None:
        cur = await self.conn.execute("PRAGMA table_info(users)")
        columns = {r["name"] for r in await cur.fetchall()}
        if "menu_cleared" not in columns:
            # Eski foydalanuvchilarda eski menyu tugmalari qolgan bo'lishi mumkin -> 0
            await self.conn.execute("ALTER TABLE users ADD COLUMN menu_cleared INTEGER NOT NULL DEFAULT 0")

    async def users_with_old_menu(self, admin_ids: frozenset[int]) -> list[int]:
        cur = await self.conn.execute(
            "SELECT id FROM users WHERE can_message = 1 AND menu_cleared = 0"
        )
        return [r["id"] for r in await cur.fetchall() if r["id"] not in admin_ids]

    async def mark_menu_cleared(self, user_id: int) -> None:
        await self.conn.execute("UPDATE users SET menu_cleared = 1 WHERE id = ?", (user_id,))
        await self.conn.commit()

    async def messageable_user_ids(self) -> list[int]:
        cur = await self.conn.execute("SELECT id FROM users WHERE can_message = 1")
        return [r["id"] for r in await cur.fetchall()]

    async def all_users(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            """
            SELECT u.*,
                   (SELECT COUNT(*) FROM quizzes q WHERE q.owner_id = u.id) AS quizzes,
                   (SELECT COUNT(*) FROM attempts a WHERE a.user_id = u.id) AS attempts
            FROM users u ORDER BY u.joined_at
            """
        )
        return await cur.fetchall()

    # ---------- testlar ----------

    @staticmethod
    def _row_to_quiz(row: aiosqlite.Row) -> Quiz:
        keys = row.keys()
        return Quiz(
            id=row["id"],
            code=row["code"],
            owner_id=row["owner_id"],
            title=row["title"],
            description=row["description"],
            open_period=row["open_period"],
            shuffle_questions=bool(row["shuffle_questions"]),
            shuffle_options=bool(row["shuffle_options"]),
            created_at=row["created_at"],
            question_count=row["question_count"] if "question_count" in keys else 0,
        )

    async def create_quiz(
        self,
        owner_id: int,
        title: str,
        description: str | None,
        open_period: int,
        shuffle_questions: bool,
        shuffle_options: bool,
        questions: list[Question],
    ) -> Quiz:
        code = secrets.token_urlsafe(6)
        cur = await self.conn.execute(
            """
            INSERT INTO quizzes (code, owner_id, title, description, open_period,
                                 shuffle_questions, shuffle_options)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (code, owner_id, title, description, open_period, int(shuffle_questions), int(shuffle_options)),
        )
        quiz_id = cur.lastrowid
        await self.conn.executemany(
            "INSERT INTO questions (quiz_id, position, text, options, correct, explanation) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (quiz_id, i, q.text, json.dumps(q.options, ensure_ascii=False), q.correct, q.explanation)
                for i, q in enumerate(questions)
            ],
        )
        await self.conn.commit()
        quiz = await self.get_quiz(quiz_id)
        assert quiz is not None
        return quiz

    _QUIZ_SELECT = """
        SELECT q.*, (SELECT COUNT(*) FROM questions x WHERE x.quiz_id = q.id) AS question_count
        FROM quizzes q
    """

    async def get_quiz(self, quiz_id: int) -> Quiz | None:
        cur = await self.conn.execute(self._QUIZ_SELECT + " WHERE q.id = ?", (quiz_id,))
        row = await cur.fetchone()
        return self._row_to_quiz(row) if row else None

    async def get_quiz_by_code(self, code: str) -> Quiz | None:
        cur = await self.conn.execute(self._QUIZ_SELECT + " WHERE q.code = ?", (code,))
        row = await cur.fetchone()
        return self._row_to_quiz(row) if row else None

    async def get_questions(self, quiz_id: int) -> list[Question]:
        cur = await self.conn.execute(
            "SELECT * FROM questions WHERE quiz_id = ? ORDER BY position", (quiz_id,)
        )
        return [
            Question(r["text"], json.loads(r["options"]), r["correct"], r["explanation"], r["id"])
            for r in await cur.fetchall()
        ]

    async def user_quizzes(self, owner_id: int) -> list[Quiz]:
        cur = await self.conn.execute(
            self._QUIZ_SELECT + " WHERE q.owner_id = ? ORDER BY q.id DESC", (owner_id,)
        )
        return [self._row_to_quiz(r) for r in await cur.fetchall()]

    async def all_quizzes(self, offset: int, limit: int) -> list[Quiz]:
        cur = await self.conn.execute(
            self._QUIZ_SELECT + " ORDER BY q.id DESC LIMIT ? OFFSET ?", (limit, offset)
        )
        return [self._row_to_quiz(r) for r in await cur.fetchall()]

    async def count_quizzes(self) -> int:
        cur = await self.conn.execute("SELECT COUNT(*) FROM quizzes")
        return (await cur.fetchone())[0]

    async def delete_quiz(self, quiz_id: int) -> None:
        await self.conn.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
        await self.conn.commit()

    # ---------- natijalar ----------

    async def save_attempt(
        self,
        quiz_id: int,
        user_id: int,
        chat_id: int,
        score: int,
        total: int,
        duration: float,
        answers: dict[int, bool],
    ) -> int:
        cur = await self.conn.execute(
            "INSERT INTO attempts (quiz_id, user_id, chat_id, score, total, duration) VALUES (?, ?, ?, ?, ?, ?)",
            (quiz_id, user_id, chat_id, score, total, duration),
        )
        attempt_id = cur.lastrowid
        await self.conn.executemany(
            "INSERT INTO answers (attempt_id, question_id, is_correct) VALUES (?, ?, ?)",
            [(attempt_id, qid, int(ok)) for qid, ok in answers.items()],
        )
        await self.conn.commit()
        return attempt_id

    async def quiz_leaderboard(self, quiz_id: int) -> list[aiosqlite.Row]:
        """Har bir o'yinchining eng yaxshi urinishi, o'rin bo'yicha tartiblangan."""
        cur = await self.conn.execute(
            """
            SELECT a.user_id, COALESCE(u.full_name, '?') AS name, a.score, a.total, a.duration
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY user_id ORDER BY score DESC, duration ASC
                ) AS rn
                FROM attempts WHERE quiz_id = ?
            ) a
            LEFT JOIN users u ON u.id = a.user_id
            WHERE a.rn = 1
            ORDER BY a.score DESC, a.duration ASC
            """,
            (quiz_id,),
        )
        return await cur.fetchall()

    async def quiz_stats(self, quiz_id: int) -> aiosqlite.Row:
        cur = await self.conn.execute(
            """
            SELECT COUNT(*) AS attempts,
                   COUNT(DISTINCT user_id) AS players,
                   COALESCE(AVG(100.0 * score / NULLIF(total, 0)), 0) AS avg_pct,
                   COALESCE(AVG(duration), 0) AS avg_duration
            FROM attempts WHERE quiz_id = ?
            """,
            (quiz_id,),
        )
        return await cur.fetchone()

    async def question_stats(self, quiz_id: int) -> list[aiosqlite.Row]:
        """Har bir savol uchun to'g'ri javoblar foizi (eng qiyini birinchi)."""
        cur = await self.conn.execute(
            """
            SELECT q.position, q.text, COUNT(a.is_correct) AS answered,
                   COALESCE(100.0 * SUM(a.is_correct) / COUNT(a.is_correct), 0) AS pct
            FROM questions q JOIN answers a ON a.question_id = q.id
            WHERE q.quiz_id = ?
            GROUP BY q.id
            ORDER BY pct ASC, answered DESC
            """,
            (quiz_id,),
        )
        return await cur.fetchall()

    async def user_stats(self, user_id: int) -> aiosqlite.Row:
        cur = await self.conn.execute(
            """
            SELECT COUNT(*) AS attempts,
                   COUNT(DISTINCT quiz_id) AS quizzes,
                   COALESCE(SUM(score), 0) AS correct,
                   COALESCE(SUM(total), 0) AS total,
                   COALESCE(MAX(100.0 * score / NULLIF(total, 0)), 0) AS best_pct,
                   (SELECT COUNT(*) FROM quizzes WHERE owner_id = :uid) AS created,
                   (SELECT COUNT(*) FROM attempts a JOIN quizzes q ON q.id = a.quiz_id
                     WHERE q.owner_id = :uid) AS plays_of_mine
            FROM attempts WHERE user_id = :uid
            """,
            {"uid": user_id},
        )
        return await cur.fetchone()

    async def user_recent_attempts(self, user_id: int, limit: int = 5) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            """
            SELECT a.*, q.title FROM attempts a JOIN quizzes q ON q.id = a.quiz_id
            WHERE a.user_id = ? ORDER BY a.id DESC LIMIT ?
            """,
            (user_id, limit),
        )
        return await cur.fetchall()

    async def global_rating(self, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            _BEST_CTE
            + """
            SELECT t.user_id, COALESCE(u.full_name, '?') AS name, t.points, t.quizzes
            FROM totals t LEFT JOIN users u ON u.id = t.user_id
            ORDER BY t.points DESC, t.quizzes ASC LIMIT ?
            """,
            (limit,),
        )
        return await cur.fetchall()

    async def user_global_place(self, user_id: int) -> aiosqlite.Row | None:
        cur = await self.conn.execute(
            _BEST_CTE
            + """
            SELECT t.points,
                   (SELECT COUNT(*) + 1 FROM totals t2 WHERE t2.points > t.points) AS place,
                   (SELECT COUNT(*) FROM totals) AS total
            FROM totals t WHERE t.user_id = ?
            """,
            (user_id,),
        )
        return await cur.fetchone()

    # ---------- admin ----------

    async def admin_counts(self) -> dict[str, int]:
        queries = {
            "users": "SELECT COUNT(*) FROM users",
            "reachable": "SELECT COUNT(*) FROM users WHERE can_message = 1",
            "users_today": "SELECT COUNT(*) FROM users WHERE date(joined_at) = date('now')",
            "quizzes": "SELECT COUNT(*) FROM quizzes",
            "quizzes_today": "SELECT COUNT(*) FROM quizzes WHERE date(created_at) = date('now')",
            "questions": "SELECT COUNT(*) FROM questions",
            "attempts": "SELECT COUNT(*) FROM attempts",
            "attempts_today": "SELECT COUNT(*) FROM attempts WHERE date(finished_at) = date('now')",
        }
        result = {}
        for key, sql in queries.items():
            cur = await self.conn.execute(sql)
            result[key] = (await cur.fetchone())[0]
        return result


# ---------- zaxira nusxa ----------

def is_valid_backup(path: str) -> bool:
    """Fayl QuizBot bazasi ekanini tekshiradi."""
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return {"users", "quizzes", "questions"} <= tables and \
                con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            con.close()
    except sqlite3.Error:
        return False
