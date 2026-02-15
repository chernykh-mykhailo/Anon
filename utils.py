from typing import Union
from aiogram import types
from aiogram.types import Message
from database import db


async def get_lang(
    user_id: int, event: Union[Message, types.MessageReactionUpdated] = None
) -> str:
    lang = db.get_user_lang(user_id, None)
    if lang:
        return lang

    user = None
    if isinstance(event, Message):
        user = event.from_user
    elif hasattr(event, "user"):
        user = event.user

    if user and user.language_code:
        return user.language_code if user.language_code in ["uk", "en"] else "uk"

    return "uk"


async def get_user_link(bot_info, user_id: int) -> str:
    return f"https://t.me/{bot_info.username}?start={user_id}"
