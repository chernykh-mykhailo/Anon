from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from typing import Union
from l10n import l10n
from database import db
from states import Form
from utils import get_lang, get_user_link
from services.voice_engine import text_to_voice, cleanup_voice
from services.image_engine import generate_image_input, cleanup_image

from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from handlers.messages import cleanup_previous_confirmation

router = Router()


@router.callback_query(F.data == "admin_set_cooldown")
async def admin_set_cooldown_callback(callback: types.CallbackQuery, state: FSMContext):
    from config import ADMIN_ID

    if str(callback.from_user.id) != str(ADMIN_ID):
        return await callback.answer("У вас немає прав 🤡")

    await state.set_state(Form.setting_cooldown)
    await callback.message.answer(
        "Введіть нове значення КД (затримки) в секундах (0 — вимкнути):"
    )
    await callback.answer()


@router.callback_query(F.data == "my_link")
async def my_link(callback: types.CallbackQuery, bot: Bot):
    lang = await get_lang(callback.from_user.id, callback.message)
    bot_info = await bot.get_me()
    user_link = await get_user_link(bot_info, callback.from_user.id)
    await callback.message.answer(
        l10n.format_value("your_link", lang, link=user_link),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_lang_"))
async def set_lang(callback: types.CallbackQuery):
    lang_code = callback.data.split("_")[-1]
    db.set_user_lang(callback.from_user.id, lang_code)
    await callback.message.edit_text(l10n.format_value("lang_changed", lang_code))
    await callback.answer()


@router.callback_query(F.data.startswith("write_to_"))
async def start_dialogue_callback(callback: types.CallbackQuery, state: FSMContext):
    """Callback to start a PERSISTENT dialogue."""
    try:
        target_id = int(callback.data.split("_")[-1])
        lang = await get_lang(callback.from_user.id, callback.message)

        # Clear stale data and set PERSISTENT target
        await state.update_data(
            target_id=target_id,
            target_name=None,
            reply_to_id=None,
            anon_num=db.get_available_anon_num(target_id, callback.from_user.id),
        )
        await state.set_state(Form.writing_message)

        kb_stop = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.stop_writing", lang),
                        callback_data="stop_writing",
                    )
                ]
            ]
        )

        await callback.message.answer(
            l10n.format_value("writing_to", lang),
            parse_mode="HTML",
            reply_markup=kb_stop,
        )
        await callback.answer()
    except Exception:
        await callback.answer()


@router.callback_query(F.data.startswith("send_again_"))
async def send_again_callback(callback: types.CallbackQuery, state: FSMContext):
    """Callback for a ONE-OFF message (Write More). Does NOT start a dialogue."""
    try:
        target_id = int(callback.data.split("_")[-1])
        lang = await get_lang(callback.from_user.id, callback.message)

        # Set temp state data but DO NOT set persistent 'writing_message' state globally?
        # Actually, we need to prompt for message. Let's use a temporary flag.
        await state.update_data(temp_target_id=target_id, temp_reply_to_id=None)
        await state.set_state(Form.writing_message)

        kb_stop = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.stop_writing", lang),
                        callback_data="stop_writing",
                    )
                ]
            ]
        )

        await callback.message.answer(
            l10n.format_value("writing_to", lang),
            parse_mode="HTML",
            reply_markup=kb_stop,
        )
        await callback.answer()
    except Exception:
        await callback.answer()


@router.callback_query(F.data == "stop_writing")
async def stop_writing_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await get_lang(callback.from_user.id, callback.message)
    await callback.message.answer(l10n.format_value("action_cancelled", lang))
    await callback.answer()


@router.callback_query(F.data.startswith("set_toggle_"))
async def toggle_setting(callback: types.CallbackQuery):
    from handlers.commands import get_settings_keyboard

    setting_key = callback.data.replace("set_toggle_", "")
    # Map keyboard labels/data to database columns if needed
    mapping = {
        "messages": "receive_messages",
        "media": "receive_media",
        "auto_voice": "auto_voice",
        "skip_confirm_voice": "skip_confirm_voice",
        "anon_audio": "anon_audio",
        "skip_confirm_media": "skip_confirm_media",
    }
    db_column = mapping.get(setting_key)
    if not db_column:
        return await callback.answer()

    # Get current and flip
    settings = db.get_user_settings(callback.from_user.id)
    new_value = 0 if settings[db_column] else 1

    db.update_user_setting(callback.from_user.id, db_column, new_value)

    # Update keyboard
    new_settings = db.get_user_settings(callback.from_user.id)
    lang = await get_lang(callback.from_user.id, callback.message)
    await callback.message.edit_reply_markup(
        reply_markup=get_settings_keyboard(lang, new_settings)
    )
    await callback.answer()


