import os
import logging

from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from typing import Union, List
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
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
    reply_to_id = state_data.get("reply_to_id")
    anon_num = state_data.get("anon_num")

    # 1. Reply to an anonymous message (one-off forward priority)
    if message.reply_to_message:
        link = db.get_link_by_receiver(
            message.reply_to_message.message_id, message.chat.id
        )
        if link:
            reply_target_id, reply_to_id, _ = link

            # If it's a reply to someone ELSE than our active session, it's a one-off
            if reply_target_id != active_target_id:
                # We need a number even for one-off replies
                anon_num_oneoff = db.get_available_anon_num(
                    reply_target_id, message.from_user.id
                )
                return reply_target_id, reply_to_id, anon_num_oneoff

            # If it's a reply to the CURRENT active session, continue
            # (fall through to update state below)

    # 2. Update persistent session if active
    if active_target_id:
        if not anon_num:
            anon_num = db.get_available_anon_num(active_target_id, message.from_user.id)
        else:
            db.update_session(message.from_user.id, active_target_id)

        await state.update_data(
            target_id=active_target_id, reply_to_id=reply_to_id, anon_num=anon_num
        )
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

        # Start dialogue button for receiver
        kb_notify = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.start_dialogue", target_lang),
                        callback_data=f"write_to_{sender_id}",
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

        # Start dialogue button for receiver
        kb_notify = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.start_dialogue", target_lang),
                        callback_data=f"write_to_{sender_id}",
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

            # Start dialogue button for receiver
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

            try:
                notify_msg = await bot.send_message(
                    target_id,
                    l10n.format_value(
                        notify_key, target_lang, name=receiver_display_name
                    ),
                    message_effect_id=effect_id,
                    reply_markup=kb_notify,
                )
                db.save_link(
                    notify_msg.message_id,
                    target_id,
                    sender_id,
                    message.message_id,
                    message.chat.id,
                )
            except Exception:
                # Fallback if effects fail
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
                )
            elif message.video:
                sent_msg_info = await bot.send_video(
                    chat_id=target_id,
                    video=message.video.file_id,
                    caption=message.caption,
                    caption_entities=message.caption_entities,
                    reply_to_message_id=reply_to_id,
                    has_spoiler=True,
                )
            elif message.animation:
                sent_msg_info = await bot.send_animation(
                    chat_id=target_id,
                    animation=message.animation.file_id,
                    caption=message.caption,
                    caption_entities=message.caption_entities,
                    reply_to_message_id=reply_to_id,
                    has_spoiler=True,
                )
            else:
                if override_text:
                    sent_msg_info = await bot.send_message(
                        chat_id=target_id,
                        text=override_text,
                        reply_to_message_id=reply_to_id,
                    )
                else:
                    sent_msg_info = await bot.copy_message(
                        chat_id=target_id,
                        from_chat_id=message.chat.id,
                        message_id=message.message_id,
                        reply_to_message_id=reply_to_id,
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
        msg_id = sent_msg_info.message_id

    # Save link for future interactions
    db.save_link(
        msg_id,
        target_id,
        sender_id,
        message.message_id,
        message.chat.id,
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

    # Only show dialogue management
    data = await state.get_data()
    in_dialogue = data.get("target_id") == target_id

    if in_dialogue:
        reply_markup = kb
    else:
        # Even if not in dialogue, show a button to start it
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.write_more", sender_lang),
                        callback_data=f"write_to_{target_id}",
                    )
                ]
            ]
        )

    # Try to delete previous confirmation to avoid clutter
    await cleanup_previous_confirmation(message.chat.id, state, bot)

    # Logic for name display:
    # Use real name ONLY if we are in an active dialogue started via link with this exact target.
    # For one-off replies or anonymous dialogs, use №NNN.
    saved_name = data.get("target_name")
    if in_dialogue and saved_name:
        target_name_to_show = saved_name
    else:
        target_name_to_show = display_name or "№???"

    sent_text = l10n.format_value("msg_sent_to", sender_lang, name=target_name_to_show)

    conf_msg = await message.answer(
        sent_text, reply_markup=reply_markup, parse_mode="HTML"
    )
    if in_dialogue:
        await state.update_data(
            last_conf_msg_id=conf_msg.message_id, last_conf_is_media=False
        )


