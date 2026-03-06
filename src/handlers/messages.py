import os
import logging

from aiogram import Router, Bot, types, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
    ReactionTypeEmoji,
)
from aiogram.filters import Command
from typing import Union, List
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from l10n import l10n
from database import db
from states import Form
from utils import get_lang
from services.voice_engine import text_to_voice
from services.image_engine import generate_image_input, cleanup_image

DEFAULT_COOLDOWN = 0

router = Router()


async def get_target_and_remind(message: Message, state: FSMContext, bot: Bot):
    """
    Finds target for the user. Logic:
    1. Reply to anonymous msg -> Returns that person but DOES NOT start persistent dialogue.
    2. Persistent State -> Returns current target.
    """
    state_data = await state.get_data()
    active_target_id = state_data.get("target_id")
    anon_num = state_data.get("anon_num")
    reply_to_id = None  # Reset for each message unless manual reply detected

    # 1. Reply to an anonymous message (one-off forward priority)
    if message.reply_to_message:
        link = db.get_link_by_receiver(
            message.reply_to_message.message_id, message.chat.id
        )
        if link:
            reply_target_id, reply_to_id, _, link_anon_num = link

            # If it's a reply to someone ELSE than our active session, it's a one-off
            if reply_target_id != active_target_id:
                # Use the number from the message itself if found, otherwise get persistent one
                num_to_use = link_anon_num or db.get_available_anon_num(
                    reply_target_id, message.from_user.id
                )
                return reply_target_id, reply_to_id, num_to_use

            # If it's a reply to the CURRENT active session, use the message's number if possible
            if link_anon_num:
                anon_num = link_anon_num

    # 2. Check for temporary "Write More" (one-off)
    temp_target_id = state_data.get("temp_target_id")
    if temp_target_id:
        temp_reply_to_id = state_data.get("temp_reply_to_id")
        num_to_use = db.get_available_anon_num(temp_target_id, message.from_user.id)
        # Clear temp target immediately so it doesn't persist
        await state.update_data(temp_target_id=None, temp_reply_to_id=None)
        return temp_target_id, temp_reply_to_id, num_to_use

    # 3. Update persistent session if active
    if active_target_id:
        # --- CHECK SESSION EXPIRY ---
        import sqlite3 as _sqlite3
        from datetime import datetime as _dt

        session_minutes = int(db.get_global_config("session_time", "5"))
        if session_minutes > 0:
            with _sqlite3.connect(db.db_path) as _conn:
                _c = _conn.cursor()
                u1, u2 = sorted([message.from_user.id, active_target_id])
                _c.execute(
                    "SELECT updated_at FROM active_sessions WHERE user_a = ? AND user_b = ?",
                    (u1, u2),
                )
                _res = _c.fetchone()
            if _res:
                try:
                    updated_at = _dt.strptime(_res[0], "%Y-%m-%d %H:%M:%S")
                    diff = (_dt.utcnow() - updated_at).total_seconds()
                    if diff > (session_minutes * 60):
                        db.delete_session(message.from_user.id, active_target_id)
                        await state.clear()
                        lang = await get_lang(message.from_user.id, message)
                        await message.answer(
                            l10n.format_value("error.session_expired", lang)
                        )
                        return None, None, None
                except Exception as _e:
                    logging.error(f"Session expiry check error: {_e}")

        # --- CHECK AUTO_DIALOGUE ---
        is_auto = db.get_global_config("auto_dialogue", "1") == "1"
        if not is_auto:
            # Clear state BEFORE returning so in_dialogue=False in forward → shows "Start Dialogue" button
            oneoff_num = anon_num or db.get_available_anon_num(
                active_target_id, message.from_user.id
            )
            await state.clear()
            return active_target_id, reply_to_id, oneoff_num

        if not anon_num:
            anon_num = db.get_available_anon_num(active_target_id, message.from_user.id)
        else:
            db.update_session(message.from_user.id, active_target_id)

        await state.update_data(target_id=active_target_id, anon_num=anon_num)
        await state.set_state(Form.writing_message)
        return active_target_id, reply_to_id, anon_num

    return None, None, None