@router.callback_query(F.data == "set_cycle_voice")
async def cycle_voice(callback: types.CallbackQuery):
    from handlers.commands import get_settings_keyboard

    settings = db.get_user_settings(callback.from_user.id)
    current = settings.get("voice_gender", "m")

    voices = ["m", "f", "j", "r", "jenny", "ryan", "ava", "andrew", "rnd"]
    try:
        idx = voices.index(current)
        next_voice = voices[(idx + 1) % len(voices)]
    except ValueError:
        next_voice = "m"

    db.update_user_setting(callback.from_user.id, "voice_gender", next_voice)

    # Update keyboard
    new_settings = db.get_user_settings(callback.from_user.id)
    lang = await get_lang(callback.from_user.id, callback.message)
    await callback.message.edit_reply_markup(
        reply_markup=get_settings_keyboard(lang, new_settings)
    )
    await callback.answer()


@router.callback_query(Form.confirming_media, F.data == "confirm_media_cancel")
async def confirm_media_cancel(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    media_path = data.get("media_path")
    media_type = data.get("media_type")

    if media_path:
        if media_type in ["voice", "video_note", "video"]:
            await cleanup_voice(media_path)
        else:
            cleanup_image(media_path)

    await state.clear()
    await callback.message.delete()
    await callback.answer()


@router.callback_query(Form.confirming_media, F.data == "confirm_media_send")
async def confirm_media_send(
    callback: Union[types.CallbackQuery, any],
    state: FSMContext,
    bot: Bot,
    check_cd: bool = True,
):
    data = await state.get_data()
    target_id = data.get("target_id")
    reply_to_id = data.get("reply_to_id")
    media_path = data.get("media_path")
    media_type = data.get("media_type")
    lang = db.get_user_lang(callback.from_user.id)

    if not target_id or not media_path:
        await callback.answer(
            l10n.format_value("error.data_missing", lang), show_alert=True
        )
        return

    target_lang = await get_lang(target_id)

    # COOLDOWN CHECK (Robust)
    if check_cd:
        cd_seconds = int(db.get_global_config("message_cooldown", "0"))
        allowed, remain = db.check_and_reserve_cooldown(
            callback.from_user.id, target_id, cd_seconds
        )
        if not allowed:
            return await callback.answer(
                l10n.format_value("error.cooldown", lang, seconds=remain),
                show_alert=True,
            )

    # Notify about new message or reply
    notify_key = "reply_received" if reply_to_id else "new_anonymous_msg"
    data = await state.get_data()
    display_name = data.get("anon_num") or "№???"

    # Receiver notification name
    receiver_display_name = display_name

    # REVEAL LOGIC: If the receiver (target_id) already knows the sender's identity via link
    try:
        target_state_ctx = FSMContext(
            storage=state.storage,
            key=StorageKey(bot_id=bot.id, chat_id=target_id, user_id=target_id),
        )
        target_data = await target_state_ctx.get_data()
        if target_data.get("target_id") == callback.from_user.id and target_data.get(
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
                    callback_data=f"write_to_{callback.from_user.id}",
                )
            ]
        ]
    )

    try:
        notify_msg = await bot.send_message(
            target_id,
            l10n.format_value(notify_key, target_lang, name=receiver_display_name),
            message_effect_id=effect_id,
            reply_markup=kb_notify,
        )
        db.save_link(
            notify_msg.message_id,
            target_id,
            callback.from_user.id,
            callback.message.message_id,
            callback.message.chat.id,
        )
    except Exception:
        # Fallback
        notify_msg = await bot.send_message(
            target_id,
            l10n.format_value(notify_key, target_lang, name=receiver_display_name),
            reply_markup=kb_notify,
        )
        db.save_link(
            notify_msg.message_id,
            target_id,
            callback.from_user.id,
            callback.message.message_id,
            callback.message.chat.id,
        )

    # Send media to target
    if media_type == "voice":
        sent_msg = await bot.send_voice(
            chat_id=target_id,
            voice=FSInputFile(media_path),
            reply_to_message_id=reply_to_id,
        )
        await cleanup_voice(media_path)
    elif media_type == "video_note":
        sent_msg = await bot.send_video_note(
            chat_id=target_id,
            video_note=FSInputFile(media_path),
            reply_to_message_id=reply_to_id,
        )
        await cleanup_voice(media_path)
    elif media_type == "video":
        sent_msg = await bot.send_video(
            chat_id=target_id,
            video=FSInputFile(media_path),
            reply_to_message_id=reply_to_id,
            has_spoiler=True,
        )
        await cleanup_voice(media_path)
    else:
        sent_msg = await bot.send_photo(
            chat_id=target_id,
            photo=FSInputFile(media_path),
            caption=l10n.format_value("received_card_caption", target_lang),
            parse_mode="HTML",
            has_spoiler=True,
        )
        cleanup_image(media_path)

    # Save link
    db.save_link(
        sent_msg.message_id,
        target_id,
        callback.from_user.id,
        callback.message.message_id,
        callback.message.chat.id,
    )

    # Confirm to sender
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=l10n.format_value("button.stop_writing", lang),
                    callback_data="stop_writing",
                )
            ]
        ]
    )

    # Try to delete previous confirmation to avoid clutter
    await cleanup_previous_confirmation(callback.message.chat.id, state, bot)

    # Anonymity fix: Use №NNN instead of real name for replies
    data = await state.get_data()
    in_dialogue = data.get("target_id") == target_id
    saved_name = data.get("target_name")

    if in_dialogue and saved_name:
        target_name_to_show = saved_name
    else:
        target_name_to_show = data.get("anon_num") or "№???"

    sent_text = l10n.format_value("msg_sent_to", lang, name=target_name_to_show)

    # Only show dialogue management
    if in_dialogue:
        reply_markup = kb
    else:
        # Even if not in dialogue, show a button to start it
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.write_more", lang),
                        callback_data=f"write_to_{target_id}",
                    )
                ]
            ]
        )

    try:
        await callback.message.edit_caption(
            caption=sent_text, reply_markup=reply_markup, parse_mode="HTML"
        )
        # If it's media (voice/photo), we save its ID with media flag to remove button later
        if in_dialogue:
            await state.update_data(
                last_conf_msg_id=callback.message.message_id, last_conf_is_media=True
            )
    except Exception:
        # If it has no caption (old voices), just answer
        conf_msg = await callback.message.answer(
            sent_text, reply_markup=reply_markup, parse_mode="HTML"
        )
        # Pure text confirmation CAN be deleted
        if in_dialogue:
            await state.update_data(
                last_conf_msg_id=conf_msg.message_id, last_conf_is_media=False
            )

    if in_dialogue:
        await state.set_state(Form.writing_message)
    else:
        # Keep dialogue info for "Write More" but clear ephemeral confirmation
        await state.update_data(media_path=None, media_type=None)

    await callback.answer()