@router.message(Command("text"))
async def process_text_command(
    message: Message, state: FSMContext, bot: Bot, command: any = None
):
    lang = await get_lang(message.from_user.id, message)
    target_id, reply_to_id, anon_num = await get_target_and_remind(message, state, bot)

    if not target_id:
        return await message.answer(l10n.format_value("error.no_target", lang))

    # Get text to send
    if command and command.args:
        text = command.args
    else:
        cmd_parts = message.text.split(maxsplit=1)
        text = cmd_parts[1] if len(cmd_parts) > 1 else None

    if not text:
        return await message.answer(l10n.format_value("error.text_instruction", lang))

    await forward_anonymous_msg(
        bot,
        message,
        target_id,
        message.from_user.id,
        state,
        reply_to_id=reply_to_id,
        anon_num=anon_num,
        override_text=text,
    )


@router.message(Command("voice", "voice_m", "voice_f", "voice_j"))
async def process_voice_command(
    message: Message,
    state: FSMContext,
    bot: Bot,
    command: any = None,
    check_cd: bool = True,
):
    lang = await get_lang(message.from_user.id, message)

    target_id, reply_to_id, anon_num = await get_target_and_remind(message, state, bot)

    if not target_id:
        return await message.answer(l10n.format_value("error.no_target", lang))

    # CHECK SETTINGS
    target_settings = db.get_user_settings(target_id)
    if not target_settings["receive_messages"]:
        return await message.answer(l10n.format_value("user_disabled_messages", lang))
    if not target_settings["receive_media"]:
        return await message.answer(l10n.format_value("user_disabled_media", lang))

    # Get text to voice
    if command and command.args:
        text = command.args
    else:
        cmd_parts = message.text.split(maxsplit=1)
        text = cmd_parts[1] if len(cmd_parts) > 1 else None

    # Get user settings for default voice character
    user_settings = db.get_user_settings(message.from_user.id)
    default_gender = user_settings.get("voice_gender", "rnd")

    # Simplified logic: always use user's selected gender (defaulting to rnd)
    gender = default_gender

    if not text:
        if message.reply_to_message:
            text = message.reply_to_message.text or message.reply_to_message.caption
        if not text:
            return await message.answer(l10n.format_value("error.no_text_voice", lang))

    status_msg = await message.answer(
        l10n.format_value("voicing_message", lang), parse_mode="HTML"
    )

    try:
        # Generate voice (Synthesized voices don't need pitch-shifting, so always False)
        anonymize = False
        voice_input = await text_to_voice(text, gender, anonymize)

        # Save to state for confirmation
        await state.update_data(
            target_id=target_id,
            reply_to_id=reply_to_id,
            media_path=voice_input.path,
            media_type="voice",
            gender=gender,
            prompt=text,  # For voice it's the text
            anon_num=anon_num,
        )
        await state.set_state(Form.confirming_media)

        if user_settings.get("skip_confirm_voice"):
            from handlers.callbacks import confirm_media_send

            # Try to get target name for personalized confirmation
            try:
                target_chat = await bot.get_chat(target_id)
                target_name = target_chat.first_name
                sent_text = l10n.format_value("msg_sent_to", lang, name=target_name)
            except Exception:
                sent_text = l10n.format_value("msg_sent", lang)

            # Check CD before sending preview/confirmation
            cd_seconds = int(db.get_global_config("message_cooldown", DEFAULT_COOLDOWN))
            allowed, remain = db.check_and_reserve_cooldown(
                message.from_user.id, target_id, cd_seconds
            )
            if not allowed:
                await status_msg.delete()
                return await message.answer(
                    l10n.format_value("error.cooldown", lang, seconds=remain)
                )

            # Send the voice to the sender as a confirmation/preview
            sent_voice = await message.answer_voice(
                voice=FSInputFile(voice_input.path),
                caption=sent_text,
                parse_mode="HTML",
            )
            # We save it with media flag to remove button later
            await state.update_data(
                last_conf_msg_id=sent_voice.message_id, last_conf_is_media=True
            )
            await status_msg.delete()

            class MockCallback:
                def __init__(self, message, user):
                    self.message = message
                    self.from_user = user

                async def answer(self, text=None, show_alert=False):
                    if text and show_alert:
                        await self.message.answer(text)

            await confirm_media_send(
                MockCallback(sent_voice, message.from_user),
                state,
                bot,
                check_cd=False,
            )
            return

        # Show preview to sender
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.confirm_send", lang),
                        callback_data="confirm_media_send",
                    ),
                    InlineKeyboardButton(
                        text=l10n.format_value("button.confirm_cancel", lang),
                        callback_data="confirm_media_cancel",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.confirm_regenerate", lang),
                        callback_data="confirm_media_regen",
                    )
                ],
            ]
        )

        preview_msg = await bot.send_voice(
            chat_id=message.from_user.id,
            voice=FSInputFile(voice_input.path),
            caption=l10n.format_value("your_voice_preview", lang),
            reply_markup=kb,
        )

        await status_msg.delete()
        await state.update_data(preview_msg_id=preview_msg.message_id)

    except Exception as e:
        print(f"Error in TTS: {e}")
        await status_msg.edit_text(l10n.format_value("error.error_voice", lang))


