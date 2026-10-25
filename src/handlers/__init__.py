import logging
import traceback
from aiogram import Router, Bot
from aiogram.types import ErrorEvent
from . import commands, callbacks, messages, reactions
from database import db


def setup_handlers() -> Router:
    root_router = Router()

    # Order matters: commands should be checked first, then states, then general messages
    root_router.include_router(commands.router)
    root_router.include_router(callbacks.router)
    root_router.include_router(reactions.router)
    root_router.include_router(messages.router)

    @root_router.error()
    async def global_error_handler(event: ErrorEvent, bot: Bot):
        logging.exception(f"Unhandled exception: {event.exception}")
        from config import ADMIN_IDS, REPORT_CHAT_ID, REPORT_THREAD_ID

        target_chat = (
            db.get_global_config("report_chat_id")
            or REPORT_CHAT_ID
            or (ADMIN_IDS[0] if ADMIN_IDS else None)
        )
        target_thread = (
            db.get_global_config("report_thread_id") or REPORT_THREAD_ID or None
        )

        if not target_chat:
            return

        try:
            tb_str = "".join(
                traceback.format_exception(
                    type(event.exception), event.exception, event.exception.__traceback__
                )
            )
            if len(tb_str) > 3000:
                tb_str = tb_str[-3000:]

            update_info = ""
            if event.update and event.update.message:
                u = event.update.message.from_user
                update_info = f"👤 <b>User:</b> {u.full_name} (ID: <code>{u.id}</code>)\n💬 <b>Msg:</b> <code>{event.update.message.text or event.update.message.caption or 'media'}</code>\n"
            elif event.update and event.update.callback_query:
                u = event.update.callback_query.from_user
                update_info = f"👤 <b>User:</b> {u.full_name} (ID: <code>{u.id}</code>)\n🔘 <b>Callback:</b> <code>{event.update.callback_query.data}</code>\n"

            error_text = (
                f"🚨 <b>ПОМИЛКА В БОТІ</b>\n\n"
                f"{update_info}"
                f"❌ <b>Error:</b> <code>{type(event.exception).__name__}: {event.exception}</code>\n\n"
                f"<pre><code class=\"language-python\">{tb_str}</code></pre>"
            )

            await bot.send_message(
                chat_id=int(target_chat),
                text=error_text,
                message_thread_id=int(target_thread) if target_thread else None,
                parse_mode="HTML",
            )
        except Exception as e:
            logging.error(f"Failed to forward error to Telegram: {e}")

    return root_router
