from aiogram import Router
from . import commands, callbacks, messages, reactions


def setup_handlers() -> Router:
    root_router = Router()

    # Order matters: commands should be checked first, then states, then general messages
    root_router.include_router(commands.router)
    root_router.include_router(callbacks.router)
    root_router.include_router(reactions.router)
    root_router.include_router(messages.router)

    return root_router