@router.message(Command("pic"))
async def process_pic_command(message: Message, state: FSMContext, bot: Bot):
    """Handler for /pic command (random templates)."""
    lang = db.get_user_lang(message.from_user.id)
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            l10n.format_value("error.pic_instruction", lang), parse_mode="HTML"
        )
        return

    prompt = parts[1]
    target_id, _, _ = await get_target_and_remind(message, state, bot)

    if not target_id:
        return await message.answer(l10n.format_value("error.no_target", lang))

    # Check privacy

    # Check privacy
    target_settings = db.get_user_settings(target_id)
    if not target_settings.get("media", True):
        await message.answer(l10n.format_value("user_disabled_media", lang))
        return

    wait_msg = await message.answer(l10n.format_value("generating_image", lang))

    try:
        # Use random template
        file_path = await generate_image_input(prompt)

        await bot.delete_message(message.chat.id, wait_msg.message_id)

        await state.update_data(
            target_id=target_id,
            media_path=file_path,
            media_type="pic",
            prompt=prompt,
        )
        await state.set_state(Form.confirming_media)

        # CHECK QUICK SEND SETTING
        user_settings = db.get_user_settings(message.from_user.id)
        if user_settings.get("skip_confirm_media"):
            from handlers.callbacks import confirm_media_send

            # Check CD before sending preview/confirmation
            cd_seconds = int(db.get_global_config("message_cooldown", DEFAULT_COOLDOWN))
            allowed, remain = db.check_and_reserve_cooldown(
                message.from_user.id, target_id, cd_seconds
            )
            if not allowed:
                # Clean up correct wait msg
                await bot.delete_message(message.chat.id, wait_msg.message_id)
                return await message.answer(
                    l10n.format_value("error.cooldown", lang, seconds=remain)
                )

            # Send the photo to the sender as a confirmation/preview
            sent_pic = await message.answer_photo(
                photo=FSInputFile(file_path),
                caption=l10n.format_value("msg_sent", lang),
            )

            class MockCallback:
                def __init__(self, message, user):
                    self.message = message
                    self.from_user = user

                async def answer(self, text=None, show_alert=False):
                    if text and show_alert:
                        await self.message.answer(text)

            await confirm_media_send(
                MockCallback(sent_pic, message.from_user),
                state,
                bot,
                check_cd=False,
            )
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.confirm_send", lang),
                        callback_data="confirm_media_send",
                    ),
                    InlineKeyboardButton(
                        text=l10n.format_value("button.confirm_cancel", lang),
                        callback_data="confirm_media_cancel",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.confirm_regenerate", lang),
                        callback_data="confirm_media_regen",
                    )
                ],
            ]
        )

        await bot.send_photo(
            chat_id=message.from_user.id,
            photo=FSInputFile(file_path),
            caption=l10n.format_value("your_image_preview", lang),
            reply_markup=kb,
        )

    except Exception as e:
        print(f"Error in /pic: {e}")
        await message.answer(l10n.format_value("error.error_pic", lang))


