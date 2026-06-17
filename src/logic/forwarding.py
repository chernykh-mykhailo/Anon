import os
import logging
from typing import List, Union
from aiogram import Bot, types
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReactionTypeEmoji,
    FSInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey

from database import db
from l10n import l10n
from utils import get_lang
from states import Form
from logic.ui import get_confirm_kb


async def handle_forwarding(
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
    media_path: str = None,
    media_type: str = None,
):
    """Centralized message forwarding logic with anonymity and settings enforcement."""
    target_lang = await get_lang(target_id, bot=bot)
    sender_lang = await get_lang(sender_id, bot=bot)

    # 1. Enforcement Checks
    target_settings = db.get_user_settings(target_id)
    if not target_settings.get("receive_messages", 1):
        return await message.answer(
            l10n.format_value("user_disabled_messages", sender_lang)
        )

    if db.is_blocked(target_id, sender_id):
        return await message.answer(l10n.format_value("msg_blocked", sender_lang))

    if check_cd:
        cd_seconds = int(db.get_global_config("message_cooldown", "0"))
        allowed, remain = db.check_and_reserve_cooldown(
            sender_id, target_id, cd_seconds
        )
        if not allowed:
            return await message.answer(
                l10n.format_value("error.cooldown", sender_lang, seconds=remain)
            )

    # 2. Anonymity Logic
    anon_display_name = anon_num or db.get_or_create_anon_num(target_id, sender_id)

    receiver_display_name = f"Anon {anon_display_name}"

    # sender_confirmation_name: What the SENDER sees in their confirmation message.
    # Can be the real name if they have it in their FSM.
    sender_user_display_name = anon_display_name

    is_target_in_dialogue = False
    try:
        target_state_ctx = FSMContext(
            storage=state.storage,
            key=StorageKey(bot_id=bot.id, chat_id=target_id, user_id=target_id),
        )
        target_data = await target_state_ctx.get_data()
        if target_data.get("target_id") == sender_id:
            is_target_in_dialogue = True

        # For the sender's confirmation, check their OWN state for a name
        sender_data = await state.get_data()
        if sender_data.get("target_id") == target_id and sender_data.get("target_name"):
            sender_user_display_name = sender_data.get("target_name")

    except Exception:
        pass
    # 3.5 Button Logic (DRY & clean UX)
    # We only show the Anon Identity and "Start Dialogue" button if the user is NOT in an active dialogue.
    # We attach it directly to the message to avoid "extra noise".
    msg_kb = None
    if not is_target_in_dialogue:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        msg_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"👤 {receiver_display_name}", callback_data="ignore_btn"
                    ),
                    InlineKeyboardButton(
                        text=l10n.format_value("button.start_dialogue", target_lang),
                        callback_data=f"write_to_{sender_id}",
                    ),
                ]
            ]
        )

    # CRITICAL SOLID/DRY FIX: Prevent Telegram from leaking the real name.
    # If the target is in a dialogue, they are "replying" to their own messages forwarded by the bot.
    # This causes Telegram to show their real name in the reply block.
    # By nullifying reply_to_id during an active dialogue, we send it as a fresh message in the stream.
    if is_target_in_dialogue:
        reply_to_id = None

    # 4. Content Forwarding
    sent_msg = None
    if media_path and media_type:
        sent_msg = await _send_local_media(
            bot,
            target_id,
            media_path,
            media_type,
            reply_to_id,
            target_lang,
            caption=message.caption or message.text,
            reply_markup=msg_kb,
        )
    elif album:
        from aiogram.utils.media_group import MediaGroupBuilder

        media_group = MediaGroupBuilder(caption=message.caption)
        for m in album:
            if m.photo:
                media_group.add_photo(media=m.photo[-1].file_id, has_spoiler=True)
            elif m.video:
                media_group.add_video(media=m.video.file_id, has_spoiler=True)
            elif m.document:
                media_group.add_document(media=m.document.file_id)

        try:
            msgs = await bot.send_media_group(
                chat_id=target_id,
                media=media_group.build(),
                reply_to_message_id=reply_to_id,
            )
            sent_msg = msgs[0]

            # Media groups don't support reply_markup, so we send a tiny action button if needed
            if msg_kb:
                action_msg = await bot.send_message(
                    target_id,
                    f"👆 👤 {receiver_display_name}",
                    reply_markup=msg_kb,
                    reply_to_message_id=sent_msg.message_id,
                )
                db.save_message_link(
                    action_msg.message_id,
                    target_id,
                    sender_id,
                    message.message_id,
                    message.chat.id,
                    anon_num=anon_display_name,
                )
        except Exception as e:
            logging.error(f"Media group forward error: {e}")
    else:
        # 4. Content Forwarding (Secure for Anonymity)
        try:
            if override_text:
                sent_msg = await bot.send_message(
                    target_id,
                    override_text,
                    reply_to_message_id=reply_to_id,
                    reply_markup=msg_kb,
                )
            elif message.photo:
                sent_msg = await bot.send_photo(
                    chat_id=target_id,
                    photo=message.photo[-1].file_id,
                    caption=message.caption,
                    reply_to_message_id=reply_to_id,
                    has_spoiler=True,
                    reply_markup=msg_kb,
                )
            elif message.video:
                sent_msg = await bot.send_video(
                    chat_id=target_id,
                    video=message.video.file_id,
                    caption=message.caption,
                    reply_to_message_id=reply_to_id,
                    has_spoiler=True,
                    reply_markup=msg_kb,
                )
            elif message.voice:
                sent_msg = await bot.send_voice(
                    chat_id=target_id,
                    voice=message.voice.file_id,
                    caption=message.caption,
                    reply_to_message_id=reply_to_id,
                    reply_markup=msg_kb,
                )
            else:
                sent_msg = await bot.copy_message(
                    chat_id=target_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                    reply_to_message_id=reply_to_id,
                    reply_markup=msg_kb,
                )
        except Exception as e:
            logging.error(f"Forwarding error: {e}")
            # Final fallback for text
            content = message.text or message.caption or "..."
            sent_msg = await bot.send_message(
                target_id, content, reply_to_message_id=reply_to_id, reply_markup=msg_kb
            )

    if not sent_msg:
        return await message.answer("❌ Error forwarding message.")

    db.save_message_link(
        sent_msg.message_id,
        target_id,
        sender_id,
        message.message_id,
        message.chat.id,
        anon_num=anon_display_name,
    )

    # No extra notification message (merged directly as inline keyboard on target message)

    # 5. Confirmation and State Update
    # Determine if the SENDER is in an active session to replace text with reaction
    sender_in_active_session = (await state.get_state()) == Form.writing_message

    await _send_sender_confirmation(
        message,
        target_id,
        state,
        bot,
        sender_lang,
        sender_in_active_session,
        sender_user_display_name,
    )

    # Update session timestamp on activity
    db.update_session(sender_id, target_id)