@router.callback_query(Form.confirming_media, F.data == "confirm_original_send")
async def confirm_original_send(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    data = await state.get_data()
    target_id = data.get("target_id")
    reply_to_id = data.get("reply_to_id")
    orig_msg_id = data.get("original_message_id")
    media_path = data.get("media_path")
    lang = db.get_user_lang(callback.from_user.id)

    if not target_id or not orig_msg_id:
        await callback.answer(
            l10n.format_value("error.data_missing", lang), show_alert=True
        )
        return

    target_lang = await get_lang(target_id)

    # COOLDOWN CHECK
    cd_seconds = int(db.get_global_config("message_cooldown", "0"))
    allowed, remain = db.check_and_reserve_cooldown(
        callback.from_user.id, target_id, cd_seconds
    )
    if not allowed:
        return await callback.answer(
            l10n.format_value("error.cooldown", lang, seconds=remain),
            show_alert=True,
        )

    # Notify target
    notify_key = "reply_received" if reply_to_id else "new_anonymous_msg"
    display_name = data.get("anon_num") or "№???"

    kb_notify = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=l10n.format_value("button.start_dialogue", target_lang),
                    callback_data=f"write_to_{callback.from_user.id}",
                )
            ]
        ]
    )

    try:
        await bot.send_message(
            target_id,
            l10n.format_value(notify_key, target_lang, name=display_name),
            reply_markup=kb_notify,
        )
    except Exception:
        pass

    # Copy original message to target
    sent_msg = await bot.copy_message(
        chat_id=target_id,
        from_chat_id=callback.message.chat.id,
        message_id=orig_msg_id,
        reply_to_message_id=reply_to_id,
    )

    # Cleanup the anonymized preview file since it won't be used
    if media_path:
        await cleanup_voice(media_path)

    # Save link
    db.save_link(
        sent_msg.message_id,
        target_id,
        callback.from_user.id,
        callback.message.message_id,
        callback.message.chat.id,
    )

    # Response to sender
    await cleanup_previous_confirmation(callback.message.chat.id, state, bot)

    in_dialogue = data.get("target_id") == target_id
    saved_name = data.get("target_name")
    target_name_to_show = (
        saved_name if (in_dialogue and saved_name) else (data.get("anon_num") or "№???")
    )

    sent_text = l10n.format_value("msg_sent_to", lang, name=target_name_to_show)

    kb_done = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=l10n.format_value("button.write_more", lang),
                    callback_data=f"write_to_{target_id}",
                )
            ]
        ]
    )

    try:
        await callback.message.edit_caption(caption=sent_text, reply_markup=kb_done)
    except Exception:
        await callback.message.answer(sent_text, reply_markup=kb_done)

    if in_dialogue:
        await state.set_state(Form.writing_message)
    else:
        await state.update_data(media_path=None, media_type=None)

    await callback.answer()


