from typing import Union, Optional
from aiogram import types, Bot
from aiogram.types import Message
from database import db


async def get_lang(
    user_id: int,
    event: Union[Message, types.MessageReactionUpdated, None] = None,
    bot: Optional[Bot] = None,
) -> str:
    # 1. Check database for saved setting
    lang = db.get_user_lang(user_id, None)
    if lang:
        return lang

    # 2. Try to get lang from the event (Message/Reaction)
    user = None
    if isinstance(event, Message):
        user = event.from_user
    elif hasattr(event, "user") and event.user:
        user = event.user

    # 3. If still no user, and bot is provided, we could fetch chat info
    # but that's expensive and chat info rarely contains language_code.
    # We'll rely on the existing user object if it was passed.

    if user and user.language_code:
        return user.language_code if user.language_code in ["uk", "en"] else "uk"

    return "uk"


async def get_user_link(bot_info, user_id: int) -> str:
    return f"https://t.me/{bot_info.username}?start={user_id}"
