import asyncio
from typing import Any, Callable, Dict, List

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

DEFAULT_LATENCY = 0.5


class MediaGroupMiddleware(BaseMiddleware):
    """
    Middleware for collecting media groups.
    Each message in a media group is handled as a separate event by aiogram.
    This middleware collects them and passes a list of messages (as 'album') to the handler.
    Wait for DEFAULT_LATENCY seconds for more messages with the same media_group_id.
    """

    def __init__(self, latency: float = DEFAULT_LATENCY):
        self.latency = latency
        self.cache: Dict[str, List[Message]] = {}
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Any],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.media_group_id:
            return await handler(event, data)

        mg_id = event.media_group_id

        if mg_id not in self.cache:
            self.cache[mg_id] = [event]
            # Wait for all messages in the group to arrive
            await asyncio.sleep(self.latency)

            # After waiting, trigger the handler with the full album
            album = self.cache.pop(mg_id)
            data["album"] = album
            return await handler(event, data)
        else:
            # If this is not the first message in the group, just add it to the cache and stop processing here
            self.cache[mg_id].append(event)
            return None
