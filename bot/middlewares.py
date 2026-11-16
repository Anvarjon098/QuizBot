from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import TelegramObject

from .db import Database


class UserMiddleware(BaseMiddleware):
    """Har bir foydalanuvchini bazaga yozib boradi (reyting va xabar yuborish uchun)."""

    def __init__(self, db: Database):
        self.db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        if user and not user.is_bot:
            await self.db.upsert_user(user, private=chat is not None and chat.type == ChatType.PRIVATE)
        return await handler(event, data)
