import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    db_path: str


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN .env faylida ko'rsatilmagan")
    raw_admins = os.getenv("ADMIN_IDS", "").replace(" ", "")
    admins = frozenset(int(x) for x in raw_admins.split(",") if x)
    return Config(
        bot_token=token,
        admin_ids=admins,
        db_path=os.getenv("DB_PATH", "quizbot.db"),
    )
