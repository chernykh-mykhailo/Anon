import os
import random
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

from l10n import l10n
from database import db
from states import Form
from utils import get_lang
from voice_engine import text_to_voice
from image_engine import generate_image_input, cleanup_image

router = Router()


async def get_target_and_remind(message: Message, state: FSMContext, bot: Bot):
    """
    Finds target for the user. Logic: State -> Reply.
    No longer falls back to DB to avoid "sticky" dialogues after /cancel.
    """
    state_data = await state.get_data()
    target_id = state_data.get("target_id")
    reply_to_id = state_data.get("reply_to_id")
    anon_num = state_data.get("anon_num")

    # 1. Reply to an anonymous message (highest priority for context change)
    if message.reply_to_message:
        link = db.get_link_by_receiver(
            message.reply_to_message.message_id, message.chat.id
        )
        if link:
            new_target_id, new_reply_to_id, _ = link
            # Reset anon_num if target changed (new session with another person)
            if new_target_id != target_id:
                target_id = new_target_id
                reply_to_id = new_reply_to_id
                anon_num = None

    # 2. Update state if we have a target to keep session alive
    if target_id:
        if not anon_num:
            anon_num = db.get_available_anon_num(target_id, message.from_user.id)
        else:
            # Keep existing session alive in DB
            db.update_session(message.from_user.id, target_id)

        await state.update_data(
            target_id=target_id, reply_to_id=reply_to_id, anon_num=anon_num
        )
        await state.set_state(Form.writing_message)

    return target_id, reply_to_id


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
    album: List[Message] = None,
):
    target_lang = await get_lang(target_id, bot=bot)
    sender_lang = await get_lang(sender_id, bot=bot)

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
    data = await state.get_data()
    anon_num = data.get("anon_num") or "№???"

    # Message effects (Premium-like animations)
    # 5159385139981059251 - Heart, 5104841245755180586 - Fire, 5046509860445903448 - Party
    effect_id = "5104841245755180586" if not reply_to_id else "5046509860445903448"

    try:
        await bot.send_message(
            target_id,
            l10n.format_value(notify_key, target_lang, name=anon_num),
            message_effect_id=effect_id,
        )
    except Exception:
        # Fallback if effects are invalid or not supported
        await bot.send_message(
            target_id,
            l10n.format_value(notify_key, target_lang, name=anon_num),
        )

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
    elif album:
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
                    text=l10n.format_value("button.stop_writing", sender_lang),
                    callback_data="stop_writing",
                )
            ]
        ]
    )

    # Try to delete previous confirmation to avoid clutter
    await cleanup_previous_confirmation(message.chat.id, state, bot)

    # Try to get target name for personalized confirmation
    try:
        target_chat = await bot.get_chat(target_id)
        target_name = target_chat.first_name
        sent_text = l10n.format_value("msg_sent_to", sender_lang, name=target_name)
    except Exception:
        sent_text = l10n.format_value("msg_sent", sender_lang)

    conf_msg = await message.answer(sent_text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(
        last_conf_msg_id=conf_msg.message_id, last_conf_is_media=False
    )


@router.message(Command("text"))
async def process_text_command(
    message: Message, state: FSMContext, bot: Bot, command: any = None
):
    lang = await get_lang(message.from_user.id, message)
    target_id, reply_to_id = await get_target_and_remind(message, state, bot)

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

    # Forward as text (ignoring auto-voice)
    # We temporarily mock the message text to the extracted text for forward_anonymous_msg
    orig_text = message.text
    message.text = text

    await forward_anonymous_msg(
        bot, message, target_id, message.from_user.id, state, reply_to_id=reply_to_id
    )

    # Restore original text just in case
    message.text = orig_text


@router.message(Command("voice", "voice_m", "voice_f", "voice_j"))
async def process_voice_command(
    message: Message, state: FSMContext, bot: Bot, command: any = None
):
    lang = await get_lang(message.from_user.id, message)

    target_id, reply_to_id = await get_target_and_remind(message, state, bot)

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
    default_gender = user_settings.get("voice_gender", "m")

    # Command determines gender: /voice uses default/random, /voice_m explicitly male, etc.
    bot_info = await bot.get_me()
    cmd = (
        message.text.split()[0]
        .replace("/", "")
        .lower()
        .replace(f"@{bot_info.username.lower()}", "")
    )

    gender_map = {"voice_m": "m", "voice_f": "f", "voice_j": "j"}
    gender = gender_map.get(cmd, default_gender)

    if gender == "r":
        gender = random.choice(["m", "f", "j"])

    if not text:
        if message.reply_to_message:
            text = message.reply_to_message.text or message.reply_to_message.caption
        if not text:
            return await message.answer(l10n.format_value("error.no_text_voice", lang))

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

        if user_settings.get("skip_confirm_voice"):
            from handlers.callbacks import confirm_media_send

            # Try to delete previous confirmation to avoid clutter
            data = await state.get_data()
            prev_conf_id = data.get("last_conf_msg_id")
            if prev_conf_id:
                try:
                    await bot.delete_message(message.chat.id, prev_conf_id)
                except Exception:
                    pass

            # Try to get target name for personalized confirmation
            try:
                target_chat = await bot.get_chat(target_id)
                target_name = target_chat.first_name
                sent_text = l10n.format_value("msg_sent_to", lang, name=target_name)
            except Exception:
                sent_text = l10n.format_value("msg_sent", lang)

            # Try to delete previous text confirmation to avoid clutter
            await cleanup_previous_confirmation(message.chat.id, state, bot)

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

                async def answer(self, *args, **kwargs):
                    pass

            await confirm_media_send(
                MockCallback(sent_voice, message.from_user), state, bot
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
    target_id, _ = await get_target_and_remind(message, state, bot)

    if not target_id:
        await message.answer(l10n.format_value("error.no_target", lang))
        return

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

            # Send the photo to the sender as a confirmation/preview
            sent_pic = await message.answer_photo(
                photo=FSInputFile(file_path),
                caption=l10n.format_value("msg_sent", lang),
            )
            await wait_msg.delete()

            class MockCallback:
                def __init__(self, message, user):
                    self.message = message
                    self.from_user = user

                async def answer(self, *args, **kwargs):
                    pass

            await confirm_media_send(
                MockCallback(sent_pic, message.from_user), state, bot
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
    target_id, _ = await get_target_and_remind(message, state, bot)

    if not target_id:
        await message.answer(l10n.format_value("error.no_target", lang))
        return

    # Check privacy
    target_settings = db.get_user_settings(target_id)
    if not target_settings.get("media", True):
        await message.answer(l10n.format_value("user_disabled_media", lang))
        return

    text = None
    photo_file_id = None

    # Case 1: Reply to photo
    # Setup temp dir
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


@router.message(Form.writing_message)
async def process_anonymous_message(
    message: Message, state: FSMContext, bot: Bot, album: List[Message] = None
):
    if (
        not album
        and message.text
        and message.text.startswith("/")
        and not message.text.startswith("/text")
    ):
        await state.clear()
        return
    target_id, reply_to_id = await get_target_and_remind(message, state, bot)
    if target_id:
        # Check for Auto-Voice setting
        user_settings = db.get_user_settings(message.from_user.id)
        if not album and message.text and user_settings.get("auto_voice"):
            # Trigger voice command logic
            from aiogram.filters import CommandObject

            # Create a fake CommandObject
            cmd_obj = CommandObject(prefix="/", command="voice", args=message.text)
            return await process_voice_command(message, state, bot, cmd_obj)

        await forward_anonymous_msg(
            bot, message, target_id, message.from_user.id, state, album=album
        )
        # Note: We NO LONGER clear the state here to allow continuous writing.
        # State will be cleared on /cancel or when starting a new /start link.


@router.message(F.reply_to_message)
async def process_reply(
    message: Message, bot: Bot, state: FSMContext, album: List[Message] = None
):
    # This will sync target from reply to state
    target_id, reply_to_id = await get_target_and_remind(message, state, bot)

    if target_id:
        await forward_anonymous_msg(
            bot,
            message,
            target_id,
            message.from_user.id,
            state,
            reply_to_id=reply_to_id,
            album=album,
        )
    else:
        # Not a known anonymous link
        pass


@router.message()
async def process_unknown(message: Message, state: FSMContext):
    # Only answer if it's not a reply (replies are handled above)
    # AND only in PRIVATE chats to avoid spamming groups
    if not message.reply_to_message and message.chat.type == "private":
        target_id, _ = await get_target_and_remind(message, state, message.bot)
        if target_id:
            # We have a target! Process it as an anonymous message
            return await process_anonymous_message(message, state, message.bot)

        lang = await get_lang(message.from_user.id, message)
        await message.answer(l10n.format_value("error.unknown_action", lang))