@router.message(Command("draw"))
async def process_draw_command(message: Message, state: FSMContext, bot: Bot):
    """Handler for /draw command (Draw 2.0)."""
    lang = db.get_user_lang(message.from_user.id)
    target_id, _, _ = await get_target_and_remind(message, state, bot)

    if not target_id:
        return await message.answer(l10n.format_value("error.no_target", lang))

    # Check privacy

    # Check privacy
    target_settings = db.get_user_settings(target_id)
    if not target_settings.get("media", True):
        await message.answer(l10n.format_value("user_disabled_media", lang))
        return

    text = None
    photo_file_id = None

    # Case 1: Reply to photo
    # Setup temp dir
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    temp_dir = os.path.join(base_dir, "temp")
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    if message.reply_to_message and message.reply_to_message.photo:
        photo_file_id = message.reply_to_message.photo[-1].file_id
        parts = message.text.split(maxsplit=1) if message.text else []
        if len(parts) > 1:
            text = parts[1]

    # Case 2: Photo with caption
    elif message.photo:
        photo_file_id = message.photo[-1].file_id
        if message.caption:
            parts = message.caption.split(maxsplit=1)
            if parts[0].lower().startswith("/draw"):
                text = parts[1] if len(parts) > 1 else None
            else:
                text = message.caption

    # Case 3: Command with text only
    else:
        parts = message.text.split(maxsplit=1) if message.text else []
        if len(parts) > 1:
            text = parts[1]

    if not text:
        await message.answer(l10n.format_value("error.draw_no_text", lang))
        return

    # Generate image
    await message.answer(l10n.format_value("drawing_wait", lang))

    custom_bg_path = None
    if photo_file_id:
        custom_bg_path = os.path.join(temp_dir, f"draw_bg_{message.from_user.id}.jpg")
        await bot.download(photo_file_id, destination=custom_bg_path)

    # Initial settings
    draw_settings = {
        "text": text,
        "custom_bg_path": custom_bg_path,
        "y_position": "center",
        "text_color": "white",
        "use_bg": True,
        "target_id": target_id,
    }

    await state.update_data(draw_settings=draw_settings)
    await state.set_state(Form.customizing_draw)
    await show_draw_customization(message, state, bot, lang, is_new=True)