async def cleanup_previous_confirmation(chat_id: int, state: FSMContext, bot: Bot):
    """
    Cleans up the previous confirmation message.
    - If it was media (voice/photo), remove its keyboard.
    - If it was text, delete it completely.
    """
    data = await state.get_data()
    prev_conf_id = data.get("last_conf_msg_id")
    if not prev_conf_id:
        return

    is_media = data.get("last_conf_is_media", False)
    if is_media:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=prev_conf_id, reply_markup=None
            )
        except Exception:
            pass
    else:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=prev_conf_id)
        except Exception:
            pass

    # Clear current
    await state.update_data(last_conf_msg_id=None, last_conf_is_media=False)


async def forward_anonymous_msg(
    bot: Bot,
    message: Message,
    target_id: int,
    sender_id: int,
    state: FSMContext,
    reply_to_id: int = None,
    anon_num: str = None,
    album: List[Message] = None,
    override_text: str = None,
    check_cd: bool = True,
):
    target_lang = await get_lang(target_id, bot=bot)
    sender_lang = await get_lang(sender_id, bot=bot)

    # CHECK SETTINGS
    target_settings = db.get_user_settings(target_id)
    sender_settings = db.get_user_settings(sender_id)
    if not target_settings["receive_messages"]:
        return await message.answer(
            l10n.format_value("user_disabled_messages", sender_lang)
        )

    # Determine if it's media
    is_media = any(
        [
            message.photo,
            message.video,
            message.animation,
            message.voice,
            message.audio,
            message.document,
            message.sticker,
            message.video_note,
            message.poll,
        ]
    )

    if is_media and not target_settings["receive_media"]:
        return await message.answer(
            l10n.format_value("user_disabled_media", sender_lang)
        )

    # CHECK BLOCKS
    if db.is_blocked(target_id, sender_id):
        return await message.answer(l10n.format_value("msg_blocked", sender_lang))

    # COOLDOWN CHECK (Robust version)
    if check_cd:
        cd_seconds = int(db.get_global_config("message_cooldown", DEFAULT_COOLDOWN))
        allowed, remain = db.check_and_reserve_cooldown(
            sender_id, target_id, cd_seconds
        )
        if not allowed:
            return await message.answer(
                l10n.format_value("error.cooldown", sender_lang, seconds=remain)
            )

    # Notify about new message or reply
    notify_key = "reply_received" if reply_to_id else "new_anonymous_msg"
    data = await state.get_data()

    # Determine display name for receiver
    # Default is the anonymous number
    display_name = anon_num or data.get("anon_num") or "№???"
    receiver_display_name = display_name

    # Copy message with native reply
    poll_id = None
    if message.poll:
        try:
            target_state_ctx = FSMContext(
                storage=state.storage,
                key=StorageKey(bot_id=bot.id, chat_id=target_id, user_id=target_id),
            )
            target_data = await target_state_ctx.get_data()

            # If the receiver is currently in a dialogue with this sender and has their name
            if target_data.get("target_id") == sender_id and target_data.get(
                "target_name"
            ):
                receiver_display_name = target_data.get("target_name")
        except Exception:
            pass

        # Message effects
        effect_id = "5104841245755180586" if not reply_to_id else "5046509860445903448"

        # Determine if we show dialogue button
        is_target_in_dialogue = target_data.get("target_id") == sender_id

        # Start dialogue button for receiver (only if not already in dialogue)
        kb_notify = None
        if not is_target_in_dialogue:
            kb_notify = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=l10n.format_value(
                                "button.start_dialogue", target_lang
                            ),
                            callback_data=f"write_to_{sender_id}",
                        )
                    ]
                ]
            )
        else:
            # Optionally show a button to end dialogue even from notification
            kb_notify = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=l10n.format_value("button.stop_writing", target_lang),
                            callback_data="stop_writing",
                        )
                    ]
                ]
            )

        try:
            await bot.send_message(
                target_id,
                l10n.format_value(notify_key, target_lang, name=receiver_display_name),
                message_effect_id=effect_id,
                reply_markup=kb_notify,
            )
        except Exception:
            # Fallback if effects fail
            await bot.send_message(
                target_id,
                l10n.format_value(notify_key, target_lang, name=receiver_display_name),
                reply_markup=kb_notify,
            )

        # For polls we use send_poll to get the new poll_id and force non-anonymous to see votes
        # This is the only way to get poll_answer events
        try:
            sent_msg = await bot.send_poll(
                chat_id=target_id,
                question=message.poll.question,
                options=[o.text for o in message.poll.options],
                is_anonymous=False,
                type=message.poll.type,
                allows_multiple_answers=message.poll.allows_multiple_answers,
                correct_option_id=message.poll.correct_option_id,
                explanation=message.poll.explanation,
                explanation_entities=message.poll.explanation_entities,
                reply_to_message_id=reply_to_id,
            )
        except Exception:
            sent_msg = await bot.send_poll(
                chat_id=target_id,
                question=message.poll.question,
                options=[o.text for o in message.poll.options],
                is_anonymous=False,
                type=message.poll.type,
                allows_multiple_answers=message.poll.allows_multiple_answers,
                correct_option_id=message.poll.correct_option_id,
                explanation=message.poll.explanation,
                explanation_entities=message.poll.explanation_entities,
            )
        msg_id = sent_msg.message_id
        poll_id = sent_msg.poll.id
    elif album:
        try:
            target_state_ctx = FSMContext(
                storage=state.storage,
                key=StorageKey(bot_id=bot.id, chat_id=target_id, user_id=target_id),
            )
            target_data = await target_state_ctx.get_data()

            # If the receiver is currently in a dialogue with this sender and has their name
            if target_data.get("target_id") == sender_id and target_data.get(
                "target_name"
            ):
                receiver_display_name = target_data.get("target_name")
        except Exception:
            pass

        # Message effects
        effect_id = "5104841245755180586" if not reply_to_id else "5046509860445903448"

        # Determine if we show dialogue button
        is_target_in_dialogue = target_data.get("target_id") == sender_id

        # Start dialogue button for receiver (only if not already in dialogue)
        kb_notify = None
        if not is_target_in_dialogue:
            kb_notify = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=l10n.format_value(
                                "button.start_dialogue", target_lang
                            ),
                            callback_data=f"write_to_{sender_id}",
                        )
                    ]
                ]
            )
        else:
            kb_notify = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=l10n.format_value("button.stop_writing", target_lang),
                            callback_data="stop_writing",
                        )
                    ]
                ]
            )

        try:
            await bot.send_message(
                target_id,
                l10n.format_value(notify_key, target_lang, name=receiver_display_name),
                message_effect_id=effect_id,
                reply_markup=kb_notify,
            )
        except Exception:
            # Fallback if effects fail
            await bot.send_message(
                target_id,
                l10n.format_value(notify_key, target_lang, name=receiver_display_name),
                reply_markup=kb_notify,
            )

        from aiogram.utils.media_group import MediaGroupBuilder

        media_group = MediaGroupBuilder(caption=message.caption)
        for m in album:
            if m.photo:
                media_group.add_photo(media=m.photo[-1].file_id, has_spoiler=True)
            elif m.video:
                media_group.add_video(media=m.video.file_id, has_spoiler=True)
            elif m.audio:
                media_group.add_audio(media=m.audio.file_id)
            elif m.document:
                media_group.add_document(media=m.document.file_id)

        msgs = await bot.send_media_group(
            chat_id=target_id,
            media=media_group.build(),
            reply_to_message_id=reply_to_id,
        )
        msg_id = msgs[0].message_id
    else:
        # For other messages use copy_message or specific methods for spoilers
        try:
            sent_msg_info = None

            # Anonymization Logic & Preview Flow
            if sender_settings.get("anon_audio", 1) == 1 and (
                message.voice or message.video_note or message.video
            ):
                from services.voice_engine import process_user_media

                status_msg = await message.answer(
                    l10n.format_value("voicing_message", sender_lang)
                )
                try:
                    m_type = "voice"
                    if message.video_note:
                        m_type = "video_note"
                    elif message.video:
                        m_type = "video"

                    processed_media = await process_user_media(
                        bot, message, media_type=m_type
                    )

                    if processed_media:
                        # Setup Confirmation Keyboard
                        kb = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text=l10n.format_value(
                                            "button.confirm_send", sender_lang
                                        ),
                                        callback_data="confirm_media_send",
                                    ),
                                    InlineKeyboardButton(
                                        text=l10n.format_value(
                                            "button.confirm_cancel", sender_lang
                                        ),
                                        callback_data="confirm_media_cancel",
                                    ),
                                ],
                                [
                                    InlineKeyboardButton(
                                        text=l10n.format_value(
                                            "button.send_original", sender_lang
                                        ),
                                        callback_data="confirm_original_send",
                                    ),
                                ],
                            ]
                        )

                        # Save to state for confirmation handler
                        # Reuse common media confirmation state
                        await state.set_state(Form.confirming_media)
                        await state.update_data(
                            media_path=processed_media.path,
                            media_type=m_type,
                            target_id=target_id,
                            reply_to_id=reply_to_id,
                            anon_num=anon_num or display_name,
                            original_message_id=message.message_id,
                        )

                        # Send preview to SENDER
                        preview_text = l10n.format_value(
                            "your_voice_preview", sender_lang
                        )
                        if m_type == "video_note":
                            await bot.send_video_note(
                                chat_id=sender_id,
                                video_note=processed_media,
                                reply_markup=kb,
                            )
                        elif m_type == "video":
                            await bot.send_video(
                                chat_id=sender_id,
                                video=processed_media,
                                caption=preview_text,
                                reply_markup=kb,
                            )
                        else:
                            await bot.send_voice(
                                chat_id=sender_id,
                                voice=processed_media,
                                caption=preview_text,
                                reply_markup=kb,
                            )

                        # Let finally handle status_msg deletion
                        return  # STOP HERE, wait for confirmation callback

                except Exception as e:
                    logging.error(f"Anonymization error: {e}")
                finally:
                    if "status_msg" in locals():
                        try:
                            await status_msg.delete()
                        except Exception:
                            pass

            # Send notification ONLY if we didn't return (meaning we are sending now)
            # Receiver notification name
            receiver_display_name = display_name

            # REVEAL LOGIC: If the receiver (target_id) already knows the sender's identity via link
            try:
                target_state_ctx = FSMContext(
                    storage=state.storage,
                    key=StorageKey(bot_id=bot.id, chat_id=target_id, user_id=target_id),
                )
                target_data = await target_state_ctx.get_data()

                # If the receiver is currently in a dialogue with this sender and has their name
                if target_data.get("target_id") == sender_id and target_data.get(
                    "target_name"
                ):
                    receiver_display_name = target_data.get("target_name")
            except Exception:
                pass

            # Message effects
            effect_id = (
                "5104841245755180586" if not reply_to_id else "5046509860445903448"
            )

            # Determine if we show dialogue button
            is_target_in_dialogue = target_data.get("target_id") == sender_id

            # Start dialogue button for receiver (only if not already in dialogue)
            kb_notify = None
            if not is_target_in_dialogue:
                kb_notify = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=l10n.format_value(
                                    "button.start_dialogue", target_lang
                                ),
                                callback_data=f"write_to_{sender_id}",
                            )
                        ]
                    ]
                )
            else:
                kb_notify = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=l10n.format_value(
                                    "button.stop_writing", target_lang
                                ),
                                callback_data="stop_writing",
                            )
                        ]
                    ]
                )

            try:
                # If target is already in dialogue with sender, skip the "New message" text to reduce spam
                if is_target_in_dialogue:
                    notify_msg = None  # We won't send the "New message" header
                else:
                    notify_msg = await bot.send_message(
                        target_id,
                        l10n.format_value(
                            notify_key, target_lang, name=receiver_display_name
                        ),
                        message_effect_id=effect_id,
                        reply_markup=kb_notify,
                    )

                if notify_msg:
                    db.save_link(
                        notify_msg.message_id,
                        target_id,
                        sender_id,
                        message.message_id,
                        message.chat.id,
                        anon_num=anon_num,
                    )
            except Exception:
                # Fallback if effects fail (only if NOT in dialogue)
                if not is_target_in_dialogue:
                    notify_msg = await bot.send_message(
                        target_id,
                        l10n.format_value(
                            notify_key, target_lang, name=receiver_display_name
                        ),
                        reply_markup=kb_notify,
                    )
                    db.save_link(
                        notify_msg.message_id,
                        target_id,
                        sender_id,
                        message.message_id,
                        message.chat.id,
                        anon_num=anon_num,
                    )

            if sent_msg_info:
                pass
            elif message.photo:
                sent_msg_info = await bot.send_photo(
                    chat_id=target_id,
                    photo=message.photo[-1].file_id,
                    caption=message.caption,
                    caption_entities=message.caption_entities,
                    reply_to_message_id=reply_to_id,
                    has_spoiler=True,
                    reply_markup=None if is_target_in_dialogue else kb_notify,
                )
            elif message.video:
                sent_msg_info = await bot.send_video(
                    chat_id=target_id,
                    video=message.video.file_id,
                    caption=message.caption,
                    caption_entities=message.caption_entities,
                    reply_to_message_id=reply_to_id,
                    has_spoiler=True,
                    reply_markup=None if is_target_in_dialogue else kb_notify,
                )
            elif message.animation:
                sent_msg_info = await bot.send_animation(
                    chat_id=target_id,
                    animation=message.animation.file_id,
                    caption=message.caption,
                    caption_entities=message.caption_entities,
                    reply_to_message_id=reply_to_id,
                    has_spoiler=True,
                    reply_markup=None if is_target_in_dialogue else kb_notify,
                )
            else:
                if override_text:
                    sent_msg_info = await bot.send_message(
                        chat_id=target_id,
                        text=override_text,
                        reply_to_message_id=reply_to_id,
                        reply_markup=None if is_target_in_dialogue else kb_notify,
                    )
                else:
                    sent_msg_info = await bot.copy_message(
                        chat_id=target_id,
                        from_chat_id=message.chat.id,
                        message_id=message.message_id,
                        reply_to_message_id=reply_to_id,
                        reply_markup=None if is_target_in_dialogue else kb_notify,
                    )

                # Save link for the actual message too if it wasn't saved above
                if sent_msg_info and not is_target_in_dialogue:
                    db.save_link(
                        sent_msg_info.message_id,
                        target_id,
                        sender_id,
                        message.message_id,
                        message.chat.id,
                        anon_num=anon_num,
                    )
        except Exception:
            if override_text:
                sent_msg_info = await bot.send_message(
                    chat_id=target_id, text=override_text
                )
            else:
                sent_msg_info = await bot.copy_message(
                    chat_id=target_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
            if sent_msg_info:
                db.save_link(
                    sent_msg_info.message_id,
                    target_id,
                    sender_id,
                    message.message_id,
                    message.chat.id,
                    anon_num=anon_num,
                )

        msg_id = sent_msg_info.message_id

    # Save link for future interactions
    db.save_link(
        msg_id,
        target_id,
        sender_id,
        message.message_id,
        message.chat.id,
        anon_num=display_name,
        poll_id=poll_id,
    )

    # Confirmation to sender
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=l10n.format_value("button.stop_writing", sender_lang),
                    callback_data="stop_writing",
                )
            ]
        ]
    )

    # Logic for name display:
    data = await state.get_data()
    in_dialogue = data.get("target_id") == target_id
    saved_name = data.get("target_name")

    if in_dialogue and saved_name:
        target_name_to_show = saved_name
    else:
        target_name_to_show = display_name or "№???"

    if in_dialogue:
        reply_markup = kb  # "Stop writing"
    else:
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.start_dialogue", sender_lang),
                        callback_data=f"write_to_{target_id}",
                    ),
                    InlineKeyboardButton(
                        text=l10n.format_value("button.write_more", sender_lang),
                        callback_data=f"send_again_{target_id}",
                    ),
                ]
            ]
        )

    # Try to delete previous confirmation to avoid clutter
    await cleanup_previous_confirmation(message.chat.id, state, bot)

    # Clear reply_to_id after success to prevent it sticking in dialogue
    await state.update_data(reply_to_id=None)

    # If in active persistent dialogue, use a seamless reaction
    if in_dialogue:
        try:
            await message.react(reactions=[ReactionTypeEmoji(emoji="\u2705")])
            return  # Don't send a text message
        except Exception:
            pass  # Fallback to text if reactions fail

    sent_text = l10n.format_value("msg_sent_to", sender_lang, name=target_name_to_show)

    conf_msg = await message.answer(
        sent_text, reply_markup=reply_markup, parse_mode="HTML"
    )
    if in_dialogue:
        await state.update_data(
            last_conf_msg_id=conf_msg.message_id, last_conf_is_media=False
        )

    if in_dialogue:
        reply_markup = kb  # Stop writing