@router.callback_query(Form.confirming_media, F.data == "confirm_media_regen")
async def confirm_media_regen(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    data = await state.get_data()
    media_type = data.get("media_type")
    media_path = data.get("media_path")
    prompt = data.get("prompt")
    gender = data.get("gender")
    lang = await get_lang(callback.from_user.id, callback.message)

    # Cleanup old
    if media_path:
        if media_type == "voice":
            cleanup_voice(media_path)
        else:
            cleanup_image(media_path)

    await callback.answer(
        l10n.format_value(
            "voicing_message" if media_type == "voice" else "generating_image", lang
        )
    )

    try:
        if media_type == "voice":
            new_voice = await text_to_voice(prompt, gender)
            new_path = new_voice.path
            # Update preview
            await callback.message.edit_media(
                media=types.InputMediaVoice(media=FSInputFile(new_path)),
                reply_markup=callback.message.reply_markup,
            )
        else:
            new_path = await generate_image_input(prompt)
            # Update preview
            await callback.message.edit_media(
                media=types.InputMediaPhoto(media=FSInputFile(new_path)),
                reply_markup=callback.message.reply_markup,
            )

        await state.update_data(media_path=new_path)
    except Exception as e:
        print(f"Error regenerating: {e}")
        await callback.answer(
            l10n.format_value("error.regen_failed", lang), show_alert=True
        )


@router.callback_query(Form.customizing_draw, F.data.startswith("draw_"))
async def process_draw_callback(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    from handlers.messages import show_draw_customization

    lang = await get_lang(callback.from_user.id, callback.message)
    data = await state.get_data()
    s = data.get("draw_settings")

    if not s:
        await callback.answer(
            l10n.format_value("error.session_expired", lang), show_alert=True
        )
        return

    action = callback.data.replace("draw_", "")

    if action == "apply":
        # Transition to confirm_media flow
        target_id = s["target_id"]
        media_path = data.get("current_preview_path")
        media_type = "draw"
        prompt = s["text"]

        await state.update_data(
            target_id=target_id,
            media_path=media_path,
            media_type=media_type,
            prompt=prompt,
        )
        await state.set_state(Form.confirming_media)

        # CHECK QUICK SEND SETTING
        user_settings = db.get_user_settings(callback.from_user.id)
        if user_settings.get("skip_confirm_media"):
            # Mock a callback for confirm_media_send
            class MockCallback:
                def __init__(self, message, user):
                    self.message = message
                    self.from_user = user

                async def answer(self, text=None, show_alert=False):
                    if text and show_alert:
                        await self.message.answer(text)

            await confirm_media_send(
                MockCallback(callback.message, callback.from_user),
                state,
                bot,
                check_cd=False,
            )
            return

        # Regular confirmation flow
        await callback.message.edit_caption(
            caption=l10n.format_value("your_image_preview", lang),
            reply_markup=InlineKeyboardMarkup(
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
                    ]
                ]
            ),
        )
        await callback.answer()
        return

    # Handle customization buttons
    if action.startswith("pos_"):
        s["y_position"] = action.replace("pos_", "")
    elif action.startswith("color_"):
        s["text_color"] = action.replace("color_", "")
    elif action == "toggle_bg":
        s["use_bg"] = not s.get("use_bg", True)

    await state.update_data(draw_settings=s)
    await show_draw_customization(callback, state, bot, lang)
    await callback.answer()
