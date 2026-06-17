import time as _time
from aiogram import Bot
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from database import db
from l10n import l10n
from utils import get_lang
from states import Form


async def get_active_target(message: Message, state: FSMContext, bot: Bot):
    """
    Core logic to find WHO the message should go to.
    Returns: (target_id, reply_to_id, anon_num)
    """
    state_data = await state.get_data()
    active_target_id = state_data.get("target_id")
    anon_num = state_data.get("anon_num")
    reply_to_id = None

    # 1. Reply to an anonymous message (Priority)
    if message.reply_to_message:
        link = db.get_link_by_receiver(
            message.reply_to_message.message_id, message.chat.id
        )
        if link:
            reply_target_id, reply_to_id, _, link_anon_num = link

            # If replying to someone else, it's a one-off (don't break current session)
            if reply_target_id != active_target_id:
                num_to_use = link_anon_num or db.get_or_create_anon_num(
                    reply_target_id, message.from_user.id
                )
                return reply_target_id, reply_to_id, num_to_use

            # If replying in active session, preserve the message-specific number
            if link_anon_num:
                anon_num = link_anon_num

    # 2. Check for temporary "Write More" state
    temp_target_id = state_data.get("temp_target_id")
    if temp_target_id:
        temp_reply_to_id = state_data.get("temp_reply_to_id")
        num_to_use = db.get_or_create_anon_num(temp_target_id, message.from_user.id)
        # Clear temp state IMMEDIATELY
        await state.update_data(
            temp_target_id=None, temp_reply_to_id=None, target_name=None
        )
        return temp_target_id, temp_reply_to_id, num_to_use

    # 3. Persistent session logic
    if active_target_id:
        # Session expiry check
        # DB returns string, convert to int
        conf_session_min = db.get_global_config("session_time", "5")
        try:
            session_minutes = int(conf_session_min)
        except (ValueError, TypeError):
            session_minutes = 5

        if session_minutes > 0:
            # Check session existence and timestamp in DB
            with db._get_connection() as conn:
                session_data = conn.execute(
                    """SELECT strftime('%s', updated_at) FROM active_sessions 
                       WHERE (user_a = ? AND user_b = ?) 
                       OR (user_a = ? AND user_b = ?)""",
                    (
                        message.from_user.id,
                        active_target_id,
                        active_target_id,
                        message.from_user.id,
                    ),
                ).fetchone()

            if session_data and session_data[0]:
                last_update = int(session_data[0])
                current_time = _time.time()
                diff_seconds = current_time - last_update

                if diff_seconds > (session_minutes * 60):
                    # SESSION EXPIRED
                    db.delete_session(message.from_user.id, active_target_id)
                    await state.clear()
                    lang = await get_lang(message.from_user.id, message)
                    await message.answer(
                        l10n.format_value("error.session_expired", lang)
                    )
                    return None, None, None
            else:
                # Session exists in FSM state but NOT in DB (expired or deleted)
                await state.clear()
                return None, None, None

        # Auto-dialogue check
        is_auto = db.get_global_config("auto_dialogue", "1") == "1"
        if not is_auto:
            pass

        if not anon_num:
            anon_num = db.get_or_create_anon_num(active_target_id, message.from_user.id)

        # IMPORTANT: Always update the session timestamp on activity
        db.update_session(message.from_user.id, active_target_id)
        await state.update_data(target_id=active_target_id, anon_num=anon_num)
        await state.set_state(Form.writing_message)
        return active_target_id, reply_to_id, anon_num

    return None, None, None


async def cleanup_previous_confirmation(chat_id: int, state: FSMContext, bot: Bot):
    """Deletes the previous confirmation message to keep chat clean."""
    data = await state.get_data()
    msg_id = data.get("last_conf_msg_id")
    is_media = data.get("last_conf_is_media", False)

    if msg_id:
        try:
            if is_media:
                # If it's media (photo/voice), we usually just remove markup to stop interaction
                await bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=msg_id, reply_markup=None
                )
            else:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except TelegramBadRequest:
            pass
        except Exception:
            pass
        await state.update_data(last_conf_msg_id=None)
