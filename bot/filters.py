from aiogram.filters import Filter
from aiogram.types import TelegramObject

from .config import Config


class IsAdmin(Filter):
    """Foydalanuvchi .env dagi ADMIN_IDS ro'yxatida bo'lsa o'tkazadi."""

    async def __call__(self, event: TelegramObject, config: Config) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and user.id in config.admin_ids)
