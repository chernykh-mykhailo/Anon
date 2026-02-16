from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.fsm.context import FSMContext
import random

from l10n import l10n
from database import db
from states import Form
from utils import get_lang
from voice_engine import text_to_voice
from image_engine import generate_image_input

router = Router()


@router.poll_answer()
async def process_poll_answer(poll_answer: types.PollAnswer, bot: Bot):
    # Find who sent this poll
    link = db.get_link_by_poll(poll_answer.poll_id)
    if link:
        sender_id, original_msg_id, _ = link
        # Find which option was selected
        # poll_answer.option_ids is a list of selected indices
        # We can't easily get the text of the option without storing it,
        # so we just notify the sender that someone voted.
        lang = await get_lang(sender_id)

        # Prepare option numbers (indices + 1)
        options_str = ", ".join(str(o + 1) for o in poll_answer.option_ids)

        try:
            await bot.send_message(
                sender_id,
                l10n.format_value("poll_voted", lang, options=options_str),
                reply_to_message_id=original_msg_id,
            )
        except Exception as e:
            print(f"Error notifying about vote: {e}")


async def forward_anonymous_msg(
    bot: Bot, message: Message, target_id: int, sender_id: int, reply_to_id: int = None
):
    target_lang = await get_lang(target_id)
    sender_lang = await get_lang(sender_id)

    # CHECK SETTINGS
    target_settings = db.get_user_settings(target_id)
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
            message.poll,  # Polls aren't strictly media but usually go under the same restriction or handled separately
        ]
    )

    if is_media and not target_settings["receive_media"]:
        return await message.answer(
            l10n.format_value("user_disabled_media", sender_lang)
        )

    # CHECK BLOCKS
    if db.is_blocked(target_id, sender_id):
        return await message.answer(l10n.format_value("msg_blocked", sender_lang))

    # Notify about new message or reply
    notify_key = "reply_received" if reply_to_id else "new_anonymous_msg"

    # Message effects (Premium-like animations)
    # 5159385139981059251 - Heart, 5104841245755180586 - Fire, 5046509860445903448 - Party
    effect_id = "5104841245755180586" if not reply_to_id else "5046509860445903448"

    try:
        await bot.send_message(
            target_id,
            l10n.format_value(notify_key, target_lang),
            message_effect_id=effect_id,
        )
    except Exception:
        # Fallback if effects are invalid or not supported
        await bot.send_message(target_id, l10n.format_value(notify_key, target_lang))

    # Copy message with native reply
    poll_id = None
    if message.poll:
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
    else:
        # For other messages use copy_message or specific methods for spoilers
        try:
            if message.photo:
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
                sent_msg_info = await bot.copy_message(
                    chat_id=target_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                    reply_to_message_id=reply_to_id,
                )
        except Exception:
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
                    text=l10n.format_value("button.send_again", sender_lang),
                    callback_data=f"write_to_{target_id}",
                )
            ]
        ]
    )
    await message.answer(l10n.format_value("msg_sent", sender_lang), reply_markup=kb)


@router.message(Command("voice", "voice_m", "voice_f", "voice_j"))
async def process_voice_command(message: Message, bot: Bot, state: FSMContext):
    lang = await get_lang(message.from_user.id, message)

    # Determine target and sender
    target_id = None
    reply_to_id = None

    # Check if we are in writing_message state
    state_curr = await state.get_state()
    if state_curr == Form.writing_message:
        data = await state.get_data()
        target_id = data.get("target_id")
    # Check if it's a reply
    elif message.reply_to_message:
        link = db.get_link_by_receiver(
            message.reply_to_message.message_id, message.chat.id
        )
        if link:
            target_id, reply_to_id, _ = link

    if not target_id:
        return await message.answer(l10n.format_value("error.no_target", lang))

    # CHECK SETTINGS
    target_settings = db.get_user_settings(target_id)
    if not target_settings["receive_messages"]:
        return await message.answer(l10n.format_value("user_disabled_messages", lang))
    if not target_settings["receive_media"]:
        return await message.answer(l10n.format_value("user_disabled_media", lang))

    # Get text to voice
    # 1. Text after command
    cmd_parts = message.text.split(maxsplit=1)
    text = cmd_parts[1] if len(cmd_parts) > 1 else None

    # 2. If no text after command, use text from replied message (if exists)
    if not text and message.reply_to_message:
        text = message.reply_to_message.text or message.reply_to_message.caption

    if not text:
        return await message.answer(l10n.format_value("error.no_text_voice", lang))

    # Determine gender/preset
    gender = "m"
    if message.text.startswith("/voice_f"):
        gender = "f"
    elif message.text.startswith("/voice_m"):
        gender = "m"
    elif message.text.startswith("/voice_j"):
        gender = "j"
    else:
        gender = random.choice(["m", "f", "j"])

    status_msg = await message.answer(
        l10n.format_value("voicing_message", lang), parse_mode="HTML"
    )

    try:
        # Generate voice
        voice_input = await text_to_voice(text, gender)

        # Save to state for confirmation
        await state.update_data(
            target_id=target_id,
            reply_to_id=reply_to_id,
            media_path=voice_input.path,
            media_type="voice",
            gender=gender,
            prompt=text,  # For voice it's the text
        )
        await state.set_state(Form.confirming_media)

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