async def _send_local_media(
    bot: Bot,
    target_id: int,
    path: str,
    m_type: str,
    reply_to: int,
    lang: str,
    caption: str = None,
    reply_markup=None,
):
    """Handle sending of local files (synthesis/generation results)."""
    try:
        if m_type == "voice":
            return await bot.send_voice(
                target_id,
                FSInputFile(path),
                reply_to_message_id=reply_to,
                caption=caption,
                reply_markup=reply_markup,
            )
        elif m_type == "video_note":
            return await bot.send_video_note(
                target_id,
                FSInputFile(path),
                reply_to_message_id=reply_to,
                reply_markup=reply_markup,
            )
        elif m_type == "photo":
            return await bot.send_photo(
                target_id,
                FSInputFile(path),
                caption=caption or l10n.format_value("received_card_caption", lang),
                has_spoiler=True,
                reply_to_message_id=reply_to,
                reply_markup=reply_markup,
            )
    finally:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


async def _send_sender_confirmation(
    message: Message,
    target_id: int,
    state: FSMContext,
    bot: Bot,
    lang: str,
    in_dialogue: bool,
    display_name: str,
):
    data = await state.get_data()
    # If we have a saved name in FSM, use it for the sender's confirmation
    # display_name already contains the name or ID from handle_forwarding
    name_to_show = display_name or "№???"

    if in_dialogue:
        try:
            # Use ReactionTypeEmoji to be safe with types
            await message.react(reactions=[ReactionTypeEmoji(emoji="✅")])
            return
        except Exception as e:
            # Fallback for old clients or bot restriction
            pass

    sent_text = l10n.format_value("msg_sent_to", lang, name=name_to_show)
    kb = None

    # Don't show "Start Dialogue" if we are ALREADY writing to this person
    current_state = await state.get_state()
    is_already_writing = (current_state == Form.writing_message) and (
        data.get("target_id") == target_id
    )

    if not in_dialogue:
        buttons = []
        if not is_already_writing:
            buttons.append(
                InlineKeyboardButton(
                    text=l10n.format_value("button.start_dialogue", lang),
                    callback_data=f"write_to_{target_id}",
                )
            )

        buttons.append(
            InlineKeyboardButton(
                text=l10n.format_value("button.write_more", lang),
                callback_data=f"send_again_{target_id}",
            )
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[buttons])

    await message.answer(sent_text, reply_markup=kb, parse_mode="HTML")