async def show_draw_customization(
    message: Union[Message, types.CallbackQuery],
    state: FSMContext,
    bot: Bot,
    lang: str,
    is_new: bool = False,
):
    user_id = (
        message.from_user.id if isinstance(message, Message) else message.from_user.id
    )
    data = await state.get_data()
    s = data["draw_settings"]

    # Show status
    status_text = (
        l10n.format_value("generating_image", lang)
        if is_new
        else l10n.format_value("editing", lang)
    )

    if not is_new and isinstance(message, types.CallbackQuery):
        await message.answer(status_text)
    else:
        wait_msg = await bot.send_message(user_id, status_text)

    try:
        file_path = await generate_image_input(
            text=s["text"],
            custom_bg_path=s["custom_bg_path"],
            y_position=s["y_position"],
            text_color_input=s["text_color"],
            use_bg=s["use_bg"],
        )

        # CHECK QUICK SEND SETTING
        user_settings = db.get_user_settings(message.from_user.id)
        if user_settings.get("skip_confirm_media"):
            # Check CD before sending preview/confirmation
            cd_seconds = int(db.get_global_config("message_cooldown", DEFAULT_COOLDOWN))
            allowed, remain = db.check_and_reserve_cooldown(
                user_id, s["target_id"], cd_seconds
            )
            if not allowed:
                # Cleanup
                if "menu_msg_id" in data:
                    try:
                        await bot.delete_message(user_id, data["menu_msg_id"])
                    except Exception:
                        pass
                elif "wait_msg" in locals():  # In case wait_msg is still around
                    try:
                        await bot.delete_message(
                            user_id, wait_msg.message_id
                        )  # wait_msg from caller? But this is inside show_draw...
                        # Actually show_draw_customization defines wait_msg locally or answers callback
                    except Exception:
                        pass

                return await bot.send_message(
                    user_id, l10n.format_value("error.cooldown", lang, seconds=remain)
                )

            # Send as sent
            from handlers.callbacks import confirm_media_send

            # We need to construct a message to act as "sent_pic"
            # Since generate_image_input returns path...
            # But wait, show_draw_customization uses "file_path" local var.

            sent_pic = await bot.send_photo(
                chat_id=user_id,
                photo=FSInputFile(file_path),
                caption=l10n.format_value("msg_sent", lang),
            )

            # Cleanup menu
            if is_new:
                await bot.delete_message(user_id, wait_msg.message_id)
            else:
                await message.delete()  # Delete old menu if editing

            class MockCallback:
                def __init__(self, message, user):
                    self.message = message
                    self.from_user = user

                async def answer(self, text=None, show_alert=False):
                    if text and show_alert:
                        await self.message.answer(text)

            await state.update_data(
                target_id=s["target_id"],
                media_path=file_path,
                media_type="pic",  # treat as pic for sending
            )

            await confirm_media_send(
                MockCallback(sent_pic, message.from_user),
                state,
                bot,
                check_cd=False,
            )
            return

        kb = get_draw_kb(s, lang)

        # Cleanup old preview if exists
        old_path = data.get("current_preview_path")
        if old_path:
            cleanup_image(old_path)

        if is_new:
            await bot.delete_message(user_id, wait_msg.message_id)
            sent_msg = await bot.send_photo(
                chat_id=user_id,
                photo=FSInputFile(file_path),
                caption=l10n.format_value("draw_menu", lang),
                reply_markup=kb,
                parse_mode="HTML",
            )
            await state.update_data(menu_msg_id=sent_msg.message_id)
        else:
            # Edit existing
            menu_msg_id = data.get("menu_msg_id")
            if menu_msg_id:
                try:
                    await bot.edit_message_media(
                        chat_id=user_id,
                        message_id=menu_msg_id,
                        media=types.InputMediaPhoto(
                            media=FSInputFile(file_path),
                            caption=l10n.format_value("draw_menu", lang),
                            parse_mode="HTML",
                        ),
                        reply_markup=kb,
                    )
                except Exception as ex:
                    print(f"Failed to edit: {ex}")
                    # Fallback to new message
                    sent_msg = await bot.send_photo(
                        chat_id=user_id,
                        photo=FSInputFile(file_path),
                        caption=l10n.format_value("draw_menu", lang),
                        reply_markup=kb,
                        parse_mode="HTML",
                    )
                    await state.update_data(menu_msg_id=sent_msg.message_id)

        await state.update_data(current_preview_path=file_path)

    except Exception as e:
        print(f"Error in show_draw_customization: {e}")
        await bot.send_message(user_id, l10n.format_value("error.error_pic", lang))