@router.message(Command("draw"))
async def process_draw_command(message: Message, bot: Bot, state: FSMContext):
    lang = await get_lang(message.from_user.id, message)
    target_id = None

    state_curr = await state.get_state()
    if state_curr == Form.writing_message:
        data = await state.get_data()
        target_id = data.get("target_id")
    elif message.reply_to_message:
        link = db.get_link_by_receiver(
            message.reply_to_message.message_id, message.chat.id
        )
        if link:
            target_id, _, _ = link

    if not target_id:
        return await message.answer(l10n.format_value("error.no_target", lang))

    # CHECK SETTINGS
    target_settings = db.get_user_settings(target_id)
    if not target_settings["receive_messages"]:
        return await message.answer(l10n.format_value("user_disabled_messages", lang))
    if not target_settings["receive_media"]:
        return await message.answer(l10n.format_value("user_disabled_media", lang))

    cmd_parts = message.text.split(maxsplit=1)
    prompt = cmd_parts[1] if len(cmd_parts) > 1 else None

    if not prompt:
        return await message.answer(
            l10n.format_value("error.draw_instruction", lang),
            parse_mode="HTML",
        )

    status_msg = await message.answer(l10n.format_value("generating_image", lang))

    try:
        file_path = await generate_image_input(prompt)

        # Save to state for confirmation
        await state.update_data(
            target_id=target_id, media_path=file_path, media_type="draw", prompt=prompt
        )
        await state.set_state(Form.confirming_media)

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

        preview_msg = await bot.send_photo(
            chat_id=message.from_user.id,
            photo=FSInputFile(file_path),
            caption=l10n.format_value("your_image_preview", lang),
            reply_markup=kb,
        )

        await status_msg.delete()
        await state.update_data(preview_msg_id=preview_msg.message_id)

    except Exception as e:
        print(f"Error in Draw: {e}")
        error_text = (
            f"{l10n.format_value('error.error_draw', lang)}\n\n<code>{str(e)}</code>"
        )
        await status_msg.edit_text(error_text, parse_mode="HTML")


@router.message(Form.writing_message)
async def process_anonymous_message(message: Message, state: FSMContext, bot: Bot):
    if message.text and message.text.startswith("/"):
        await state.clear()
        return
    data = await state.get_data()
    target_id = data.get("target_id")
    if target_id:
        await forward_anonymous_msg(bot, message, target_id, message.from_user.id)
        await state.clear()


@router.message(F.reply_to_message)
async def process_reply(message: Message, bot: Bot):
    # Skip if it's a command (handled in commands.py)
    if message.text and message.text.startswith("/"):
        return

    link = db.get_link_by_receiver(message.reply_to_message.message_id, message.chat.id)

    if link:
        original_sender_id, original_msg_id, _ = link
        await forward_anonymous_msg(
            bot,
            message,
            original_sender_id,
            message.from_user.id,
            reply_to_id=original_msg_id,
        )
    else:
        # Not a known anonymous link
        pass


@router.message()
async def process_unknown(message: Message):
    # Only answer if it's not a reply (replies are handled above)
    # AND only in PRIVATE chats to avoid spamming groups
    if not message.reply_to_message and message.chat.type == "private":
        lang = await get_lang(message.from_user.id, message)
        await message.answer(l10n.format_value("error.unknown_action", lang))