def get_draw_kb(s: dict, lang: str) -> InlineKeyboardMarkup:
    # Position buttons
    pos_text = {
        "top": l10n.format_value("button.draw_pos_top", lang),
        "center": l10n.format_value("button.draw_pos_center", lang),
        "bottom": l10n.format_value("button.draw_pos_bottom", lang),
    }

    # Color buttons
    color_text = {
        "white": l10n.format_value("button.draw_color_white", lang),
        "black": l10n.format_value("button.draw_color_black", lang),
    }

    # BG button
    bg_text = (
        l10n.format_value("button.draw_bg_on", lang)
        if s["use_bg"]
        else l10n.format_value("button.draw_bg_off", lang)
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=pos_text["top"], callback_data="draw_pos_top"
                ),
                InlineKeyboardButton(
                    text=pos_text["center"], callback_data="draw_pos_center"
                ),
                InlineKeyboardButton(
                    text=pos_text["bottom"], callback_data="draw_pos_bottom"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=color_text["white"], callback_data="draw_color_white"
                ),
                InlineKeyboardButton(
                    text=color_text["black"], callback_data="draw_color_black"
                ),
            ],
            [InlineKeyboardButton(text=bg_text, callback_data="draw_toggle_bg")],
            [
                InlineKeyboardButton(
                    text=l10n.format_value("button.draw_apply", lang),
                    callback_data="draw_apply",
                )
            ],
        ]
    )
    return kb


@router.message(F.reply_to_message)
async def process_reply(
    message: Message, bot: Bot, state: FSMContext, album: List[Message] = None
):
    # This will sync target from reply
    target_id, reply_to_id, anon_num = await get_target_and_remind(message, state, bot)

    if target_id:
        await forward_anonymous_msg(
            bot,
            message,
            target_id,
            message.from_user.id,
            state,
            reply_to_id=reply_to_id,
            album=album,
            anon_num=anon_num,
            check_cd=True,
        )
    else:
        # Not a known anonymous link
        pass


@router.message(Form.writing_message)
async def process_anonymous_message(
    message: Message,
    state: FSMContext,
    bot: Bot,
    album: List[Message] = None,
    target_id: int = None,
    reply_to_id: int = None,
    anon_num: str = None,
):
    if (
        not album
        and message.text
        and message.text.startswith("/")
        and not message.text.startswith("/text")
    ):
        await state.clear()
        return

    # If not already provided (e.g. from process_unknown), find it
    if not target_id:
        target_id, r_to_id, a_num = await get_target_and_remind(message, state, bot)
        reply_to_id = reply_to_id or r_to_id
        anon_num = anon_num or a_num

    if target_id:
        # Check for Auto-Voice setting
        user_settings = db.get_user_settings(message.from_user.id)
        if not album and message.text and user_settings.get("auto_voice"):
            # Trigger voice command logic
            from aiogram.filters import CommandObject

            # Create a fake CommandObject
            cmd_obj = CommandObject(prefix="/", command="voice", args=message.text)
            return await process_voice_command(
                message, state, bot, cmd_obj, check_cd=True
            )

        await forward_anonymous_msg(
            bot,
            message,
            target_id,
            message.from_user.id,
            state,
            reply_to_id=reply_to_id,
            anon_num=anon_num,
            album=album,
            check_cd=True,
        )


@router.message(Form.setting_cooldown)
async def process_setting_cooldown(message: Message, state: FSMContext):
    from config import ADMIN_ID

    if str(message.from_user.id) != str(ADMIN_ID):
        await state.clear()
        return

    lang = await get_lang(message.from_user.id, message)
    text = message.text.strip()

    if text.isdigit():
        new_cd = int(text)
        db.set_global_config("message_cooldown", new_cd)
        await message.answer(
            l10n.format_value("admin.cooldown_set", lang, seconds=new_cd)
        )
        await state.clear()
    else:
        await message.answer("Будь ласка, введіть число (секунди):")


@router.message()
async def process_unknown(message: Message, state: FSMContext):
    # Only answer if it's not a reply (replies are handled above)
    # AND only in PRIVATE chats to avoid spamming groups
    if not message.reply_to_message and message.chat.type == "private":
        target_id, reply_to_id, anon_num = await get_target_and_remind(
            message, state, message.bot
        )
        if target_id:
            # We have a target! Process it as an anonymous message
            return await process_anonymous_message(
                message,
                state,
                message.bot,
                target_id=target_id,
                reply_to_id=reply_to_id,
                anon_num=anon_num,
            )

        lang = await get_lang(message.from_user.id, message)
        await message.answer(l10n.format_value("error.unknown_action", lang))
